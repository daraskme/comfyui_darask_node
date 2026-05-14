"""
DARASK EXIF Apply.

Reads A1111-style metadata from an image's PNG/EXIF info and applies it as a
ready-to-use upscale / hires-fix configuration: loads the matching checkpoint,
stacks the LoRAs found in the prompt, encodes positive / negative conditioning,
and exposes sampler settings as outputs.
"""
from __future__ import annotations

import os

from nodes import CheckpointLoaderSimple, LoraLoader, CLIPTextEncode

from . import meta_util


def _safe_int(s, default=0):
    try:
        return int(float(str(s).strip()))
    except (ValueError, TypeError):
        return default


def _safe_float(s, default=0.0):
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return default


def _parse_size(s):
    """`512x768` → (512, 768). Returns (0, 0) if unparseable."""
    if not s:
        return 0, 0
    m = str(s).lower().split("x")
    if len(m) != 2:
        return 0, 0
    return _safe_int(m[0]), _safe_int(m[1])


def _split_sampler_scheduler(params):
    """Return (sampler_name, scheduler), splitting A1111-style fused names."""
    sampler = (params.get("Sampler", "") or "").strip()
    scheduler = (params.get("Schedule type", params.get("Schedule", "")) or "").strip()
    if not scheduler or scheduler.lower() == "normal":
        for sched in ("karras", "exponential", "sgm_uniform", "simple", "ddim_uniform"):
            if sched in sampler.lower():
                scheduler = sched
                sampler = sampler.lower().replace(sched, "").strip()
                break
    return sampler, scheduler


def _merge_loras(prompt_loras, comfy_loras):
    """
    Merge LoRA lists from `<lora:...>` tags and ComfyUI workflow nodes,
    deduplicating by normalized basename. Comfy node entries win on conflict
    because rgthree / loraStack store fuller paths.
    """
    seen: dict[str, tuple[str, float, float]] = {}
    # Insert comfy first so prompt-tag duplicates fall back to it
    for entry in comfy_loras:
        name = entry[0]
        key = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0].lower()
        seen[key] = entry
    for entry in prompt_loras:
        name = entry[0]
        key = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0].lower()
        if key not in seen:
            seen[key] = entry
    return list(seen.values())


