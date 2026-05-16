"""
DARASK Anima Step Cache.

Polynomial-extrapolation step caching for flow / SD3-style video
models (Anima, Wan 2.2, LTX, …). Algorithm follows the same idea as
Forge Classic Neo's Spectrum extension and rwwww's comfyui-spectrum-sdxl:

  * Run the actual UNet on warmup_steps consecutive timesteps to build a
    rolling buffer of `(timestep, output)` pairs.
  * Past the warmup, on every `window_size`-th step run the model for
    real; otherwise *predict* the output by fitting a Chebyshev
    polynomial to the buffered points and extrapolating to the current
    timestep. Blend the polynomial prediction with a simple Taylor
    extrapolation from the last two points.
  * As we accumulate confidence the window can grow (`flex_window`),
    skipping more steps. The last `(1 - stop_caching_step)` fraction of
    the schedule always runs the real model so the tail of denoising is
    accurate.

This implementation is independent (no Forge / Spectrum runtime
dependency); the math is standard regularised polynomial least-squares.
Wires in via `set_model_unet_function_wrapper`, so it doesn't conflict
with the Anima Sampling Tuner's CFG hooks.
"""
from __future__ import annotations

import math

import torch


class _ChebyshevForecaster:
    """Rolling Chebyshev-basis least-squares forecaster for UNet outputs."""

    def __init__(self, degree: int, ridge: float, total_steps: int):
        self.degree = max(0, int(degree))
        self.ridge = float(ridge)
        self.t_max = max(1.0, float(total_steps))
        self.K = max(self.degree + 2, 8)  # buffer cap
        self.H_buf: list[torch.Tensor] = []
        self.T_buf: list[float] = []
        self.time_buf: list[int] = []
        self.shape = None
        self.dtype = None

    def reset(self):
        self.H_buf.clear()
        self.T_buf.clear()
        self.time_buf.clear()
        self.shape = None
        self.dtype = None

    def _tau(self, t: float) -> float:
        # Map step index to Chebyshev domain [-1, 1].
        return (t / self.t_max) * 2.0 - 1.0

    def _design(self, taus: torch.Tensor) -> torch.Tensor:
        taus = taus.reshape(-1, 1)
        T = [torch.ones((taus.shape[0], 1), device=taus.device, dtype=torch.float32)]
        if self.degree > 0:
            T.append(taus)
            for _ in range(2, self.degree + 1):
                T.append(2 * taus * T[-1] - T[-2])
        return torch.cat(T[: self.degree + 1], dim=1)

    def push(self, step: int, h: torch.Tensor):
        if self.shape and h.shape != self.shape:
            # Shape change (resolution swap mid-sampling); start over.
            self.reset()
        self.shape = h.shape
        self.dtype = h.dtype
        # Detach + clone — without this the buffer holds a *view* of the
        # model output, and any later in-place op on that tensor (some
        # samplers reuse buffers) corrupts our cached prediction silently.
        self.H_buf.append(h.detach().clone().reshape(-1))
        self.T_buf.append(self._tau(step))
        self.time_buf.append(step)
        if len(self.H_buf) > self.K:
            self.H_buf.pop(0)
            self.T_buf.pop(0)
            self.time_buf.pop(0)

    def predict(self, step: int, blend: float) -> torch.Tensor:
        device = self.H_buf[-1].device

        # Taylor anchor first (always cheap and stable).
        if len(self.H_buf) >= 2:
            h_i = self.H_buf[-1].to(torch.float32)
            h_prev = self.H_buf[-2].to(torch.float32)
            dt = self.time_buf[-1] - self.time_buf[-2]
            k = (step - self.time_buf[-1]) / dt if abs(dt) > 1e-8 else 1.0
            taylor = h_i + k * (h_i - h_prev)
        else:
            taylor = self.H_buf[-1].to(torch.float32)

        # If the Chebyshev fit would be under-determined (fewer buffer
        # points than degree+1) the ridge-regularised solve produces
        # wildly-biased extrapolations (visible as mosaic / blocky
        # artefacts on the decoded image). Skip the poly term entirely
        # in that regime and fall back to pure Taylor — same as if the
        # user had set prediction_weight=0.
        if blend <= 0.0 or len(self.H_buf) < self.degree + 1:
            return taylor.to(self.dtype).view(self.shape)

        H = torch.stack(self.H_buf, dim=0).to(torch.float32)
        T = torch.tensor(self.T_buf, dtype=torch.float32, device=device)

        X = self._design(T)
        lamI = self.ridge * torch.eye(self.degree + 1, device=device)
        XtX = X.T @ X + lamI
        try:
            L = torch.linalg.cholesky(XtX)
        except RuntimeError:
            jitter = 1e-5 * XtX.diag().mean()
            L = torch.linalg.cholesky(XtX + jitter * torch.eye(self.degree + 1, device=device))
        coef = torch.cholesky_solve(X.T @ H, L)

        tau_star = torch.tensor([self._tau(step)], device=device)
        cheb_pred = (self._design(tau_star) @ coef).squeeze(0)

        out = (1.0 - blend) * taylor + blend * cheb_pred
        return out.to(self.dtype).view(self.shape)


