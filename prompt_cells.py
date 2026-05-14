"""
DARASK Prompt Cells.

A "cellular" prompt builder: each cell holds N variants, cells chain together,
and the chain expands to the cartesian product of every choice — quality tags ×
costumes × poses × lighting × ... — without any manual permutation work.

Two nodes:

* DARASK Prompt Cell           : one segment of the chain, multiline text where
                                 each non-empty line is a variant. Optional `prev`
                                 input lets cells chain.
* DARASK Prompt Cell Output    : terminates the chain. Accepts a CLIP and emits
                                 CONDITIONING either one-at-a-time (Iterate, auto
                                 advance per queue), at a fixed index, or all at
                                 once as a batched CONDITIONING (one image per
                                 combination — pair with a matching latent batch
                                 size).
"""
from __future__ import annotations

import random as _random

import torch

from nodes import CLIPTextEncode


# Custom socket type — any list of strings.
PROMPT_SET = "DARASK_PROMPT_SET"


def _parse_variants(text: str, skip_comments: bool = True) -> list[str]:
    """
    Split a multiline text into variants.
    * Trailing whitespace stripped.
    * Lines starting with `#` (after optional whitespace) are comments.
    * Blank lines are preserved as "no-op" variants ─ the parent prompt stays
      unchanged when that variant is selected. This lets you write
            white dress
            black dress
            (blank)
      to mean "or no costume change at all".
    """
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if skip_comments and line.lstrip().startswith("#"):
            continue
        out.append(line.strip())
    # Drop fully empty trailing lines (textbox cosmetic), but keep blank
    # variants the user explicitly wanted in the middle.
    while out and out[-1] == "":
        out.pop()
    return out


def _join(a: str, b: str, sep: str) -> str:
    """Join two prompt fragments, collapsing the separator if either side is empty."""
    if a and b:
        return f"{a}{sep}{b}"
    return a or b


class DARASK_PromptCell:
    """One cell in a prompt chain. Each non-empty line in `text` is a variant."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "dynamicPrompts": False,
                    "placeholder": "one variant per line\n# lines starting with # are comments\n# blank lines = 'no addition'",
                }),
                "separator": ("STRING", {"default": ", "}),
                "mode": (
                    ["Cartesian (all combos)", "Concat (all lines as one)", "Random pick one", "Fixed index"],
                    {"default": "Cartesian (all combos)"},
                ),
                "enabled": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "prev": (PROMPT_SET,),
                "label": ("STRING", {"default": ""}),
                "index": ("INT", {"default": 0, "min": 0, "max": 4096}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
            },
        }

    RETURN_TYPES = (PROMPT_SET, "INT", "STRING")
    RETURN_NAMES = ("set", "count", "preview")
    FUNCTION = "run"
    CATEGORY = "DARASK/Prompt"

    @classmethod
    def IS_CHANGED(cls, mode, seed, **kwargs):
        if mode == "Random pick one":
            return float("nan") if seed == 0 else seed
        return None

    def run(self, text, separator, mode, enabled, prev=None, label="", index=0, seed=0):
        prev_list = list(prev) if prev else [""]

        if not enabled:
            return (prev_list, len(prev_list), self._format_preview(prev_list))

        variants = _parse_variants(text)

        if mode == "Concat (all lines as one)":
            combined = separator.join(v for v in variants if v)
            variants = [combined] if combined else [""]
        elif mode == "Random pick one":
            rng = _random.Random(seed if seed else None)
            non_blank = [v for v in variants if v]
            variants = [rng.choice(non_blank)] if non_blank else [""]
        elif mode == "Fixed index":
            if variants:
                variants = [variants[max(0, min(index, len(variants) - 1))]]
            else:
                variants = [""]

        if not variants:
            variants = [""]

        result = [_join(p, v, separator) for p in prev_list for v in variants]
        return (result, len(result), self._format_preview(result, label))

    @staticmethod
    def _format_preview(items: list[str], label: str = "") -> str:
        header = f"[{label}] " if label else ""
        head = f"{header}{len(items)} pattern{'s' if len(items) != 1 else ''}"
        sample = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(items[:8]))
        more = f"\n  ... +{len(items) - 8} more" if len(items) > 8 else ""
        return f"{head}\n{sample}{more}"


class DARASK_PromptCellOutput:
    """
    Terminates a prompt-cell chain.

    Iterate     : returns ONE prompt per queue, advancing internally — pair
                  with ComfyUI's auto-queue to render every combination.
    Index       : pick one specific combination by index.
    All as Batch: encodes every combination and stacks them along the batch
                  dimension of CONDITIONING. Wire EmptyLatent batch_size to
                  match `total_count` to render all images in one run.
    """

    _state: dict[int, dict] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "set": (PROMPT_SET,),
                "clip": ("CLIP",),
                "mode": (
                    ["Iterate (auto-advance)", "Index", "All as Batch"],
                    {"default": "Iterate (auto-advance)"},
                ),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "loop": ("BOOLEAN", {"default": True}),
                "reset": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "STRING", "INT", "INT")
    RETURN_NAMES = ("conditioning", "current_prompt", "current_index", "total_count")
    FUNCTION = "run"
    CATEGORY = "DARASK/Prompt"

    @classmethod
    def IS_CHANGED(cls, mode, **kwargs):
        if mode.startswith("Iterate"):
            return float("nan")
        return None

    def run(self, set, clip, mode, index, loop, reset):
        prompts = list(set) if set else [""]
        total = len(prompts)
        encoder = CLIPTextEncode()

        state_key = id(self)
        state = self._state.setdefault(state_key, {"cursor": 0})
        if reset:
            state["cursor"] = 0

        if mode == "All as Batch":
            tensors = []
            dicts = []
            for p in prompts:
                (cond,) = encoder.encode(clip, p)
                tensors.append(cond[0][0])
                dicts.append(cond[0][1])
            batched = torch.cat(tensors, dim=0)
            merged = dict(dicts[0])
            if all("pooled_output" in d for d in dicts):
                merged["pooled_output"] = torch.cat([d["pooled_output"] for d in dicts], dim=0)
            return ([[batched, merged]], "\n---\n".join(prompts), 0, total)

        if mode.startswith("Iterate"):
            cur = state["cursor"]
            if cur >= total:
                cur = 0 if loop else total - 1
            text = prompts[cur]
            (cond,) = encoder.encode(clip, text)
            state["cursor"] = cur + 1
            if state["cursor"] >= total and loop:
                state["cursor"] = 0
            return (cond, text, cur, total)

        # Index mode
        cur = max(0, min(index, total - 1))
        text = prompts[cur]
        (cond,) = encoder.encode(clip, text)
        return (cond, text, cur, total)