class DARASK_ExifRead:
    """Lightweight node: read metadata from a filepath and expose all parsed fields as outputs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "filepath": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = (
        "STRING", "STRING", "STRING",
        "STRING", "STRING",
        "INT", "FLOAT", "STRING", "STRING", "INT", "FLOAT",
        "INT", "INT",
        "STRING",
    )
    RETURN_NAMES = (
        "positive", "negative", "loras_text",
        "model_name", "vae_name",
        "seed", "cfg", "sampler_name", "scheduler", "steps", "denoise",
        "width", "height",
        "raw_metadata",
    )
    FUNCTION = "run"
    CATEGORY = "DARASK"

    def run(self, filepath):
        if not filepath or not os.path.isfile(filepath):
            raise ValueError(f"DARASK Exif Read: file not found: {filepath!r}")

        from PIL import Image
        with Image.open(filepath) as img:
            parsed = meta_util.parse_metadata(img)

        cleaned_pos, prompt_loras = meta_util.extract_loras(parsed["positive"])
        cleaned_neg, _ = meta_util.extract_loras(parsed["negative"])
        # Merge LoRAs from prompt tags + ComfyUI nodes (Power Lora Loader / easy loraStack / ...)
        all_loras = _merge_loras(prompt_loras, parsed.get("comfy_loras", []))
        params = parsed["params"]

        loras_text = ", ".join(f"<lora:{n}:{m:.3g}>" for n, m, _ in all_loras)
        sampler, scheduler = _split_sampler_scheduler(params)
        width, height = _parse_size(params.get("Size", ""))

        return (
            cleaned_pos, cleaned_neg, loras_text,
            params.get("Model", ""), params.get("VAE", ""),
            _safe_int(params.get("Seed", 0)),
            _safe_float(params.get("CFG scale", params.get("CFG", 7.0)), 7.0),
            sampler or "euler",
            scheduler or "normal",
            _safe_int(params.get("Steps", 20), 20),
            _safe_float(params.get("Denoising strength", params.get("Denoise", 1.0)), 1.0),
            width, height,
            parsed.get("raw_text", ""),
        )


class DARASK_ExifApply:
    """
    Full EXIF → Model + Conditioning pipeline.
    Loads the checkpoint named in the metadata, stacks LoRAs from the prompt,
    encodes positive / negative prompts, and outputs everything KSampler needs.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "filepath": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "model_override": ("MODEL",),
                "clip_override": ("CLIP",),
                "vae_override": ("VAE",),
                "fallback_ckpt": ("STRING", {"default": ""}),
                "positive_prefix": ("STRING", {"default": "", "multiline": True}),
                "positive_suffix": ("STRING", {"default": "", "multiline": True}),
                "negative_prefix": ("STRING", {"default": "", "multiline": True}),
                "negative_suffix": ("STRING", {"default": "", "multiline": True}),
                "lora_strength_multiplier": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 4.0, "step": 0.05}),
                "skip_loras": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = (
        "MODEL", "CLIP", "VAE",
        "CONDITIONING", "CONDITIONING",
        "STRING", "STRING", "STRING", "STRING",
        "INT", "FLOAT", "STRING", "STRING", "INT", "FLOAT",
        "INT", "INT",
    )
    RETURN_NAMES = (
        "model", "clip", "vae",
        "positive", "negative",
        "positive_text", "negative_text", "model_name", "loras_applied",
        "seed", "cfg", "sampler_name", "scheduler", "steps", "denoise",
        "width", "height",
    )
    FUNCTION = "run"
    CATEGORY = "DARASK"

    def run(
        self, filepath,
        model_override=None, clip_override=None, vae_override=None,
        fallback_ckpt="",
        positive_prefix="", positive_suffix="",
        negative_prefix="", negative_suffix="",
        lora_strength_multiplier=1.0, skip_loras="",
    ):
        if not filepath or not os.path.isfile(filepath):
            raise ValueError(f"DARASK Exif Apply: file not found: {filepath!r}")

        from PIL import Image
        with Image.open(filepath) as img:
            parsed = meta_util.parse_metadata(img)

        params = parsed["params"]
        cleaned_pos, prompt_loras = meta_util.extract_loras(parsed["positive"])
        cleaned_neg, _ = meta_util.extract_loras(parsed["negative"])
        # Merge LoRAs from prompt tags + ComfyUI workflow nodes
        all_loras = _merge_loras(prompt_loras, parsed.get("comfy_loras", []))

        # Resolve checkpoint (override > metadata > fallback)
        model, clip, vae = model_override, clip_override, vae_override
        ckpt_used = ""
        if model is None or clip is None or vae is None:
            ckpt_name = params.get("Model", "") or fallback_ckpt
            resolved = meta_util.resolve_model_file(ckpt_name, "checkpoints")
            if resolved is None:
                raise ValueError(
                    f"DARASK Exif Apply: cannot resolve checkpoint '{ckpt_name}'. "
                    f"Provide a fallback_ckpt or override MODEL/CLIP/VAE."
                )
            loaded_model, loaded_clip, loaded_vae = CheckpointLoaderSimple().load_checkpoint(resolved)
            model = model if model is not None else loaded_model
            clip = clip if clip is not None else loaded_clip
            vae = vae if vae is not None else loaded_vae
            ckpt_used = resolved

        # Apply LoRAs
        skip_set = {s.strip().lower() for s in skip_loras.replace(",", "\n").splitlines() if s.strip()}
        applied: list[str] = []
        lora_loader = LoraLoader()
        for name, mw, cw in all_loras:
            if name.replace("\\", "/").lower() in skip_set or os.path.basename(name).lower() in skip_set:
                continue
            resolved = meta_util.resolve_model_file(name, "loras")
            if resolved is None:
                applied.append(f"!MISSING:{name}")
                continue
            mw_eff = mw * lora_strength_multiplier
            cw_eff = cw * lora_strength_multiplier
            model, clip = lora_loader.load_lora(model, clip, resolved, mw_eff, cw_eff)
            applied.append(f"<lora:{os.path.basename(name)}:{mw_eff:.3g}>")

        # Build final prompt strings
        final_pos = "\n".join(p for p in (positive_prefix, cleaned_pos, positive_suffix) if p).strip()
        final_neg = "\n".join(p for p in (negative_prefix, cleaned_neg, negative_suffix) if p).strip()

        encoder = CLIPTextEncode()
        (positive_cond,) = encoder.encode(clip, final_pos)
        (negative_cond,) = encoder.encode(clip, final_neg)

        sampler, scheduler = _split_sampler_scheduler(params)
        width, height = _parse_size(params.get("Size", ""))

        return (
            model, clip, vae,
            positive_cond, negative_cond,
            final_pos, final_neg, ckpt_used or (params.get("Model", "")),
            ", ".join(applied),
            _safe_int(params.get("Seed", 0)),
            _safe_float(params.get("CFG scale", params.get("CFG", 7.0)), 7.0),
            sampler or "euler",
            scheduler or "normal",
            _safe_int(params.get("Steps", 20), 20),
            _safe_float(params.get("Denoising strength", params.get("Denoise", 1.0)), 1.0),
            width, height,
        )
