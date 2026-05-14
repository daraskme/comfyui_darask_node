"""DARASK custom nodes for ComfyUI."""
from .folder_loader import DARASK_FolderImageLoader
from .exif_apply import (
    DARASK_ExifRead,
    DARASK_ExifApply,
    DARASK_ExifApplyAnima,
    DARASK_ExifApplySDXL,
)
from .latent_preset import DARASK_EmptyLatentPreset
from .lora_loader import DARASK_LoraLoader
from .prompt_cells import DARASK_PromptCell, DARASK_PromptCellOutput
from .rife_loader import DARASK_RIFEInterpolation
from .video_loader import DARASK_LoadVideoUpload, DARASK_VideoInfo


NODE_CLASS_MAPPINGS = {
    "DARASK Folder Image Loader": DARASK_FolderImageLoader,
    "DARASK Exif Read": DARASK_ExifRead,
    "DARASK Exif Apply": DARASK_ExifApply,
    "DARASK Exif Apply Anima": DARASK_ExifApplyAnima,
    "DARASK Exif Apply SDXL": DARASK_ExifApplySDXL,
    "DARASK Empty Latent Preset": DARASK_EmptyLatentPreset,
    "DARASK Lora Loader": DARASK_LoraLoader,
    "DARASK Prompt Cell": DARASK_PromptCell,
    "DARASK Prompt Cell Output": DARASK_PromptCellOutput,
    "DARASK Load Video Upload": DARASK_LoadVideoUpload,
    "DARASK Video Info": DARASK_VideoInfo,
    "DARASK RIFE Interpolation": DARASK_RIFEInterpolation,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DARASK Folder Image Loader": "DARASK Folder Image Loader",
    "DARASK Exif Read": "DARASK Exif Read",
    "DARASK Exif Apply": "DARASK Exif Apply (Auto-detect)",
    "DARASK Exif Apply Anima": "DARASK Exif Apply (Anima / UNET stack)",
    "DARASK Exif Apply SDXL": "DARASK Exif Apply (SDXL / Checkpoint)",
    "DARASK Empty Latent Preset": "DARASK Empty Latent (Preset)",
    "DARASK Lora Loader": "DARASK Lora Loader",
    "DARASK Prompt Cell": "DARASK Prompt Cell",
    "DARASK Prompt Cell Output": "DARASK Prompt Cell Output (CLIP Encode)",
    "DARASK Load Video Upload": "DARASK Load Video (Upload)",
    "DARASK Video Info": "DARASK Video Info",
    "DARASK RIFE Interpolation": "DARASK RIFE Interpolation",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
