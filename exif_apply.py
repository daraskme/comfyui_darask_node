"""
DARASK EXIF Apply.

Reads A1111-style metadata from an image's PNG/EXIF info and applies it as a
ready-to-use upscale / hires-fix configuration: loads the matching checkpoint,
stacks the LoRAs found in the prompt, encodes positive / negative conditioning,
and exposes sampler settings as outputs.
"""
from __future__ import annotations

import os

from nodes import (
    CheckpointLoaderSimple,
    CLIPLoader,
    CLIPTextEncode,
    DualCLIPLoader,
    LoraLoader,
    UNETLoader,
    VAELoader,
)

from . import meta_util


# Folder aliases ComfyUI exposes for each loader type. Resolution walks the
# list in order and the first hit wins, so the canonical name comes first.
_CKPT_FOLDERS = ("checkpoints",)
_UNET_FOLDERS = ("diffusion_models", "unet", "checkpoints")
_CLIP_FOLDERS = ("text_encoders", "clip")
_VAE_FOLDERS = ("vae",)


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


_CLIP_TYPES = [
    "stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi",
    "ltxv", "pixart", "cosmos", "lumina2", "wan", "hidream", "chroma",
    "ace", "omnigen2", "qwen_image", "hunyuan_image", "flux2", "ovis",
    "longcat_image", "cogvideox",
]
_DUAL_CLIP_TYPES = [
    "sdxl", "sd3", "flux", "hunyuan_video", "hidream", "hunyuan_image",
    "hunyuan_video_15", "kandinsky5", "kandinsky5_image", "ltxv", "newbie",
    "ace",
]
_WEIGHT_DTYPES = ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"]


