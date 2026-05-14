"""
DARASK LTX 2.3 helpers.

Small utility nodes that make assembling a flat (no-subgraph) LTX Video
2.3 image-to-video graph less painful:

* DARASK LTX23 Video Settings — width / height / length / fps in one
  node, with a live readout of the final clip dimensions, frame count,
  and duration drawn on the node so you can sanity-check what you're
  about to render before pressing Queue. Outputs the values separately
  so they can be wired into EmptyLTXVLatentVideo, LTXVEmptyLatentAudio,
  LTXVConditioning, CreateVideo, etc.

* DARASK Float to Int — round-to-nearest float → int. Replaces the
  single ComfyMath node (`CM_FloatToInt`) that the LTX 2.3 templates
  use, so the rest of the workflow doesn't need that dependency.
"""
from __future__ import annotations

from math import gcd


class DARASK_LTX23VideoSettings:
    """
    One-stop settings node for an LTX 2.3 clip.

    Widgets:
      * width  (INT)    — pixels, step 32
      * height (INT)    — pixels, step 32
      * length (INT)    — frames; LTX wants (n * 8) + 1 (e.g. 97 / 121 / 241)
      * fps    (FLOAT)  — playback frame rate

    Outputs:
      * width   (INT)   → EmptyLTXVLatentVideo.width
      * height  (INT)   → EmptyLTXVLatentVideo.height
      * length  (INT)   → EmptyLTXVLatentVideo.length, LTXVEmptyLatentAudio.frames_number
      * fps     (FLOAT) → LTXVConditioning.frame_rate, CreateVideo.fps
      * fps_int (INT)   → LTXVEmptyLatentAudio.frame_rate (rounded — no ComfyMath needed)
      * info    (STRING) → "1024×576 (16:9) · 97f @ 24fps = 4.04s" — also drawn on the node.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "INT", "STRING")
    RETURN_NAMES = ("width", "height", "length", "fps", "fps_int", "info")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {
                    "default": 1024, "min": 64, "max": 4096, "step": 32,
                    "tooltip": "Frame width in pixels.",
                }),
                "height": ("INT", {
                    "default": 576, "min": 64, "max": 4096, "step": 32,
                    "tooltip": "Frame height in pixels.",
                }),
                "length": ("INT", {
                    "default": 97, "min": 1, "max": 4096, "step": 8,
                    "tooltip": "Frame count. LTX prefers (n × 8) + 1 (97, 121, 241, …).",
                }),
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 240.0, "step": 0.1,
                    "tooltip": "Playback frame rate.",
                }),
            },
        }

    @staticmethod
    def _format_info(width: int, height: int, length: int, fps: float) -> str:
        if width <= 0 or height <= 0:
            return f"{width}×{height}"
        g = gcd(width, height) or 1
        rw, rh = width // g, height // g
        if fps > 0:
            duration = length / fps
            return (
                f"{width}×{height} ({rw}:{rh}) · "
                f"{length}f @ {fps:g}fps = {duration:.2f}s"
            )
        return f"{width}×{height} ({rw}:{rh}) · {length}f"

    def run(self, width, height, length, fps):
        info = self._format_info(width, height, length, fps)
        fps_int = int(round(fps))
        return {
            "ui": {"text": [info]},
            "result": (
                int(width), int(height), int(length),
                float(fps), fps_int, info,
            ),
        }


class DARASK_FloatToInt:
    """
    Round a FLOAT to the nearest INT.

    Functionally equivalent to ComfyMath's `CM_FloatToInt`; bundled here
    so workflows that only need that one conversion (e.g. the LTX 2.3
    templates feeding `fps` into LTXVEmptyLatentAudio.frame_rate) don't
    have to install the full ComfyMath pack.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("INT",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "value": ("FLOAT", {
                    "default": 0.0, "step": 0.01, "min": -1e18, "max": 1e18,
                    "forceInput": True,
                }),
            },
            "optional": {
                "mode": (["round", "floor", "ceil", "trunc"], {"default": "round"}),
            },
        }

    def run(self, value, mode="round"):
        import math
        v = float(value)
        if mode == "floor":
            out = math.floor(v)
        elif mode == "ceil":
            out = math.ceil(v)
        elif mode == "trunc":
            out = math.trunc(v)
        else:
            out = round(v)
        return (int(out),)
