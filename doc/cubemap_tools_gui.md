# Step 4 SfM / Step 5 Dataset GUI

Step 4 is where you choose how camera poses and sparse points will be prepared for the training dataset. If you already ran SfM in Metashape, RealityScan, COLMAP, or COLMAP spherical SfM, there is usually nothing else to run in this step. Open a route card only when you want this app to run COLMAP or when you want to create RealityScan realignment data from a Metashape result.

Step 5 converts SfM results into datasets that training apps can read. Use it to create NeRF-style JSON/PLY datasets from Metashape, COLMAP, or COLMAP spherical SfM, COLMAP-format datasets from Metashape or RealityScan, or to apply AprilTag scale to an existing dataset.

## Related Tools

| Tool | Use in this app |
| --- | --- |
| [COLMAP](https://github.com/colmap/colmap) | Step 4 COLMAP routes, native EQUIRECTANGULAR spherical SfM in COLMAP 4.1+ (4.2+ recommended), and COLMAP-format dataset outputs |
| [LichtFeld Studio](https://lichtfeld.io/) | LichtFeld presets, GUT output, and RealityScan-to-COLMAP dataset use |
| [Postshot](https://www.jawset.com/) | Postshot presets and Step 6 CLI launch |
| [Brush](https://github.com/ArthurBrussee/brush) | Cubemap-style output for open-source Gaussian Splatting training |

## First Decision

Start by deciding whether camera poses already exist.

| Situation | What to do |
| --- | --- |
| Metashape SfM is already done | In Step 4, choose `Use Existing SfM Result`. In Step 5, choose a Metashape dataset card |
| RealityScan realignment is already done | In Step 4, choose `Use Existing SfM Result`. In Step 5, choose `RealityScan -> COLMAP Dataset` |
| You already have a COLMAP images/masks/sparse dataset | In Step 4, choose `Use Existing SfM Result`. For COLMAP-compatible training apps, continue directly to training; for Nerfstudio JSON/PLY, use `COLMAP RIG -> NeRF Dataset (JSON/PLY)` |
| You want this app to run COLMAP | In Step 4, choose `Run COLMAP SfM` |
| You want this app to run spherical SfM on same-resolution ERP 360° images | In Step 4, choose `Run COLMAP Spherical SfM` |
| You want to realign a Metashape result in RealityScan | In Step 4, choose `Metashape -> RealityScan Data` |
| You want to inspect an existing result | In Step 4, choose `Inspect SfM Result` |

## Step 4: SfM Route Cards

### Use Existing SfM Result

Choose this when Metashape, RealityScan, COLMAP, COLMAP spherical SfM, or another tool has already produced camera poses and sparse points. This route means "nothing to run here"; continue to Step 5 and choose the dataset format you need.

For Metashape results, export cameras as Agisoft XML and sparse points as Stanford PLY. Saving both files in the scene folder is recommended because it keeps the SfM result together with the scene; if they are elsewhere, select the XML and PLY manually in the Step 5 card.

### Run COLMAP SfM

Choose this when you want this app to run [COLMAP](https://github.com/colmap/colmap) or GLOMAP without using Metashape.

- 360° images are expanded into cubemap rigs
- normal images and normal video frames remain normal cameras
- mixed sources can be processed in one COLMAP dataset
- output goes to `output/colmap_rig/`

For video-like input, start with `Sequential` matching. For a smaller unordered photo set, consider `Exhaustive`.

Normal images use automatic camera estimation in the GUI. If you need explicit calibrated intrinsics, prepare them as external metadata before import rather than entering per-image camera parameters in this step.

### Run COLMAP Spherical SfM

Choose this when you want to run SfM on equirectangular 360° images as spherical cameras without cubemap projection first. This route uses official [COLMAP](https://github.com/colmap/colmap) 4.1 or newer with the native `EQUIRECTANGULAR` camera model. Treat it as a route for same-resolution ERP 360° images only. Use the cubemap COLMAP route or Metashape when you need mixed normal images or multiple ERP resolutions.

#### Select the Launcher and Version

COLMAP is not bundled with this app and is not installed by `setup_windows.bat`. Install or extract COLMAP separately, then use one of these choices:

| Installation | Selection in Step 4 |
| --- | --- |
| Official Windows ZIP | Select the package's top-level `COLMAP.bat`. This is the recommended choice because it establishes the package library paths. |
| Official Windows `bin/colmap.exe` | You may select it; the app detects the adjacent top-level `COLMAP.bat` and uses that launcher automatically. |
| Standalone or custom `colmap.exe` | Select it directly only when its runtime libraries are already available. The capability preflight still applies. |
| COLMAP on `PATH` | Leave the field blank. On Windows, the app searches for `COLMAP.bat` first and then `colmap.exe`. |

COLMAP 4.1 is the supported minimum because it introduced the native `EQUIRECTANGULAR` camera model used by this route. COLMAP 4.2 or newer is recommended, particularly with the `Quality` preset: that preset enables guided matching, and the [COLMAP 4.2 changelog](https://github.com/colmap/colmap/blob/4.2.0/CHANGELOG.rst) includes the corresponding spherical-camera fix. COLMAP 4.1 remains usable for existing projects and the `Fast` / `Standard` presets.

#### What the Preflight Checks

Before the full SfM run, the app performs these checks in order:

1. Run the selected launcher and require COLMAP 4.1.0 or newer.
2. Read the help for the selected feature extractor, matcher, and mapper, then confirm every CLI option required by the current GUI settings is available.
3. Create an isolated temporary database and run GPU SIFT on one source image.

A successful preflight confirms that the launcher, selected command-line contract, packaged libraries, and GPU SIFT startup work together. It does not guarantee that every image will register in the scene. The spherical mapper intentionally produces one reconstruction component so the downstream `sparse/0` contract stays stable; if the capture separates into disconnected groups, improve overlap or matching rather than expecting several output components.

On RTX 50-series GPUs, older CUDA builds can fail during GPU SIFT. If that happens, select a COLMAP build made with a CUDA architecture that supports the GPU.

#### Updating an Existing Project

- An existing successful COLMAP 4.1 sparse model does not need to be rebuilt only because COLMAP 4.2 is available. Step 5 can continue to convert it.
- Existing scene settings remain valid. Point the Step 4 field at the new `COLMAP.bat` when moving to the official 4.2 Windows package.
- If an older app build stopped on the unsupported `--Mapper.ba_global_images_ratio` option, update this app and rerun Step 4. The current command contract uses the supported COLMAP option.
- If launching `bin/colmap.exe` directly previously failed to find packaged DLLs, select the top-level `COLMAP.bat` or rerun with the current app, which redirects that executable selection to the package launcher.

The SfM working folder is `output/colmap_equirect/`. Create JSON/PLY or cubemap datasets from that result in Step 5 with `COLMAP Spherical -> NeRF Dataset (JSON/PLY)`.

### Metashape -> RealityScan Data

Choose this when you have a Metashape camera XML and want to import cubemap images plus XMP camera data into RealityScan. This is useful when you want RealityScan to realign the scene, include extra image sources already registered in Steps 1-3, or export RealityScan CSV/PLY for downstream tools.

The output is `output/realityscan/`. Images present in the Metashape XML are written to `images/_geometry/` as cubemap images with XMP sidecars, and their masks are written to `images/_mask/`. Registered scene images missing from the XML are hard-linked when possible, otherwise copied, into `extra_images/_geometry/` as unposed extra inputs, with matching masks in `extra_images/_mask/`. In RealityScan, add `images/` first and run Align until sparse points are generated, then add `extra_images/` and run Align again. After exporting CSV and PLY from RealityScan, use Step 5 `RealityScan -> COLMAP Dataset` when LichtFeld needs a COLMAP-format Dataset.

The staged RealityScan import is intentional. Aligning the cubemap images first creates a stable component from the Metashape result; adding normal images after that usually avoids more wrong placements and small disconnected components than importing all images at once.

### Inspect SfM Result

Open a read-only viewer for point clouds, camera positions, selected camera images, and matching masks. Use it to confirm that camera poses, point clouds, image links, and masks line up before training.

## Step 5: Dataset Cards

### Metashape -> NeRF Dataset (JSON/PLY)

Create a NeRF/3DGS-style dataset from a Metashape camera XML and point-cloud PLY. PINHOLE output writes profile-specific JSON/PLY files such as `transforms_postshot.json` and `pointcloud_postshot.ply`.

| Choice | Use when |
| --- | --- |
| `PINHOLE` | You want cubemap-style perspective images for Postshot, Brush, LichtFeld, or similar tools |
| `ERP 360°` | You want LichtFeld GUT to train directly on equirectangular images |

Start with `PINHOLE` unless you specifically need [LichtFeld Studio](https://lichtfeld.io/) GUT. If the Metashape result contains normal images or multiple ERP resolutions, direct ERP 360° output is not safe; use `PINHOLE`. For LichtFeld, mixed Metashape results with multiple camera settings are safer through `Metashape -> COLMAP Dataset` because LichtFeld's JSON/PLY import does not handle per-frame camera intrinsics.

Typical outputs:

| Output | Folder |
| --- | --- |
| PINHOLE cubemap | `output/metashape_cubemap/` |
| ERP 360° / GUT | `output/metashape_3dgut/` |

### Metashape -> COLMAP Dataset

Create a COLMAP-format dataset with `images/`, `masks/`, and `sparse/0/` from Metashape camera XML and point-cloud PLY. Choose this for COLMAP-input training apps or when Metashape aligned mixed 360° and normal-camera sources.

- ERP 360° cameras are expanded to the selected view set
- PINHOLE normal images are referenced without cubemap conversion
- distorted normal images are undistorted to PINHOLE, and matching masks are transformed the same way
- output goes to `output/metashape_colmap/`

For LichtFeld with mixed Metashape sources, this is the safer route.

### COLMAP RIG -> NeRF Dataset (JSON/PLY)

Create a Nerfstudio-style dataset from this app's COLMAP SfM output, normally `output/colmap_rig/`. The output is `output/colmap_nerfstudio/` with `transforms.json`, binary little-endian `pointcloud.ply`, and an `images/` folder containing only registered COLMAP images.

Nerfstudio has no rig layer in `transforms.json`. This tool reads the final COLMAP registered image poses from `images.bin/txt`; any rig sensor pose has already been folded into those per-image poses by COLMAP. Camera poses are converted from COLMAP/OpenCV camera axes to Nerfstudio/OpenGL axes, then the same Nerfstudio world-axis transform is applied to both cameras and PLY points so the sparse point cloud stays aligned with the cameras.

If `output/colmap_rig/masks/` exists, masks are attached only when every registered image has a matching mask. A partial mask set fails rather than creating a dataset where some training frames are masked and others are not.

### RealityScan -> COLMAP Dataset

Create a LichtFeld-readable COLMAP dataset from RealityScan Internal/External CSV and a PLY exported in the same coordinate state.

Normally, use it when CSV, PLY, `images/`, and optionally `extra_images/` are already under `output/realityscan/`. The tool reads images from each `_geometry` layer and masks from the matching `_mask` layer, then gathers CSV-listed assets into the output `images/` and `masks/` folders. Output goes to `output/realityscan/lfs_colmap/`.

Before exporting from RealityScan, confirm the component you want to train from. The CSV should contain the cameras you expect; images that are not in the exported camera CSV are kept out of the COLMAP poses even if their files exist.

Turn on `Undistort to PINHOLE` only when RealityScan includes normal-camera images with distortion and LichtFeld refuses to train on them. Cubemap-derived PINHOLE images are linked or copied into the output, while only distorted normal images are converted. Invalid image regions introduced by undistortion are also reflected in the masks.

### COLMAP Spherical -> NeRF Dataset (JSON/PLY)

Create a JSON/PLY dataset from the COLMAP spherical sparse model created in Step 4, or from another selected COLMAP sparse model that uses `EQUIRECTANGULAR` or legacy `SPHERE` cameras.

Use same-resolution ERP 360° input for COLMAP spherical SfM. The output can be ERP 360° data for LichtFeld GUT or PINHOLE cubemap data for Postshot, Brush, or LichtFeld.

New COLMAP models use the official `EQUIRECTANGULAR` camera. Existing legacy SphereSfM `SPHERE` sparse models remain importable through this spherical conversion route, so they do not need camera-name or numeric-ID edits before conversion.

### Scale Adjustment

Use printed AprilTags to correct the metric scale of an existing dataset. Tags must be printed and fixed in the scene before capture.

1. Create a cubemap or COLMAP-style dataset in Step 5.
2. Open `Scale Adjustment`, then confirm the target dataset, tag family, tag IDs, and printed tag size.
3. Run estimation and review the detected observations and scale value.
4. Apply the scale only when the result looks reasonable.

Scale application multiplies the target dataset's camera positions and point cloud by the same factor. A backup is created before files are changed.

## Output Choices

### Mask Output

The Step 5 mask output setting is for the training dataset output. Step 3 `masks/` can stay as the SfM mask source while training masks are rebuilt separately when needed.

| Mode | Use when |
| --- | --- |
| `Keep Masks Unchanged (Default)` | Training masks should not be rebuilt, and the Step 3 SfM masks should be used. Cubemap output splits those masks into the same views; 3DGUT/equirect output uses the masks matching the source images. |
| `Rebuild Training Masks` | Training masks should be rebuilt with the current mask settings. The app creates them from the `images/` used for Step 3 SfM, then splits them for Cubemap output or writes them as dataset `masks/` for 3DGUT/equirect output. |
| `No Masks` | Training should run without dataset mask links, or masks will be handled manually in the training app. |

When `Rebuild Training Masks` is selected, missing masks and masks affected by changed settings are regenerated automatically. Turn on `Force overwrite` only when every existing training mask should be overwritten and rebuilt.

### Image Type

`PINHOLE` expands ERP 360° images into normal perspective views. Use it first for normal Postshot, Brush, and LichtFeld training.

`ERP 360°` keeps equirectangular images for LichtFeld GUT. It is available only for the LichtFeld preset.

### View Set

`Cubemap` exports the standard six front/back/left/right/up/down views. Use it when unsure.

`Custom Grid` adds or removes view directions. More views mean more output images, longer conversion time, and more training images.

### Image Size

Start with the default. Use a smaller size for fast tests and a larger size when you need final-detail output. Also consider source resolution and training-app VRAM use.

## Scene Preview

Open `Inspect SfM Result` from Step 4 to inspect point clouds, camera positions, images, and masks together.

The viewer can load output datasets, Metashape XML/PLY, COLMAP sparse models, and COLMAP spherical sparse models found in the scene. Selecting a camera shows its image and matching mask.

## Common Decisions

- If Metashape SfM is already done, choose `Use Existing SfM Result` in Step 4.
- For normal Postshot / Brush / LichtFeld training, start with `PINHOLE` + `Cubemap`.
- For LichtFeld GUT, choose `ERP 360°` and enable GUT in the training app.
- If a Metashape result mixes normal images or multiple ERP resolutions, use `Metashape -> COLMAP Dataset` for LichtFeld.
- If a finished COLMAP result needs to be trained in Nerfstudio, use `COLMAP RIG -> NeRF Dataset (JSON/PLY)` instead of the "conversion not needed" card.
- If RealityScan output is going to Postshot, CSV/PLY may be enough. If LichtFeld needs a Dataset folder, use `RealityScan -> COLMAP Dataset`.
- For the Metashape -> RealityScan -> LichtFeld route, keep Metashape XML/PLY and RealityScan CSV/PLY with the scene, then train from `output/realityscan/lfs_colmap/`.
- Treat COLMAP spherical SfM as same-resolution ERP 360° only. Use the cubemap COLMAP route or Metashape for mixed sources.
- To rebuild only images or masks, reopen the same dataset card, check the output settings, and run it again.

## Continue to Step 6

After Step 5 creates a dataset, load it directly in LichtFeld Studio, Postshot, Brush, or another training app. Use Step 6 only when you want to launch a compatible CLI for repeat runs or headless training.

See [Step 6 Training GUI](training_gui.md) for Step 6 details.
