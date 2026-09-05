# Step 4 SfM / Step 5 データセットGUI

Step 4は、学習データセットの元になるカメラポーズと疎点群をどう用意するかを選ぶ画面です。すでにMetashape、RealityScan、COLMAP、COLMAP球面SfMなどでSfM済みなら、ここで追加作業をする必要はありません。これからこのアプリでCOLMAPを実行したい場合、またはMetashape結果からRealityScan再アライン用データを作りたい場合だけ、対応するカードを開きます。

Step 5は、SfM結果を学習アプリで読み込めるデータセットへ変換する画面です。Metashape、COLMAP、COLMAP球面SfMの結果からNeRF系JSON/PLYを作る、MetashapeやRealityScanの結果からCOLMAP形式データセットを作る、AprilTagでスケールを反映する、といった作業をここで行います。

## 関連ツール

| ツール | このアプリでの用途 |
| --- | --- |
| [COLMAP](https://github.com/colmap/colmap) | Step 4のCOLMAPルート、COLMAP 4.1以降（4.2以降推奨）のネイティブEQUIRECTANGULAR球面SfM、COLMAP形式データセット出力 |
| [LichtFeld Studio](https://lichtfeld.io/) | LichtFeldプリセット、GUT出力、RealityScanからCOLMAPデータセットへの変換先 |
| [Postshot](https://www.jawset.com/) | PostshotプリセットとStep 6のCLI起動 |
| [Brush](https://github.com/ArthurBrussee/brush) | オープンソースのGaussian Splatting学習向けCubemap出力 |

## まず決めること

最初に決めるのは、「カメラポーズはもうあるか」です。

| 状態 | 進み方 |
| --- | --- |
| MetashapeでSfM済み | Step 4は `既存のSfM結果を使う`。Step 5でMetashape系カードを選ぶ |
| RealityScanで再アライン済み | Step 4は `既存のSfM結果を使う`。Step 5で `RealityScan → COLMAPデータセット` を選ぶ |
| COLMAPのimages/masks/sparseがすでにある | Step 4は `既存のSfM結果を使う`。COLMAP対応アプリならそのまま学習へ進み、Nerfstudio用JSON/PLYが必要なら `COLMAP RIG → NeRFデータセット(JSON/PLY)` を使う |
| このアプリからCOLMAPでSfMしたい | Step 4で `COLMAPでSfMを実行` |
| 同一解像度のERP 360°画像を球面カメラのままSfMしたい | Step 4で `COLMAP球面SfMを実行` |
| Metashape結果をRealityScanで再アラインしたい | Step 4で `Metashape → RealityScan用データ作成` |
| 作成済み結果を確認したい | Step 4で `SfM結果を確認` |

## Step 4: SfMカードの選び方

### 既存のSfM結果を使う

Metashape、RealityScan、COLMAP、COLMAP球面SfMなどで、すでにカメラポーズと疎点群を作ってある場合に選びます。このカードは「何もしないで次へ進む」ための選択肢です。次のStep 5で、その結果をどのデータセット形式へ変換するかを選びます。

Metashape結果を使う場合は、カメラをAgisoft XML、疎点群をStanford PLYとしてエクスポートします。どちらもシーンフォルダに保存しておくと、SfM結果をシーンと一緒に管理しやすくなります。別の場所に保存した場合は、Step 5のカードでXMLとPLYを手動選択してください。

### COLMAPでSfMを実行

Metashapeを使わず、このアプリから[COLMAP](https://github.com/colmap/colmap)またはGLOMAPでSfMしたい場合に選びます。

Windowsでは[公式COLMAP 4.2.0 CUDA版ZIP](https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip)を使います。ZIPを展開し、最上位の `COLMAP.bat` を選びます。RTX 50シリーズにも自前ビルドなしで対応しています。

- 360°画像はCubemap Rigへ展開します
- 通常画像や通常動画フレームは通常カメラとして扱います
- 混在ソースを一つのCOLMAPデータセットとして処理できます
- 出力は `output/colmap_rig/` です

通常は、動画順に撮った素材なら `Sequential` から始めます。写真枚数が少なく、順序より全体照合を優先したい場合は `Exhaustive` を検討します。

通常画像のカメラはGUIでは自動推定を使います。明示的な校正済み内部パラメータが必要な場合は、このStepで手入力するのではなく、取り込み前の外部メタデータとして用意します。

Cubemapの解像度は画像変換の倍率で選び、特徴点上限は1面あたり8,192です。ERP球面SfMの処理設定とは別の設定で、1枚の360°画像から複数の面を作るため、球面画像1枚の上限とは単純比較できません。

COLMAPのGlobal / Incremental Mapperでは、同じ360°フレームから作ったビューの相対位置・向きを固定します。ERPのみなら描画時に決まる画角と画像中心も固定し、通常写真を混ぜる場合は内部パラメータの推定を有効に保ちます。重なりのない90°以下のCube配置を今回生成するときだけ、同一フレーム内の照合を省略します。カスタムの重なりがある配置は照合対象に残します。外部GLOMAPは、その実行ファイルの設定で推定します。

以前に生成したRig画像でSfMをやり直す場合、アプリが画像変換を案内したら、画像変換もONにしてビュー画像とカメラ設定をそろえます。完成済みのSparseモデルをStep 5で使うだけなら再生成は不要です。

### COLMAP球面SfMを実行

360°動画から抽出したエクイレクタングラー画像を、Cubemap化せずにSfMしたい場合に選びます。入力は**同一解像度のERP 360°画像**にそろえ、連番の順序を保ってください。通常写真や異なる解像度を混ぜる場合は、CubemapのCOLMAPルートまたはMetashapeを使います。

#### COLMAPの選び方

[公式COLMAP 4.2.0 Windows CUDA版ZIP](https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip)を展開し、最上位の `COLMAP.bat` を選びます。RTX 50シリーズにも対応しており、そのGPU世代への対応のための自前ビルドは不要です。COLMAPはこのアプリや `setup_windows.bat` には含まれません。

- 同じ配布物の `bin/colmap.exe` を選んだ場合も、同梱ランチャーを自動使用します。
- 空欄ならWindowsのPATH上で `COLMAP.bat`、次に `colmap.exe` を探します。
- 既存のCOLMAP 4.1も利用できます。使用する版のCLI機能とGPU SIFTは実行前に確認されます。
- COLMAP用のCUDA版数に合わせて、アプリのマスク生成用Python環境を変更する必要はありません。

#### 処理設定の選び方

標準は入力の細部を活用する設定です。処理時間やGPUメモリを節約したい場合は、軽量、最軽量の順に下げます。

| 処理設定 | 特徴抽出の解像度 | 7680 × 3840入力の例 | 特徴点上限 / ERP画像1枚 |
| --- | --- | --- | --- |
| 標準（既定） | 入力のまま | 7680 × 3840 | 32,768 |
| 軽量 | 縦横1/2 | 3840 × 1920 | 16,384 |
| 最軽量 | 縦横1/4 | 1920 × 960 | 8,192 |

縮小するのはSfM内部の特徴抽出用画像だけです。元画像を変更せず、Step 5の出力解像度もこの設定では変わりません。別の入力解像度でも同じ比率を使い、拡大はしません。

特徴点数は上限であり、必ずその数が見つかるわけではありません。32,768は360°画像全体に特徴点を確保するための**アプリの初期設定**で、COLMAP公式の8K最適値ではありません。遠くの模様など細部を残したい場合は標準、撮影経路を短時間で確認したい場合は軽量・最軽量が目安です。特徴の少ない壁、強いブレ、画像間の重なり不足は、上限を増やすだけでは補えません。

全設定で動画向けのSequentialマッチングとIncremental Mapperを使い、Guided MatchingはOFFです。[公式パノラマ例](https://github.com/colmap/colmap/blob/4.2.0/python/pycolmap/panorama.py)と同じ基本構成で、処理設定によって照合方式や推定の反復数は変わりません。

#### ループ検出の選び方

- **OFF（既定）**: 一方向に通り抜ける撮影や、まず処理時間を抑えたい場合。
- **ON**: 一周して出発点に戻る、同じ部屋へ再入場する、同じ道を往復する撮影。時間が離れたフレームでも同じ場所を探して照合します。

ONでは追加の照合に時間がかかります。初回はCOLMAPが照合用の語彙データをダウンロードするため、インターネット接続が必要です。以後はキャッシュを使います。ループ検出は離れた区間を結び付ける補助であり、撮影時の重なりも必要です。

#### 結果の確認と再実行

実行前にCLI機能と画像1枚でのGPU SIFT起動を確認します。完了後はプレビューでカメラの経路、登録された画像、点群を確認してください。このルートは1つの復元を作ります。経路のつながりが不足する場合は、フレーム間隔、画像のブレや重なり、再訪部分のループ検出を見直します。

処理設定やループ検出を変更した結果を得るには、Step 4でSfMを再実行します。既存のSfM作業結果は置き換え確認の後に作り直し、元画像は残します。成功済みのSparseモデルをそのまま使う場合は、Step 5だけで変換できます。

旧設定の標準・クオリティは新しい標準に、旧軽量は最軽量に引き継ぎます。以前選んだ照合方式にかかわらずSequentialを使用し、旧設定にループ検出の指定がなければOFFになります。

SfM作業フォルダは `output/colmap_equirect/` です。学習アプリへ渡すJSON/PLYやCubemapデータは、Step 5の `COLMAP球面 → NeRFデータセット(JSON/PLY)` で作ります。

### Metashape → RealityScan用データ作成

Metashapeで作ったカメラXMLから、RealityScanへ読み込ませるCubemap画像とXMPを作ります。RealityScanで再アラインしたい、ステップ1から3で登録済みの別ソース画像も一緒に投入したい、RealityScanのCSV/PLYを書き出して後段へ渡したい場合に使います。

出力は `output/realityscan/` です。Metashape XMLにある画像はCubemap画像とXMPとして `images/_geometry/` に書き出され、マスクは `images/_mask/` に入ります。XMLにない登録済み画像は姿勢なしの追加画像として `extra_images/_geometry/` へ可能ならハードリンク、必要ならコピーされ、対応マスクは `extra_images/_mask/` に入ります。RealityScanでは先に `images/` を追加してAlignし、点群まで生成してから `extra_images/` を追加して再度Alignします。その後、CSVとPLYを書き出し、LichtFeld用COLMAPデータセットが必要な場合はStep 5の `RealityScan → COLMAPデータセット` を使います。

RealityScanへ段階的に投入するのは意図した使い方です。先にCubemap画像だけでMetashape由来の安定したコンポーネントを作り、その後で通常画像を追加するほうが、最初から全画像をまとめて入れるより誤配置や小さな別コンポーネントが起きにくくなります。

### SfM結果を確認

点群、カメラ位置、選択カメラ画像、対応マスクを読み取り専用ビューで確認します。SfM結果が意図した位置関係になっているか、画像とマスクの対応が壊れていないかを見るためのカードです。

## Step 5: データセットカードの選び方

### Metashape → NeRFデータセット(JSON/PLY)

MetashapeのカメラXMLと点群PLYから、NeRF/3DGS系データセットを作ります。PINHOLE出力では `transforms_postshot.json` と `pointcloud_postshot.ply` のように、出力プリセット別のJSON/PLYを書き出します。

| 選択 | 使う場面 |
| --- | --- |
| `PINHOLE` | 360°画像をCubemapへ展開して、Postshot / Brush / LichtFeldなどで扱いやすいデータにする |
| `ERP 360°` | LichtFeldでGUTを使い、エクイレクタングラー画像を直接使う |

通常は `PINHOLE` から始めます。通常画像や複数解像度ERPが混在するMetashape結果では、ERP 360°のまま安全に出力できないため、`PINHOLE` を使ってください。[LichtFeld Studio](https://lichtfeld.io/)のJSON/PLY読み込みはフレームごとのカメラ内部パラメータを扱えないため、複数カメラ設定の混在結果では `Metashape → COLMAPデータセット` のほうが安全です。

出力先は主に次の通りです。

| 出力 | フォルダ |
| --- | --- |
| PINHOLE Cubemap | `output/metashape_cubemap/` |
| ERP 360° / GUT | `output/metashape_3dgut/` |

### Metashape → COLMAPデータセット

MetashapeのカメラXMLと点群PLYから、`images/`, `masks/`, `sparse/0/` を持つCOLMAP形式データセットを作ります。COLMAP入力に対応した学習ソフトへ渡したい場合、またはMetashapeで360°画像と通常画像を混在SfMした結果を安全に使いたい場合に選びます。

- ERP 360°カメラは選択した視点セットへ展開します
- PINHOLEの通常画像はCubemap化せず参照します
- 歪み係数を持つ通常画像はPINHOLEへ補正し、対応マスクも同じ変換をかけます
- 出力は `output/metashape_colmap/` です

LichtFeldでMetashape混在結果を使う場合は、このルートが安全です。

### COLMAP RIG → NeRFデータセット(JSON/PLY)

このアプリのCOLMAP SfM出力、通常は `output/colmap_rig/` からNerfstudio形式のデータセットを作ります。出力は `output/colmap_nerfstudio/` で、`transforms.json`、binary little-endian の `pointcloud.ply`、登録済みCOLMAP画像だけを含む `images/` を作成します。

Nerfstudioの `transforms.json` にはリグ層がありません。このツールはCOLMAPの最終登録済み画像ポーズを `images.bin/txt` から読みます。COLMAPのリグ内センサー姿勢は、その時点ですでに各画像のポーズへ畳み込まれています。カメラ姿勢はCOLMAP/OpenCVカメラ軸からNerfstudio/OpenGLカメラ軸へ変換し、その後、カメラとPLY点群の両方へ同じNerfstudio向けワールド軸変換を適用するため、疎点群とカメラが同じ座標系に揃います。

`output/colmap_rig/masks/` がある場合は、登録済み画像すべてに対応マスクがある時だけ `mask_path` を付けます。部分的なマスクセットは、フレームによってマスク有無が混ざるデータセットを作らないようエラーにします。

### RealityScan → COLMAPデータセット

RealityScanのRegistrationから書き出したInternal/External CSVと、同じ座標状態で書き出したPLYから、LichtFeldでDatasetとして開けるCOLMAPデータセットを作ります。

通常は `output/realityscan/` 配下にCSV、PLY、`images/`、必要に応じて `extra_images/` がある状態で使います。各 `_geometry` layerから画像を、対応する `_mask` layerからマスクを読み取り、CSVに載っている画像を出力先の `images/` と `masks/` に統合します。出力先は `output/realityscan/lfs_colmap/` です。

RealityScanからエクスポートする前に、学習に使うコンポーネントを確認してください。COLMAP側のカメラ姿勢として使われるのはCSVに含まれるカメラだけです。画像ファイルが存在していても、CSVにない画像には姿勢は付きません。

`レンズ補正してPINHOLE化` は、RealityScanで通常画像も混ぜてアラインし、LichtFeldが歪みつきカメラを受け付けず止まる場合に使います。Cubemap由来のPINHOLE画像は出力先へリンクまたはコピーし、歪み係数を持つ通常画像だけを補正します。補正で生じる無効領域はマスクにも反映されます。

### COLMAP球面 → NeRFデータセット(JSON/PLY)

Step 4で作ったCOLMAP球面sparse、または別途指定した `EQUIRECTANGULAR` / 旧 `SPHERE` カメラのCOLMAP sparseから、JSON/PLYデータセットを作ります。

COLMAP球面SfMの入力は同一解像度のERP 360°画像です。出力は、LichtFeldでGUTを使うERP 360°データ、またはPostshot / Brush / LichtFeldで扱いやすいPINHOLE Cubemapデータから選びます。

新しいCOLMAPモデルは公式 `EQUIRECTANGULAR` カメラを使います。既存の旧SphereSfM `SPHERE` Sparseモデルもこの球面変換ルートで読み込めるため、変換前にカメラ名や数値IDを手作業で書き換える必要はありません。

### スケール調整

AprilTagの実寸から、作成済みデータセットのスケールを補正します。撮影前にタグを印刷し、現場に固定しておく必要があります。

1. Step 5でCubemapまたはCOLMAP系データセットを作ります。
2. `スケール調整` を開き、対象データセット、タグファミリ、タグID、実寸を確認します。
3. `推定` を実行し、検出数や推定値を確認します。
4. 結果が妥当な場合だけ反映します。

スケール反映は対象データセットのカメラ位置と点群に同じ倍率をかけます。反映前にはバックアップを作ります。

## 出力設定の選び方

### マスク出力

Step 5のマスク出力設定は、学習データセット出力専用です。Step 3の `masks/` はSfM用として残し、学習用マスクだけを別に作り直せます。

| モード | 使う場面 |
| --- | --- |
| `マスクを変更しない（既定）` | 学習データ用のマスクを作り直さず、Step 3で作ったSfM用マスクを使う場合。Cubemap出力ではマスクも同じビューへ分割し、3DGUT/equirect出力では元画像に対応するマスクとして使います。 |
| `トレーニング時に使用するマスクを作り直す` | 学習用マスクだけを現在のマスク設定で作り直す場合。Step 3でSfMに使った `images/` から作成し、出力がCubemapなら作り直したマスクをCubemapへ分割し、3DGUT/equirectなら出力 `masks/` として書き出します。 |
| `マスクなし` | マスクなしで学習する場合、または学習アプリ側で別途マスクを扱う場合。 |

`トレーニング時に使用するマスクを作り直す` を選んだ場合、未作成または設定変更が必要なマスクは自動で再生成されます。既存の学習用マスクをすべて上書きして作り直したい場合だけ `強制上書き` をオンにします。

### 画像タイプ

`PINHOLE` は、ERP 360°画像をCubemapなどの通常視点画像へ展開する出力です。Postshot、Brush、LichtFeldの通常学習ではまずこれを使います。

`ERP 360°` は、LichtFeldでGUTを使ってエクイレクタングラー画像を直接学習する場合だけ選びます。LichtFeld以外のプリセットでは選べません。

### 視点セット

`Cubemap` は前後左右上下の6方向を出力する標準設定です。迷ったらこれを使います。

`Custom Grid` は、6方向では足りない場合に視点方向を増やす設定です。視点数を増やすほど出力枚数、処理時間、学習時の画像数が増えます。

### 画像サイズ

通常は既定値から始めます。軽く試す場合は小さめ、最終品質を見たい場合は大きめを選びます。元画像の情報量や学習アプリのVRAM消費も合わせて判断します。

## シーンプレビュー

Step 4の `SfM結果を確認` から、点群、カメラ位置、画像、マスクを同じ画面で確認できます。

プレビューでは、出力済みデータセット、Metashape XML/PLY、COLMAP sparse、COLMAP球面sparseなどを候補として選べます。カメラをクリックすると、そのカメラ画像と対応マスクを確認できます。

## よくある判断

- MetashapeでSfM済みなら、Step 4は `既存のSfM結果を使う` で十分です。
- Postshot / Brush / LichtFeldの通常学習へ渡すなら、まず `PINHOLE` + `Cubemap` を使います。
- LichtFeldでGUTを試すなら、`ERP 360°` を選び、学習時にGUTをONにします。
- Metashape結果に通常画像や複数解像度ERPが混ざるなら、LichtFeld向けには `Metashape → COLMAPデータセット` が安全です。
- 完成済みCOLMAP結果をNerfstudioで学習したい場合は、`変換不要` カードではなく `COLMAP RIG → NeRFデータセット(JSON/PLY)` を使います。
- RealityScanからPostshotへ渡すだけならCSV/PLYで足りる場合があります。LichtFeldでDatasetとして読みたい場合は `RealityScan → COLMAPデータセット` を使います。
- Metashape → RealityScan → LichtFeldのルートでは、Metashape XML/PLYとRealityScan CSV/PLYをシーンと一緒に管理し、最終的に `output/realityscan/lfs_colmap/` を学習に使います。
- COLMAP球面SfMは同一解像度ERP 360°専用と考えてください。混在ソースはCubemap化するCOLMAPルートまたはMetashapeを使います。
- 画像やマスクだけを作り直したい場合は、同じカードを開き、出力設定を確認して再実行します。

## Step 6へ進む

Step 5でデータセットを作ったら、LichtFeld Studio、Postshot、Brushなどの学習アプリへ直接読み込ませます。対応CLIで再実行やヘッドレス学習をしたい場合だけ、Step 6を使います。

Step 6の操作は [Step 6 学習GUI](training_gui.ja.md) を参照してください。