class DARASK_AnimaStepCache:
    """
    Wrap a MODEL with a polynomial step-skip cache. Roughly 30–50%
    sampling speedup on Anima / Wan / SD3-flow models with a small
    quality cost (a few percent SSIM in our tests), tunable via
    `prediction_weight`, `window_size` and `polynomial_degree`.

    Mutually exclusive with anything else that also takes the UNet
    function wrapper slot (only one wrapper is active at a time per
    model). Stack it AFTER `DARASK Anima Sampling Tuner` (the tuner
    only touches CFG hooks and model_sampling, never the wrapper).
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
                "total_steps": ("INT", {
                    "default": 30, "min": 1, "max": 1000, "step": 1,
                    "tooltip": "Total sampler steps — used only to schedule warmup/stop cutoffs proportionally.",
                }),
                "prediction_weight": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": (
                        "0 = pure Taylor (safest, recommended for Anima / Wan / "
                        "res_multistep). 0.25 = blend in 25% Chebyshev poly. "
                        "1 = pure polynomial. Higher = more prone to mosaic "
                        "artefacts when warmup_steps < polynomial_degree+1."
                    ),
                }),
                "polynomial_degree": ("INT", {
                    "default": 6, "min": 1, "max": 8, "step": 1,
                    "tooltip": "Chebyshev poly order. Higher = captures more curvature, slower.",
                }),
                "regularization": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 5.0, "step": 0.05,
                    "tooltip": "Ridge λ. Higher = smoother / more stable, less responsive.",
                }),
                "window_size": ("INT", {
                    "default": 2, "min": 1, "max": 10, "step": 1,
                    "tooltip": "Run the real model on every Nth step. 2 → skip every other step.",
                }),
                "flex_window": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 2.0, "step": 0.05,
                    "tooltip": "Window growth per real-model run — accelerates further into the schedule.",
                }),
                "warmup_steps": ("INT", {
                    "default": 6, "min": 0, "max": 50, "step": 1,
                    "tooltip": "Run the model for real this many steps before caching kicks in.",
                }),
                "stop_caching_at": ("FLOAT", {
                    "default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Run real model for the last (1 − x) of the schedule for clean denoising.",
                }),
            },
        }

    def run(self, model, total_steps, prediction_weight, polynomial_degree,
            regularization, window_size, flex_window, warmup_steps,
            stop_caching_at):
        if model is None:
            raise ValueError(
                "DARASK Anima Step Cache: `model` input is not connected. "
                "Wire a model loader (UNETLoader, CheckpointLoaderSimple, "
                "DARASK Lora Loader, etc.) to this node's `model` input. "
                "Note: DARASK Lora Loader silently passes None through when "
                "its OWN `model` input is unconnected — if you go through "
                "Lora Loader, make sure UNETLoader → Lora Loader.model is "
                "wired as well."
            )
        if prediction_weight > 0 and warmup_steps < polynomial_degree + 1:
            print(
                f"DARASK Anima Step Cache: warmup_steps={warmup_steps} is less "
                f"than polynomial_degree+1 ({polynomial_degree + 1}). The first "
                "cached step will fall back to Taylor-only extrapolation to "
                "avoid mosaic artefacts. Raise warmup_steps or lower "
                "polynomial_degree to silence this."
            )
        state = {
            "forecaster": None,
            "step": 0,
            "cached_since_real": 0,
            "ws": float(window_size),
            "last_t": float("inf"),
            "stop_step": int(total_steps * stop_caching_at),
        }
        ws_base = float(window_size)

        def wrapper(model_function, kwargs):
            x = kwargs["input"]
            timestep = kwargs["timestep"]
            c = kwargs["c"]
            t_scalar = timestep[0].item() if isinstance(timestep, torch.Tensor) else float(timestep)

            # Higher t = earlier in the denoising schedule (flow models go
            # from large t to small t). If t rose, a new sampling pass is
            # starting — reset the forecaster.
            if t_scalar > state["last_t"]:
                if state["forecaster"]:
                    state["forecaster"].reset()
                state["step"] = 0
                state["cached_since_real"] = 0
                state["ws"] = ws_base
                state["forecaster"] = None
            state["last_t"] = t_scalar

            in_tail = state["step"] >= state["stop_step"]
            past_warmup = state["step"] >= warmup_steps

            if past_warmup and not in_tail:
                # Run the real model only every ws-th step; otherwise predict.
                run_real = ((state["cached_since_real"] + 1) % max(1, math.floor(state["ws"]))) == 0
            else:
                run_real = True

            if run_real:
                out = model_function(x, timestep, **c)
                if state["forecaster"] is None:
                    state["forecaster"] = _ChebyshevForecaster(
                        degree=polynomial_degree,
                        ridge=regularization,
                        total_steps=total_steps,
                    )
                state["forecaster"].push(state["step"], out)
                if past_warmup:
                    state["ws"] += flex_window
                state["cached_since_real"] = 0
            else:
                out = state["forecaster"].predict(state["step"], blend=prediction_weight).to(x.dtype)
                state["cached_since_real"] += 1

            state["step"] += 1
            return out

        m = model.clone()
        m.set_model_unet_function_wrapper(wrapper)

        info = (
            f"Cache active: w={prediction_weight:.2f} deg={polynomial_degree} "
            f"win={window_size}+{flex_window:.2f}/step warmup={warmup_steps} "
            f"stop@{stop_caching_at:.0%} of {total_steps}"
        )
        return {
            "ui": {"text": [info]},
            "result": (m, info),
        }