class DARASK_ExifApply:
    """
    Full EXIF → Model + Conditioning pipeline.

    Auto-detecting variant: reads the source image's metadata, figures out
    whether the original used a single-file `CheckpointLoaderSimple` (SDXL
    style) or a three-file `UNETLoader + CLIPLoader + VAELoader` stack
    (Anima / Qwen / Flux style), and rebuilds the matching loader chain.
    Stacks the LoRAs found in the prompt, encodes positive / negative
    prompts, and outputs everything KSampler needs.

    Two thin wrappers below pin this to one path explicitly:
    `DARASK Exif Apply (Anima)` and `DARASK Exif Apply (SDXL)`.
    """

    # Subclasses override to force a loader path regardless of metadata.
    _FORCED_KIND: str | None = None
    _DISPLAY_NAME = "Exif Apply"

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

    # ----- helpers ----------------------------------------------------------

    def _resolve_loader_kind(self, parsed: dict) -> str:
        """Forced kind beats metadata; otherwise use the auto-detected one."""
        if self._FORCED_KIND:
            return self._FORCED_KIND
        return (parsed.get("model_loader") or {}).get("kind") or ""

    def _load_unet_stack(
        self,
        parsed: dict,
        params: dict,
        model_override, clip_override, vae_override,
        fallback_ckpt: str,
        fallback_unet: str = "",
        fallback_clip: str = "",
        fallback_clip2: str = "",
        fallback_vae: str = "",
        clip_type_override: str = "",
        weight_dtype_override: str = "",
    ):
        """UNETLoader + CLIPLoader/DualCLIPLoader + VAELoader path."""
        model_info = parsed.get("model_loader") or {"kind": "", "name": ""}
        clip_info = parsed.get("clip_loader") or {"names": [], "type": ""}
        meta_vae_name = parsed.get("vae_loader") or ""

        model, clip, vae = model_override, clip_override, vae_override
        ckpt_used = ""

        if model is None:
            target = model_info.get("name") or params.get("Model", "") or fallback_unet or fallback_ckpt
            resolved = meta_util.resolve_model_file(target, _UNET_FOLDERS)
            if resolved is None:
                raise ValueError(
                    f"{self._DISPLAY_NAME}: cannot resolve diffusion model "
                    f"'{target}' in diffusion_models/. Set `fallback_unet` "
                    f"or wire `model_override`."
                )
            weight_dtype = weight_dtype_override or (model_info.get("weight_dtype") or "default")
            (model,) = UNETLoader().load_unet(resolved, weight_dtype)
            ckpt_used = resolved

        if clip is None:
            meta_names = list(clip_info.get("names") or [])
            override_names = [n for n in (fallback_clip, fallback_clip2) if n]
            clip_names = meta_names or override_names
            if not clip_names:
                raise ValueError(
                    f"{self._DISPLAY_NAME}: metadata has no CLIPLoader info. "
                    f"Set `fallback_clip` (and `fallback_clip2` for dual-CLIP "
                    f"models) or wire `clip_override`."
                )
            clip_type = clip_type_override or (clip_info.get("type") or "stable_diffusion")
            resolved_clips = []
            for cn in clip_names:
                rc = meta_util.resolve_model_file(cn, _CLIP_FOLDERS)
                if rc is None:
                    raise ValueError(
                        f"{self._DISPLAY_NAME}: cannot resolve text encoder "
                        f"'{cn}' in text_encoders/. Wire `clip_override`."
                    )
                resolved_clips.append(rc)
            if len(resolved_clips) == 1:
                (clip,) = CLIPLoader().load_clip(resolved_clips[0], clip_type)
            else:
                # DualCLIPLoader's type vocabulary differs from CLIPLoader's;
                # if a single-CLIP type was supplied, fall through to the SDXL
                # default to avoid an attribute error.
                dual_type = clip_type if clip_type in _DUAL_CLIP_TYPES else "sdxl"
                (clip,) = DualCLIPLoader().load_clip(
                    resolved_clips[0], resolved_clips[1], dual_type,
                )

        if vae is None:
            target = meta_vae_name or fallback_vae or fallback_ckpt
            if not target:
                raise ValueError(
                    f"{self._DISPLAY_NAME}: metadata has no VAELoader entry. "
                    f"Set `fallback_vae` or wire `vae_override`."
                )
            resolved_vae = meta_util.resolve_model_file(target, _VAE_FOLDERS)
            if resolved_vae is None:
                raise ValueError(
                    f"{self._DISPLAY_NAME}: cannot resolve VAE '{target}' in "
                    f"vae/. Wire `vae_override`."
                )
            (vae,) = VAELoader().load_vae(resolved_vae)

        return model, clip, vae, ckpt_used

    def _load_checkpoint_stack(
        self, parsed: dict, params: dict,
        model_override, clip_override, vae_override,
        fallback_ckpt: str,
    ):
        """CheckpointLoaderSimple path."""
        model_info = parsed.get("model_loader") or {"kind": "", "name": ""}
        model, clip, vae = model_override, clip_override, vae_override
        ckpt_used = ""

        if model is None or clip is None or vae is None:
            target = model_info.get("name") or params.get("Model", "") or fallback_ckpt
            resolved = meta_util.resolve_model_file(target, _CKPT_FOLDERS)
            if resolved is None:
                resolved_unet = meta_util.resolve_model_file(target, _UNET_FOLDERS)
                hint = (
                    " The file exists in diffusion_models/ — switch to "
                    "`DARASK Exif Apply (Anima)` instead, or wire "
                    "`model_override` + `clip_override` + `vae_override`."
                    if resolved_unet else ""
                )
                raise ValueError(
                    f"{self._DISPLAY_NAME}: cannot resolve checkpoint "
                    f"'{target}'. Provide `fallback_ckpt` or override "
                    f"MODEL/CLIP/VAE.{hint}"
                )
            loaded_model, loaded_clip, loaded_vae = CheckpointLoaderSimple().load_checkpoint(resolved)
            model = model if model is not None else loaded_model
            clip = clip if clip is not None else loaded_clip
            vae = vae if vae is not None else loaded_vae
            ckpt_used = resolved

        return model, clip, vae, ckpt_used

    def _resolve_stack(self, parsed, params, model_override, clip_override, vae_override,
                       fallback_ckpt, **kwargs):
        """Pick UNET vs Checkpoint and load."""
        kind = self._resolve_loader_kind(parsed)
        if kind == "unet":
            return self._load_unet_stack(
                parsed, params, model_override, clip_override, vae_override,
                fallback_ckpt,
                fallback_unet=kwargs.get("fallback_unet", ""),
                fallback_clip=kwargs.get("fallback_clip", ""),
                fallback_clip2=kwargs.get("fallback_clip2", ""),
                fallback_vae=kwargs.get("fallback_vae", ""),
                clip_type_override=kwargs.get("clip_type", ""),
                weight_dtype_override=kwargs.get("weight_dtype", ""),
            )
        # default: checkpoint (also covers empty / A1111 metadata)
        return self._load_checkpoint_stack(
            parsed, params, model_override, clip_override, vae_override,
            fallback_ckpt,
        )

    # ----- entry point ------------------------------------------------------

    def run(
        self, filepath,
        model_override=None, clip_override=None, vae_override=None,
        fallback_ckpt="",
        positive_prefix="", positive_suffix="",
        negative_prefix="", negative_suffix="",
        lora_strength_multiplier=1.0, skip_loras="",
        **kwargs,
    ):
        if not filepath or not os.path.isfile(filepath):
            raise ValueError(f"{self._DISPLAY_NAME}: file not found: {filepath!r}")

        from PIL import Image
        with Image.open(filepath) as img:
            parsed = meta_util.parse_metadata(img)

        params = parsed["params"]
        cleaned_pos, prompt_loras = meta_util.extract_loras(parsed["positive"])
        cleaned_neg, _ = meta_util.extract_loras(parsed["negative"])
        all_loras = _merge_loras(prompt_loras, parsed.get("comfy_loras", []))

        model, clip, vae, ckpt_used = self._resolve_stack(
            parsed, params, model_override, clip_override, vae_override,
            fallback_ckpt, **kwargs,
        )

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


