"""DARASK custom nodes for ComfyUI."""
from .folder_loader import DARASK_FolderImageLoader
from .exif_apply import DARASK_ExifRead, DARASK_ExifApply
from .latent_preset import DARASK_EmptyLatentPreset


NODE_CLASS_MAPPINGS = {
    "DARASK Folder Image Loader": DARASK_FolderImageLoader,
    "DARASK Exif Read": DARASK_ExifRead,
    "DARASK Exif Apply": DARASK_ExifApply,
    "DARASK Empty Latent Preset": DARASK_EmptyLatentPreset,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DARASK Folder Image Loader": "DARASK Folder Image Loader",
    "DARASK Exif Read": "DARASK Exif Read",
    "DARASK Exif Apply": "DARASK Exif Apply (Model + LoRA + Prompt)",
    "DARASK Empty Latent Preset": "DARASK Empty Latent (Preset)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
