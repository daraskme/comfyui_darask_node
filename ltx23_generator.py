"""
DARASK LTX 2.3 Generator — all-in-one image-to-video pipeline.

Bundles every step of the standard LTX Video 2.3 i2v workflow into a
single node:

  1. Models  — load diffusion model (safetensors or GGUF), audio VAE,
                CLIP / text encoder, optional latent upscale model.
                Auto-detects "10Eros-style" checkpoints that contain the
                audio VAE / video VAE / CLIP all in one file and reuses
                them in-place.
  2. LoRA    — 6 fixed slots, each with toggle + name + strength.
  3. Image   — resize + LTXVPreprocess.
  4. Settings — width / height / length / fps with live readout
                ("1024×576 (16:9) · 97f @ 24fps = 4.04s") drawn on the node.
  5. Latents — empty video latent + empty audio latent + LTXVConcatAVLatent.
  6. Prompts — CLIPTextEncode (positive / negative) + LTXVConditioning.
  7. Sampling — RandomNoise + CFGGuider + KSamplerSelect + ManualSigmas +
                SamplerCustomAdvanced + LTXVSeparateAVLatent.
  8. 2x / 4x Upscale — optional LTXVLatentUpsampler → re-condition → sample.
  9. Decode  — VAEDecodeTiled (video) + LTXVAudioVAEDecode (audio) +
                CreateVideo.

Outputs: VIDEO, IMAGE (frames), AUDIO, STRING (info).

Replaces ComfyMath's CM_FloatToInt usage internally (just `int(round(fps))`),
so no ComfyMath dependency is needed.
"""
from __future__ import annotations

import os
import re
import math
from math import gcd
from typing import Any

import torch

import folder_paths
import nodes as core_nodes
import comfy.samplers
import comfy.utils

# V3 nodes from comfy_extras
from comfy_extras.nodes_lt import (
    EmptyLTXVLatentVideo,
    LTXVImgToVideoInplace,
    LTXVConditioning,
    LTXVPreprocess,
    LTXVConcatAVLatent,
    LTXVSeparateAVLatent,
)
from comfy_extras.nodes_lt_audio import (
    LTXVAudioVAELoader,
    LTXVAudioVAEDecode,
    LTXVEmptyLatentAudio,
    LTXAVTextEncoderLoader,
)
from comfy_extras.nodes_lt_upsampler import LTXVLatentUpsampler  # V1 style
from comfy_extras.nodes_custom_sampler import (
    KSamplerSelect,
    RandomNoise,
    CFGGuider,
    SamplerCustomAdvanced,
    ManualSigmas,
)
from comfy_extras.nodes_post_processing import ResizeImageMaskNode
from comfy_extras.nodes_hunyuan import LatentUpscaleModelLoader
from comfy_extras.nodes_video import CreateVideo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NONE_LORA = "None"


def _exec(cls, *args, **kwargs):
    """Invoke a V3 ComfyNode `.execute()` and return its result tuple."""
    out = cls.execute(*args, **kwargs)
    return out.args


def _ckpts() -> list[str]:
    try:
        return list(folder_paths.get_filename_list("checkpoints") or [])
    except Exception:
        return []


def _diffusion_models() -> list[str]:
    try:
        return list(folder_paths.get_filename_list("diffusion_models") or [])
    except Exception:
        return []


def _text_encoders() -> list[str]:
    for k in ("text_encoders", "clip"):
        try:
            v = folder_paths.get_filename_list(k) or []
            if v:
                return list(v)
        except Exception:
            pass
    return []


def _upscale_models() -> list[str]:
    out = []
    for k in ("latent_upscale_models", "upscale_models"):
        try:
            out.extend(folder_paths.get_filename_list(k) or [])
        except Exception:
            pass
    # unique preserve order
    seen = set()
    return [m for m in out if not (m in seen or seen.add(m))]


def _vaes() -> list[str]:
    try:
        return list(folder_paths.get_filename_list("vae") or [])
    except Exception:
        return []


