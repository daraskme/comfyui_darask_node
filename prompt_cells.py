"""
DARASK Prompt Cells.

A "cellular" prompt builder: each cell holds N variants, cells chain together,
and the chain expands to the cartesian product of every choice — quality tags ×
costumes × poses × lighting × ... — without any manual permutation work.

Cells now accept MULTIPLE `prev` inputs so chains can branch and merge: each
upstream branch is unioned into the cell's incoming pattern set before the
cell's own variants are applied. Likewise, the Output node accepts MULTIPLE
`set` inputs and unions them — every leaf cell wired in contributes its
patterns to the final batch.

Two nodes:

* DARASK Prompt Cell           : one segment of the chain, multiline text where
                                 each non-empty line is a variant. Optional
                                 `prev` inputs (16 slots) let multiple upstream
                                 branches merge into this cell.
* DARASK Prompt Cell Output    : terminates the chain. Accepts a CLIP and emits
                                 CONDITIONING either one-at-a-time (Iterate, auto
                                 advance per queue), at a fixed index, or all at
                                 once as a batched CONDITIONING (one image per
                                 combination — pair with a matching latent batch
                                 size). Accepts up to 16 `set` inputs and unions
                                 every connected branch.
"""
from __future__ import annotations

import random as _random

import torch

from nodes import CLIPTextEncode


# Custom socket type — any list of strings.
PROMPT_SET = "DARASK_PROMPT_SET"

# Max dynamic input slots. Python declares all of them; the JS extension
# (web/darask_prompt_cells.js) hides trailing empty ones for a clean UI.
PREV_SLOTS = 16
SET_SLOTS = 16


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


def _gather_prev_lists(prev, kwargs, prefix: str, max_slots: int) -> list[list[str]]:
    """Collect every connected upstream set in declared slot order."""
    lists: list[list[str]] = []
    if prev:
        lists.append(list(prev))
    for i in range(2, max_slots + 1):
        val = kwargs.get(f"{prefix}_{i}")
        if val:
            lists.append(list(val))
    return lists


class DARASK_PromptCell:
    """
    One cell in a prompt chain. Each non-empty line in `text` is a variant.

    Multiple `prev` inputs are merged (union) before this cell's variants are
    applied — this lets several upstream branches converge into one cell.
    """

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict = {"prev": (PROMPT_SET,)}
        for i in range(2, PREV_SLOTS + 1):
            optional[f"prev_{i}"] = (PROMPT_SET,)
        optional.update({
            "label": ("STRING", {"default": ""}),
            "index": ("INT", {"default": 0, "min": 0, "max": 4096}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
        })
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
            "optional": optional,
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

    def run(self, text, separator, mode, enabled, prev=None, label="", index=0, seed=0, **kwargs):
        prev_lists = _gather_prev_lists(prev, kwargs, "prev", PREV_SLOTS)
        if prev_lists:
            prev_list = [p for lst in prev_lists for p in lst]
        else:
            prev_list = [""]

        if not enabled:
            return (prev_list, len(prev_list), self._format_preview(prev_list, label))

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

    Accepts up to 16 `set` inputs — every connected branch's patterns are
    unioned into one flat list before encoding. Wire as many leaf cells as
    you need; the output covers every pattern from every branch.

    Iterate (auto-advance) : returns ONE prompt per queue, advancing an
                             internal cursor. Pair with ComfyUI's *Auto
                             Queue* (in the queue panel, set to "instant")
                             to render every combination — by itself,
                             pressing Queue once only produces one image.
    Index                  : pick one specific combination by index.
    All as Batch (default) : encodes every combination and stacks them
                             along the batch dimension. Set the latent's
                             `batch_size` to match `total_count` (or convert
                             the widget to an input and wire it) and
                             KSampler renders the whole sweep in a single
                             queue.
    """

    # state is per-node-id so the cursor survives instance recreation that
    # may happen on workflow edits / cache invalidation.
    _state: dict[str, dict] = {}

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict = {"set": (PROMPT_SET,)}
        for i in range(2, SET_SLOTS + 1):
            optional[f"set_{i}"] = (PROMPT_SET,)
        return {
            "required": {
                "clip": ("CLIP",),
                "mode": (
                    ["Iterate (auto-advance)", "Index", "All as Batch"],
                    {"default": "All as Batch"},
                ),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "loop": ("BOOLEAN", {"default": True}),
                "reset": ("BOOLEAN", {"default": False}),
            },
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CONDITIONING", "STRING", "INT", "INT")
    RETURN_NAMES = ("conditioning", "current_prompt", "current_index", "total_count")
    FUNCTION = "run"
    CATEGORY = "DARASK/Prompt"

    @classmethod
    def IS_CHANGED(cls, mode, **kwargs):
        # Iterate must re-run every queue so the cursor advances; the legacy
        # "Iterate (auto-advance)" label is kept for back-compat with old
        # saved workflows.
        if mode.startswith("Iterate"):
            return float("nan")
        return None

    def run(self, clip, mode, index, loop, reset, set=None, unique_id=None, **kwargs):
        set_lists = _gather_prev_lists(set, kwargs, "set", SET_SLOTS)
        if set_lists:
            prompts = [p for lst in set_lists for p in lst]
        else:
            prompts = [""]
        total = len(prompts)
        encoder = CLIPTextEncode()

        state_key = str(unique_id) if unique_id is not None else f"_inst_{id(self)}"
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
