# comfyui_darask_node

DARASK custom nodes for ComfyUI. Built around the upscale / hires-fix workflow:
batch through a folder of generated images, recover the **model + LoRAs + prompts**
that produced each one from its EXIF/PNGinfo, and run a tiled / hires pass with
the original parameters automatically restored.

## Nodes

### DARASK Folder Image Loader
Combined replacement for `D2 Folder Image Queue` + `D2 Load Image`.
- Modes: **Auto Advance** (one image per queue, internal cursor), **Manual Index**, **All as Batch**
- Outputs: `image, mask, width, height, positive, negative, filename, filepath, raw_metadata, current_index, total_count`
- `loop` to wrap around, `reset` to restart cursor

### DARASK Exif Apply (Model + LoRA + Prompt)
Reads EXIF / PNGinfo from a `filepath` and produces a ready-to-sample pipeline:
- Loads the matching checkpoint (fuzzy filename match against `folder_paths`)
- Stacks **all** LoRAs found in:
    - A1111 `<lora:name:weight>` prompt tags
    - ComfyUI **Power Lora Loader (rgthree)** nodes (only entries with `on=true`)
    - `easy loraStack`, `LoraLoader`, `Lora Loader (LoraManager)`
- Encodes positive / negative `CONDITIONING`
- Outputs sampler settings: `seed, cfg, sampler_name, scheduler, steps, denoise, width, height`

Optional inputs: `model_override / clip_override / vae_override`, `fallback_ckpt`,
prefix/suffix prompts, `lora_strength_multiplier`, `skip_loras`.

### DARASK Exif Read
Lightweight version — same parsing without loading anything. Returns parsed
fields as raw outputs.

### DARASK Empty Latent (Preset)
Pick a canvas from a labelled list instead of typing dimensions. Each label shows
both the exact and approximate aspect ratio.

| Preset | Pixels | Ratio |
|---|---|---|
| 1024 × 1024 | 1024×1024 | 1:1 |
| 2048 × 2048 | 2048×2048 | 1:1 (2x) |
| 832 × 1216 | 832×1216 | 13:19 ≈ 2:3 portrait |
| 1216 × 832 | 1216×832 | 19:13 ≈ 3:2 landscape |
| 896 × 1152 | 896×1152 | 7:9 ≈ 3:4 portrait |
| 1152 × 896 | 1152×896 | 9:7 ≈ 4:3 landscape |
| 768 × 1344 | 768×1344 | 4:7 portrait, wide |
| 1344 × 768 | 1344×768 | 7:4 landscape, wide |

`swap_orientation` flips W/H with one click.

## Install

### Via ComfyUI Manager (recommended once published)
Search "DARASK" in the Manager.

### Via Git
```
cd ComfyUI/custom_nodes
git clone https://github.com/daraskme/comfyui_darask_node
cd comfyui_darask_node
pip install -r requirements.txt   # only piexif
```

## Typical workflow

```
DARASK Folder Image Loader  ──image──▶ easy hiresFix
                            ──filepath─▶ DARASK Exif Apply ──model/clip/vae/positive/negative/sampler params─▶ easy pipeIn → preSampling → kSampler → SaveImage
```

For first-pass generation, use **DARASK Empty Latent (Preset)** in place of the
default `EmptyLatentImage` widget.

## License
MIT
