"""
Metadata helpers for DARASK nodes.

Parses A1111 / ComfyUI / NovelAI style EXIF / PNG info, extracts LoRA tags,
and resolves model file names against ComfyUI's folder_paths.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths

try:
    import piexif
    import piexif.helper
    HAS_PIEXIF = True
except ImportError:
    HAS_PIEXIF = False


LORA_TAG_RE = re.compile(r"<lora:([^:>]+?)(?::([-\d.]+))?(?::([-\d.]+))?>")
PARAM_LINE_KEYS = (
    "Steps", "Sampler", "Schedule type", "Schedule", "CFG scale", "CFG",
    "Seed", "Size", "Model", "Model hash", "Denoising strength", "Denoise",
    "Clip skip", "VAE", "VAE hash", "Hires upscale", "Hires steps",
    "Hires upscaler", "Lora hashes", "TI hashes", "Version",
)


def _decode_user_comment(exif_bytes: bytes) -> str | None:
    if not HAS_PIEXIF:
        return None
    try:
        exif_data = piexif.load(exif_bytes)
        uc = exif_data.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
        if not uc:
            return None
        return piexif.helper.UserComment.load(uc)
    except Exception:
        return None


def get_raw_metadata(img_or_info) -> str:
    """
    Return the raw A1111-style metadata text from a PIL.Image *or* an info dict.
    """
    if isinstance(img_or_info, dict):
        items = img_or_info.copy()
    else:
        items = (img_or_info.info or {}).copy()

    if "parameters" in items:
        return items["parameters"]

    if "exif" in items:
        comment = _decode_user_comment(items["exif"])
        if comment:
            return comment

    if "prompt" in items or "workflow" in items:
        # ComfyUI native — return prompt JSON so caller can parse
        return items.get("prompt", "") or items.get("workflow", "")

    if items.get("Software") == "NovelAI":
        return items.get("Comment", "")

    return ""


def parse_a1111(text: str) -> dict[str, Any]:
    """
    Parse A1111-style metadata into a dict with keys:
        positive, negative, params (dict of Steps/Sampler/etc.)
    """
    result = {"positive": "", "negative": "", "params": {}}
    if not text:
        return result

    # Find the params line (last non-empty line that begins with "Steps:")
    lines = text.split("\n")
    params_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*Steps:\s*\d", line):
            params_idx = i
            break

    if params_idx >= 0:
        params_text = " ".join(lines[params_idx:]).strip()
        prompt_text = "\n".join(lines[:params_idx]).rstrip()
    else:
        params_text = ""
        prompt_text = text

    # Split positive / negative on "Negative prompt:"
    neg_split = re.split(r"\nNegative prompt:\s*", prompt_text, maxsplit=1)
    if len(neg_split) == 2:
        result["positive"] = neg_split[0].strip()
        result["negative"] = neg_split[1].strip()
    else:
        result["positive"] = prompt_text.strip()
        result["negative"] = ""

    if params_text:
        result["params"] = _parse_params_line(params_text)

    return result


_KEY_RE = re.compile(r"\s*([A-Za-z][A-Za-z0-9 _]*?):\s*")


def _parse_params_line(text: str) -> dict[str, str]:
    """Parse `Steps: 20, Sampler: euler, ...` style lines, respecting quoted values."""
    params: dict[str, str] = {}
    pos = 0
    n = len(text)
    while pos < n:
        m = _KEY_RE.match(text, pos)
        if not m:
            break
        key = m.group(1).strip()
        pos = m.end()

        if pos < n and text[pos] == '"':
            end_quote = text.find('"', pos + 1)
            if end_quote == -1:
                value = text[pos + 1:]
                pos = n
            else:
                value = text[pos + 1:end_quote]
                pos = end_quote + 1
        else:
            # Scan forward for next ", Key:" boundary
            search_pos = pos
            value_end = n
            while search_pos < n:
                comma = text.find(",", search_pos)
                if comma == -1:
                    break
                # Check if a key starts after this comma
                after = comma + 1
                if _KEY_RE.match(text, after):
                    value_end = comma
                    break
                search_pos = comma + 1
            value = text[pos:value_end].strip()
            pos = value_end

        # Skip trailing comma + whitespace
        while pos < n and text[pos] in ", \t":
            pos += 1

        params[key] = value
    return params


def extract_loras(prompt: str) -> tuple[str, list[tuple[str, float, float]]]:
    """
    Extract `<lora:name:weight[:clip_weight]>` tags from a prompt.
    Returns (cleaned_prompt, [(name, model_weight, clip_weight), ...]).
    """
    loras: list[tuple[str, float, float]] = []

    def _repl(m: re.Match) -> str:
        name = m.group(1).strip()
        try:
            mw = float(m.group(2)) if m.group(2) else 1.0
        except ValueError:
            mw = 1.0
        try:
            cw = float(m.group(3)) if m.group(3) else mw
        except ValueError:
            cw = mw
        loras.append((name, mw, cw))
        return ""

    cleaned = LORA_TAG_RE.sub(_repl, prompt)
    # Collapse runs of empty comma-separated chunks left by removed tags
    cleaned = re.sub(r"(\s*,\s*){2,}", ", ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = cleaned.strip(" ,\n\t")
    return cleaned, loras


def resolve_model_file(name: str, folder_type) -> str | None:
    """
    Find the best matching file in a ComfyUI model folder.
    Tries exact > basename > substring matches across allowed extensions.

    `folder_type` may be a single folder name (str) or an iterable of folder
    names to try in order — the first folder that yields a match wins. The
    iterable form is how callers search across legacy + canonical folder
    aliases (e.g. ("text_encoders", "clip")).
    """
    if not name:
        return None

    if isinstance(folder_type, str):
        folder_types = [folder_type]
    else:
        folder_types = list(folder_type)

    name_norm = name.replace("\\", "/").strip()
    name_lower = name_norm.lower()
    name_base = os.path.splitext(os.path.basename(name_norm))[0].lower()

    for ft in folder_types:
        try:
            available = folder_paths.get_filename_list(ft)
        except Exception:
            available = []
        if not available:
            continue

        # 1. Exact match (case-insensitive, normalized separators)
        for f in available:
            if f.replace("\\", "/").lower() == name_lower:
                return f

        # 2. Basename match without extension
        for f in available:
            f_base = os.path.splitext(os.path.basename(f))[0].lower()
            if f_base == name_base:
                return f

        # 3. Substring match on basename (one direction)
        candidates = []
        for f in available:
            f_base = os.path.splitext(os.path.basename(f))[0].lower()
            if name_base and (name_base in f_base or f_base in name_base):
                candidates.append((abs(len(f_base) - len(name_base)), f))
        if candidates:
            candidates.sort()
            return candidates[0][1]

    return None


def load_image_with_meta(filepath: str) -> tuple[torch.Tensor, torch.Tensor, dict]:
    """
    Load an image file as (image_tensor, mask_tensor, info_dict).
    Mirrors ComfyUI's LoadImage logic.
    """
    img = Image.open(filepath)
    info = (img.info or {}).copy()

    output_images = []
    output_masks = []

    for frame in ImageSequence.Iterator(img):
        frame = ImageOps.exif_transpose(frame)
        if frame.mode == "I":
            frame = frame.point(lambda v: v * (1 / 255))
        rgb = frame.convert("RGB")
        arr = np.array(rgb).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr)[None,]

        if "A" in frame.getbands():
            mask_arr = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask_arr)
        else:
            mask = torch.zeros((tensor.shape[1], tensor.shape[2]), dtype=torch.float32)

        output_images.append(tensor)
        output_masks.append(mask.unsqueeze(0))

    if len(output_images) > 1:
        out_img = torch.cat(output_images, dim=0)
        out_mask = torch.cat(output_masks, dim=0)
    else:
        out_img = output_images[0]
        out_mask = output_masks[0]

    return out_img, out_mask, info


# --------------------------------------------------------------------------
# ComfyUI prompt-JSON parsing
# --------------------------------------------------------------------------
#
# When ComfyUI saves an image, the PNG's `prompt` info key contains the
# executed graph as JSON. This lets us pull out:
#   * checkpoint / unet name
#   * LoRAs from rgthree's "Power Lora Loader", LoraLoader, easy fullLoader,
#     easy loraStack, "Lora Loader (LoraManager)"
#   * positive / negative prompts (traced through KSampler-like nodes)
#   * sampler params, latent size

_KSAMPLER_HINTS = ("KSampler", "kSampler", "SamplerCustom")
_LORA_LOADER_HINTS = ("LoraLoader", "Lora Loader")  # excludes "Power Lora Loader" — handled separately
_CHECKPOINT_HINTS = (
    "CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader",
    "UnetLoaderGGUF", "easy fullLoader", "easy fullkSampler",
    "D2 Checkpoint Loader", "D2 Load Diffusion Model",
)
_UNET_LOADER_HINTS = (
    "UNETLoader", "UnetLoaderGGUF", "D2 Load Diffusion Model",
)
_CLIP_LOADER_HINTS = (
    "CLIPLoader", "DualCLIPLoader", "TripleCLIPLoader", "QuadrupleCLIPLoader",
    "CLIPLoaderGGUF", "DualCLIPLoaderGGUF",
)
_VAE_LOADER_HINTS = ("VAELoader",)
_EMPTY_LATENT_HINTS = (
    "EmptyLatentImage", "EmptySD3LatentImage", "EmptyHunyuanLatentVideo",
    "EmptyMochiLatentVideo",
)


def _coerce_scalar(v, default):
    """Return v if it's a plain scalar; default if it's a graph link or unparseable."""
    if isinstance(v, (int, float, str)) and not isinstance(v, bool):
        return v
    if isinstance(v, bool):
        return v
    return default


def _trace_text(prompt_json: dict, val) -> str:
    """Resolve a value that might be a literal string or a `[node_id, slot]` link."""
    if isinstance(val, str):
        return val
    if isinstance(val, list) and val:
        nid = str(val[0])
        node = prompt_json.get(nid, {})
        if not isinstance(node, dict):
            return ""
        inputs = node.get("inputs", {})
        # Try common text-bearing inputs in priority order
        for key in ("text", "string", "wildcard", "positive", "negative"):
            if key in inputs:
                resolved = _trace_text(prompt_json, inputs[key])
                if resolved:
                    return resolved
        # Fallback: any string input
        for v in inputs.values():
            if isinstance(v, str) and v:
                return v
    return ""


def _extract_loras_from_comfy_prompt(prompt_json: dict) -> list[tuple[str, float, float]]:
    """Walk the ComfyUI prompt JSON and collect (name, model_strength, clip_strength) tuples."""
    loras: list[tuple[str, float, float]] = []

    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        # rgthree Power Lora Loader / DARASK Lora Loader — same widget value
        # format: lora_N entries are dicts {on, lora, strength, strengthTwo}.
        if "Power Lora Loader" in ct or "DARASK Lora Loader" in ct:
            for v in inputs.values():
                if isinstance(v, dict) and "lora" in v and "on" in v:
                    if not v.get("on"):
                        continue
                    name = str(v.get("lora", "")).strip()
                    if not name or name.lower() == "none":
                        continue
                    try:
                        sm = float(v.get("strength", 1.0))
                    except (ValueError, TypeError):
                        sm = 1.0
                    s2 = v.get("strengthTwo")
                    try:
                        sc = float(s2) if s2 not in (None, "") else sm
                    except (ValueError, TypeError):
                        sc = sm
                    loras.append((name, sm, sc))
            continue

        # easy loraStack: widget-style stack with lora_1_name / lora_1_strength inputs
        if ct == "easy loraStack" or "loraStack" in ct:
            i = 1
            while True:
                name_key = f"lora_{i}_name"
                if name_key not in inputs:
                    break
                name = str(inputs.get(name_key, "")).strip()
                try:
                    sm = float(_coerce_scalar(inputs.get(f"lora_{i}_strength", 1.0), 1.0))
                except (ValueError, TypeError):
                    sm = 1.0
                try:
                    mw = float(_coerce_scalar(inputs.get(f"lora_{i}_model_strength", sm), sm))
                except (ValueError, TypeError):
                    mw = sm
                try:
                    cw = float(_coerce_scalar(inputs.get(f"lora_{i}_clip_strength", sm), sm))
                except (ValueError, TypeError):
                    cw = sm
                if name and name.lower() != "none":
                    loras.append((name, mw, cw))
                i += 1
            continue

        # Standard LoraLoader / LoraLoaderModelOnly / etc.
        if any(h in ct for h in _LORA_LOADER_HINTS):
            name = inputs.get("lora_name")
            if isinstance(name, str) and name and name.lower() != "none":
                try:
                    sm = float(_coerce_scalar(inputs.get("strength_model", 1.0), 1.0))
                except (ValueError, TypeError):
                    sm = 1.0
                try:
                    sc = float(_coerce_scalar(inputs.get("strength_clip", sm), sm))
                except (ValueError, TypeError):
                    sc = sm
                loras.append((name, sm, sc))
            # LoraManager: text widget contains <lora:...> tags; merge those
            if "LoraManager" in ct:
                text = inputs.get("text", "")
                if isinstance(text, str):
                    _, mloras = extract_loras(text)
                    loras.extend(mloras)
            continue

    # Deduplicate while preserving order
    seen = set()
    deduped: list[tuple[str, float, float]] = []
    for name, mw, cw in loras:
        key = (name.replace("\\", "/").lower(), round(mw, 4), round(cw, 4))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, mw, cw))
    return deduped


def _extract_ckpt_from_comfy_prompt(prompt_json: dict) -> str:
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        if any(h in ct for h in _CHECKPOINT_HINTS):
            for key in ("ckpt_name", "unet_name", "model_name", "checkpoint"):
                v = inputs.get(key)
                if isinstance(v, str) and v:
                    return v
    return ""


def _extract_model_loader_info(prompt_json: dict) -> dict:
    """
    Identify how the source workflow loaded its diffusion model.

    Returns one of:
        {"kind": "checkpoint", "name": "..."}        — CheckpointLoaderSimple / easy fullLoader
        {"kind": "unet",       "name": "...",
         "weight_dtype": "..."}                       — UNETLoader / UnetLoaderGGUF
        {"kind": "", "name": ""}                      — nothing matched
    The first match wins, with UNET-style loaders preferred only when a
    plain CheckpointLoader is absent (some "easy" loaders are detected as
    checkpoints because they output MODEL+CLIP+VAE bundles).
    """
    checkpoint_hit: dict | None = None
    unet_hit: dict | None = None

    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        if any(h in ct for h in _UNET_LOADER_HINTS):
            name = ""
            for key in ("unet_name", "model_name", "ckpt_name", "checkpoint"):
                v = inputs.get(key)
                if isinstance(v, str) and v:
                    name = v
                    break
            if name and unet_hit is None:
                weight_dtype = inputs.get("weight_dtype")
                unet_hit = {
                    "kind": "unet",
                    "name": name,
                    "weight_dtype": str(weight_dtype) if isinstance(weight_dtype, str) else "default",
                }
            continue

        if any(h in ct for h in _CHECKPOINT_HINTS):
            name = ""
            for key in ("ckpt_name", "unet_name", "model_name", "checkpoint"):
                v = inputs.get(key)
                if isinstance(v, str) and v:
                    name = v
                    break
            if name and checkpoint_hit is None:
                checkpoint_hit = {"kind": "checkpoint", "name": name}

    return checkpoint_hit or unet_hit or {"kind": "", "name": ""}


def _extract_clip_loader_info(prompt_json: dict) -> dict:
    """
    Find a CLIP/text-encoder loader in the workflow.

    Returns {"names": [...], "type": "stable_diffusion"} or {"names": [], "type": ""}.
    Multi-clip loaders (DualCLIPLoader, TripleCLIPLoader) return every wired
    clip_nameN in order.
    """
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if not any(h in ct for h in _CLIP_LOADER_HINTS):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        names: list[str] = []
        single = inputs.get("clip_name")
        if isinstance(single, str) and single:
            names.append(single)
        i = 1
        while True:
            v = inputs.get(f"clip_name{i}")
            if not isinstance(v, str) or not v:
                # also tolerate clip_name_1 style (rare)
                v2 = inputs.get(f"clip_name_{i}")
                if isinstance(v2, str) and v2:
                    names.append(v2)
                else:
                    break
            else:
                names.append(v)
            i += 1
        if not names:
            continue

        clip_type = inputs.get("type") or inputs.get("clip_type") or "stable_diffusion"
        if not isinstance(clip_type, str):
            clip_type = "stable_diffusion"
        return {"names": names, "type": clip_type}

    return {"names": [], "type": ""}


def _extract_vae_loader_info(prompt_json: dict) -> str:
    """Find a VAELoader's `vae_name` in the workflow, or empty string."""
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if not any(h in ct for h in _VAE_LOADER_HINTS):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        v = inputs.get("vae_name")
        if isinstance(v, str) and v:
            return v
    return ""


