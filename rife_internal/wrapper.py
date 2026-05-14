"""
RIFE inference wrapper. Adapts the IFNet `Model` to ComfyUI's IMAGE tensor
layout ([N, H, W, 3] float in [0,1]) and streams batches through the GPU so
long sequences don't blow up VRAM.

Derived from the ComfyUI-VFI inference wrapper; the underlying Model /
IFNet code is from hzwer's MIT-licensed RIFE.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import torch
from torch.nn import functional as F

from .train_log.RIFE_HDv3 import Model


class RIFEWrapper:
    """Wrapper around the RIFE Model for ComfyUI IMAGE tensors."""

    def __init__(self, model_path: str, device: Optional[torch.device] = None, use_fp16: bool = False):
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.use_fp16 = use_fp16 and torch.cuda.is_available()

        torch.set_grad_enabled(False)
        if torch.cuda.is_available():
            torch.backends.cudnn.enabled = True
            torch.backends.cudnn.benchmark = True

        self.model = Model()
        self.model.load_model(model_path, -1)
        self.model.eval()
        self.model.device()

        if self.use_fp16:
            self.model.flownet = self.model.flownet.half()

    def interpolate_frames(
        self,
        images: torch.Tensor,
        source_fps: float,
        target_fps: float,
        scale: float = 1.0,
        progress_callback=None,
        batch_size: int = 8,
    ) -> torch.Tensor:
        assert images.dim() == 4 and images.shape[-1] == 3, "Input must be [N, H, W, 3]"

        if source_fps == target_fps:
            return images

        total_source_frames = images.shape[0]
        height, width = images.shape[1:3]

        # Pad to a multiple compatible with RIFE's scale pyramid.
        tmp = max(128, int(128 / scale))
        ph = ((height - 1) // tmp + 1) * tmp
        pw = ((width - 1) // tmp + 1) * tmp
        padding = (0, pw - width, 0, ph - height)

        frame_positions = self._target_frame_positions(source_fps, target_fps, total_source_frames)

        output_frames: list = []
        interp_jobs: list[Tuple[int, int, float]] = []
        output_index_map: dict = {}

        for out_idx, (src1, src2, t) in enumerate(frame_positions):
            if t == 0.0 or src1 == src2:
                output_frames.append(images[src1])
            else:
                output_frames.append(None)
                output_index_map[len(interp_jobs)] = out_idx
                interp_jobs.append((src1, src2, t))

        num_jobs = len(interp_jobs)
        gpu_dtype = torch.float16 if self.use_fp16 else torch.float32

        with torch.inference_mode():
            for batch_start in range(0, num_jobs, batch_size):
                batch_end = min(batch_start + batch_size, num_jobs)
                cur_bs = batch_end - batch_start

                needed = set()
                for j in range(batch_start, batch_end):
                    a, b, _ = interp_jobs[j]
                    needed.add(a)
                    needed.add(b)
                cache = {i: images[i].to(device=self.device, dtype=gpu_dtype) for i in needed}

                batch_I0 = torch.empty((cur_bs, 3, ph, pw), dtype=gpu_dtype, device=self.device)
                batch_I1 = torch.empty((cur_bs, 3, ph, pw), dtype=gpu_dtype, device=self.device)
                timesteps: List[float] = []
                for i, j in enumerate(range(batch_start, batch_end)):
                    src1, src2, t = interp_jobs[j]
                    I0 = cache[src1].permute(2, 0, 1).unsqueeze(0)
                    I1 = cache[src2].permute(2, 0, 1).unsqueeze(0)
                    batch_I0[i] = F.pad(I0, padding)[0]
                    batch_I1[i] = F.pad(I1, padding)[0]
                    timesteps.append(t)

                out = self.model.inference_batch(batch_I0, batch_I1, timesteps, scale=scale)

                for i, j in enumerate(range(batch_start, batch_end)):
                    output_frames[output_index_map[j]] = (
                        out[i, :, :height, :width].permute(1, 2, 0).cpu().to(torch.float32)
                    )

                if progress_callback:
                    progress_callback(batch_end, num_jobs)

                del batch_I0, batch_I1, out, cache
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        return torch.stack(output_frames, dim=0)

    @staticmethod
    def _target_frame_positions(
        source_fps: float, target_fps: float, total_source_frames: int
    ) -> List[Tuple[int, int, float]]:
        positions = []
        duration = total_source_frames / source_fps
        total_target_frames = int(duration * target_fps)
        for k in range(total_target_frames):
            t = k / target_fps
            src_pos = t * source_fps
            a = int(src_pos)
            b = min(a + 1, total_source_frames - 1)
            tt = 0.0 if a == b else src_pos - a
            positions.append((a, b, tt))
        return positions