class DARASK_ExifApplyAnima(DARASK_ExifApply):
    """
    Exif Apply locked to the Anima / Qwen / Flux loader stack:
        UNETLoader + CLIPLoader (or DualCLIPLoader) + VAELoader.

    Skips checkpoint auto-detection entirely — even if the metadata names a
    file present in `checkpoints/`, this node will always try `diffusion_models/`
    for the UNET, `text_encoders/` for CLIP(s), and `vae/` for VAE. Use the
    extra `fallback_*` widgets when the source image's metadata doesn't
    spell out every component.
    """

    _FORCED_KIND = "unet"
    _DISPLAY_NAME = "Exif Apply (Anima)"

    @classmethod
    def INPUT_TYPES(cls):
        base = DARASK_ExifApply.INPUT_TYPES()
        optional = dict(base["optional"])
        # Anima-specific component overrides — leave blank to let metadata win.
        optional.update({
            "fallback_unet": ("STRING", {"default": ""}),
            "fallback_clip": ("STRING", {"default": ""}),
            "fallback_clip2": ("STRING", {"default": ""}),
            "fallback_vae": ("STRING", {"default": ""}),
            "clip_type": (_CLIP_TYPES, {"default": "stable_diffusion"}),
            "weight_dtype": (_WEIGHT_DTYPES, {"default": "default"}),
        })
        return {"required": base["required"], "optional": optional}


class DARASK_ExifApplySDXL(DARASK_ExifApply):
    """
    Exif Apply locked to the classic single-file SDXL / SD1.5 loader path:
        CheckpointLoaderSimple → MODEL + CLIP + VAE in one go.

    Skips UNET / separate-CLIP auto-detection. If the metadata names a file
    that's actually in `diffusion_models/` rather than `checkpoints/`, this
    node will tell you to switch to the Anima variant instead.
    """

    _FORCED_KIND = "checkpoint"
    _DISPLAY_NAME = "Exif Apply (SDXL)"
