# comfyui_darask_node

ComfyUI 用 DARASK カスタムノード集。4つの実用ワークフローを軸にした17個のノード:

1. **画像フォルダの一括アップスケール** — フォルダから画像を順に読み、EXIF / PNGinfo に
   埋め込まれた **元のモデル + LoRA + プロンプト** を自動復元してアップスケール
2. **プロンプト断片の全パターン生成** — quality × costume × pose × lighting × …
   のような掛け合わせを、手動で順列を書かずに自動展開
3. **動画フレーム補間 + 音声生成** — 動画ファイルを読み込み、RIFE でフレーム補間して
   フレームレートを上げ、MMAudio 等で音声を合成する一連の処理
4. **LTX Video 2.3 image-to-video** — 静止画から動画を生成。サブグラフを使わない
   フラットなノードグラフで全ステップを編集可能。ComfyMath 不要

カテゴリ: `DARASK` と `DARASK/Prompt`

---

## インストール

### ComfyUI Manager 経由 (Comfy Registry 公開時)
Manager で **DARASK** を検索。

### Git URL で今すぐ
Manager → **Install via Git URL** に下記を貼り付け:
```
https://github.com/daraskme/comfyui_darask_node
```

### 手動
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/daraskme/comfyui_darask_node
pip install -r comfyui_darask_node/requirements.txt   # piexif
```
ComfyUI を再起動してください。

---

## ノード一覧

| # | ノード名 | カテゴリ | 役割 |
|---|---|---|---|
| 1 | DARASK Folder Image Loader | DARASK | フォルダから順に画像を読み込む(D2 の Folder Image Queue + Load Image を1ノードに統合) |
| 2 | DARASK Exif Apply (Auto-detect) | DARASK | EXIF を読んで MODEL+CLIP+VAE+CONDITIONING を構築。ローダー種別は自動判定 |
| 3 | DARASK Exif Apply (Anima / UNET stack) | DARASK | 同上、ただし UNETLoader+CLIPLoader+VAELoader 固定 |
| 4 | DARASK Exif Apply (SDXL / Checkpoint) | DARASK | 同上、ただし CheckpointLoaderSimple 固定 |
| 5 | DARASK Exif Read | DARASK | EXIF をロードせずパースだけ。値を別ノードに流したいとき用 |
| 6 | DARASK Empty Latent (Preset) | DARASK | プリセット解像度から EmptyLatentImage を生成 |
| 7 | DARASK Lora Loader | DARASK | 複数LoRAを1ノードでスタック(rgthree Power Lora Loader 互換) |
| 8 | DARASK Prompt Cell | DARASK/Prompt | プロンプト断片の1セル。複数チェイン/分岐で全組合せ展開 |
| 9 | DARASK Prompt Cell Output (CLIP Encode) | DARASK/Prompt | プロンプトチェインの終端。CONDITIONING を出力 |
| 10 | DARASK Load Video (Upload) | DARASK | 動画ファイルをアップロード&フレーム読み込み(VHS_LoadVideo 互換) |
| 11 | DARASK Video Info | DARASK | 動画メタ情報(FPS/総フレーム数/duration/W/H)を出力 |
| 12 | DARASK RIFE Interpolation | DARASK | RIFE モデルでフレーム補間しFPSアップサンプル |
| 13 | DARASK LTX 2.3 Video Settings | DARASK | LTX 2.3用の動画サイズ設定(W/H/length/fps + 最終サイズプレビュー) |
| 14 | DARASK Float → Int | DARASK | FLOAT を INT に丸める(ComfyMath の `CM_FloatToInt` 置き換え) |
| 15 | DARASK LTX 2.3 Generator (All-in-One) | DARASK | LTX Video 2.3 i2v ワークフロー(7サブグラフ+LoRA)を1ノードに統合 |
| 16 | DARASK Anima Sampling Tuner | DARASK | Anima/Wan/SD3-flow 用に Shift / TSR / EpsilonScaling / RescaleCFG / CFG-Zero★ を1ノード集約 |
| 17 | DARASK Anima Step Cache (Spectrum) | DARASK | Chebyshev 多項式外挿による step caching で動画モデルを30〜50%高速化 |

---

### 1. DARASK Folder Image Loader  *(カテゴリ `DARASK`)*

D2 の `Folder Image Queue` + `Load Image` を1ノードに統合した置き換え。

| モード | 動作 |
|---|---|
| Auto Advance | 1キューにつき1枚返し、内部カーソルが自動で進む。ComfyUI の Auto Queue と組み合わせてフォルダ全体を順に処理 |
| Manual Index | `index` ウィジェットで特定の1枚を指定 |
| All as Batch | 全ファイルを1つのバッチ IMAGE テンソルにまとめてロード |

**出力**: `image, mask, width, height, positive, negative, filename, filepath, raw_metadata, current_index, total_count, progress`

#### 進捗表示

* `progress` は1始まりの人間用カウンター STRING(`"3/20"` / `"20/20 (done)"` / `"1-20/20 (batch)"`)。`Show Text` に繋げばログ出力可能。
* 同じ文字列が **ノード右上に色付きピル(バッジ)で常時表示** されます — 走行中は黄色、`loop=False` で末尾到達後は緑の `(done)`。`progress` をどこにも配線しなくても見えるので、Auto Queue を回しっぱなしでも進捗が一目瞭然。

#### ループ・リセット・自動キュー

* **`auto_queue_all`**(デフォルト **ON**)— **Queue Prompt を1回押すだけでフォルダ全部キューに積む** モード。フレッシュ押下時に残り全画像分のプロンプトを `PromptServer.prompt_queue.put` で **その場で一気にエンキュー** するので、ComfyUI のキューパネルに N 個並んで見え、途中でキャンセル/クリアも普通にできます。
  * Auto Queue (instant) を毎回ONにする手間がなくなります
  * 1パス処理し終えたら自動で停止(無限ループしない)
  * Auto Queue (instant) と併用すると2倍に enqueue される(無駄が生じる)ので、片方だけ使ってください。**通常はこちら(`auto_queue_all`)を ON のままで十分**
* **`index` は Auto Advance の開始位置** — `auto_queue_all = ON` の場合、Queue を押すたびに `index` をスタート地点として(残り画像分を)前倒しキュー。途中の画像から再開したい時は `index` を変えてからもう一度 Queue を押すだけ。`loop = True` なら必ず1周分(計 `total` 枚)が積まれる。
* `loop`(デフォルト **ON**)— 末尾到達後にカーソルを 0 にラップ。`auto_queue_all = True` と組み合わせる場合は **1パスで止まる**(無限ループ防止のため)。`auto_queue_all = False` の場合は通常通り無限ラップ。
* `loop = False` — 1パス処理用。
  * **末尾到達 → 次の1キューだけ `ExecutionBlocker(None)` で下流(SaveImage / KSampler 等)を遮断**(ノードのバッジが緑の `(done)` になる)。**エラートースト表示なし** のサイレント遮断
  * その後 cursor は自動で 0 にリセット されるので、次のキューからは1枚目から再生開始
* `reset = True` で次回実行時にカーソルを強制ゼロ化(任意のタイミングで先頭に戻したい時用)。

#### カーソルの永続性

* カーソル状態は **ワークフロー上のノードID** にひも付けて保存されます。ワークフローを少し編集して Python インスタンスが作り直されても、ノードID が同じなら続きから再開します。
* `folder` / `extension` / `sort_by` / `order_by` / ファイル総数のどれかが変わると **自動的にカーソルを0にリセット**。別フォルダを指定したのに前回の途中から始まる、という事故を防ぎます。

---

### 2-4. DARASK Exif Apply  *(カテゴリ `DARASK`)*

`filepath` から EXIF / PNGinfo を読み、**そのままアップスケール可能なパイプライン全部** を組み立てる:
チェックポイント読み込み・LoRA を全部スタック・プロンプトをエンコード。

3つのバリアントが出力スキーマ共通で挙動だけ違います:

| バリアント | メニュー名 | 挙動 |
|---|---|---|
| **Auto-detect** | `DARASK Exif Apply (Auto-detect)` | メタデータを見て UNET 系か Checkpoint 系か自動判定。混在フォルダ向け |
| **Anima / UNET** | `DARASK Exif Apply (Anima / UNET stack)` | 常に `UNETLoader + CLIPLoader/DualCLIPLoader + VAELoader`。Qwen / Anima / Flux / Hunyuan / Wan など MODEL・CLIP・VAE が別ファイルのスタック用。`fallback_unet`, `fallback_clip`, `fallback_clip2`, `fallback_vae`, `clip_type`, `weight_dtype` の追加ウィジェットあり |
| **SDXL / Checkpoint** | `DARASK Exif Apply (SDXL / Checkpoint)` | 常に `CheckpointLoaderSimple`。SD1.5 / SDXL / Pony / Illustrious など、1つの `.safetensors` に MODEL+CLIP+VAE 全部入りのケース用。ソースが UNET 系を使っていた場合は「Anima バリアントに切り替えて」とエラーメッセージで案内 |

#### 認識するメタデータ

* **A1111 / Forge / Reforge** の `parameters` テキスト / EXIF UserComment
* **A1111 プロンプトタグ** `<lora:name:weight[:clip_weight]>`
* **ComfyUI native** `prompt` JSON(PNG に埋め込まれたワークフロー)
  * LoRA: `Power Lora Loader (rgthree)`(`on=true` のみ)、`easy loraStack`、`LoraLoader`、`Lora Loader (LoraManager)`(text widget タグも)
  * Diffusion モデル(自動振り分け):
    * `CheckpointLoaderSimple` / `easy fullLoader` → 単体ファイル(`checkpoints/`)
    * `UNETLoader` / `UnetLoaderGGUF` → 単独 diffusion モデル(`diffusion_models/`)、`weight_dtype` ウィジェットも復元
  * テキストエンコーダー:
    * `CLIPLoader`(単一)/ `DualCLIPLoader`(sdxl, sd3, flux, …) → `text_encoders/`(レガシーの `clip/` フォルダにもフォールバック)、`type` ウィジェットも復元
  * `VAELoader` → `vae/`
  * `KSampler` 系 — seed, steps, cfg, sampler_name, scheduler, denoise
  * `EmptyLatentImage` 系 — width, height
* **NovelAI** `Comment` JSON

#### ローダー自動振り分け(Auto-detect バリアント)

ソース画像が `UNETLoader + CLIPLoader + VAELoader` 構成(Qwen / Anima / Flux系で MODEL・CLIP・VAE がそれぞれ `diffusion_models/` / `text_encoders/` / `vae/` に別ファイルで存在)で生成されていた場合、Exif Apply は同じ3点ローダーチェインを自動再構築します。`checkpoints/` には該当ファイルがなくても問題ありません。

`CheckpointLoaderSimple` 系のソースなら従来通り単体ファイル経路。

`model_override` / `clip_override` / `vae_override` のいずれかに何か繋ぐとそのスロットはオーバーライド優先、繋がなかった残りはメタデータ経由でロード(部分オーバーライド可)。

#### 入出力

**出力**: `model, clip, vae, positive, negative, positive_text, negative_text, model_name, loras_applied, seed, cfg, sampler_name, scheduler, steps, denoise, width, height`

**任意入力(共通)**:
- `model_override` / `clip_override` / `vae_override` — 各スロットのオーバーライド
- `fallback_ckpt` — メタデータに Model 名が無い時のフォールバック
- `positive_prefix` / `positive_suffix` / `negative_prefix` / `negative_suffix` — プロンプトの前後追加
- `lora_strength_multiplier` — 全LoRA強度に乗算
- `skip_loras` — フルパスまたはbasename指定でスキップ(複数行可)

**Anima バリアント追加ウィジェット**:
- `fallback_unet` / `fallback_clip` / `fallback_clip2` / `fallback_vae` — メタデータに無い時のフォールバック
- `clip_type` — `stable_diffusion / qwen_image / sdxl / sd3 / flux / hunyuan_image / wan / lumina2 / chroma / ...`(CLIPLoader の `type` 全種)
- `weight_dtype` — `default / fp8_e4m3fn / fp8_e4m3fn_fast / fp8_e5m2`

LoRA はプロンプトタグから抽出されたものと、ワークフローノードから抽出されたものを **basename で重複除去してマージ**。重複時はワークフローノード側を優先(フルパス情報が残るため)。

---

### 5. DARASK Exif Read  *(カテゴリ `DARASK`)*

Exif Apply と同じパースをするが、**何もロードしない**。生のフィールドだけ出力します。値を他のノードに手動で流したい時用。

---

### 6. DARASK Empty Latent (Preset)  *(カテゴリ `DARASK`)*

素の `EmptyLatentImage` の数値ウィジェットを、ラベル付きプリセットリストに置き換え。各ラベルに正確な比率と概算比率を表示。

| プリセット | ピクセル | 比率 |
|---|---|---|
| 1024 × 1024 | 1024×1024 | 1:1 |
| 2048 × 2048 | 2048×2048 | 1:1 (2x) |
| 832 × 1216 | 832×1216 | 13:19 ≈ 2:3 portrait |
| 1216 × 832 | 1216×832 | 19:13 ≈ 3:2 landscape |
| 896 × 1152 | 896×1152 | 7:9 ≈ 3:4 portrait |
| 1152 × 896 | 1152×896 | 9:7 ≈ 4:3 landscape |
| 768 × 1344 | 768×1344 | 4:7 portrait, wide |
| 1344 × 768 | 1344×768 | 7:4 landscape, wide |

`swap_orientation` で W/H を1クリック反転。出力は `LATENT, width, height`。

> **Tips**: `batch_size` ウィジェットを右クリック → **Convert Widget to Input** で入力ソケット化できます。これと Prompt Cell Output の `total_count` を繋ぐと「全パターン1キューでバッチ生成」が無設定で完結。

---

### 7. DARASK Lora Loader  *(カテゴリ `DARASK`)*

複数のLoRAを1ノードでスタック適用するノード。UXは [rgthree の Power Lora Loader](https://github.com/rgthree/rgthree-comfy)(MIT)に倣った独立実装で、1行=1カスタムウィジェットの単行UI。

#### 操作

* **`+ Add LoRA` ボタン**(ノード下部)で行を追加
* 各行に並ぶ要素(左から右):
  * **ドラッグハンドル**(≡)— 上下にドラッグで行の並び替え
  * **トグル**(✓/—)— ON/OFF
  * **LoRA名** — クリックでフォルダ階層付きピッカーメニュー
  * **strength**(model)— `◀` / `▶` で ±0.05 刻み、中央をドラッグでスクラブ、ダブルクリックで直接入力
  * **strengthTwo**(CLIP、任意)— 行右クリック → `Show CLIP strength` で表示。Model と別の強度を CLIP に適用
  * **×** — 行削除
* **行を右クリック** で Move Up / Move Down / Enable・Disable / Show・Hide CLIP strength / Remove
* LoRA名ピッカーはフォルダ階層を `📁 sub` のサブメニューで展開

#### 入出力

**入力**: `model`(MODEL)、`clip`(CLIP)— どちらもオプション。`clip` なしで `model` だけ繋いでも動作します。

**出力**: `MODEL`、`CLIP`

#### 動作の細部

* `on = false` または `lora = "None"` または `strength = 0` かつ `strengthTwo = 0` の行はスキップ
* `strengthTwo` 未指定の行は `strength` をそのまま CLIP にも適用(rgthree と同じ挙動)
* LoRAファイル名は **fuzzy match** で解決:exact → basename(拡張子なし)→ substring の順
* 行は表示順(`lora_N` の N の昇順)に適用

#### 既存 rgthree ワークフローとの互換性

ウィジェットの保存形式は rgthree Power Lora Loader と同じ dict 形式 (`{on, lora, strength, strengthTwo}`) なので、rgthree で作成したワークフローをそのままロードできます。Python 側は旧 split 形式 (`lora_N_on` / `lora_N` / `lora_N_strength` の3キー、本ノードの古い実装)も後方互換でフォールバック解釈します。`DARASK Exif Apply` 系もどちらの形式も認識。

---

### 8. DARASK Prompt Cell  *(カテゴリ `DARASK/Prompt`)*

プロンプトチェインの「1セル」。`text` 内の各非空行が variant(候補)になり、セルを `prev` で繋ぐとチェイン全体が **全 variant のデカルト積(掛け合わせ)** に展開されます。

```
[Quality cell]   →  [Costume cell]   →   [Pose cell]   →   [Lighting cell]   →   Output
   2 行              4 行                 3 行               2 行
                              =  2 × 4 × 3 × 2  =  48 パターン
