"""
DARASK Anima Sampling Tuner.

Single node that bundles every common sampling-side optimization for
Anima / Wan 2.2 / SD3-flow-style video generators into one place:

  • Shift           — `ModelSamplingDiscreteFlow` shift, à la Forge
                      Classic Neo's "Shift" slider. Defaults to 5.0,
                      higher = more weight on noisy steps (better motion
                      coherence for Anima/Wan).
  • TSR             — Temporal Score Rescaling, the video-model-specific
                      bias-fix from ComfyUI's `TemporalScoreRescaling`.
  • Epsilon Scaling — exposure-bias mitigation
                      (2308.15321), uniform schedule.
  • CFG mode        — radio between "Rescale CFG" (multiplier-based) and
                      "CFG Zero Star" (zero out uncond on near-zero
                      cfg). Mutually exclusive because both override
                      `sampler_cfg_function`.

Live info badge at the top of the node summarises which patches are
on. Each section has an enable toggle so you can leave the node wired
in and just flip on what you need.
"""
from __future__ import annotations

import math

import torch

import comfy.model_sampling


# ─── helpers ──────────────────────────────────────────────────────────────

_STYLE_SD3 = "SD3 / Anima / Wan (flow)"
_STYLE_AURA = "AuraFlow"
_STYLE_FLUX = "Flux (resolution-aware)"


def _resolve_multiplier(m, explicit) -> float:
    """
    Pick the correct flow-multiplier:
      * SD3 / Flux → 1000 (the stock ComfyUI default for ModelSamplingSD3)
      * Anima / Wan / Wan-AV → 1.0 (per comfy/supported_models.py)
      * LTX-V → 1.0
    `explicit > 0` overrides; otherwise we inherit whatever the model's
    current `model_sampling.multiplier` is (which ComfyUI sets up from
    the model's `sampling_settings` at load time).
    """
    if explicit is not None and float(explicit) > 0:
        return float(explicit)
    try:
        current = getattr(m.model, "model_sampling", None)
        if current is not None:
            mult = getattr(current, "multiplier", None)
            if mult is not None:
                return float(mult)
    except Exception:
        pass
    return 1.0  # safe default for Anima / Wan / LTX flow models


def _patch_shift_sd3(m, shift: float, multiplier=None):
    """
    ModelSamplingSD3-style shift patch.

    `multiplier=None` auto-inherits the source model's native multiplier
    (Anima/Wan → 1.0, SD3 → 1000). Earlier versions hard-coded 1000,
    which collapsed Anima's sigma schedule by 1000× and produced
    mosaic/sandstorm output. See comfy/supported_models.py — Anima's
    `sampling_settings = {"multiplier": 1.0, "shift": 3.0}`.
    """
    mult = _resolve_multiplier(m, multiplier)

    sampling_base = comfy.model_sampling.ModelSamplingDiscreteFlow
    sampling_type = comfy.model_sampling.CONST

    class ModelSamplingAdvanced(sampling_base, sampling_type):
        pass

    ms = ModelSamplingAdvanced(m.model.model_config)
    ms.set_parameters(shift=float(shift), multiplier=mult)
    m.add_object_patch("model_sampling", ms)
    return mult


def _patch_shift_flux(m, max_shift: float, base_shift: float, width: int, height: int):
    x1, x2 = 256, 4096
    mm = (max_shift - base_shift) / (x2 - x1)
    b = base_shift - mm * x1
    shift = (width * height / (8 * 8 * 2 * 2)) * mm + b

    sampling_base = comfy.model_sampling.ModelSamplingFlux
    sampling_type = comfy.model_sampling.CONST

    class ModelSamplingAdvanced(sampling_base, sampling_type):
        pass

    ms = ModelSamplingAdvanced(m.model.model_config)
    ms.set_parameters(shift=shift)
    m.add_object_patch("model_sampling", ms)
    return shift


def _attach_epsilon_scaling(m, scaling_factor: float):
    """Post-CFG hook that scales the predicted noise (exposure bias fix)."""
    def post_cfg(args):
        denoised = args["denoised"]
        x = args["input"]
        noise = x - denoised
        return x - (noise / scaling_factor)
    m.set_model_sampler_post_cfg_function(post_cfg)


def _compute_tsr_factor(sigma: torch.Tensor, k: float, sigma_pivot: float):
    """
    Time-step-dependent rescaling factor — large at high sigma,
    1.0 at sigma=sigma_pivot, tapering for low sigma. Matches the
    formulation used by ComfyUI's TemporalScoreRescaling node:
        factor = ((sigma / sigma_pivot) ** k) when sigma > sigma_pivot, else 1
    """
    safe = sigma_pivot if sigma_pivot > 1e-8 else 1e-8
    ratio = sigma / safe
    factor = torch.where(ratio > 1.0, ratio ** k, torch.ones_like(ratio))
    return factor