def _all_loras() -> list[str]:
    try:
        return list(folder_paths.get_filename_list("loras") or [])
    except Exception:
        return []


def _resolve_lora_name(name: str) -> str | None:
    if not name or name == NONE_LORA:
        return None
    available = _all_loras()
    norm = name.replace("\\", "/").strip()
    norm_l = norm.lower()
    base_l = os.path.splitext(os.path.basename(norm))[0].lower()
    for f in available:
        if f.replace("\\", "/").lower() == norm_l:
            return f
    for f in available:
        if os.path.splitext(os.path.basename(f))[0].lower() == base_l:
            return f
    return None


def _format_size_info(width: int, height: int, length: int, fps: float) -> str:
    if width <= 0 or height <= 0:
        return f"{width}×{height}"
    g = gcd(width, height) or 1
    rw, rh = width // g, height // g
    if fps > 0:
        duration = length / fps
        return f"{width}×{height} ({rw}:{rh}) · {length}f @ {fps:g}fps = {duration:.2f}s"
    return f"{width}×{height} ({rw}:{rh}) · {length}f"


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def _load_diffusion_model(model_name: str, weight_dtype: str):
    """Load the LTX diffusion model. Returns (model, video_vae_or_None,
    is_full_checkpoint). The video VAE is only returned when the file is in
    `checkpoints/` and contains it bundled."""
    if not model_name or model_name.startswith("("):
        raise ValueError("DARASK LTX 2.3 Generator: no model_name selected.")

    is_gguf = model_name.lower().endswith(".gguf")
    if is_gguf:
        # ComfyUI-GGUF dependency
        try:
            from ComfyUI_GGUF.nodes import UnetLoaderGGUF  # type: ignore
        except Exception:
            try:
                # Folder name with dash → underscore variants
                import importlib
                UnetLoaderGGUF = None
                for cand in ("ComfyUI-GGUF.nodes", "ComfyUI_GGUF.nodes"):
                    try:
                        mod = importlib.import_module(cand)
                        UnetLoaderGGUF = getattr(mod, "UnetLoaderGGUF", None)
                        if UnetLoaderGGUF:
                            break
                    except Exception:
                        continue
                if UnetLoaderGGUF is None:
                    # Try fishing it from NODE_CLASS_MAPPINGS that ComfyUI may
                    # have already registered.
                    from nodes import NODE_CLASS_MAPPINGS  # noqa
                    UnetLoaderGGUF = NODE_CLASS_MAPPINGS.get("UnetLoaderGGUF")
            except Exception:
                UnetLoaderGGUF = None
        if UnetLoaderGGUF is None:
            raise RuntimeError(
                "DARASK LTX 2.3 Generator: .gguf model selected but "
                "ComfyUI-GGUF is not installed/available."
            )
        loader = UnetLoaderGGUF()
        # UnetLoaderGGUF API: load_unet(unet_name)
        result = loader.load_unet(model_name)
        if isinstance(result, tuple):
            model = result[0]
        else:
            model = result
        return model, None, False

    in_checkpoints = model_name in _ckpts()
    if in_checkpoints:
        model, _clip, vae = core_nodes.CheckpointLoaderSimple().load_checkpoint(model_name)
        return model, vae, True

    # Diffusion model file — use UNETLoader
    (model,) = core_nodes.UNETLoader().load_unet(model_name, weight_dtype)
    return model, None, False


def _load_audio_vae(audio_vae_choice: str, fallback_ckpt: str):
    """Audio VAE — either from a separate file or from the same checkpoint."""
    pick = audio_vae_choice
    if pick == "(from model)" or not pick:
        pick = fallback_ckpt
    if not pick:
        raise ValueError(
            "DARASK LTX 2.3 Generator: cannot resolve audio_vae. Select an "
            "explicit file or use a checkpoint that bundles one."
        )
    if pick not in _ckpts():
        raise ValueError(
            f"DARASK LTX 2.3 Generator: audio_vae '{pick}' must live in "
            f"`checkpoints/` (LTXVAudioVAELoader's contract)."
        )
    (vae,) = _exec(LTXVAudioVAELoader, pick)
    return vae


