# comfyui_darask_node

DARASK custom nodes for ComfyUI. Six tightly-scoped helpers built around two
real workflows: **batch-upscaling a folder of generated images** while
restoring their original model + LoRAs + prompts from EXIF, and
**generating every combination of a stack of prompt fragments** (quality ×
costume × pose × lighting × …) without writing any permutation logic.

Categories: `DARASK` and `DARASK/Prompt`.

---

## Install

### Via ComfyUI Manager (when published to the Comfy Registry)
Search **DARASK** in the Manager.

### Right now — install via Git URL
In Manager: **Install via Git URL** → paste:
```
https://github.com/daraskme/comfyui_darask_node
```

### Manual
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/daraskme/comfyui_darask_node
pip install -r comfyui_darask_node/requirements.txt   # piexif
```
Restart ComfyUI.

---

## Nodes

### 1. DARASK Folder Image Loader  *(category `DARASK`)*

A single-node replacement for D2's `Folder Image Queue` + `Load Image`.

| Mode | Behaviour |
|---|---|
| Auto Advance | Returns one image per queue, advances internally. Pair with ComfyUI's auto-queue to chew through the whole folder. |
| Manual Index | `index` widget picks one specific file. |
| All as Batch | Loads every file into a single batched IMAGE tensor. |

**Outputs**: `image, mask, width, height, positive, negative, filename, filepath, raw_metadata, current_index, total_count`

`loop` wraps around at the end; `reset` zeroes the cursor.

---

### 2. DARASK Exif Apply (Model + LoRA + Prompt)  *(category `DARASK`)*

Reads EXIF / PNGinfo from a `filepath` and produces an **entire upscale-ready
pipeline** — checkpoint loaded, every LoRA stacked, prompts encoded.

Recognised metadata sources:

* **A1111 / Forge / Reforge** `parameters` text or EXIF UserComment
* **A1111 prompt tags** `<lora:name:weight[:clip_weight]>`
* **ComfyUI native** `prompt` JSON (workflow embedded in PNG)
  * `Power Lora Loader (rgthree)` — only entries with `on=true`, both strengths
  * `easy loraStack` — widget-style stack
  * `LoraLoader`, `Lora Loader (LoraManager)` — including LoraManager's text widget tags
  * `CheckpointLoaderSimple`, `UNETLoader`, `easy fullLoader`
  * `KSampler` family — seed, steps, cfg, sampler_name, scheduler, denoise
  * `EmptyLatentImage` — width, height
* **NovelAI** `Comment` JSON

**Outputs**: `model, clip, vae, positive, negative, positive_text, negative_text, model_name, loras_applied, seed, cfg, sampler_name, scheduler, steps, denoise, width, height`

**Optional inputs**: `model_override / clip_override / vae_override`,
`fallback_ckpt`, prompt prefix/suffix on each side, `lora_strength_multiplier`,
`skip_loras` (matches by full path or basename).

LoRAs from prompt tags and from workflow nodes are merged and de-duplicated
by basename — workflow node entries win on conflict because they carry the
fuller path.

---

### 3. DARASK Exif Read  *(category `DARASK`)*

Same parsing as **Exif Apply** without loading anything. Returns the parsed
fields as plain outputs — useful when you want to feed values into other
nodes manually.

---

### 4. DARASK Empty Latent (Preset)  *(category `DARASK`)*

Replaces the bare `EmptyLatentImage` widgets with a labelled preset list.
Each label shows the exact and approximate aspect ratio.

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

`swap_orientation` flips W/H with one click. Outputs `LATENT, width, height`.

---

### 5. DARASK Prompt Cell  *(category `DARASK/Prompt`)*

A "cell" in a prompt chain. Each non-empty line in `text` is a variant.
Connect cells via the `prev` socket and the chain expands to the **cartesian
product** of every variant set.

```
[Quality cell]   →  [Costume cell]   →   [Pose cell]   →   [Lighting cell]   →   Output
   2 lines           4 lines              3 lines          2 lines
                              =  2 × 4 × 3 × 2  =  48 patterns
```

| Mode | Behaviour |
|---|---|
| Cartesian (all combos) | Default. Multiplies with everything upstream. |
| Concat (all lines as one) | Joins every line with `separator` into a single fragment. Useful for "always-on" tag blocks. |
| Random pick one | Picks one variant at random (per `seed`). |
| Fixed index | Pins to one specific line. |

* Lines starting with `#` are comments.
* Blank lines in the middle of the text become **no-op variants** — the
  parent prompt passes through unchanged. Lets you express "with X / with Y /
  or no costume change".
* `enabled=false` skips the cell entirely (passes `prev` through unchanged).
* `label` is a free-text annotation shown in the `preview` output.

**Outputs**: `set` (custom `DARASK_PROMPT_SET` socket), `count`, `preview`
(numbered list, first 8 patterns).

---

### 6. DARASK Prompt Cell Output (CLIP Encode)  *(category `DARASK/Prompt`)*

Terminates a chain. Takes the `set` and a `CLIP`, emits CONDITIONING.

| Mode | Behaviour |
|---|---|
| Iterate (auto-advance) | One prompt per queue. Pair with ComfyUI's auto-queue to render every combination. `loop` wraps around. |
| Index | Pick a specific combination. |
| All as Batch | Encodes every combination into one batched CONDITIONING. Set `EmptyLatent.batch_size` to match `total_count` and KSampler renders all images in a single run. |

**Outputs**: `conditioning, current_prompt, current_index, total_count`.

---

## Recipe — folder → upscale, EXIF-driven

```
DARASK Folder Image Loader
  ├── image      ──▶ easy hiresFix (image input)
  └── filepath   ──▶ DARASK Exif Apply
                       ├── model, clip, vae      ──▶ easy pipeIn
                       ├── positive, negative    ──▶ easy pipeIn
                       └── seed/steps/cfg/sampler/scheduler/denoise
                                                  ──▶ easy preSampling (widget→input)
```
Drop `easy fullLoader` and `easy loraStack` — `Exif Apply` covers both.

## Recipe — generate every combination

```
DARASK Prompt Cell (quality)
        │
        ▼
DARASK Prompt Cell (costume)            ──▶  CLIP loader ──┐
        │                                                  │
        ▼                                                  │
DARASK Prompt Cell (lighting)                              │
        │                                                  ▼
        └────────────▶ DARASK Prompt Cell Output ───── CONDITIONING ──▶ KSampler
                                  │
                                  └── set mode = Iterate, hit auto-queue
```

For first-pass generation, use **DARASK Empty Latent (Preset)** in place of
the default `EmptyLatentImage`.

---

## License
MIT