def _attach_tsr(m, tsr_k: float, tsr_sigma: float):
    """Post-CFG hook that rescales noise prediction by a sigma-dependent factor."""
    def post_cfg(args):
        denoised = args["denoised"]
        x = args["input"]
        sigma = args["sigma"]
        sigma = sigma.view(sigma.shape[:1] + (1,) * (denoised.ndim - 1))
        noise = x - denoised
        scale = _compute_tsr_factor(sigma, tsr_k, tsr_sigma)
        return x - (noise / scale)
    m.set_model_sampler_post_cfg_function(post_cfg)


def _attach_rescale_cfg(m, multiplier: float):
    """Replace cfg_function with rescale_cfg from nodes_model_advanced.py."""
    def rescale_cfg(args):
        cond = args["cond"]
        uncond = args["uncond"]
        cond_scale = args["cond_scale"]
        sigma = args["sigma"]
        sigma = sigma.view(sigma.shape[:1] + (1,) * (cond.ndim - 1))
        x_orig = args["input"]

        x = x_orig / (sigma * sigma + 1.0)
        cond = ((x - (x_orig - cond)) * (sigma ** 2 + 1.0) ** 0.5) / (sigma)
        uncond = ((x - (x_orig - uncond)) * (sigma ** 2 + 1.0) ** 0.5) / (sigma)

        x_cfg = uncond + cond_scale * (cond - uncond)
        ro_pos = torch.std(cond, dim=tuple(range(1, cond.ndim)), keepdim=True)
        ro_cfg = torch.std(x_cfg, dim=tuple(range(1, x_cfg.ndim)), keepdim=True)

        x_rescaled = x_cfg * (ro_pos / ro_cfg)
        x_final = multiplier * x_rescaled + (1.0 - multiplier) * x_cfg
        return x_orig - (x - x_final * sigma / (sigma * sigma + 1.0) ** 0.5)

    m.set_model_sampler_cfg_function(rescale_cfg)


def _attach_cfg_zero_star(m):
    """Replace cfg_function with CFG Zero Star (optimized scale)."""
    def optimized_scale(positive, negative):
        positive_flat = positive.reshape(positive.shape[0], -1)
        negative_flat = negative.reshape(negative.shape[0], -1)
        dot_product = torch.sum(positive_flat * negative_flat, dim=1, keepdim=True)
        squared_norm = torch.sum(negative_flat ** 2, dim=1, keepdim=True) + 1e-8
        st_star = dot_product / squared_norm
        return st_star.reshape([positive.shape[0]] + [1] * (positive.ndim - 1))

    def cfg_zero_star(args):
        guidance_scale = args["cond_scale"]
        x = args["input"]
        cond_p = args["cond_denoised"]
        uncond_p = args["uncond_denoised"]
        out = args["denoised"]
        alpha = optimized_scale(x - cond_p, x - uncond_p)
        return out + uncond_p * (alpha - 1.0) + guidance_scale * uncond_p * (1.0 - alpha)

    m.set_model_sampler_cfg_function(cfg_zero_star)


# ─── main node ─────────────────────────────────────────────────────────────


