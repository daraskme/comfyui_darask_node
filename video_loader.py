"""
DARASK video helpers.

Clean-room cv2-based equivalents of VHS_LoadVideo / VHS_VideoInfo, with no
dependency on ComfyUI-VideoHelperSuite or its GPL code. Intended for the
"load a video → interpolate frames → score audio with MMAudio" pipeline.

* DARASK Load Video (Upload) — UI shows an upload button (standard ComfyUI
  `video_upload` widget). Reads the video with OpenCV, optionally
  resampling the frame rate, skipping leading frames, sub-sampling every
  Nth frame, or capping the total frame count. Emits IMAGE, frame_count,
  and a DARASK_VIDEO_INFO dict.
* DARASK Video Info — splits a DARASK_VIDEO_INFO dict into individual
  scalar outputs (source_fps, loaded_duration, etc.).

The DARASK_VIDEO_INFO dict carries:
    source_fps, source_frame_count, source_duration, source_width, source_height,
    loaded_fps, loaded_frame_count, loaded_duration, loaded_width, loaded_height
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import torch

try:
    import cv2
except ImportError as e:
    raise ImportError(
        "DARASK video helpers require opencv-python. Install with "
        "`pip install opencv-python`."
    ) from e

import folder_paths


VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".gif", ".avi", ".m4v")


def _list_input_videos() -> list[str]:
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return []
    out = []
    for name in os.listdir(input_dir):
        full = os.path.join(input_dir, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in VIDEO_EXTS:
            out.append(name)
    out.sort(key=str.lower)
    return out


def _read_video(
    filepath: str,
    force_rate: float,
    frame_load_cap: int,
    skip_first_frames: int,
    select_every_nth: int,
    custom_width: int,
    custom_height: int,
) -> tuple[torch.Tensor, dict]:
    """
    Decode `filepath` with OpenCV. Returns (IMAGE_tensor, info_dict).

    `force_rate > 0` resamples the source FPS to that rate by nearest-frame
    selection. `select_every_nth > 1` keeps every Nth frame after that.
    `skip_first_frames` drops leading frames. `frame_load_cap > 0` caps the
    total returned frame count. `custom_width` / `custom_height` resize each
    frame (0 = source size).
    """
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        raise ValueError(f"DARASK Load Video: cannot open {filepath!r}")

    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    src_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    src_duration = (src_total / src_fps) if src_fps > 0 else 0.0

    # Plan which source frames to actually decode.
    target_fps = src_fps if force_rate <= 0 else float(force_rate)
    if target_fps <= 0:
        target_fps = src_fps if src_fps > 0 else 30.0

    # Build the index list to keep.
    if force_rate > 0 and src_fps > 0 and abs(force_rate - src_fps) > 1e-3:
        # Resample by nearest source frame for each target tick.
        if src_duration > 0:
            n_target = int(src_duration * target_fps)
        else:
            n_target = src_total
        indices = []
        for k in range(n_target):
            t = k / target_fps
            src_idx = int(round(t * src_fps))
            if 0 <= src_idx < src_total:
                indices.append(src_idx)
    else:
        # Use all source frames; force_rate is effectively the source rate.
        indices = list(range(src_total)) if src_total > 0 else []

    # Apply skip + every-nth + cap.
    if skip_first_frames > 0:
        indices = indices[skip_first_frames:]
    if select_every_nth > 1:
        indices = indices[::select_every_nth]
        target_fps = target_fps / select_every_nth
    if frame_load_cap > 0:
        indices = indices[:frame_load_cap]

    if not indices:
        cap.release()
        raise ValueError(
            f"DARASK Load Video: no frames selected from {os.path.basename(filepath)} "
            f"(source has {src_total} frames @ {src_fps:.2f} fps)."
        )

    # Decode by seeking — fall back to sequential if seek fails.
    frames: list[np.ndarray] = []
    needed = set(indices)
    max_needed = max(indices)

    # Sequential pass — for typical mp4 this is faster + more reliable than
    # per-frame seeks.
    pos = 0
    while pos <= max_needed:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if pos in needed:
            # cv2 returns BGR; ComfyUI expects RGB.
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if custom_width > 0 or custom_height > 0:
                cw = custom_width if custom_width > 0 else rgb.shape[1]
                ch = custom_height if custom_height > 0 else rgb.shape[0]
                # Match upstream aspect if only one dim was given.
                if custom_width > 0 and custom_height == 0:
                    ch = int(round(rgb.shape[0] * (cw / rgb.shape[1])))
                elif custom_height > 0 and custom_width == 0:
                    cw = int(round(rgb.shape[1] * (ch / rgb.shape[0])))
                rgb = cv2.resize(rgb, (cw, ch), interpolation=cv2.INTER_AREA)
            frames.append(rgb)
        pos += 1
    cap.release()

    if not frames:
        raise ValueError(
            f"DARASK Load Video: decoded zero frames from {os.path.basename(filepath)}."
        )

    arr = np.stack(frames).astype(np.float32) / 255.0
    tensor = torch.from_numpy(arr)  # [N, H, W, 3]

    loaded_h, loaded_w = tensor.shape[1], tensor.shape[2]
    loaded_count = tensor.shape[0]
    loaded_duration = loaded_count / target_fps if target_fps > 0 else 0.0

    info = {
        "source_fps": float(src_fps),
        "source_frame_count": int(src_total),
        "source_duration": float(src_duration),
        "source_width": int(src_w),
        "source_height": int(src_h),
        "loaded_fps": float(target_fps),
        "loaded_frame_count": int(loaded_count),
        "loaded_duration": float(loaded_duration),
        "loaded_width": int(loaded_w),
        "loaded_height": int(loaded_h),
        "filepath": filepath,
    }
    return tensor, info


class DARASK_LoadVideoUpload:
    """
    Load a video file from ComfyUI's input/ directory.

    The `video` widget gets a standard ComfyUI upload button (the
    `video_upload` hint). The decoded frames are emitted as a single batched
    IMAGE tensor, alongside the frame count and a DARASK_VIDEO_INFO dict.
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "INT", "DARASK_VIDEO_INFO")
    RETURN_NAMES = ("IMAGE", "frame_count", "video_info")

    @classmethod
    def INPUT_TYPES(cls):
        files = _list_input_videos()
        return {
            "required": {
                "video": (files if files else ["(no videos in input/)"], {"video_upload": True}),
                "force_rate": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 240.0, "step": 0.1,
                    "tooltip": "Resample to this FPS (0 = keep source FPS).",
                }),
                "custom_width": ("INT", {
                    "default": 0, "min": 0, "max": 8192, "step": 1,
                    "tooltip": "Resize width (0 = source).",
                }),
                "custom_height": ("INT", {
                    "default": 0, "min": 0, "max": 8192, "step": 1,
                    "tooltip": "Resize height (0 = source).",
                }),
                "frame_load_cap": ("INT", {
                    "default": 0, "min": 0, "max": 0x7FFFFFFF, "step": 1,
                    "tooltip": "Max frames to load (0 = all).",
                }),
                "skip_first_frames": ("INT", {
                    "default": 0, "min": 0, "max": 0x7FFFFFFF, "step": 1,
                    "tooltip": "Drop this many leading frames.",
                }),
                "select_every_nth": ("INT", {
                    "default": 1, "min": 1, "max": 100, "step": 1,
                    "tooltip": "Keep every Nth frame after skipping.",
                }),
            },
        }

    @classmethod
    def IS_CHANGED(cls, video, **kwargs):
        # Hash by file mtime so re-uploads invalidate the cache.
        path = folder_paths.get_annotated_filepath(video)
        try:
            return f"{path}|{os.path.getmtime(path)}"
        except OSError:
            return path

    @classmethod
    def VALIDATE_INPUTS(cls, video, **kwargs):
        if not video or video.startswith("(no videos"):
            return "No video selected — upload one via the widget's button."
        path = folder_paths.get_annotated_filepath(video)
        if not os.path.isfile(path):
            return f"Video file not found: {path}"
        return True

    def run(self, video, force_rate, custom_width, custom_height,
            frame_load_cap, skip_first_frames, select_every_nth):
        path = folder_paths.get_annotated_filepath(video)
        if not os.path.isfile(path):
            raise ValueError(f"DARASK Load Video: file not found: {path}")
        tensor, info = _read_video(
            path,
            force_rate=force_rate,
            frame_load_cap=frame_load_cap,
            skip_first_frames=skip_first_frames,
            select_every_nth=select_every_nth,
            custom_width=custom_width,
            custom_height=custom_height,
        )
        return (tensor, info["loaded_frame_count"], info)


