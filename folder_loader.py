"""
DARASK Folder Image Loader.

A single node that combines D2 Folder Image Queue + D2 Load Image:
reads a folder, picks one image (or all as a batch), and outputs the image
plus its EXIF metadata, mask, dimensions, and prompt strings.
"""
from __future__ import annotations

import os

import torch

from . import meta_util


class DARASK_FolderImageLoader:
    """Folder-driven image loader with auto-advance, manual index, or batch modes."""

    # Per-node-instance counters for Auto Advance mode.
    _state: dict[int, dict] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder": ("STRING", {"default": ""}),
                "extension": ("STRING", {"default": "*.*"}),
                "mode": (
                    ["Auto Advance", "Manual Index", "All as Batch"],
                    {"default": "Auto Advance"},
                ),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "sort_by": (["Name", "Date", "Random"], {"default": "Name"}),
                "order_by": (["A-Z", "Z-A"], {"default": "A-Z"}),
                "loop": ("BOOLEAN", {"default": False}),
                "reset": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = (
        "IMAGE", "MASK",
        "INT", "INT",
        "STRING", "STRING",
        "STRING", "STRING", "STRING",
        "INT", "INT",
    )
    RETURN_NAMES = (
        "image", "mask",
        "width", "height",
        "positive", "negative",
        "filename", "filepath", "raw_metadata",
        "current_index", "total_count",
    )
    FUNCTION = "run"
    CATEGORY = "DARASK"

    @classmethod
    def IS_CHANGED(cls, mode, folder, extension, index, sort_by, order_by, loop, reset):
        # Auto Advance and Random sort must always re-execute so the queue moves forward.
        if mode == "Auto Advance" or sort_by == "Random":
            return float("nan")
        return f"{folder}|{extension}|{mode}|{index}|{sort_by}|{order_by}|{loop}"

    def run(self, folder, extension, mode, index, sort_by, order_by, loop, reset):
        files = meta_util.list_folder_images(folder, extension, sort_by, order_by)
        total = len(files)
        if total == 0:
            raise ValueError(f"DARASK Folder Image Loader: no files in '{folder}' matching '{extension}'")

        state_key = id(self)
        state = self._state.setdefault(state_key, {"cursor": 0})

        if reset:
            state["cursor"] = 0

        if mode == "All as Batch":
            images, masks = [], []
            for fp in files:
                img, mask, _ = meta_util.load_image_with_meta(fp)
                images.append(img)
                masks.append(mask)
            batch = torch.cat(images, dim=0)
            mask_batch = torch.cat(masks, dim=0)
            # Read meta from the first file so downstream EXIF nodes have something to work with.
            _, _, info = meta_util.load_image_with_meta(files[0])
            raw = meta_util.get_raw_metadata(info)
            parsed = meta_util.parse_a1111(raw)
            return (
                batch, mask_batch,
                int(batch.shape[2]), int(batch.shape[1]),
                parsed["positive"], parsed["negative"],
                os.path.basename(files[0]), files[0], raw,
                0, total,
            )

        if mode == "Manual Index":
            cur = max(0, min(index, total - 1)) if total > 0 else 0
        else:  # Auto Advance
            cur = state["cursor"]
            if cur >= total:
                if loop:
                    cur = 0
                else:
                    cur = total - 1

        filepath = files[cur]
        image, mask, info = meta_util.load_image_with_meta(filepath)
        raw = meta_util.get_raw_metadata(info)
        parsed = meta_util.parse_a1111(raw)

        # Advance the cursor for next run (Auto Advance only).
        if mode == "Auto Advance":
            state["cursor"] = cur + 1
            if state["cursor"] >= total and loop:
                state["cursor"] = 0

        return (
            image, mask,
            int(image.shape[2]), int(image.shape[1]),
            parsed["positive"], parsed["negative"],
            os.path.basename(filepath), filepath, raw,
            cur, total,
        )


