"""
DARASK Folder Image Loader.

A single node that combines D2 Folder Image Queue + D2 Load Image:
reads a folder, picks one image (or all as a batch), and outputs the image
plus its EXIF metadata, mask, dimensions, and prompt strings.

Auto-advance cursor is keyed by the node's workflow ID so it survives
instance recreation (workflow edits, hot-reloads). Folder / sort changes
auto-reset the cursor so a different listing starts from index 0.
"""
from __future__ import annotations

import os

import torch

from comfy_execution.graph_utils import ExecutionBlocker

from . import meta_util


class DARASK_FolderImageLoader:
    """Folder-driven image loader with auto-advance, manual index, or batch modes."""

    # Keyed by workflow node ID so the cursor doesn't get lost on workflow
    # edits that recreate the Python instance.
    _state: dict[str, dict] = {}

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
                "loop": ("BOOLEAN", {"default": True}),
                "reset": ("BOOLEAN", {"default": False}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (
        "IMAGE", "MASK",
        "INT", "INT",
        "STRING", "STRING",
        "STRING", "STRING", "STRING",
        "INT", "INT", "STRING",
    )
    RETURN_NAMES = (
        "image", "mask",
        "width", "height",
        "positive", "negative",
        "filename", "filepath", "raw_metadata",
        "current_index", "total_count", "progress",
    )
    FUNCTION = "run"
    CATEGORY = "DARASK"

    @classmethod
    def IS_CHANGED(cls, mode, folder, extension, index, sort_by, order_by, loop, reset, **kwargs):
        # Auto Advance, Random sort, and explicit reset must always re-execute
        # so the queue actually moves / the cursor zeros.
        if mode == "Auto Advance" or sort_by == "Random" or reset:
            return float("nan")
        return f"{folder}|{extension}|{mode}|{index}|{sort_by}|{order_by}|{loop}"

    def run(self, folder, extension, mode, index, sort_by, order_by, loop, reset, unique_id=None):
        files = meta_util.list_folder_images(folder, extension, sort_by, order_by)
        total = len(files)
        if total == 0:
            raise ValueError(f"DARASK Folder Image Loader: no files in '{folder}' matching '{extension}'")

        state_key = str(unique_id) if unique_id is not None else f"_inst_{id(self)}"
        state = self._state.setdefault(state_key, {"cursor": 0, "signature": ""})

        # Auto-reset when the listing changed under us — different folder,
        # extension filter, sort key, or even just a different file count.
        # Without this the cursor from the previous folder would silently
        # carry over and you'd see "starts from index 5" type bugs.
        signature = f"{folder}|{extension}|{sort_by}|{order_by}|{total}"
        if state.get("signature") != signature:
            state["cursor"] = 0
            state["signature"] = signature

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
            _, _, info = meta_util.load_image_with_meta(files[0])
            raw = meta_util.get_raw_metadata(info)
            parsed = meta_util.parse_a1111(raw)
            progress = f"1-{total}/{total} (batch)"
            ui_payload = {"text": [progress]}
            return {
                "ui": ui_payload,
                "result": (
                    batch, mask_batch,
                    int(batch.shape[2]), int(batch.shape[1]),
                    parsed["positive"], parsed["negative"],
                    os.path.basename(files[0]), files[0], raw,
                    0, total, progress,
                ),
            }

        done = False
        if mode == "Manual Index":
            cur = max(0, min(index, total - 1)) if total > 0 else 0
            suffix = " (manual)"
        else:  # Auto Advance
            cur = state["cursor"]
            if cur >= total:
                if loop:
                    cur = 0
                else:
                    done = True
            suffix = " (done)" if done else ""

        if done:
            # End of folder reached with loop=False. Block downstream once
            # so this queue doesn't re-save the same last image, and then
            # auto-reset the cursor to 0 so the NEXT queue starts over from
            # the beginning. That way both Auto Queue (instant) and regular
            # manual Queue Prompt clicks work intuitively:
            #
            # * Auto Queue: one blocked queue lands between passes — the
            #   green "(done)" pill on the node is your cue to stop the
            #   auto-queue if you only wanted one pass.
            # * Manual Queue Prompt: pressing Queue past the end skips one
            #   image cleanly (no duplicate save, no error) and the next
            #   press resumes from image 0 — no need to toggle `reset`.
            progress = f"{total}/{total} (done)"
            blocker = ExecutionBlocker(
                f"DARASK Folder Image Loader: folder fully processed "
                f"({total}/{total}). Cursor reset — next queue starts at 1/{total}."
            )
            state["cursor"] = 0
            return {
                "ui": {"text": [progress]},
                "result": (blocker,) * len(self.RETURN_TYPES),
            }

        filepath = files[cur]
        image, mask, info = meta_util.load_image_with_meta(filepath)
        raw = meta_util.get_raw_metadata(info)
        parsed = meta_util.parse_a1111(raw)

        if mode == "Auto Advance":
            next_cur = cur + 1
            if next_cur >= total and loop:
                next_cur = 0
            state["cursor"] = next_cur

        progress = f"{cur + 1}/{total}{suffix}"
        ui_payload = {"text": [progress]}
        return {
            "ui": ui_payload,
            "result": (
                image, mask,
                int(image.shape[2]), int(image.shape[1]),
                parsed["positive"], parsed["negative"],
                os.path.basename(filepath), filepath, raw,
                cur, total, progress,
            ),
        }