def _extract_size_from_comfy_prompt(prompt_json: dict) -> tuple[int, int]:
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if any(h in ct for h in _EMPTY_LATENT_HINTS):
            inputs = node.get("inputs", {})
            try:
                return int(_coerce_scalar(inputs.get("width", 0), 0)), int(_coerce_scalar(inputs.get("height", 0), 0))
            except (ValueError, TypeError):
                pass
    return 0, 0


def _extract_sampler_from_comfy_prompt(prompt_json: dict) -> dict:
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if any(h in ct for h in _KSAMPLER_HINTS):
            inputs = node.get("inputs", {})
            return {
                "seed": int(_coerce_scalar(inputs.get("seed", 0), 0)),
                "steps": int(_coerce_scalar(inputs.get("steps", 20), 20)),
                "cfg": float(_coerce_scalar(inputs.get("cfg", 7.0), 7.0)),
                "sampler_name": str(_coerce_scalar(inputs.get("sampler_name", "euler"), "euler")),
                "scheduler": str(_coerce_scalar(inputs.get("scheduler", "normal"), "normal")),
                "denoise": float(_coerce_scalar(inputs.get("denoise", 1.0), 1.0)),
            }
    return {}


def _extract_prompts_from_comfy_prompt(prompt_json: dict) -> tuple[str, str]:
    for node in prompt_json.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if any(h in ct for h in _KSAMPLER_HINTS):
            inputs = node.get("inputs", {})
            pos = _trace_text(prompt_json, inputs.get("positive"))
            neg = _trace_text(prompt_json, inputs.get("negative"))
            if pos or neg:
                return pos, neg
    return "", ""