```

| モード | 挙動 |
|---|---|
| Cartesian (all combos) | デフォルト。上流の全パターンとこのセルの全 variant を掛け合わせ |
| Concat (all lines as one) | 全行を `separator` で結合して1個の variant にする。Quality / Character の "always-on" ブロック向け |
| Random pick one | seed に基づきランダムに1行選択 |
| Fixed index | `index` ウィジェットで特定の1行を指定 |

* `#` で始まる行は **コメント** で展開前に削除されます
* テキスト途中の **空行** は "no-op variant" として扱われ、上流のプロンプトをそのまま通します(「Xを追加 / Yを追加 / または何も追加しない」を表現)
* `enabled = false` でセルをスキップ(`prev` の内容をそのまま出力)
* `label` は preview ヘッダーに表示される注釈用フリーテキスト

#### 分岐(Branch)

`prev` 入力は **動的スロット**:1個繋ぐたびに下に空スロットが1個増え、最大16個まで上流ブランチを束ねられます。切断すると末尾の空スロットが1個に畳まれて自動整理されます。

> **⚠️ 推奨パターン: 常に枝分かれさせる、途中で収束させない**
>
> セル → セルの繋ぎ方は **必ずだんだんと枝分かれしていく**(ファンアウトする)方向で組んでください。
> 複数ブランチを **中間セルでマージ(収束)させない** こと。
>
> ```
> 良い ✅              悪い ✗
>
>   [head]              [head]
>     │                   │
>     ▼                   ▼
>   [reactions]         [reactions]
>    ├──▶ [scene A] ─┐    ├──▶ [scene A] ─┐
>    ├──▶ [scene B] ─┤    ├──▶ [scene B] ─┤
>    ├──▶ [scene C] ─┼─▶ Output           ├──▶ [merge cell] ──▶ [climax] ──▶ Output
>    └──▶ [scene D] ─┘    └──▶ [scene D] ─┘
> ```
>
> 中間で収束させると、各リーフごとに違う variants を後付けしたい時に表現できなくなったり、ブランチ数 × 後付け variants の組合せが意図せず爆発したりします。**リーフセルはそれぞれ独立に Output ノードの `set / set_2 / set_3 / ...` に直接繋ぐ** のが安全。
>
> Output の `set` 入力も動的スロットなので、リーフを何本でも追加できます。各リーフは独立した「シーン定義」として扱われ、Output で Union されて全パターンが揃います。