class DARASK_AnimaSamplingTuner:
    """
    All-in-one Anima / Wan 2.2 sampling tuner.

    Each section has its own enable toggle — flip what you need and the
    info STRING at the top of the node lists every active patch. Wire
    `MODEL` in / `MODEL` out, drop between your model loader and the
    sampler.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("MODEL", "STRING")
    RETURN_NAMES = ("MODEL", "info")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),

                # ─── Shift ─────────────────────────────
                # Defaults match Forge Classic Neo presets (modules_forge/presets.py):
                #   anima=3.0, wan=5.0, lumina=6.0, z-image-turbo=9.0, ernie=3.0.
                # The node is named "Anima Tuner" → ship with the Anima default.
                "shift_enable": ("BOOLEAN", {"default": True, "tooltip": "Apply ModelSamplingDiscreteFlow shift (the Anima/Wan/Forge 'Shift' slider)."}),
                "shift_style": ([_STYLE_SD3, _STYLE_AURA, _STYLE_FLUX], {"default": _STYLE_SD3}),
                "shift": ("FLOAT", {
                    "default": 3.0, "min": 1.0, "max": 24.0, "step": 0.5,
                    "tooltip": (
                        "Forge Classic Neo preset values:\n"
                        "  Anima: 3.0 (default), Wan 2.2: 5.0, Lumina: 6.0, Z-Image-Turbo: 9.0,\n"
                        "  Ernie: 3.0.  AuraFlow: ~1.73.  Flux: ignored, use max/base instead."
                    ),
                }),

                # ─── Temporal Score Rescaling ───────────
                # Not in Forge — these are ComfyUI's defaults from
                # comfy_extras/nodes_eps.py.
                "tsr_enable": ("BOOLEAN", {"default": False, "tooltip": "Video-model-specific noise rescaling (good for Anima/Wan motion coherence)."}),
                "tsr_k": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "tsr_sigma": ("FLOAT", {"default": 1.0, "min": 0.001, "max": 100.0, "step": 0.01, "tooltip": "Sigma pivot — rescaling kicks in for sigma above this."}),

                # ─── Epsilon Scaling ─────────────────────
                # Defaults from Forge Classic Neo (modules/shared_options.py):
                #   default 1.0 (disabled), range 1.0–1.05, step 0.005.
                "eps_enable": ("BOOLEAN", {"default": False, "tooltip": "Exposure-bias mitigation (post-CFG noise rescale)."}),
                "eps_scaling": ("FLOAT", {
                    "default": 1.0, "min": 1.0, "max": 1.05, "step": 0.005,
                    "tooltip": "Forge Classic Neo: 1.0 (disabled) - 1.05, step 0.005. 1.0 = no-op.",
                }),

                # ─── CFG mode (mutually exclusive) ───────
                # Forge Classic Neo defaults (processing_scripts/rescale_cfg.py):
                #   slider range 0.0–1.0, step 0.05, default 0.0 (disabled).
                # The mode selector here doubles as the on/off — when set to
                # "Rescale CFG", a multiplier of 0.7 (ComfyUI's stock default)
                # is a sensible starting point. 0.0 mimics Forge's "off".
                "cfg_mode": (["off", "Rescale CFG", "CFG Zero Star"], {
                    "default": "off",
                    "tooltip": "Only one CFG variant can be applied at a time (they both replace `sampler_cfg_function`).",
                }),
                "rescale_cfg_multiplier": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05}),
            },
            "optional": {
                # ─── Flux-style shift extras ──────────────
                "flux_max_shift": ("FLOAT", {"default": 1.15, "min": 0.0, "max": 100.0, "step": 0.01}),
                "flux_base_shift": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 100.0, "step": 0.01}),
                "flux_width": ("INT", {"default": 1024, "min": 16, "max": 8192, "step": 8}),
                "flux_height": ("INT", {"default": 1024, "min": 16, "max": 8192, "step": 8}),
                # ─── SD3 multiplier (advanced override) ─────
                # 0 = auto-detect from the source model. Manual override
                # only if you know exactly which sigma schedule you want.
                # Anima/Wan native = 1.0, SD3 native = 1000.
                "shift_multiplier": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100000.0, "step": 1.0,
                    "tooltip": (
                        "0 = auto-detect from source model "
                        "(Anima/Wan/LTX → 1.0, SD3 → 1000). Override only "
                        "if you specifically need a non-native multiplier."
                    ),
                }),
            },
        }

    def run(self, model, shift_enable, shift_style, shift,
            tsr_enable, tsr_k, tsr_sigma,
            eps_enable, eps_scaling,
            cfg_mode, rescale_cfg_multiplier,
            flux_max_shift=1.15, flux_base_shift=0.5,
            flux_width=1024, flux_height=1024,
            shift_multiplier=1000.0):
        if model is None:
            raise ValueError(
                "DARASK Anima Sampling Tuner: `model` input is not connected. "
                "Wire a model loader (UNETLoader, CheckpointLoaderSimple, "
                "DARASK Lora Loader, etc.) to this node's `model` input. "
                "Note: DARASK Lora Loader silently passes None through when "
                "its OWN `model` input is unconnected — if you go through "
                "Lora Loader, make sure UNETLoader → Lora Loader.model is "
                "wired as well."
            )
        m = model.clone()
        active: list[str] = []

        # 1. Shift
        if shift_enable:
            if shift_style == _STYLE_AURA:
                _patch_shift_sd3(m, shift, multiplier=1.0)
                active.append(f"shift(AuraFlow)={shift:.3g}")
            elif shift_style == _STYLE_FLUX:
                derived = _patch_shift_flux(m, flux_max_shift, flux_base_shift, flux_width, flux_height)
                active.append(
                    f"shift(Flux)={derived:.3g} "
                    f"[max={flux_max_shift:.3g}, base={flux_base_shift:.3g}, {flux_width}×{flux_height}]"
                )
            else:
                # multiplier=0 → _resolve_multiplier auto-detects from
                # the source model's native sampling_settings.
                explicit = float(shift_multiplier) if shift_multiplier and shift_multiplier > 0 else None
                effective_mult = _patch_shift_sd3(m, shift, multiplier=explicit)
                active.append(f"shift(SD3/Anima)={shift:.3g} (mult={effective_mult:g})")

        # 2. CFG mode (replaces cfg_function — must come BEFORE post_cfg hooks)
        if cfg_mode == "Rescale CFG":
            _attach_rescale_cfg(m, rescale_cfg_multiplier)
            active.append(f"RescaleCFG×{rescale_cfg_multiplier:.2f}")
        elif cfg_mode == "CFG Zero Star":
            _attach_cfg_zero_star(m)
            active.append("CFG-Zero★")

        # 3. Post-CFG transforms (stack)
        if eps_enable and abs(eps_scaling - 1.0) > 1e-6:
            _attach_epsilon_scaling(m, eps_scaling)
            active.append(f"ε-scale {eps_scaling:.3f}")

        if tsr_enable:
            _attach_tsr(m, tsr_k, tsr_sigma)
            active.append(f"TSR k={tsr_k:.2f}@σ{tsr_sigma:.2f}")

        info = "Active: " + (" + ".join(active) if active else "(passthrough)")
        return {
            "ui": {"text": [info]},
            "result": (m, info),
        }