class DARASK_VideoInfo:
    """
    Unpack a DARASK_VIDEO_INFO dict into individual scalar outputs.

    Mirrors VHS_VideoInfo's split between *source* properties (what was in
    the file on disk) and *loaded* properties (what came out of the loader
    after force_rate / select_every_nth / cap were applied).
    """

    CATEGORY = "DARASK"
    FUNCTION = "run"
    RETURN_TYPES = (
        "FLOAT", "INT", "FLOAT", "INT", "INT",
        "FLOAT", "INT", "FLOAT", "INT", "INT",
    )
    RETURN_NAMES = (
        "source_fps", "source_frame_count", "source_duration",
        "source_width", "source_height",
        "loaded_fps", "loaded_frame_count", "loaded_duration",
        "loaded_width", "loaded_height",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video_info": ("DARASK_VIDEO_INFO",)}}

    def run(self, video_info: dict[str, Any]):
        return (
            float(video_info.get("source_fps", 0.0)),
            int(video_info.get("source_frame_count", 0)),
            float(video_info.get("source_duration", 0.0)),
            int(video_info.get("source_width", 0)),
            int(video_info.get("source_height", 0)),
            float(video_info.get("loaded_fps", 0.0)),
            int(video_info.get("loaded_frame_count", 0)),
            float(video_info.get("loaded_duration", 0.0)),
            int(video_info.get("loaded_width", 0)),
            int(video_info.get("loaded_height", 0)),
        )