複数の `prev` を1つのセルに集約することは技術的にはできます(Union されてからこのセルの variants でデカルト積)が、上記の理由で **頭側のファンアウト用途のみに留める** ことを強くおすすめします。
複数の出力ストリームを1つにまとめたい時は **マージセルを置かず、Output ノードまで直接運ぶ** のが鉄則です。

**出力**: `set`(カスタム型 `DARASK_PROMPT_SET`)、`count`(INT)、`preview`(STRING、最初の8パターンを番号付きで表示)

---

### 9. DARASK Prompt Cell Output (CLIP Encode)  *(カテゴリ `DARASK/Prompt`)*

チェインの終端。1つ以上の `set` 入力と `CLIP` を受け取り、**繋がっている全ブランチの全パターンを網羅した** CONDITIONING を出力します。

`set` 入力も `prev` と同じく動的スロット:繋いだら下に空スロットが追加されます。リーフセルを片っ端から繋ぎ込めば、Output が全部 Union して `total_count` に総数が反映されます。

| モード | 動作 |
|---|---|
| **All as Batch** *(デフォルト)* | 全パターンを1つのバッチ CONDITIONING にスタック。**`EmptyLatent.batch_size` を `total_count` に合わせる** (ウィジェットを Convert Widget to Input してから `total_count` を繋ぐのが楽)。KSampler が1キューで全画像を生成 |
| Iterate (auto-advance) | 1キューにつき1プロンプト、カーソルが内部で +1 ずつ進む。**Queue を1回押すだけでは1枚しか生成されません**。全パターン回すには ComfyUI の *Auto Queue*(キューパネル → "Extra options" → Auto Queue: `instant`)を有効化。`loop` で末尾から先頭に戻る |
| Index | `index` で1パターンだけ指定。デバッグ・A/B比較用 |

カーソルは Folder Image Loader 同様、**ワークフローのノードID** にひも付けて保存されるため、ワークフロー編集で Python インスタンスが作り直されても継続。`reset` で手動ゼロ化可能。

**出力**: `conditioning, current_prompt, current_index, total_count`

> **「1枚生成して止まる」のは正常です** — `Iterate` モードは1キュー1プロンプトの仕様。`All as Batch` に切り替えるか、ComfyUI の Auto Queue (instant) を ON にしてください。

---

### 10. DARASK Load Video (Upload)  *(カテゴリ `DARASK`)*

動画ファイルを ComfyUI の `input/` ディレクトリから読み込んでフレーム列に変換するノード。VHS_LoadVideo の代替で、OpenCV(cv2)ベースのクリーンルーム実装。

#### ウィジェット

* **`video`** — `input/` 配下の動画ファイル選択。標準の **動画アップロードボタン**(`video_upload: True`)が右に表示されるので、その場でアップロード可能。対応拡張子: `.mp4 / .webm / .mkv / .mov / .gif / .avi / .m4v`
* **`force_rate`**(FLOAT, デフォルト 0)— 指定FPSへリサンプリング(0 はソースFPSを維持)
* **`custom_width` / `custom_height`**(INT, デフォルト 0)— リサイズ。0 はソース解像度を維持。片方だけ指定するとアスペクト比保持で計算
* **`frame_load_cap`**(INT, デフォルト 0)— 読み込む最大フレーム数(0 は全部)
* **`skip_first_frames`**(INT, デフォルト 0)— 先頭から N フレーム破棄
* **`select_every_nth`**(INT, デフォルト 1)— skip 後に N フレームごとに採用(ダウンサンプリング、`loaded_fps` も同時に N で割られる)

#### 出力

* **`IMAGE`** — フレームバッチ `[N, H, W, 3]`(0..1 の float32)
* **`frame_count`**(INT)— 実際にロードされたフレーム数
* **`video_info`**(`DARASK_VIDEO_INFO`)— `DARASK Video Info` に流し込んで詳細値に分解

#### 注意

* 音声出力は持ちません(MMAudio 用ワークフローでは元動画の音声を使わない前提のため割愛)
* 巨大動画(数千フレーム以上)はメモリに乗り切らない可能性があるので `frame_load_cap` で制限してください

---

### 11. DARASK Video Info  *(カテゴリ `DARASK`)*

`DARASK_VIDEO_INFO` dict を10個のスカラー出力に分解するシンプルなノード。VHS_VideoInfo 互換。

#### 入力

* **`video_info`**(`DARASK_VIDEO_INFO`)— `DARASK Load Video (Upload)` の `video_info` 出力を接続

#### 出力(全10個)

ソース(ファイル本来の値):
* `source_fps`(FLOAT)
* `source_frame_count`(INT)
* `source_duration`(FLOAT, 秒)
* `source_width`(INT)
* `source_height`(INT)

ロード後(`force_rate` / `select_every_nth` / `frame_load_cap` / カスタムリサイズ適用後):
* `loaded_fps`(FLOAT)
* `loaded_frame_count`(INT)
* `loaded_duration`(FLOAT, 秒)
* `loaded_width`(INT)
* `loaded_height`(INT)

MMAudio に渡す duration として `loaded_duration` を繋ぐのが定番。

---

### 13. DARASK LTX 2.3 Video Settings  *(カテゴリ `DARASK`)*

LTX Video 2.3 のクリップ設定を1ノードに集約。**入力中の最終的な動画サイズ・アスペクト比・フレーム数・尺をノード上に常時プレビュー** するので、Queue を押す前に「実際に何が出てくるか」一目で確認できます。

#### ウィジェット

* **`width`** (INT, デフォルト 1024, step 32) — フレーム幅(px)
* **`height`** (INT, デフォルト 576, step 32) — フレーム高(px)
* **`length`** (INT, デフォルト 97, step 8) — フレーム数。LTXは `(n × 8) + 1` を推奨(97 / 121 / 241 …)
* **`fps`** (FLOAT, デフォルト 24.0) — 再生フレームレート

#### ライブプレビュー

ウィジェットを編集するたびに、ノード上部のバッジが即座に更新されます:

```
1024×576 (16:9) · 97f @ 24fps = 4.04s
720×1280 (9:16) · 241f @ 25.5fps = 9.45s
```

アスペクト比は `gcd` で自動約分(`1024×576` → `16:9`)。`length / fps` から動画の長さ(秒)も自動計算。

#### 出力

| 出力 | 型 | 接続先(LTX 2.3 ワークフローでの典型例) |
|---|---|---|
| `width` | INT | `EmptyLTXVLatentVideo.width` |
| `height` | INT | `EmptyLTXVLatentVideo.height` |
| `length` | INT | `EmptyLTXVLatentVideo.length`, `LTXVEmptyLatentAudio.frames_number` |
| `fps` | FLOAT | `LTXVConditioning.frame_rate`, `CreateVideo.fps` |
| `fps_int` | INT | `LTXVEmptyLatentAudio.frame_rate`(自動 round — ComfyMath 不要) |
| `info` | STRING | `Show Text` などにログ出力したい時用 |

`fps_int` 出力があるので、ComfyMath の `CM_FloatToInt` ノードは不要になります。

---

### 14. DARASK Float → Int  *(カテゴリ `DARASK`)*

