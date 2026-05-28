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
from .ltx23 import DARASK_LTX23VideoSettings, DARASK_FloatToInt
from .model_sampling import DARASK_AnimaSamplingTuner
from .step_cache import DARASK_AnimaStepCache

try:
    from .ltx23_generator import DARASK_LTX23Generator
    _HAS_LTX23_GEN = True
except Exception as _e:
    DARASK_LTX23Generator = None
    _HAS_LTX23_GEN = False
    import logging
    logging.warning(f"DARASK LTX 2.3 Generator unavailable (likely missing comfy_extras): {_e}")
from .prompt_cells import DARASK_PromptCell, DARASK_PromptCellOutput
from .rife_loader import DARASK_RIFEInterpolation

try:
    from .video_loader import DARASK_LoadVideoUpload, DARASK_VideoInfo
    _HAS_VIDEO_LOADER = True
except Exception as _e:
    DARASK_LoadVideoUpload = None
    DARASK_VideoInfo = None
    _HAS_VIDEO_LOADER = False
    import logging
    logging.warning(f"DARASK Video loader unavailable (likely missing opencv-python): {_e}")


NODE_CLASS_MAPPINGS = {
    "DARASK Folder Image Loader": DARASK_FolderImageLoader,
    "DARASK Exif Read": DARASK_ExifRead,
    "DARASK Exif Apply": DARASK_ExifApply,
    "DARASK Exif Apply Anima": DARASK_ExifApplyAnima,
    "DARASK Exif Apply SDXL": DARASK_ExifApplySDXL,
    "DARASK Empty Latent Preset": DARASK_EmptyLatentPreset,
    "DARASK Lora Loader": DARASK_LoraLoader,
    "DARASK LTX23 Video Settings": DARASK_LTX23VideoSettings,
    "DARASK Float to Int": DARASK_FloatToInt,
    "DARASK Anima Sampling Tuner": DARASK_AnimaSamplingTuner,
    "DARASK Anima Step Cache": DARASK_AnimaStepCache,
    **({"DARASK LTX 2.3 Generator": DARASK_LTX23Generator} if _HAS_LTX23_GEN else {}),
    "DARASK Prompt Cell": DARASK_PromptCell,
    "DARASK Prompt Cell Output": DARASK_PromptCellOutput,
    **({
        "DARASK Load Video Upload": DARASK_LoadVideoUpload,
        "DARASK Video Info": DARASK_VideoInfo,
    } if _HAS_VIDEO_LOADER else {}),
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
    "DARASK LTX23 Video Settings": "DARASK LTX 2.3 Video Settings",
    "DARASK Float to Int": "DARASK Float → Int",
    "DARASK Anima Sampling Tuner": "DARASK Anima Sampling Tuner",
    "DARASK Anima Step Cache": "DARASK Anima Step Cache (Spectrum)",
    **({"DARASK LTX 2.3 Generator": "DARASK LTX 2.3 Generator (All-in-One)"} if _HAS_LTX23_GEN else {}),
    "DARASK Prompt Cell": "DARASK Prompt Cell",
    "DARASK Prompt Cell Output": "DARASK Prompt Cell Output (CLIP Encode)",
    **({
        "DARASK Load Video Upload": "DARASK Load Video (Upload)",
        "DARASK Video Info": "DARASK Video Info",
    } if _HAS_VIDEO_LOADER else {}),
    "DARASK RIFE Interpolation": "DARASK RIFE Interpolation",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