def _load_clip(text_encoder: str, clip_source: str, fallback_ckpt: str):
    """LTXAVTextEncoderLoader takes (text_encoder, ckpt_name, device)."""
    pick = clip_source
    if pick == "(from model)" or not pick:
        pick = fallback_ckpt
    if not pick or not text_encoder:
        raise ValueError(
            "DARASK LTX 2.3 Generator: text_encoder + clip_source must both be set."
        )
    if pick not in _ckpts():
        raise ValueError(
            f"DARASK LTX 2.3 Generator: clip_source '{pick}' must live in `checkpoints/`."
        )
    (clip,) = _exec(LTXAVTextEncoderLoader, text_encoder, pick, "default")
    return clip


def _load_video_vae_external(video_vae_choice: str, fallback_ckpt: str, bundled):
    """Resolve the *video* VAE: prefer bundled (from a full checkpoint),
    else fall back to a user-picked VAE / checkpoint."""
    if bundled is not None and (not video_vae_choice or video_vae_choice == "(from model)"):
        return bundled
    pick = video_vae_choice
    if not pick or pick == "(from model)":
        pick = fallback_ckpt
    if pick in _vaes():
        return core_nodes.VAELoader().load_vae(pick)[0]
    if pick in _ckpts():
        _m, _c, vae = core_nodes.CheckpointLoaderSimple().load_checkpoint(pick)
        return vae
    raise ValueError(
        f"DARASK LTX 2.3 Generator: cannot resolve video VAE '{pick}'. "
        "Pick a file in `vae/` or `checkpoints/`."
    )


