"""DARASK custom nodes for ComfyUI."""
from .folder_loader import DARASK_FolderImageLoader
from .exif_apply import DARASK_ExifRead, DARASK_ExifApply
from .latent_preset import DARASK_EmptyLatentPreset
from .prompt_cells import DARASK_PromptCell, DARASK_PromptCellOutput


NODE_CLASS_MAPPINGS = {
    "DARASK Folder Image Loader": DARASK_FolderImageLoader,
    "DARASK Exif Read": DARASK_ExifRead,
    "DARASK Exif Apply": DARASK_ExifApply,
    "DARASK Empty Latent Preset": DARASK_EmptyLatentPreset,
    "DARASK Prompt Cell": DARASK_PromptCell,
    "DARASK Prompt Cell Output": DARASK_PromptCellOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DARASK Folder Image Loader": "DARASK Folder Image Loader",
    "DARASK Exif Read": "DARASK Exif Read",
    "DARASK Exif Apply": "DARASK Exif Apply (Model + LoRA + Prompt)",
    "DARASK Empty Latent Preset": "DARASK Empty Latent (Preset)",
    "DARASK Prompt Cell": "DARASK Prompt Cell",
    "DARASK Prompt Cell Output": "DARASK Prompt Cell Output (CLIP Encode)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
