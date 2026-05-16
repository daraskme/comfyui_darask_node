"""
DARASK Lora Loader.

A multi-LoRA stacker in one node, inspired by rgthree's Power Lora Loader.
Each row has an on/off toggle, a LoRA file picker, and a strength slider.
Add rows via the "+ Add Lora" button on the node. Right-click a row for
move / toggle / delete options.

The widget value format mirrors rgthree's so saved workflows look familiar
(`{on, lora, strength, strengthTwo}`), but the implementation is standalone
— no rgthree dependency.
"""
from __future__ import annotations

import os
import re
from typing import Union

import folder_paths

from nodes import LoraLoader


# Widget naming convention used by web/darask_lora_loader.js
# Each row generates three kwargs:
#   lora_<N>_on        BOOLEAN
#   lora_<N>           STRING  (lora filename or "None")
#   lora_<N>_strength  FLOAT
_RE_NAME = re.compile(r"^lora_(\d+)$")
_RE_ON = re.compile(r"^lora_(\d+)_on$")
_RE_STRENGTH = re.compile(r"^lora_(\d+)_strength$")
_RE_STRENGTH_CLIP = re.compile(r"^lora_(\d+)_strength_clip$")


class _AnyType(str):
    """A string that compares equal to anything (used as the "*" wildcard type)."""

    def __ne__(self, other) -> bool:  # type: ignore[override]
        return False


_ANY = _AnyType("*")


class _FlexibleOptionalInputs(dict):
    """
    A dict subclass that claims to contain every possible key.

    ComfyUI uses `key in INPUT_TYPES['optional']` to decide whether to accept
    an input from the prompt JSON. By making this dict's `__contains__`
    always return True and `__getitem__` return `(any_type,)` for unknown
    keys, we can accept arbitrary `lora_N` entries that the JS UI adds
    dynamically, without having to pre-declare a fixed number of them.

    Real, declared inputs (`model`, `clip`) keep their actual types so the
    upstream connection-type validation still works.
    """

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return (_ANY,)

    def __contains__(self, key) -> bool:  # type: ignore[override]
        return True


def _resolve_lora(name: str) -> Union[str, None]:
    """Fuzzy-resolve a LoRA filename against `folder_paths.get_filename_list('loras')`."""
    if not name or name in ("None", "none"):
        return None
    try:
        available = folder_paths.get_filename_list("loras") or []
    except Exception:
        return None
    norm = name.replace("\\", "/").strip()
    norm_l = norm.lower()
    base_l = os.path.splitext(os.path.basename(norm))[0].lower()
    # Exact match (normalised separators, case-insensitive).
    for f in available:
        if f.replace("\\", "/").lower() == norm_l:
            return f
    # Basename match without extension.
    for f in available:
        if os.path.splitext(os.path.basename(f))[0].lower() == base_l:
            return f
    # Substring fallback — pick the candidate whose basename length is closest.
    candidates: list[tuple[int, str]] = []
    for f in available:
        fb = os.path.splitext(os.path.basename(f))[0].lower()
        if base_l and (base_l in fb or fb in base_l):
            candidates.append((abs(len(fb) - len(base_l)), f))
    if candidates:
        candidates.sort()
        return candidates[0][1]
    return None


