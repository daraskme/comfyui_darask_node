# comfyui_darask_node

ComfyUI 用 DARASK カスタムノード集。3つの実用ワークフローを軸にした12個のノード:

1. **画像フォルダの一括アップスケール** — フォルダから画像を順に読み、EXIF / PNGinfo に
   埋め込まれた **元のモデル + LoRA + プロンプト** を自動復元してアップスケール
2. **プロンプト断片の全パターン生成** — quality × costume × pose × lighting × …
   のような掛け合わせを、手動で順列を書かずに自動展開
3. **動画フレーム補間 + 音声生成** — 動画ファイルを読み込み、RIFE でフレーム補間して
   フレームレートを上げ、MMAudio 等で音声を合成する一連の処理

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

#### ループ・リセット

* `loop`(デフォルト **ON**)— 末尾到達後にカーソルを 0 にラップ。常に新しい画像を回したいなら ON のまま。**通常の Queue Prompt(即時ではない)で連打する場合もこちらが自然** — 押すたびに次の画像が出て、最後まで行ったら自動で先頭に戻ります。
* `loop = False` — 1パス処理用。
  * **末尾到達 → 次の1キューだけ `ExecutionBlocker` で下流(SaveImage / KSampler 等)を遮断**(ノードのバッジが緑の `(done)` になる)
  * **その後 cursor は自動で 0 にリセット** されるので、次のキューからは1枚目から再生開始
  * Auto Queue (instant) ユーザー: 緑バッジを見たタイミングで Auto Queue を OFF にすれば「1パスだけ処理」が綺麗に実現
  * 通常 Queue Prompt ユーザー: 連打しても末尾の1回が空振り(画像保存スキップ)するだけで、その次の Queue から普通に1枚目に戻ります — `reset` を手動で切り替える必要なし
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

複数のLoRAを1ノードでスタック適用するノード。[rgthree の Power Lora Loader](https://github.com/rgthree/rgthree-comfy) と同じ機能を独立実装したものです。ウィジェットの保存形式(`{on, lora, strength, strengthTwo}`)も rgthree と同じなので、Exif Apply 系がメタデータからLoRA情報を読み出す時もこのノードを認識します。

#### 操作

* **`+ Add Lora` ボタン** をクリックでLoRA行を追加
* 各行:
  * **左のトグル** — クリックでON/OFF切り替え。緑がON、灰色がOFF
  * **中央のファイル名** — クリックでLoRAピッカー(`folder_paths.get_filename_list("loras")` の一覧)が開く
  * **右の数値ボックス** — strength。`−` / `+` ボタンで±0.05、中央クリックで直接入力、左右ドラッグでスクラブ調整(0.01単位)
* **行を右クリック** → コンテキストメニュー:
  * Enable / Disable(トグル)
  * Change LoRA…(別のLoRAに変更)
  * Move Up / Move Down(行の並び替え)
  * Remove(行削除)

#### プロパティ

ノード自体を右クリック → Properties から:

* `Show Strengths` — `Single`(1つのstrengthを model/clip 両方に適用、デフォルト)/ `Model + Clip`(modelとclipのstrengthを別々に設定する2スロット表示)
* `Match` — LoRAピッカーに表示するファイルを正規表現でフィルタ(空なら全部表示)

#### 入出力

**入力**: `model`(MODEL)、`clip`(CLIP)— どちらもオプション。`clip` なしで `model` だけ繋いでも動作します(その場合はmodel側のみにLoRAを適用)。

**出力**: `MODEL`、`CLIP`

#### 動作の細部

* `on=false` または `strength=0`(strengthTwo も合わせて0)の行はスキップ
* `lora` が空、または `folder_paths.get_filename_list("loras")` で見つからないファイル名の行はスキップ(コンソールに `missing LoRA '...'` 警告)
* ファイル名は **fuzzy match** で解決:exact → basename(拡張子なし)→ substring の順
* `strengthTwo` が `None` の時は `strength` を model/clip 両方に適用、`strengthTwo` が数値なら model=`strength`, clip=`strengthTwo`

#### rgthree との互換性

ウィジェット保存形式が同じなので、rgthree Power Lora Loader を使ったワークフローで生成された画像のメタデータからは、`DARASK Exif Apply` がそのまま LoRA リストを復元できます(逆も同じ)。ノード自体は別物なので、rgthree がインストールされていない環境でも DARASK Lora Loader だけで完結します。

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
| `hiresfix_folder_exif.json` | フォルダ内の画像を順に読み込み、EXIF から元のモデル/LoRA/プロンプト/サンプラー設定を復元して `easy hiresFix` でアップスケール → SaveImage。`DARASK Folder Image Loader` + `DARASK Exif Apply (Auto-detect)` を `easy pipeIn / hiresFix / preSampling / kSampler / pipeOut` と組み合わせた例。[comfyui-easy-use](https://github.com/yolain/ComfyUI-Easy-Use) が必要 |
| `mmaudio_video_to_audio.json` | 動画ファイル → RIFE でフレーム補間(16→25fps)→ MMAudio で音声生成 → SaveAudio。`DARASK Load Video (Upload)` + `DARASK RIFE Interpolation` + `DARASK Video Info` の組み合わせ例。[ComfyUI-MMAudio](https://github.com/kijai/ComfyUI-MMAudio) が必要 |

---

## ライセンス
MIT(ただし `rife_internal/` 配下は派生元の MIT を継承)
