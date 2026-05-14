"""
DARASK RIFE Interpolation.

Video frame interpolation via the RIFE (Real-Time Intermediate Flow
Estimation) model. Takes an IMAGE batch + a source FPS, produces an
upsampled IMAGE batch at a target FPS.

The model checkpoint is searched in (first match wins):
* `folder_paths.get_filename_list("rife")` — set up via extra_model_paths
* `<ComfyUI>/models/rife/<model_name>`
* `<this package>/rife_internal/train_log/<model_name>`

Default model name is `flownet.pkl` (RIFE v4.25+, fp16 supported).
Download from https://huggingface.co/hzwer/RIFE (RIFEv4.26_0921.zip).
The actual model architecture is bundled under `rife_internal/`, derived
from the MIT-licensed RIFE reference implementation by hzwer.
"""
from __future__ import annotations

import os

import torch

try:
    import folder_paths
except ImportError:
    folder_paths = None  # type: ignore


def _comfy_progress_bar(total: int):
    """Return a ComfyUI ProgressBar if available, else None. Lazy import so
    module load doesn't break when comfy.utils pulls in torch.float8 etc."""
    try:
        import comfy.utils  # type: ignore
        return comfy.utils.ProgressBar(total)
    except Exception:
        return None


_MODEL_CACHE: dict[str, "object"] = {}


def _candidate_model_paths(model_name: str) -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    paths: list[str] = []

    # 1. Explicit folder_paths entry (allows users to add "rife" in extra_model_paths.yaml).
    if folder_paths is not None:
        try:
            listing = folder_paths.get_filename_list("rife")
        except Exception:
            listing = []
        for f in listing or []:
            if f == model_name or os.path.basename(f) == model_name:
                try:
                    resolved = folder_paths.get_full_path("rife", f)
                    if resolved:
                        paths.append(resolved)
                except Exception:
                    pass

    # 2. <ComfyUI>/models/rife/<model_name>
    if folder_paths is not None and getattr(folder_paths, "models_dir", None):
        paths.append(os.path.join(folder_paths.models_dir, "rife", model_name))

    # 3. Bundled with this package — useful for shipping the model alongside.
    paths.append(os.path.join(here, "rife_internal", "train_log", model_name))

    return paths


def _resolve_model_path(model_name: str) -> str | None:
    for p in _candidate_model_paths(model_name):
        if p and os.path.exists(p):
            return p
    return None


def _load_rife(model_name: str, use_fp16: bool):
    from .rife_internal.wrapper import RIFEWrapper

    cache_key = f"{model_name}|fp16={bool(use_fp16)}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    model_path = _resolve_model_path(model_name)
    if model_path is None:
        searched = "\n  - ".join(_candidate_model_paths(model_name))
        raise FileNotFoundError(
            f"DARASK RIFE Interpolation: cannot find '{model_name}'.\n"
            f"Searched:\n  - {searched}\n"
            "Download RIFEv4.26_0921.zip from https://huggingface.co/hzwer/RIFE "
            "and place 'flownet.pkl' in <ComfyUI>/models/rife/."
        )
    print(f"DARASK RIFE Interpolation: loading {model_path}")
    wrapper = RIFEWrapper(model_path, use_fp16=use_fp16)
    _MODEL_CACHE[cache_key] = wrapper
    return wrapper


class DARASK_RIFEInterpolation:
    """
    Frame-rate upsampling via RIFE. Input is a fixed-FPS clip; output is the
    same clip rendered to `target_fps`.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    DESCRIPTION = "Interpolate frames with RIFE to upsample frame rate."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "source_fps": ("FLOAT", {
                    "default": 16.0, "min": 1.0, "max": 240.0, "step": 0.1,
                    "tooltip": "Source clip's frame rate.",
                }),
                "target_fps": ("FLOAT", {
                    "default": 25.0, "min": 1.0, "max": 480.0, "step": 0.1,
                    "tooltip": "Desired frame rate after interpolation.",
                }),
                "scale": ("FLOAT", {
                    "default": 1.0, "min": 0.25, "max": 4.0, "step": 0.25,
                    "tooltip": "Internal processing scale. <1 is faster but lower quality.",
                }),
            },
            "optional": {
                "model_name": ("STRING", {"default": "flownet.pkl"}),
                "batch_size": ("INT", {
                    "default": 8, "min": 1, "max": 64, "step": 1,
                    "tooltip": "Frame-pairs processed in parallel — higher = faster, more VRAM.",
                }),
                "use_fp16": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Use FP16 on CUDA for faster inference / lower VRAM.",
                }),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def run(self, images, source_fps, target_fps, scale,
            model_name="flownet.pkl", batch_size=8, use_fp16=True):
        if images is None or len(images) == 0:
            raise ValueError("DARASK RIFE Interpolation: no input images.")
        if images.dim() != 4 or images.shape[-1] != 3:
            raise ValueError(
                f"DARASK RIFE Interpolation: expected [N,H,W,3] IMAGE, got {tuple(images.shape)}"
            )
        if source_fps <= 0 or target_fps <= 0 or scale <= 0:
            raise ValueError("DARASK RIFE Interpolation: source_fps/target_fps/scale must be > 0.")
        if abs(source_fps - target_fps) < 1e-3:
            return (images,)

        model = _load_rife(model_name, use_fp16)

        duration = len(images) / source_fps
        total_target = max(1, int(duration * target_fps))
        pbar = _comfy_progress_bar(total_target)

        def on_progress(cur, total):
            if pbar:
                pbar.update_absolute(cur, total)

        autocast = (
            torch.amp.autocast("cuda")
            if (use_fp16 and torch.cuda.is_available())
            else torch.nullcontext()
        )
        with autocast:
            out = model.interpolate_frames(
                images=images, source_fps=source_fps, target_fps=target_fps,
                scale=scale, progress_callback=on_progress, batch_size=batch_size,
            )
        return (out,)