def _apply_loras(model, clip, kwargs: dict) -> tuple[Any, Any, list[str]]:
    """
    Apply LoRAs from kwargs. Uses DARASK_LoraLoader's parse logic so the
    same dynamic widget naming (lora_N + lora_N_on + lora_N_strength,
    optional lora_N_strength_clip) works here too — frontend can add as
    many rows as the user wants via the `+ Add LoRA` button.
    """
    from .lora_loader import DARASK_LoraLoader

    applied: list[str] = []
    loader = core_nodes.LoraLoader()
    for idx, spec in DARASK_LoraLoader._collect_loras(kwargs):
        if not spec.get("on", False):
            continue
        name = spec.get("lora", "")
        if not name or name == NONE_LORA:
            continue
        try:
            strength = float(spec.get("strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        sc = spec.get("strength_clip")
        try:
            strength_clip = float(sc) if sc not in (None, "") else strength
        except (TypeError, ValueError):
            strength_clip = strength
        if strength == 0 and strength_clip == 0:
            continue
        resolved = _resolve_lora_name(name)
        if resolved is None:
            print(f"DARASK LTX 2.3 Generator: missing LoRA '{name}', skipping.")
            continue
        try:
            model, clip = loader.load_lora(model, clip, resolved, strength, strength_clip)
            applied.append(f"<{os.path.basename(resolved)}:{strength:.3g}>")
        except Exception as e:
            print(f"DARASK LTX 2.3 Generator: LoRA '{resolved}' failed: {e}")
    return model, clip, applied


# ---------------------------------------------------------------------------
# Sampling helper
# ---------------------------------------------------------------------------


def _sample_stage(model, clip, vae, audio_vae, positive_cond, negative_cond,
                  image, av_latent, sampler_name: str, sigmas_str: str,
                  cfg: float, seed: int) -> tuple[Any, Any]:
    """One sampling pass. Returns (video_latent, audio_latent)."""
    (sampler,) = _exec(KSamplerSelect, sampler_name)
    (sigmas,) = _exec(ManualSigmas, sigmas_str)
    (noise,) = _exec(RandomNoise, seed)
    (guider,) = _exec(CFGGuider, model, positive_cond, negative_cond, cfg)
    sampled, _denoised = _exec(SamplerCustomAdvanced, noise, guider, sampler, sigmas, av_latent)
    video_latent, audio_latent = _exec(LTXVSeparateAVLatent, sampled)
    return video_latent, audio_latent


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------


class DARASK_LTX23Generator:
    """
    Single-node LTX Video 2.3 image-to-video generator. Bundles the entire
    workflow (load → encode → sample → optional upscale × 2 → decode →
    create video) so the user sees one configurable node rather than 40+
    flat ones or 7 subgraphs.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("VIDEO", "IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("VIDEO", "frames", "audio", "info")

    @classmethod
    def INPUT_TYPES(cls):
        ckpts = _ckpts()
        models_all = ckpts + [m for m in _diffusion_models() if m not in ckpts]
        if not models_all:
            models_all = ["(no models found — place in checkpoints/ or diffusion_models/)"]
        tes = _text_encoders() or ["(no text encoders found)"]
        upscalers = _upscale_models() or ["(no upscale models found)"]

        audio_vae_choices = ["(from model)"] + ckpts
        clip_src_choices = ["(from model)"] + ckpts
        video_vae_choices = ["(from model)"] + ckpts + _vaes()

        samplers = list(comfy.samplers.SAMPLER_NAMES)

        def def_sampler(*candidates):
            for c in candidates:
                if c in samplers:
                    return c
            return samplers[0]

        # LoRA rows are added dynamically by the JS UI (`+ Add LoRA` button)
        # just like DARASK Lora Loader. FlexibleOptional accepts any
        # `lora_N` / `lora_N_on` / `lora_N_strength` keys the frontend sends
        # without us having to declare each slot upfront.
        from .lora_loader import _FlexibleOptionalInputs
        optional = _FlexibleOptionalInputs({
            "image": ("IMAGE",),
        })

        return {
            "required": {
                # ─── Model ───
                "model_name": (models_all,),
                "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"], {"default": "default"}),
                "audio_vae_source": (audio_vae_choices, {"default": "(from model)"}),
                "video_vae_source": (video_vae_choices, {"default": "(from model)"}),
                "text_encoder": (tes,),
                "clip_source": (clip_src_choices, {"default": "(from model)"}),
                "upscale_model": (upscalers,),

                # ─── Video size (live preview drawn on node by JS) ───
                "width": ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 32}),
                "height": ("INT", {"default": 576, "min": 64, "max": 4096, "step": 32}),
                "length": ("INT", {"default": 97, "min": 1, "max": 4096, "step": 8}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.1}),

                # ─── Prompts ───
                "positive_prompt": ("STRING", {"multiline": True, "default": "", "placeholder": "positive prompt"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": "", "placeholder": "negative prompt"}),

                # ─── Image preprocess ───
                "image_max_dim": ("INT", {"default": 1536, "min": 128, "max": 4096, "step": 32}),
                "image_resize_method": (
                    ["scale longer dimension", "scale shorter dimension", "stretch"],
                    {"default": "scale longer dimension"},
                ),
                "img_compression": ("INT", {"default": 18, "min": 0, "max": 100}),
                "bypass_i2v": ("BOOLEAN", {"default": False}),
                "i2v_strength": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01}),

                # ─── Sampler / base pass ───
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "cfg_scale": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 30.0, "step": 0.1}),
                "base_sampler": (samplers, {"default": def_sampler("euler_ancestral_cfg_pp", "euler_ancestral", "euler")}),
                "base_sigmas": ("STRING", {
                    "default": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0",
                    "multiline": False,
                }),

                # ─── 2x Upscale ───
                "enable_2x_upscale": ("BOOLEAN", {"default": False}),
                "upscale_2x_sampler": (samplers, {"default": def_sampler("euler_cfg_pp", "euler")}),
                "upscale_2x_sigmas": ("STRING", {"default": "0.85, 0.725, 0.4219, 0.0"}),
                "upscale_2x_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "upscale_2x_bypass_i2v": ("BOOLEAN", {"default": False}),

                # ─── 4x Upscale ───
                "enable_4x_upscale": ("BOOLEAN", {"default": False}),
                "upscale_4x_sampler": (samplers, {"default": def_sampler("euler_cfg_pp", "euler")}),
                "upscale_4x_sigmas": ("STRING", {"default": "0.85, 0.725, 0.4219, 0.0"}),
                "upscale_4x_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "upscale_4x_bypass_i2v": ("BOOLEAN", {"default": False}),

                # ─── Decode ───
                "vae_tile_size": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 32}),
                "vae_overlap": ("INT", {"default": 64, "min": 0, "max": 4096, "step": 32}),
                "vae_temporal_size": ("INT", {"default": 512, "min": 8, "max": 4096, "step": 4}),
                "vae_temporal_overlap": ("INT", {"default": 4, "min": 1, "max": 4096, "step": 1}),
            },
            "optional": optional,
        }

    # ----- pipeline ---------------------------------------------------------

    def run(self, **kw):
        # ──── 1. MODELS ──────────────────────────────────────────────────────
        model_name = kw["model_name"]
        weight_dtype = kw.get("weight_dtype", "default")
        model, bundled_video_vae, is_full_ckpt = _load_diffusion_model(model_name, weight_dtype)

        # Resolve video VAE
        video_vae = _load_video_vae_external(
            kw.get("video_vae_source", "(from model)"),
            model_name if is_full_ckpt else "",
            bundled_video_vae,
        )

        # Resolve audio VAE
        audio_vae = _load_audio_vae(
            kw.get("audio_vae_source", "(from model)"),
            model_name if is_full_ckpt else "",
        )

        # CLIP / text encoder
        clip = _load_clip(
            kw["text_encoder"],
            kw.get("clip_source", "(from model)"),
            model_name if is_full_ckpt else "",
        )

        # Upscale model (only needed if user enables 2x or 4x)
        enable_2x = bool(kw.get("enable_2x_upscale", False))
        enable_4x = bool(kw.get("enable_4x_upscale", False))
        upscale_model = None
        upscale_name = kw.get("upscale_model", "")
        if (enable_2x or enable_4x) and upscale_name and not upscale_name.startswith("("):
            (upscale_model,) = _exec(LatentUpscaleModelLoader, upscale_name)

        # ──── 2. LoRA ────────────────────────────────────────────────────────
        model, clip, applied_loras = _apply_loras(model, clip, kw)

        # ──── 3. IMAGE PREPROCESS ───────────────────────────────────────────
        image = kw.get("image", None)
        if image is None:
            raise ValueError(
                "DARASK LTX 2.3 Generator: `image` input is required "
                "(i2v needs a reference frame)."
            )

        resize_opts = {
            "resize_type": kw.get("image_resize_method", "scale longer dimension"),
            "scale_method": "lanczos",
            "crop": "disabled",
            "multiplier": 1.0,
            "width": 0,
            "height": 0,
            "longer_size": int(kw.get("image_max_dim", 1536)),
            "shorter_size": 0,
            "megapixels": 0.0,
            "multiple": 1,
        }
        try:
            (resized,) = _exec(ResizeImageMaskNode, image, resize_opts)
        except Exception:
            # ResizeImageMaskNode signature variations — fall back to no resize
            resized = image

        (preproc_image,) = _exec(LTXVPreprocess, resized, int(kw.get("img_compression", 18)))

        # ──── 4. SETTINGS / LATENTS ─────────────────────────────────────────
        width = int(kw["width"])
        height = int(kw["height"])
        length = int(kw["length"])
        fps = float(kw["fps"])
        fps_int = max(1, int(round(fps)))

        (empty_video_latent,) = _exec(EmptyLTXVLatentVideo, width, height, length, 1)
        (video_cond_latent,) = _exec(
            LTXVImgToVideoInplace,
            video_vae, preproc_image, empty_video_latent,
            float(kw.get("i2v_strength", 0.7)),
            bool(kw.get("bypass_i2v", False)),
        )
        (audio_latent,) = _exec(LTXVEmptyLatentAudio, length, fps_int, 1, audio_vae)
        (av_latent,) = _exec(LTXVConcatAVLatent, video_cond_latent, audio_latent)

        # ──── 5. PROMPTS ────────────────────────────────────────────────────
        (positive_cond,) = core_nodes.CLIPTextEncode().encode(clip, kw["positive_prompt"])
        (negative_cond,) = core_nodes.CLIPTextEncode().encode(clip, kw["negative_prompt"])
        positive_cond, negative_cond = _exec(LTXVConditioning, positive_cond, negative_cond, fps)

        # ──── 6. BASE SAMPLE ────────────────────────────────────────────────
        seed = int(kw.get("seed", 0))
        cfg = float(kw.get("cfg_scale", 1.0))

        video_latent, out_audio_latent = _sample_stage(
            model, clip, video_vae, audio_vae,
            positive_cond, negative_cond,
            resized, av_latent,
            kw.get("base_sampler"), kw.get("base_sigmas"),
            cfg, seed,
        )

        # ──── 7. 2x UPSCALE (optional) ──────────────────────────────────────
        if enable_2x and upscale_model is not None:
            (up_latent,) = LTXVLatentUpsampler().upsample_latent(video_latent, upscale_model, video_vae)
            (video_cond_2x,) = _exec(
                LTXVImgToVideoInplace,
                video_vae, resized, up_latent,
                float(kw.get("upscale_2x_strength", 1.0)),
                bool(kw.get("upscale_2x_bypass_i2v", False)),
            )
            (av_latent_2x,) = _exec(LTXVConcatAVLatent, video_cond_2x, out_audio_latent)
            video_latent, out_audio_latent = _sample_stage(
                model, clip, video_vae, audio_vae,
                positive_cond, negative_cond,
                resized, av_latent_2x,
                kw.get("upscale_2x_sampler"), kw.get("upscale_2x_sigmas"),
                cfg, seed + 1,
            )

        # ──── 8. 4x UPSCALE (optional) ──────────────────────────────────────
        if enable_4x and upscale_model is not None:
            (up_latent,) = LTXVLatentUpsampler().upsample_latent(video_latent, upscale_model, video_vae)
            (video_cond_4x,) = _exec(
                LTXVImgToVideoInplace,
                video_vae, resized, up_latent,
                float(kw.get("upscale_4x_strength", 1.0)),
                bool(kw.get("upscale_4x_bypass_i2v", False)),
            )
            (av_latent_4x,) = _exec(LTXVConcatAVLatent, video_cond_4x, out_audio_latent)
            video_latent, out_audio_latent = _sample_stage(
                model, clip, video_vae, audio_vae,
                positive_cond, negative_cond,
                resized, av_latent_4x,
                kw.get("upscale_4x_sampler"), kw.get("upscale_4x_sigmas"),
                cfg, seed + 2,
            )

        # ──── 9. DECODE ─────────────────────────────────────────────────────
        decoder = core_nodes.NODE_CLASS_MAPPINGS.get("VAEDecodeTiled") if hasattr(core_nodes, "NODE_CLASS_MAPPINGS") else None
        if decoder is None:
            from nodes import VAEDecodeTiled as _VDT  # type: ignore
            decoder = _VDT
        (frames,) = decoder().decode(
            video_vae, video_latent,
            int(kw.get("vae_tile_size", 512)),
            int(kw.get("vae_overlap", 64)),
            int(kw.get("vae_temporal_size", 512)),
            int(kw.get("vae_temporal_overlap", 4)),
        )

        (audio,) = _exec(LTXVAudioVAEDecode, out_audio_latent, audio_vae)
        (video,) = _exec(CreateVideo, frames, fps, audio)

        # ──── INFO ──────────────────────────────────────────────────────────
        size_info = _format_size_info(width, height, length, fps)
        info_parts = [size_info]
        if applied_loras:
            info_parts.append("LoRAs: " + ", ".join(applied_loras))
        if enable_2x:
            info_parts.append("2x upscale ON")
        if enable_4x:
            info_parts.append("4x upscale ON")
        info_text = " | ".join(info_parts)

        return {
            "ui": {"text": [info_text]},
            "result": (video, frames, audio, info_text),
        }