def parse_metadata(img_or_info) -> dict[str, Any]:
    """
    Unified entry point. Detects A1111 vs ComfyUI vs NovelAI metadata and
    returns a normalized dict:
        {positive, negative, params, comfy_loras, raw_text}
    `comfy_loras` is a list of (name, model_w, clip_w) collected from ComfyUI
    workflow nodes (Power Lora Loader, easy loraStack, LoraLoader, ...).
    """
    if isinstance(img_or_info, dict):
        items = img_or_info.copy()
    else:
        items = (img_or_info.info or {}).copy()

    # ComfyUI native: structured prompt JSON
    if "prompt" in items:
        try:
            prompt_json = items["prompt"]
            if isinstance(prompt_json, str):
                prompt_json = json.loads(prompt_json)
            if isinstance(prompt_json, dict):
                pos, neg = _extract_prompts_from_comfy_prompt(prompt_json)
                comfy_loras = _extract_loras_from_comfy_prompt(prompt_json)
                model_info = _extract_model_loader_info(prompt_json)
                clip_info = _extract_clip_loader_info(prompt_json)
                vae_name = _extract_vae_loader_info(prompt_json)
                w, h = _extract_size_from_comfy_prompt(prompt_json)
                samp = _extract_sampler_from_comfy_prompt(prompt_json)

                ckpt = model_info.get("name") or _extract_ckpt_from_comfy_prompt(prompt_json)
                params = {
                    "Steps": str(samp.get("steps", "")),
                    "Sampler": str(samp.get("sampler_name", "")),
                    "Schedule type": str(samp.get("scheduler", "")),
                    "CFG scale": str(samp.get("cfg", "")),
                    "Seed": str(samp.get("seed", "")),
                    "Size": f"{w}x{h}" if (w and h) else "",
                    "Model": ckpt,
                    "VAE": vae_name,
                    "Denoising strength": str(samp.get("denoise", "")),
                }
                params = {k: v for k, v in params.items() if v not in ("", "0")}
                return {
                    "positive": pos,
                    "negative": neg,
                    "params": params,
                    "comfy_loras": comfy_loras,
                    "model_loader": model_info,
                    "clip_loader": clip_info,
                    "vae_loader": vae_name,
                    "raw_text": json.dumps(prompt_json, indent=2, ensure_ascii=False)[:8000],
                }
        except Exception:
            pass

    # A1111 / Forge / NAI: text-based parameters
    raw = get_raw_metadata(items)
    parsed = parse_a1111(raw)
    parsed["comfy_loras"] = []
    parsed["model_loader"] = {"kind": "", "name": ""}
    parsed["clip_loader"] = {"names": [], "type": ""}
    parsed["vae_loader"] = ""
    parsed["raw_text"] = raw
    return parsed


# --------------------------------------------------------------------------


def list_folder_images(folder: str, extension: str, sort_by: str, order_by: str) -> list[str]:
    """Return absolute paths of files in `folder` matching `extension`, sorted."""
    import glob
    import random as _random

    if not folder or not os.path.isdir(folder):
        return []

    patterns = [p.strip() for p in extension.split(",") if p.strip()] or ["*.*"]
    files: list[str] = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(folder, pat)))

    files = [os.path.abspath(f) for f in files if os.path.isfile(f)]
    # Filter to image extensions if pattern was the default *.*
    if patterns == ["*.*"]:
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
        files = [f for f in files if os.path.splitext(f)[1].lower() in image_exts]

    if sort_by == "Name":
        files.sort(key=lambda p: os.path.basename(p).lower())
    elif sort_by == "Date":
        files.sort(key=os.path.getmtime)
    elif sort_by == "Random":
        _random.shuffle(files)

    if order_by == "Z-A" and sort_by != "Random":
        files.reverse()

    return files