`FLOAT` を `INT` に変換する小さなユーティリティ。[ComfyMath の `CM_FloatToInt`](https://github.com/evanspearman/ComfyMath) と同じ機能を、ComfyMath パック全体に依存せず使えるようにしたもの。

LTX 2.3 のテンプレートが `fps`(FLOAT)を `LTXVEmptyLatentAudio.frame_rate`(INT)に渡す時にこの変換が必要ですが、上記の `DARASK LTX 2.3 Video Settings` が `fps_int` を直接出すので、新規ワークフローではそちらを使えば本ノードは不要です(既存の ComfyMath ワークフロー移植用の置き換えノードという位置付け)。

**ウィジェット:**
* `value`(FLOAT, 入力強制)— 変換元の値
* `mode`(`round` / `floor` / `ceil` / `trunc`、デフォルト `round`) — 丸め方を選択(オプション)

**出力:** `INT`

---

### 15. DARASK LTX 2.3 Generator (All-in-One)  *(カテゴリ `DARASK`)*

LTX Video 2.3 の画像→動画パイプライン全体を **たった1ノード** にまとめた集約ノード。元の7サブグラフ(Models / I2V Image / Settings / Prompt / Low Res Gen / 2x Upscale / 4x Upscale / Decode)+ LoRA スタックを内部で全部こなします。

#### 入力(`image` のみ)

* `image` (IMAGE, 任意) — i2v の参照フレーム

それ以外はすべて **ウィジェットで設定** します(下のセクション)。

#### セクション構成(ウィジェット)

> **Anima/Wan の砂嵐・モザイク対策**: SD3スタイルの `multiplier` はモデルごとに違います(SD3=1000, Anima/Wan=1.0, LTX=1.0)。本ノードは `shift_multiplier=0`(デフォルト)で **モデルから自動検出** するので、Anima を選んでも壊れません。古い設定値で `shift_multiplier=1000` のまま保存されたワークフローを読み込んだ場合は、ノード上で **`shift_multiplier` を `0`** に変更してください(`/1000` で sigma がほぼゼロに圧縮されて砂嵐になります)。

**① Model**
* `model_name` — `checkpoints/` と `diffusion_models/` を統合した一覧。`.safetensors`(VAEバンドル可)と `.gguf` の両対応。10Eros 系の checkpoint を選ぶと audio VAE / CLIP も同じファイルから引ける
* `weight_dtype` — `default / fp8_e4m3fn / fp8_e4m3fn_fast / fp8_e5m2`(diffusion_models / gguf 用)
* `audio_vae_source` — `(from model)`(model_name と同じ checkpoint から取り出す)/ 個別 checkpoint 指定
* `video_vae_source` — 同上、`vae/` フォルダのファイルも選択可
* `text_encoder` — `text_encoders/` の gemma 等
* `clip_source` — `(from model)` または個別 checkpoint
* `upscale_model` — `latent_upscale_models/` の LTX 用アップスケーラー(2x/4xを使う時のみ)

**② LoRA(動的、`+ Add LoRA` で増やす)**

`DARASK Lora Loader` と同じ動的UI:
* ノード下部の **`+ Add LoRA` ボタン** を押すごとに行が1つ追加(toggle + ファイル選択 + 強度)
* **`− Remove Last LoRA` ボタン** で末尾の行を削除
* 行数の上限なし(必要なだけ追加可能)
* 各行のウィジェット:
  * `lora_N_on` (toggle) — ON/OFF
  * `lora_N` (combo) — LoRAファイル選択(`None` で無効)
  * `lora_N_strength` (number) — 強度
* ワークフローを保存して再読み込みすると、追加した行と値が復元されます

**③ Video Size(ライブプレビュー付き)**
* `width / height / length / fps` — 編集と同時にノード上部のバッジが更新:
  ```
  1024×576 (16:9) · 97f @ 24fps = 4.04s
  ```

**④ Prompts**
* `positive_prompt / negative_prompt` (multiline STRING)

**⑤ Image Preprocess**
* `image_max_dim` — リサイズ後の長辺/短辺
* `image_resize_method` — `scale longer dimension` 等
* `img_compression` — LTXVPreprocess の圧縮係数
* `bypass_i2v` — 画像コンディショニングを無効化(text-to-video モード)
* `i2v_strength` — 画像の影響度

**⑥ Sampling (base pass)**
* `seed`, `cfg_scale`
* `base_sampler` — `euler_ancestral_cfg_pp` など
* `base_sigmas` — マニュアル sigmas(カンマ区切り)

**⑦ 2x Upscale(オプション)**
* `enable_2x_upscale` — ON にすると LTXVLatentUpsampler で2倍化して再サンプル
* `upscale_2x_sampler / sigmas / strength / bypass_i2v`

**⑧ 4x Upscale(オプション)**
* `enable_4x_upscale` — 2xの後にもう1段(=4x)
* `upscale_4x_sampler / sigmas / strength / bypass_i2v`

**⑨ Decode**
* `vae_tile_size / vae_overlap / vae_temporal_size / vae_temporal_overlap` — `VAEDecodeTiled` のタイル設定

#### 出力

* `VIDEO` — `CreateVideo` の最終動画(SaveVideo に接続)
* `frames` (IMAGE) — VAE デコード後のフレーム列
* `audio` (AUDIO) — 同時に生成された音声
* `info` (STRING) — `"1024×576 (16:9) · 97f @ 24fps = 4.04s | LoRAs: <a.safetensors:1>, <b:0.8> | 2x upscale ON"` のようなサマリ

#### 10Eros モデル対応

[TenStrip/LTX2.3-10Eros](https://huggingface.co/TenStrip/LTX2.3-10Eros) のような **video VAE + audio VAE + CLIP の重みが全部1ファイルに入った checkpoint** は、`checkpoints/` に置いて:

* `model_name` = `10Eros_v1_bf16.safetensors`
* `audio_vae_source` = `(from model)`
* `video_vae_source` = `(from model)`
* `clip_source` = `(from model)`

と設定するだけで、内部で同じファイルから:
- `CheckpointLoaderSimple` で video VAE を抽出
- `LTXVAudioVAELoader` が `audio_vae.` プレフィックスから audio VAE を抽出
- `LTXAVTextEncoderLoader` が CLIP-V を抽出

を全部やってくれます。

#### GGUF モデル対応

`model_name` で `.gguf` ファイルを選ぶと、内部で **[ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)** の `UnetLoaderGGUF` を呼んで MODEL をロードします(要 ComfyUI-GGUF インストール)。GGUF は VAE / CLIP がバンドルされていないので、`audio_vae_source`, `video_vae_source`, `clip_source` は別の checkpoint(例: 10Eros)を指定してください。

#### ComfyMath 非依存

内部で `fps_int = int(round(fps))` に変換するため、`CM_FloatToInt` などの ComfyMath ノードは一切不要です。

---

### 16. DARASK Anima Sampling Tuner  *(カテゴリ `DARASK`)*

Anima / Wan 2.2 / SD3-flow 系の動画モデル向けに、よく使われるサンプリング最適化を **1ノードに集約** した調整ノード。Forge Classic Neo の「Shift」スライダー相当の操作感を ComfyUI で実現しつつ、ComfyUI 本体に元々あるけど分散している関連ノードを1箇所にまとめます。

#### 含まれる最適化

| 機能 | デフォルト(Forge Classic Neo 準拠) | 対応 ComfyUI 本体ノード |
|---|---|---|
| **Shift** (`ModelSamplingDiscreteFlow`) | ON, **3.0**(Anima preset 値), range 1.0–24.0, step 0.5 | `ModelSamplingSD3` / `ModelSamplingAuraFlow` / `ModelSamplingFlux` |
| **Temporal Score Rescaling** (TSR) — 動画特化のノイズ予測再スケーリング | OFF, k=1.0, σ=1.0 | `TemporalScoreRescaling` |
| **Epsilon Scaling** — exposure bias 補正 | OFF, **factor=1.0**(Forge 既定), range 1.0–1.05, step 0.005 | `EpsilonScaling` (arXiv:2308.15321) |
| **CFG mode**(排他):`Rescale CFG` / `CFG Zero Star` | off, multiplier 0.7, range 0.0–1.0, step 0.05 | `RescaleCFG` / `CFGZeroStar` |

CFG mode はラジオ式(`sampler_cfg_function` は1つしか持てない仕様のため)、それ以外は post-CFG hook なので **スタック可能**。

#### Forge Classic Neo の preset 値(参考)

`modules_forge/presets.py` の `SHIFT` 辞書より:

| Architecture | Forge デフォルト Shift |
|---|---|
| **Anima** | **3.0** (本ノードのデフォルト) |
| Wan 2.2 | 5.0 |
| Lumina-Image-2.0 | 6.0 |
| Z-Image-Turbo | 9.0 |
| Ernie-Image | 3.0 |
| AuraFlow | ~1.73 |

動きの一貫性を強めたいなら高め(5〜8)、シャープさ重視なら低め(3〜5)。

#### 出力

* `MODEL` — パッチ済みモデル
* `info` (STRING) — `"Active: shift(SD3/Anima)=5 + TSR k=1.00@σ1.00 + CFG-Zero★"` のような readout

#### Forge Classic Neo の "Anima Shift" UI との対応

* Forge の「Shift」スライダー = このノードの `shift_enable` + `shift` + `shift_style=SD3/Anima/Wan`
* Forge は実装は `ModelSamplingDiscreteFlow.set_parameters(shift=...)` を呼んでるだけで、ComfyUI の `ModelSamplingSD3` と完全に同じ処理。**機能差はゼロ、UI 集約のみ**

---

### 17. DARASK Anima Step Cache (Spectrum)  *(カテゴリ `DARASK`)*

Chebyshev 多項式外挿による **step caching** ノード。実 UNet 呼び出しを間引いて、欠けたステップは過去の出力から外挿予測で埋めます。動画系の flow モデル(Anima / Wan / SD3 / LTX 等)で **30〜50% の生成高速化**(品質コストはわずか)。

[Forge Classic Neo の Spectrum 拡張](https://github.com/Haoming02/sd-webui-forge-classic) / [rwwww/comfyui-spectrum-sdxl](https://github.com/ruwwww/comfyui-spectrum-sdxl) の同アルゴリズムを独立実装したもの。Forge / Spectrum 本体は不要。

#### ウィジェット

| ウィジェット | デフォルト | 役割 |
|---|---|---|
| `total_steps` | 30 | サンプラーの総ステップ数(warmup/stop 比率計算用) |
| `prediction_weight` | 0.25 | 0=Taylor 線形外挿のみ、1=多項式予測のみ |
| `polynomial_degree` | 6 | Chebyshev 多項式の次数(1〜8) |
| `regularization` | 0.5 | リッジ正則化 λ(高いほど平滑) |
| `window_size` | 2 | N ステップごとに実 UNet を1回呼ぶ |
| `flex_window` | 0.0 | window_size の漸進的増加幅 |
| `warmup_steps` | 6 | キャッシュ開始までの初期実行ステップ数 |
| `stop_caching_at` | 0.9 | スケジュール後半 (1-x) は実行モデル必須(クリーンなデノイズ) |

#### 内部実装

* `set_model_unet_function_wrapper` で UNet 呼び出しをラップ
* 過去 K=max(degree+2, 8) ステップの `(timestep, output)` をローリングバッファに保持
* Chebyshev 多項式を `XᵀX + λI` でリッジ回帰、Cholesky 分解で解く
* スケジュール先頭(warmup)と末尾(stop_caching_at 以降)は必ず実 UNet を実行 → 品質を担保

#### 注意

* `set_model_unet_function_wrapper` は **1つしか持てない** — 同じく wrapper を使う他ノード(TeaCache 等)と併用不可
* `DARASK Anima Sampling Tuner` は CFG hook と `model_sampling` のみ触るので、**この Step Cache の前段または後段に並べて両方適用可能**
* **mosaic / 砂嵐 が出た時のチェックリスト**:
  * **まず `DARASK Anima Sampling Tuner` の `shift_multiplier` を `0`(自動検出)に**。Anima/Wan 用の native multiplier=1.0 が必要なのに 1000 が指定されていると、σ が 1000× 圧縮されて砂嵐になります(古い保存値の典型)
  * Step Cache 側で `warmup_steps >= polynomial_degree + 1` を満たす(degree=6 なら warmup ≥ 7)。満たない場合は自動で Taylor フォールバックされるので致命的にはなりませんが、警告がログに出ます
  * それでも改善しない場合は `prediction_weight = 0` で Taylor 外挿のみに切替え
  * 効果検証として一時的に Step Cache をミュート(右クリック → Bypass)し、Sampling Tuner のみで正常生成できるか確認

#### 推奨組合せ

```
Loader → DARASK Anima Sampling Tuner (shift=5, TSR=on)
       → DARASK Anima Step Cache (window=2, warmup=6, stop_at=0.9)
       → KSampler
```

これで Anima 動画モデルの生成が **品質維持しつつ ~1.5x 高速** になります。

---

### 12. DARASK RIFE Interpolation  *(カテゴリ `DARASK`)*

RIFE(Real-Time Intermediate Flow Estimation)モデルで動画フレーム補間。`source_fps` のフレーム列を `target_fps` まで補間でアップサンプルします。8FPS → 24FPS など。

#### 入力

* **`images`**(IMAGE)— `[N, H, W, 3]` のフレーム列
* **`source_fps`**(FLOAT, デフォルト 16)— ソースのフレームレート
* **`target_fps`**(FLOAT, デフォルト 25)— 補間後の目標フレームレート
* **`scale`**(FLOAT, デフォルト 1.0)— 内部処理スケール。0.5 で約2倍速、画質は少し落ちる
* **`model_name`**(STRING, デフォルト `flownet.pkl`)— 使用する RIFE モデルファイル名
* **`batch_size`**(INT, デフォルト 8)— 並列処理フレームペア数。多いほど高速だがVRAM使用量増
* **`use_fp16`**(BOOLEAN, デフォルト True)— CUDA で FP16 推論(高速 + 省VRAM)

#### モデルの配置

下記のいずれかに `flownet.pkl` を置いてください(上から優先順):

1. `extra_model_paths.yaml` で `rife` フォルダ指定(`folder_paths.get_filename_list("rife")` で見つかる場所)
2. `<ComfyUI>/models/rife/flownet.pkl`(おすすめ)
3. `<このパッケージ>/rife_internal/train_log/flownet.pkl`

モデルファイル(`flownet.pkl`)は [hzwer/RIFE on Hugging Face](https://huggingface.co/hzwer/RIFE) から `RIFEv4.26_0921.zip` をダウンロードして展開してください。

#### 出力

* **`images`**(IMAGE)— 補間後フレーム列 `[M, H, W, 3]` where `M = (loaded_duration * target_fps)`

#### 帰属

このノード内部の RIFE モデルアーキテクチャ(`rife_internal/` 配下)は、Zhewei Huang et al. (hzwer) による MITライセンスの RIFE 公式実装 ([megvii-research/ECCV2022-RIFE](https://github.com/megvii-research/ECCV2022-RIFE), [hzwer/Practical-RIFE](https://github.com/hzwer/Practical-RIFE))から派生しています。ComfyUI ノードラッパー部分は darask 独自実装(MIT)。

---

## レシピ — フォルダ → アップスケール(EXIF駆動)

```
DARASK Folder Image Loader
  ├── image      ──▶ easy hiresFix (image input)
  └── filepath   ──▶ DARASK Exif Apply (Anima または SDXL)
                       ├── model, clip, vae      ──▶ easy pipeIn
                       ├── positive, negative    ──▶ easy pipeIn
                       └── seed/steps/cfg/sampler/scheduler/denoise
                                                  ──▶ easy preSampling (widget→input)
```

`easy fullLoader` と `easy loraStack` は不要 — `Exif Apply` がモデルロードと LoRA スタックを両方カバーします。

**フォルダ全部処理する場合**: Folder Image Loader を `Auto Advance` モード + `loop=False` にして、Auto Queue (instant) を有効化。最後の画像が処理されたら自動的に下流が `ExecutionBlocker` で止まり、ノードのバッジが緑の `(done)` に変わるので Auto Queue を OFF にしてください。

そのまま動かせる **完全なワークフロー JSON** が `example_workflows/hiresfix_folder_exif.json` にあります。ComfyUI 上で右クリック → "Load" でドラッグ&ドロップしてください([comfyui-easy-use](https://github.com/yolain/ComfyUI-Easy-Use) の事前インストールが必要)。

---

## レシピ — 全パターン生成(1キューでバッチ)

```
DARASK Prompt Cell (quality, Concat)
        │
        ▼
DARASK Prompt Cell (costume, Cartesian) ──▶ CLIP loader ──┐
        │                                                 │
        ▼                                                 │
DARASK Prompt Cell (lighting, Cartesian)                  │
        │                                                 ▼
        └──────────▶ DARASK Prompt Cell Output ─── CONDITIONING ──▶ KSampler
                              │
                              └── mode = All as Batch
                                  total_count ──▶ EmptyLatent.batch_size
```

`EmptyLatentImage` の代わりに **DARASK Empty Latent (Preset)** を使うとプリセット解像度から選べます。`batch_size` を Convert Widget to Input して `total_count` を繋ぐと、variant を追加するたびに自動でバッチサイズが追従します。

---

## レシピ — 動画フレーム補間 → MMAudio で音声合成

低FPSの動画を RIFE で滑らかに補間し、MMAudio で音声を合成する流れ:

```
DARASK Load Video (Upload)
  ├── IMAGE        ──▶ DARASK RIFE Interpolation
  │                       │ source_fps = 16, target_fps = 25
  │                       ▼
  │                    IMAGE ──▶ MMAudioSampler (images)
  │
  └── video_info   ──▶ DARASK Video Info
                          │
                          └── loaded_duration ──▶ MMAudioSampler (duration)

MMAudioSampler ──▶ AUDIO ──▶ SaveAudio
```

ポイント:

* RIFE の `source_fps` は Load Video の `force_rate` または `Video Info` の `loaded_fps` と合わせる(`select_every_nth > 1` の場合は割り算後の値)
* `target_fps` を上げすぎるとフレーム数が爆発する点に注意(`source_fps=16, target_fps=60` で約4倍)
* `Video Info` の `loaded_duration` を MMAudioSampler の duration に繋げば、補間で生成されるフレーム数と音声長がぴったり合う
* RIFE モデル(`flownet.pkl`)は事前に `<ComfyUI>/models/rife/` に配置

そのまま動かせる **完全なワークフロー JSON** が `example_workflows/mmaudio_video_to_audio.json` にあります。ComfyUI 上で右クリック → "Load" でドラッグ&ドロップしてください([ComfyUI-MMAudio](https://github.com/kijai/ComfyUI-MMAudio) の事前インストールが必要)。

---

## レシピ — 分岐ツリーで全シーンを1バッチに(推奨パターン)

variants が排他的なシーン(姿勢/アングル/フレーミングが互いに掛け合わせるべきでない)に分かれる時、**ツリー状にファンアウトしてリーフを全部 Output へ直結** します。中間でブランチを再合流させないのがポイント:

```
[Quality + character]
        │
        ▼
[Shared reactions]
        ├──▶ [Scene: paizuri]    ─┐
        ├──▶ [Scene: anal]       ─┤
        ├──▶ [Scene: cowgirl]    ─┼──▶ DARASK Prompt Cell Output ──▶ KSampler
        └──▶ [Scene: spooning]   ─┘
                                  ↑
                          Output の set / set_2 / set_3 / set_4 に直接接続
```

各シーンに固有の climax タグや細かい後付けを足したい場合は、**そのシーンセルの中(またはそのシーンの直後にそれ専用の追加セル)で完結** させ、再びファンインしないでください:

```
[Shared reactions]
   ├──▶ [Scene: paizuri]  ──▶ [Paizuri climax]   ─┐
   ├──▶ [Scene: anal]     ──▶ [Anal climax]      ─┤
   ├──▶ [Scene: cowgirl]  ──▶ [Cowgirl climax]   ─┼──▶ Output
   └──▶ [Scene: spooning] ──▶ [Spooning climax]  ─┘
```

Output の `set` 入力は1個繋ぐたびに空スロットが増えるので、リーフを何本でも差せます。`total_count` には全リーフを合計した総数が反映されます。

> **なぜマージセル(中間収束)を勧めないか**: 1つのマージセルに複数の上流ブランチを集約すると、そのセルが持つ variants が **全ブランチに対して掛け合わさる** ため、ブランチごとに違う追加タグを使いたい場合に対応できません。また、Union の結果に後段でデカルト積を掛けると組合せ数が想定以上に膨れがちです。**ツリーを維持したまま Output に直結する** のが最もシンプルで予測可能。

**実際にスイープを回すには:**

* `All as Batch`(デフォルト)+ `EmptyLatent.batch_size` を Convert Widget to Input にして `total_count` を接続 → Queue 1回で全画像生成
* `Iterate (auto-advance)` + ComfyUI の Auto Queue (instant) → 1キューずつ全パターンを順番に処理

Auto Queue 無しで `Iterate` を押した場合は1枚しか生成されません(次のインデックスは次のキューを待つ)— これは仕様であってバグではありません。

---

## Prompt Cells — 詳細ガイド

長尺の解説。一度読めばこの後の節はリファレンスとして使えます。

### コンセプト

**セル** はテキストボックスで、各行がプロンプト断片の variant です。セルを `prev → set` で繋ぐと **チェイン全体がデカルト積に展開**(2行 × 3行 × 4行 = 24パターン)。セルは **複数の上流ブランチ** を `prev`, `prev_2`, … で受けられ、これらは Union されます(4分岐 → 3行セル = `(全ブランチの合計) × 3` パターン)。終端の **Output** ノードも複数の `set` 入力を Union して CONDITIONING を出力。

### 主要な2ソケット

| ソケット | 型 | 流れる内容 |
|---|---|---|
| `prev`(セル入力) | `DARASK_PROMPT_SET` | 上流セルが組み立てた全プロンプト文字列のリスト |
| `set`(セル出力 / Output 入力) | `DARASK_PROMPT_SET` | 同じく — セルの `set` は **そこまでのデカルト積/Union結果** そのもの |

両方とも **動的スロット**(最大16個)。1個繋ぐと下に空スロット出現、切断すると末尾が畳まれる。

### Cell モード詳細

| モード | このセルの各行をどう扱う |
|---|---|
| `Cartesian (all combos)` *(デフォルト)* | 各行を独立した variant 扱い。出力数 = `上流 × 行数`。「これらのうちどれか」分岐用 |
| `Concat (all lines as one)` | 全行を `separator` で結合して **1個** の断片に。出力数 = `上流 × 1`。Quality / Character の "常にON" ブロック向け |
| `Random pick one` | 1キューごとにランダムに1行選択(seed制御)。出力数 = `上流 × 1` |
| `Fixed index` | `index` ウィジェットで1行を固定。出力数 = `上流 × 1` |

`enabled = false` でセル完全スキップ(上流をそのまま通す)— レイヤーを配線を外さず A/B トグルしたい時に。

テキストボックス内:
* `#` で始まる行は **コメント**(展開前に削除)
* 途中の **空行** は no-op variant — 上流のプロンプトを変更せず通す。「X追加 / Y追加 / 何も追加しない」を1つのセルで表現できる

### Output モード詳細

| モード | 出力 | 使いどき |
|---|---|---|
| `All as Batch` *(デフォルト)* | 全パターンをバッチ次元にスタックした CONDITIONING テンソル1個。`total_count` に総数 | **1キューで全部出したい時**。`total_count` を latent の `batch_size` に繋いで KSampler に全画像を生成させる |
| `Iterate (auto-advance)` | 1キューにつき1プロンプト、カーソル +1。`current_prompt` / `current_index` で進捗確認。`loop` で末尾ラップ | 順次レンダリングしたい(VRAM節約)。**ComfyUI の Auto Queue (instant) 必須** — 押すだけだと1枚 |
| `Index` | `index` 指定の1パターンを返す。進めない、バッチしない | 特定パターンのデバッグ、A/B比較 |

`reset = true` で Iterate カーソルを次回ゼロ化。カーソルはノードID付きで保存されるので軽い編集では位置を保持。

### Step-by-step — 最初のチェイン

ゴール: 3セルのチェインで全組合せをバッチ生成。

1. **DARASK Prompt Cell** を3個並べる。頭の中で *Quality*, *Costume*, *Pose* と命名
2. *Quality* に常時オンタグ(`masterpiece, best quality, 1girl, ...`)を貼り、`mode` を **`Concat (all lines as one)`** に。各行を別 variant にしたくないので Concat
3. *Costume* に衣装を1行ずつ3〜4個、`mode` は **`Cartesian`** のまま:
   ```
   white sundress
   black hoodie, jeans
   school uniform
   ```
4. *Pose* に2〜3個、`Cartesian`
5. 配線: `Quality.set → Costume.prev`, `Costume.set → Pose.prev`
6. **DARASK Prompt Cell Output** を1個追加。`Pose.set → Output.set`, CLIP loader の CLIP を `Output.clip` に
7. 各セルの `preview` ソケットを `Show Text`(rgthree/easy-use等)に繋ぐと実際に組み立てられたプロンプトが確認できる。`count` ソケットは INT — latent batch size との比較に便利

### Step-by-step — 1キューで全パターン生成

上の続きから、`Output.mode = All as Batch` で:

1. **DARASK Empty Latent (Preset)** を追加
2. `batch_size` ウィジェットを **右クリック → Convert Widget to Input**(入力ソケット化)
3. `Output.total_count → EmptyLatent.batch_size` を接続
4. `EmptyLatent.latent → KSampler.latent_image`, `Output.conditioning → KSampler.positive` を接続
5. **Queue** を押す → N 個のプロンプトと N 個の空 latent が KSampler に渡り、1パスで全 N 枚を生成、SaveImage が全部書き出す

> **`batch_size` に数字直書きでもいいんじゃ?** 一応OK、でも上流に variant 1個増やした瞬間 `total_count` が変わって手書きのバッチサイズと合わなくなる。配線しておけば常に variant 数と一致して自動追従。

> **VRAM注意**. `batch_size = total_count` は並列レンダリング。SDXL解像度で64パターンとかは大量のVRAMを食う。OOM したら次節の Iterate + Auto Queue に切り替え。

### Step-by-step — 順次生成(低VRAM)

`All as Batch` で OOM する時、または1枚ずつ保存されてほしい時:

1. `Output.mode = Iterate (auto-advance)` に
2. latent の `batch_size = 1` のまま
3. キューパネル(右側)の最下部の **Extra options** をクリック、**Auto Queue: `instant`** に設定
4. **Queue Prompt** を1回押す → 1枚目レンダリング完了 → ComfyUI が自動で次をエンキュー → Output のカーソルが +1 されてるので次のプロンプトでエンコード → ... → `total_count` まで到達したら `loop` 次第でラップまたはストップ
5. 途中で止める: Auto Queue を OFF、または Queue を **Clear**
6. 最初から: `Output.reset` を ON にして1回 Queue(カーソル0化)、OFF に戻してもう一度 Queue

> **「Queue 1回で1枚しか出ない」** は `Iterate` の正しい挙動。Auto Queue で連鎖させてください

### Step-by-step — 分岐ツリーで全シーンを1バッチに

`Anima_simple` 系ワークフローの定石パターン。Quality と Character は共通、シーンは排他(`paizuri × anal × doggystyle` の組合せは要らない)で扱います。**ツリー状にファンアウトしてリーフを全部 Output に直結** するのが推奨:

```
[Quality+character]    ┌─▶ [Scene: paizuri]    ──▶ [Paizuri climax]  ─┐
        │              ├─▶ [Scene: anal]       ──▶ [Anal climax]     ─┤
        ▼              │                                               ├─▶ Output ─▶ KSampler
[Shared reactions] ────┼─▶ [Scene: cowgirl]    ──▶ [Cowgirl climax]  ─┤
                       └─▶ [Scene: spooning]   ──▶ [Spooning climax] ─┘
                                                                       ↑
                                                          Output の set / set_2 / set_3 / set_4
```

仕組み:

1. **ファンアウト** はタダ — 1つのセルの `set` 出力は複数の `prev` に同時接続可能。*Shared reactions* の `set` を4つのシーンセルの `prev` に繋ぐ。ComfyUI 上で同じ出力から4本の線が出るが正常
2. **各シーンセル** は自分の variants を持ち `Cartesian` モード。各ブランチ終端のパターン数 = `共通分のパターン数 × シーン行数`
3. **後付けタグは各ブランチ専用のセル** で。シーンごとに違う climax タグを使いたい時、各シーンの後ろに専用の小さなセルを並べる。**マージセル(複数の上流から `prev / prev_2 / ...` に集約するセル)は置かない** — 後付け variants が全ブランチに掛け合わさる事故を防ぐため
4. **Output の `set` 入力で初めて合流** — リーフを `Output.set / set_2 / set_3 / set_4 / ...` に直接接続。Output は受けた全リーフを Union(連結)するだけなので、各ブランチの variants は独立に保たれる
5. **`total_count`** は全配線ブランチの総和。`EmptyLatent.batch_size` に繋いで一発バッチ生成

> 動的スロットUIは常に末尾に空スロットを1個維持する。繋ぐと下に空が追加、最大16ブランチ/セル(Output も同様)。

> **鉄則(再掲)**: ノードは **だんだんと枝分かれしていく方向にのみ繋ぐ**。中間セルでブランチを再合流させない。合流は **Output ノードでだけ** 行う。

### 接続スタイルの使い分け

| 状況 | どう繋ぐ |
|---|---|
| ブランチ同士を **デカルト掛け合わせ** したい(衣装 × ポーズ × アングル の全組合せ) | 分岐させずに **1本の直線チェイン**(セル → セル → セル)に。分岐は OR、直線は AND |
| シーンごとに **排他的な variants** を試したい(掛け合わせたくない) | 共通の頭セルから **ファンアウト**、各リーフを **Output へ直結**。マージセルは置かない |
| 全シーンに **同じ後付けタグ** を適用したい(例: 全シーンに共通の climax タグ) | **各シーンセルの後ろに同じ内容の小さなセルを並べる**(コピペで4個並べる)、または **シーンセルの中に直接書く**。マージセルで集約しない(後付け variants が全ブランチに掛け合わさってしまうため) |
| シーンごとに **違う後付けタグ** を適用したい(例: paizuri には bukkake、anal には cum_overflow) | 各シーンの後ろに **シーン専用の追加セル** を置く。ツリー構造を維持したまま Output へ |

**鉄則: ノードはだんだんと枝分かれしていく方向にのみ繋ぐ。再合流(マージ)は Output ノードでだけ行う。**

### preview / count の見方

* `set` は実際のプロンプト配列(カスタム型 — 下流に繋ぐ用)
* `count` は INT — このセルまでのパターン総数。各セルの隣に `Show INT` を置くと行を増やすたびに数が増えるのが見える
* `preview` は STRING — 最初の8パターンを番号付きでリスト表示 + `+N more` 末尾。`label`(任意 STRING ウィジェット)で preview ヘッダーに接頭辞を付けられるので、複数の `Show Text` を区別したい時に便利

### ハマりやすいポイント

1. **Quality セルが Concat ではなく Cartesian になっている** — 常時ON用の6行ブロックが Cartesian だと、それぞれが排他 variant 扱いになり下流のパターン数が6倍に膨れる。Quality / Character の頭は **Concat** に
2. **中間セルで複数ブランチを再合流させてしまう** — マージセルにシーンA・B・C・Dの4本を集めて、そのセルが2行 variants を持つと「全シーンに同じ2 variants が掛け合わさる」結果になる。シーンごとに違う後付けタグを使いたい場合は表現できない。**枝分かれは保ったまま Output に直結**、合流は Output だけで行う
3. **`All as Batch` なのに `batch_size = 1` のまま** — Output は N 個のバッチ CONDITIONING を出すが、KSampler は latent batch size が1だと先頭プロンプトだけ繰り返す。`total_count → batch_size` 必須
4. **`Iterate` で Queue を1回押しただけ** — 仕様通り1枚。Auto Queue (instant) を有効化
5. **`Cartesian` セルの空行** — 意図的な no-op variant(上流を改変せず通す)。不要なら行を削除するか `Concat` モードに
6. **循環** — ComfyUI のグラフは DAG。セルの `set` を自分の `prev` に戻すループは不可。ファンアウトとOutputでの合流はOK、循環はNG
7. **`total_count` がウィジェットパネルに表示されない** — 出力ポートでありウィジェットではないため。`Show INT` に繋ぐか(または latent の batch_size に繋ぐ)で数値を確認

### サンプルワークフローの読み方

`Anima_simple` シリーズ: quality + character + reactions の頭 → 4つのシーンブランチ → ブランチごとの cum セル(任意)→ 4つの `set` 入力を持つ Output ノード。`Output.mode = All as Batch` にして `total_count → EmptyLatent.batch_size` を繋ぎ、Queue を1回押すだけで全シーン全組合せが1バッチで出力されます。

---

## サンプルワークフロー

`example_workflows/` 配下に DARASK ノードを組み合わせた完全なワークフロー JSON を置いています。ComfyUI 上で右クリック → "Load" でドラッグ&ドロップして使えます。

| ファイル | 内容 |
|---|---|
| `anima_simple.json` | Anima(`hakushiMixAnima_v02.safetensors` + Qwen-3 0.6B CLIP + Qwen VAE)で 832×1216 ポートレートを生成するミニマルな i2v 用ベース。`DARASK Lora Loader` で複数 LoRA をスタック、`DARASK Anima Step Cache` で 30 ステップを Chebyshev キャッシュで加速、`DARASK Anima Sampling Tuner` で shift=3.0(Forge Anima 既定)を適用、`DARASK Empty Latent (Preset)` でアスペクト比選択 |
| `hiresfix_folder_exif.json` | フォルダ内の画像を順に読み込み、EXIF から元のモデル/LoRA/プロンプト/サンプラー設定を復元して `easy hiresFix` でアップスケール → SaveImage。`DARASK Folder Image Loader` + `DARASK Exif Apply (Auto-detect)` を `easy pipeIn / hiresFix / preSampling / kSampler / pipeOut` と組み合わせた例。[comfyui-easy-use](https://github.com/yolain/ComfyUI-Easy-Use) が必要 |
| `mmaudio_video_to_audio.json` | 動画ファイル → RIFE でフレーム補間(16→25fps)→ MMAudio で音声生成 → SaveAudio。`DARASK Load Video (Upload)` + `DARASK RIFE Interpolation` + `DARASK Video Info` の組み合わせ例。[ComfyUI-MMAudio](https://github.com/kijai/ComfyUI-MMAudio) が必要 |
| `ltx23_video_to_video.json` | **サブグラフを使わないフラットなLTX 2.3 image-to-video パイプライン**。元のサブグラフ7個(Settings / Prompt / Low Res Gen / 2x Upscale / 4x Upscale / Decode / Models / I2V Image)をすべて展開し、各ステップのノードを直接編集可能に。ComfyMath の `CM_FloatToInt` は `DARASK Float → Int` に置き換え済み。`DARASK Lora Loader` で複数 LTX 2.3 LoRA をスタック。48ノード/74リンク。[ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) が必要 |

---

## Development Notes / 引き継ぎメモ

このセクションは、ノード群を開発・保守する上で **コードや git log から推測しづらい背景知識** をまとめたものです。将来のセッションで同じ問題を二度踏まないためのチェックリストとして利用してください。

### Architecture-specific sampling multiplier(超重要)

`ModelSamplingDiscreteFlow.set_parameters(shift, multiplier)` の `multiplier` は **モデルアーキテクチャごとに違う値** が `comfy/supported_models.py` で定義されています。間違った値を入れると σ が桁違いに圧縮/拡大されて **砂嵐 / モザイク** が出ます。

| Architecture | `multiplier` | 出典 |
|---|---|---|
| **Anima** | **1.0** | `comfy/supported_models.py` の `class Anima.sampling_settings` |
| **Wan 2.x** | **1.0** | 同上 (`Wan21`) |
| **LTX-Video** | **1.0** | 同上 |
| **SD3** | **1000** | 同上 (`class SD3`) |
| Flux | 1.0(`set_parameters` 引数なし) | `ModelSamplingFlux` |

→ `model_sampling.py:_resolve_multiplier()` は `explicit > 0` ならそれを、`0` なら `m.model.model_sampling.multiplier` から自動検出します。`shift_multiplier` ウィジェットのデフォルトは **`0.0`(自動)**。SD3 専用に使う時だけ `1000` を手で入れる。

過去のバグ: `shift_multiplier` のデフォルトを `1000`(SD3 値)にしていた時期があり、Anima を繋ぐと sigma が 1/1000 になって砂嵐が出ました。**絶対に 0(自動)から変えない**。

### Forge Classic Neo SHIFT preset table(参考)

`modules_forge/presets.py` の `SHIFT` 辞書より。Forge Classic Neo の Anima Shift スライダーは内部で `ModelSamplingDiscreteFlow.set_parameters(shift=...)` を呼んでいるだけなので、ComfyUI 側でも同じ値が使えます。

| Architecture | Forge デフォルト |
|---|---|
| Anima | **3.0** ← `DARASK Anima Sampling Tuner` のデフォルト |
| Ernie-Image | 3.0 |
| Wan 2.2 | 5.0 |
| Lumina-Image-2.0 | 6.0 |
| Z-Image-Turbo | 9.0 |
| SDXL | -9.0(負値で「逆shift」) |
| AuraFlow | ~1.73 |

### バグ史(同じ事を二度やらないために)

| 症状 | 真因 | 修正 |
|---|---|---|
| **砂嵐/モザイク** が出力に出る | `_patch_shift_sd3` の `multiplier` デフォルトが SD3 値の 1000 だった。Anima native は 1.0 なので σ が 1/1000 に圧縮 | `_resolve_multiplier()` で model から自動検出。widget デフォルト `0` |
| 似た砂嵐(別件) | Step Cache の `_ChebyshevForecaster.push` が `h.view(-1)` で **view** を保持していた。サンプラーが内部で in-place 操作するとキャッシュが silently 壊れる | `h.detach().clone().reshape(-1)` に変更 |
| Step Cache が under-determined poly fit でモザイク | バッファ点数 < `degree+1` の状態で ridge regression を呼んでいた | `len(H_buf) < degree+1` なら Taylor フォールバック + 起動時に warmup_steps チェックの警告 |
| `AttributeError: 'NoneType' object has no attribute 'clone'` (Step Cache / Sampling Tuner) | `DARASK Lora Loader` は `model=None` を **黙って** pass-through する仕様。ワークフローで UNETLoader→Lora Loader.model が未配線だと None が下流に流れる | Lora Loader 側で `clip` だけ繋がっている時は warning print、Step Cache / Sampling Tuner 側でも明示的 `ValueError` を投げる |
| Folder Image Loader のカーソルが workflow 編集で巻き戻る | Python の `id(self)` を state キーに使っていたが、ノード再構築で id が変わる | hidden input `unique_id`(LiteGraph ノードID)を state キーに |
| `ExecutionBlocker` で赤いエラートーストが毎回出る | `ExecutionBlocker("msg")` は文字列を渡すとトーストが出る仕様 | `ExecutionBlocker(None)` でサイレント遮断 |

### Implementation patterns(再利用パターン)

1. **動的入力(`+ Add` ボタン等)** — `_FlexibleOptionalInputs` (dict サブクラス) を `INPUT_TYPES.optional` に渡し、`__contains__` を常に True、未宣言キーには `(_ANY,)` を返す。JS 側が `lora_N` 等の任意キーを serialise すれば Python 側でそのまま受け取れる。`lora_loader.py:_FlexibleOptionalInputs` 参照。

2. **`set_model_sampler_cfg_function` は単一スロット** — RescaleCFG と CFGZeroStar が両方とも `sampler_cfg_function` に書き込むため **排他**。Sampling Tuner では radio で1つだけ選べる UI に。一方 `set_model_sampler_post_cfg_function` は **スタック可能**(リスト)、`set_model_unet_function_wrapper` も **単一スロット**。

3. **状態の永続化** — workflow に紐付ける state は hidden input の `unique_id`(LiteGraph ノードID)をキーにすること。`id(self)`(Python オブジェクトID)は ComfyUI が頻繁に再生成するので NG。

4. **size の保存** — JS で `addWidget` / `addInput` するとノードが伸びる。`preserveSize()` ヘルパで snapshot→操作→restore する(`web/darask_ltx23.js` 参照)。

5. **V3 API** — `io.ComfyNode` 子クラスは `_exec` クラスメソッドを `args` で受けて中で unpack、`io.NodeOutput(...)` を返す。レガシー V1 と異なり戻り値は tuple ではなく `NodeOutput`。

6. **自前で再キュー** — `PromptServer.instance.prompt_queue.put((number, prompt_id, prompt, extra_data, outputs_to_execute, sensitive))` の **6-tuple** 形式。`outputs_to_execute` は `OUTPUT_NODE=True` なノードの ID リスト。`folder_loader.py:_enqueue_self()` 参照。

7. **ExecutionBlocker** — `comfy_execution.graph.ExecutionBlocker` を **OUTPUT のどれか1つ** に流せば、それを受け取る下流ノードすべてがスキップされる。`None` 引数で silent、文字列引数で赤トースト。

### モデルファイル配置(典型構成)

| 用途 | パス | 例 |
|---|---|---|
| UNet(diffusion model) | `models/diffusion_models/` | `hakushiMixAnima_v02.safetensors` |
| Text encoder | `models/text_encoders/` | `qwen_3_06b_base.safetensors` |
| VAE | `models/vae/` | `qwen_image_vae.safetensors` |
| RIFE モデル | `models/rife/` | `flownet.pkl`(hzwer/RIFE の RIFEv4.26_0921.zip) |
| Checkpoints(SDXL/SD1.5/Pony 等) | `models/checkpoints/` | `<arch>.safetensors` |
| LoRAs | `models/loras/` | サブフォルダOK、fuzzy match で解決 |
| GGUF | `models/diffusion_models/` または `models/unet/` | ComfyUI-GGUF 必須 |

### Anima_simple ワークフローの注意

- `anima_simple.json` は **UNETLoader → DARASK Lora Loader** に `model` リンクが必要(link 150)。これが無いと Lora Loader が None pass-through し、下流の Step Cache / Sampling Tuner で `AttributeError` または無限の "model is not connected" エラー。
- 古い保存版を読み込んだ時は、ノード上で UNETLoader の `MODEL` 出力から Lora Loader の `model` 入力に手動で線を引き直すこと。
- スタック順: `UNETLoader → DARASK Lora Loader → DARASK Anima Step Cache → DARASK Anima Sampling Tuner → KSampler`(Step Cache は `unet_function_wrapper`、Sampling Tuner は CFG hook + `model_sampling` なので順序は逆でも動くが、慣例的にこの順)。

### JS extension パターン

- **ライブプレビュー badge**(LTX23 Generator / Video Settings の右上ピル)— `onDrawForeground(ctx)` でノードのウィジェット値を読んで CanvasRenderingContext2D で描画。`node.setDirtyCanvas(true)` を widget callback で呼んで再描画トリガ。
- **動的 add/remove** — `addWidget(type, name, value, callback, options)` / `removeWidget(idx)` を `node.widgets` 配列に対して呼ぶ。`node.serialize_widgets = true` で値が workflow JSON に保存される。
- **`onConfigure`** で workflow ロード時に widgets を再構築(`+ Add LoRA` で追加された行は Python 側に存在しないので、JS が前回の数だけ widget を再生成する必要がある)。
- **`onNodeCreated`** は新規ノード配置時、`onConfigure` は workflow ロード時に呼ばれる。両方で widget 初期化ロジックを共有する。

### Auto Queue 関連の挙動メモ

- ComfyUI の Queue panel → "Extra options" → **Auto Queue: `instant`** が一番強力。1キュー終了で即次キュー。`change` は workflow が変わった時だけ。
- `DARASK Folder Image Loader.auto_queue_all = True`(デフォルト)を有効にすると、Queue 1回押下時にノードが残り画像分のプロンプトを **その場で一気に `prompt_queue.put`**(フロントロード)するので、Auto Queue が OFF でも1パス完走する。キューパネルに N 個並ぶので途中キャンセル/クリアもしやすい。両方有効にすると **二重 enqueue** されて無駄なので、片方だけ使う。

### トラブルシューティング クイックリファレンス

| 症状 | まず確認すること |
|---|---|
| 砂嵐/モザイク | `DARASK Anima Sampling Tuner.shift_multiplier = 0`(自動)か |
| `AttributeError: 'NoneType' object has no attribute 'clone'` | `UNETLoader → DARASK Lora Loader.model` の線が繋がっているか |
| Iterate モードで1枚しか出ない | Auto Queue (instant) が ON か |
| Folder Image Loader が同じ画像を返し続ける | `mode = Auto Advance` か(Manual Index になっていないか)/ folder パスを変えた直後ならカーソル自動リセット済 |
| Step Cache で品質劣化が酷い | `warmup_steps >= polynomial_degree + 1` を満たすか / `prediction_weight = 0` で Taylor only に切替えて検証 |
| LTX 2.3 で `CM_FloatToInt` 不要 | `DARASK LTX 2.3 Video Settings` の `fps_int` 出力を使う |
| rgthree workflow から LoRA が復元されない | `DARASK Exif Apply` の Anima / SDXL バリアントを試す(Auto-detect が判定ミスする場合あり) |

---

## ライセンス
MIT(ただし `rife_internal/` 配下は派生元の MIT を継承)