class DARASK_LoraLoader:
    """
    Stack multiple LoRAs in one node.

    The frontend (web/darask_lora_loader.js) adds custom row widgets named
    `lora_1`, `lora_2`, … and serialises each as
    `{on: bool, lora: str, strength: float, strengthTwo: float|None}`.
    Those dicts arrive here as kwargs; we apply the enabled ones in order.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("MODEL", "CLIP")
    RETURN_NAMES = ("MODEL", "CLIP")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            # FlexibleOptional accepts any extra `lora_N` keys without us
            # declaring each one. `model` / `clip` are the real declared
            # inputs that need actual types.
            "optional": _FlexibleOptionalInputs({
                "model": ("MODEL",),
                "clip": ("CLIP",),
            }),
            "hidden": {},
        }

    @staticmethod
    def _collect_loras(kwargs: dict) -> "list[tuple[int, dict]]":
        """
        Walk kwargs and assemble a list of (index, spec) tuples sorted by
        index. Accepts two save formats:

        * **Split format** (current frontend) — three keys per row:
          `lora_N_on` (bool), `lora_N` (str), `lora_N_strength` (float),
          plus optional `lora_N_strength_clip` (float).
        * **Dict format** (legacy / rgthree-compatible) — one key per row:
          `lora_N` = `{on, lora, strength, strengthTwo}`.

        Both can coexist; the dict's fields win over individual keys for
        the same index.
        """
        rows: dict[int, dict] = {}
        for key, val in kwargs.items():
            if not isinstance(key, str):
                continue
            k = key.lower()

            # Dict-format (lora_N = {on, lora, strength, strengthTwo})
            m = _RE_NAME.match(k)
            if m and isinstance(val, dict) and ("lora" in val or "on" in val):
                n = int(m.group(1))
                rows.setdefault(n, {})
                rows[n]["on"] = bool(val.get("on", True))
                rows[n]["lora"] = val.get("lora", "")
                rows[n]["strength"] = val.get("strength", 1.0)
                rows[n]["strength_clip"] = val.get("strengthTwo")
                continue

            # Split-format: lora_N (str)
            if m and isinstance(val, str):
                n = int(m.group(1))
                rows.setdefault(n, {})
                rows[n].setdefault("on", True)
                rows[n].setdefault("strength", 1.0)
                rows[n]["lora"] = val
                continue

            # lora_N_on (bool)
            m = _RE_ON.match(k)
            if m:
                n = int(m.group(1))
                rows.setdefault(n, {})
                rows[n]["on"] = bool(val)
                continue

            # lora_N_strength (float)
            m = _RE_STRENGTH.match(k)
            if m:
                n = int(m.group(1))
                rows.setdefault(n, {})
                try:
                    rows[n]["strength"] = float(val)
                except (TypeError, ValueError):
                    rows[n]["strength"] = 1.0
                continue

            # lora_N_strength_clip (float, optional override)
            m = _RE_STRENGTH_CLIP.match(k)
            if m:
                n = int(m.group(1))
                rows.setdefault(n, {})
                try:
                    rows[n]["strength_clip"] = float(val)
                except (TypeError, ValueError):
                    pass
                continue

        return sorted(rows.items(), key=lambda kv: kv[0])

    def run(self, model=None, clip=None, **kwargs):
        # Nothing to do if there's no model to stack onto — pass through.
        if model is None:
            # `clip` connected but `model` not connected is almost always a
            # mistake (the user forgot to wire UNETLoader/CheckpointLoader
            # to this node's model input). Lora Loader still passes None
            # through so CLIP-only LoRA chains work, but warn loudly so the
            # downstream "'NoneType' has no attribute 'clone'" cascade is
            # easier to debug.
            if clip is not None:
                print(
                    "DARASK Lora Loader: `model` input is None but `clip` is "
                    "connected — passing None through. If you intended to "
                    "stack LoRA on a diffusion model, wire your model loader "
                    "(UNETLoader / CheckpointLoaderSimple / etc.) to this "
                    "node's `model` input. Otherwise downstream nodes that "
                    "call `model.clone()` will fail with AttributeError."
                )
            return (model, clip)

        loader = LoraLoader()
        for idx, spec in self._collect_loras(kwargs):
            if not spec.get("on", False):
                continue
            name = spec.get("lora", "")
            if not name or name == "None":
                continue
            try:
                strength_model = float(spec.get("strength", 1.0))
            except (TypeError, ValueError):
                strength_model = 1.0
            two = spec.get("strength_clip")
            if two in (None, ""):
                strength_clip = strength_model
            else:
                try:
                    strength_clip = float(two)
                except (TypeError, ValueError):
                    strength_clip = strength_model
            if strength_model == 0 and strength_clip == 0:
                continue
            resolved = _resolve_lora(name)
            if resolved is None:
                print(f"DARASK Lora Loader: missing LoRA '{name}', skipping.")
                continue
            try:
                if clip is None:
                    model, _ = loader.load_lora(
                        model, clip, resolved, strength_model, 0
                    )
                else:
                    model, clip = loader.load_lora(
                        model, clip, resolved, strength_model, strength_clip
                    )
            except Exception as e:
                print(f"DARASK Lora Loader: failed to load '{resolved}': {e}")

        return (model, clip)
