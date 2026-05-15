"""
DARASK Folder Image Loader.

A single node that combines D2 Folder Image Queue + D2 Load Image:
reads a folder, picks one image (or all as a batch), and outputs the image
plus its EXIF metadata, mask, dimensions, and prompt strings.

Auto-advance cursor is keyed by the node's workflow ID so it survives
instance recreation (workflow edits, hot-reloads). Folder / sort changes
auto-reset the cursor so a different listing starts from index 0.

`auto_queue_all = True` makes the node *self-enqueue* the same workflow
once per image until the whole folder is processed — so a single press of
the regular Queue Prompt button is enough to chew through the entire
folder (no need to leave Auto Queue / instant turned on).
"""
from __future__ import annotations

import os
import time
import uuid as _uuid

import torch

from comfy_execution.graph_utils import ExecutionBlocker

from . import meta_util


def _enqueue_self(prompt_dict, extra_pnginfo) -> bool:
    """
    Programmatically push another copy of the current workflow onto
    ComfyUI's prompt queue. Returns True on success.

    Equivalent to one press of the frontend's "Queue Prompt" button —
    used to chain through every file in the folder from a single user
    queue press when `auto_queue_all` is on.
    """
    try:
        from server import PromptServer  # type: ignore
        from nodes import NODE_CLASS_MAPPINGS  # type: ignore
    except Exception as e:
        print(f"DARASK Folder Image Loader: cannot import PromptServer ({e})")
        return False

    ps = getattr(PromptServer, "instance", None)
    if ps is None or not isinstance(prompt_dict, dict):
        return False

    # Output nodes = anything with class-level OUTPUT_NODE=True.
    outputs_to_execute: list[str] = []
    for nid, node_data in prompt_dict.items():
        if not isinstance(node_data, dict):
            continue
        ct = node_data.get("class_type")
        if not ct:
            continue
        klass = NODE_CLASS_MAPPINGS.get(ct)
        if klass is not None and getattr(klass, "OUTPUT_NODE", False):
            outputs_to_execute.append(nid)
    if not outputs_to_execute:
        return False

    # Build the same 6-tuple PromptServer.put uses on the /prompt endpoint.
    number = ps.number if hasattr(ps, "number") else 0
    if hasattr(ps, "number"):
        ps.number += 1
    prompt_id = str(_uuid.uuid4())
    extra_data: dict = {"create_time": int(time.time() * 1000)}
    if extra_pnginfo:
        extra_data["extra_pnginfo"] = extra_pnginfo
    if getattr(ps, "client_id", None) is not None:
        extra_data["client_id"] = ps.client_id
    sensitive: dict = {}

    try:
        ps.prompt_queue.put(
            (number, prompt_id, prompt_dict, extra_data, outputs_to_execute, sensitive)
        )
        return True
    except Exception as e:
        print(f"DARASK Folder Image Loader: self-enqueue failed: {e}")
        import traceback
        traceback.print_exc()
        return False


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
                "auto_queue_all": ("BOOLEAN", {
                    "default": True,
                    "tooltip": (
                        "Auto Advance mode only: after each generated image, "
                        "the node enqueues another copy of the workflow so a "
                        "single press of the regular Queue Prompt button "
                        "processes the entire folder. Turn off to require one "
                        "manual queue press per image."
                    ),
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
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
        auto_queue_all = kwargs.get("auto_queue_all", False)
        return f"{folder}|{extension}|{mode}|{index}|{sort_by}|{order_by}|{loop}|{auto_queue_all}"

    def run(self, folder, extension, mode, index, sort_by, order_by, loop, reset,
            auto_queue_all=True, unique_id=None, prompt=None, extra_pnginfo=None):
        files = meta_util.list_folder_images(folder, extension, sort_by, order_by)
        total = len(files)
        if total == 0:
            raise ValueError(f"DARASK Folder Image Loader: no files in '{folder}' matching '{extension}'")

        state_key = str(unique_id) if unique_id is not None else f"_inst_{id(self)}"
        state = self._state.setdefault(state_key, {"cursor": 0, "signature": ""})

        # Auto-reset when the listing changed under us — different folder,
        # extension filter, sort key, or even just a different file count.
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
            return {
                "ui": {"text": [progress]},
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
            # End of folder reached with loop=False. Silently block the
            # downstream nodes (no error toast — ExecutionBlocker(None))
            # and reset the cursor so the next queue press starts over.
            progress = f"{total}/{total} (done)"
            blocker = ExecutionBlocker(None)
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

            # Self-enqueue another run if there's more work to do.
            # * loop=True: keep going only while we advance (next_cur > cur).
            #   Once we'd wrap (next_cur < cur), stop — that's one full pass.
            # * loop=False: keep going while next_cur < total.
            if auto_queue_all:
                if loop:
                    more = next_cur > cur
                else:
                    more = next_cur < total
                if more:
                    _enqueue_self(prompt, extra_pnginfo)

        progress = f"{cur + 1}/{total}{suffix}"
        return {
            "ui": {"text": [progress]},
            "result": (
                image, mask,
                int(image.shape[2]), int(image.shape[1]),
                parsed["positive"], parsed["negative"],
                os.path.basename(filepath), filepath, raw,
                cur, total, progress,
            ),
        }
