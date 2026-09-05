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

For Windows, use the [official COLMAP 4.2.0 CUDA ZIP](https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip). Extract the ZIP and select its top-level `COLMAP.bat`. It supports RTX 50-series GPUs without a custom build.

- 360° images are expanded into cubemap rigs
- normal images and normal video frames remain normal cameras
- mixed sources can be processed in one COLMAP dataset
- output goes to `output/colmap_rig/`

For video-like input, start with `Sequential` matching. For a smaller unordered photo set, consider `Exhaustive`.

Normal images use automatic camera estimation in the GUI. If you need explicit calibrated intrinsics, prepare them as external metadata before import rather than entering per-image camera parameters in this step.

Choose cubemap resolution with the image-conversion scale; the feature limit is 8,192 per face. These settings are separate from spherical ERP SfM. Since each 360° frame produces several faces, a per-face limit is not directly comparable with a per-ERP-image limit.

COLMAP Global / Incremental Mapper keeps the relative positions and orientations of views from one 360° frame fixed. ERP-only projects also keep the rendered field of view and image center fixed; mixed ordinary-photo projects retain intrinsic calibration. Matching within the same frame is skipped only when this run generates a non-overlapping cube layout with fields of view at most 90°. Custom overlapping layouts remain eligible for matching. External GLOMAP uses its own mapper settings.

When rerunning SfM with previously generated rig images, enable Image Conversion as well if prompted, so the view images and camera settings stay aligned. Reusing a completed sparse model in Step 5 does not require regeneration.

### Run COLMAP Spherical SfM

Choose this to run SfM directly on equirectangular frames from a 360° video, without cubemap conversion. Use **ERP 360° images of the same resolution**, keeping their sequential filename order. For mixed ordinary photos or different ERP resolutions, use the cubemap COLMAP route or Metashape.

#### Choosing COLMAP

Extract the [official COLMAP 4.2.0 Windows CUDA ZIP](https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip) and select its top-level `COLMAP.bat`. This package supports RTX 50-series GPUs without a custom build for that generation. COLMAP is not bundled with the app or `setup_windows.bat`.

- Selecting the same package's `bin/colmap.exe` automatically uses its packaged launcher.
- Leaving the field blank searches Windows PATH for `COLMAP.bat`, then `colmap.exe`.
- Existing COLMAP 4.1 installations remain supported. Required CLI capabilities and GPU SIFT startup are checked before processing.
- COLMAP's CUDA version does not require changing the app's mask-generation Python environment.

#### Choosing a Processing Setting

Standard retains input detail. Choose Light, then Lightest when reducing processing time or GPU memory use matters more.

| Processing setting | Feature-extraction resolution | Example for 7680 × 3840 input | Feature limit per ERP image |
| --- | --- | --- | --- |
| Standard (default) | Original input | 7680 × 3840 | 32,768 |
| Light | Half width and height | 3840 × 1920 | 16,384 |
| Lightest | Quarter width and height | 1920 × 960 | 8,192 |

Resizing applies only to SfM's internal feature-extraction images. Source files remain untouched, and this setting does not change Step 5 output resolution. The same ratios apply to other input resolutions, without upscaling.

The feature count is a limit, not a guaranteed number of detections. 32,768 is an **app starting point** for coverage across a full 360° image, not an official COLMAP optimum for 8K. Use Standard to retain fine details such as distant textures, or Light/Lightest to inspect a capture route sooner. A higher limit cannot compensate for textureless walls, strong motion blur, or insufficient overlap.

All settings use video-oriented Sequential matching and the Incremental Mapper, with Guided Matching off. This follows the basic pipeline in the [official panorama example](https://github.com/colmap/colmap/blob/4.2.0/python/pycolmap/panorama.py); changing the processing setting does not change the matching method or solver iteration settings.

#### Choosing Loop Detection

- **Off (default):** one-way passes, or when keeping processing time down is the priority.
- **On:** walks that return to their starting point, re-enter rooms, or retrace a route. Matches revisited places even when frames are far apart in time.

Additional matching takes time. On first use, COLMAP downloads vocabulary data and needs an internet connection; subsequent runs use its cache. Loop detection helps connect distant portions of a capture, but overlap is still necessary.

#### Reviewing and Rerunning

Before processing, the app checks CLI capabilities and GPU SIFT startup on one image. Afterward, inspect the camera path, registered images, and point cloud in the preview. This route produces one reconstruction. If the path lacks connections, review frame spacing, blur, overlap, and loop detection for revisited areas.

Rerun SfM in Step 4 to apply a different processing setting or loop-detection choice. Existing SfM working results are recreated after replacement confirmation; source images are retained. To reuse an already successful sparse model, run only the Step 5 conversion.

Old Standard and Quality settings migrate to the new Standard; old Fast migrates to Lightest. Sequential matching is used regardless of the old matcher selection, and loop detection defaults to off when absent from saved settings.

The SfM working folder is `output/colmap_equirect/`. Create JSON/PLY or cubemap datasets for training apps in Step 5 with `COLMAP Spherical -> NeRF Dataset (JSON/PLY)`.

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
