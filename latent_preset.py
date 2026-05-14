"""
DARASK Empty Latent Preset.

Replaces ComfyUI's default EmptyLatentImage number widgets with a curated
preset list (SDXL-friendly buckets + 1024² and 2048²), labelled with both
the exact and an approximate aspect ratio.
"""
from __future__ import annotations

import torch


# (label, width, height)
# Labels use full-width × so they line up nicely in ComfyUI's combobox.
PRESETS: list[tuple[str, int, int]] = [
    ("1024 × 1024  (1:1)",                 1024, 1024),
    ("2048 × 2048  (1:1, 2x)",             2048, 2048),
    ("832 × 1216  (13:19 ≈ 2:3 portrait)", 832, 1216),
    ("1216 × 832  (19:13 ≈ 3:2 landscape)",1216, 832),
    ("896 × 1152  (7:9 ≈ 3:4 portrait)",   896, 1152),
    ("1152 × 896  (9:7 ≈ 4:3 landscape)",  1152, 896),
    ("768 × 1344  (4:7 portrait, wide)",   768, 1344),
    ("1344 × 768  (7:4 landscape, wide)",  1344, 768),
]

PRESET_LABELS = [p[0] for p in PRESETS]
_PRESET_LOOKUP = {p[0]: (p[1], p[2]) for p in PRESETS}


class DARASK_EmptyLatentPreset:
    """Pick a latent canvas size from a labelled preset list."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset": (PRESET_LABELS, {"default": PRESET_LABELS[0]}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "swap_orientation": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("latent", "width", "height")
    FUNCTION = "run"
    CATEGORY = "DARASK"

    def run(self, preset, batch_size, swap_orientation):
        width, height = _PRESET_LOOKUP.get(preset, (1024, 1024))
        if swap_orientation:
            width, height = height, width
        # Standard SDXL-style empty latent: 4 channels, /8 spatial.
        latent = torch.zeros([batch_size, 4, height // 8, width // 8])
        return ({"samples": latent}, width, height)
