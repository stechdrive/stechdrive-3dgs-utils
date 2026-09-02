# stechdrive-3dgs-utils

**v1.25.2**

## What Is This?

A Windows GUI app that prepares images, masks, and camera data for 3D Gaussian Splatting (3DGS) training from 360° video, normal video, and still-image sequences.

The main workflow is to organize and mask ERP/equirectangular footage from cameras such as Insta360 / Osmo 360, run SfM in Metashape, then convert the result into datasets for Postshot, Brush, LichtFeld Studio, COLMAP-format workflows, or RealityScan realignment. It also supports normal-camera images/video, in-app COLMAP routes including native spherical SfM (COLMAP 4.1+, with 4.2 recommended), and RealityScan-to-LichtFeld conversion.

## Download

For normal use, download the latest release ZIP:

[Download stechdrive-3dgs-utils-v1.25.2.zip](https://github.com/stechdrive/stechdrive-3dgs-utils/releases/download/v1.25.2/stechdrive-3dgs-utils-v1.25.2.zip)

After extracting the ZIP, run `setup_windows.bat`, then `run_gui.bat`.

[JP 日本語の説明](README.ja.md)

![STechDrive 3DGS Utils GUI](images/stechdrive-3dgs-utils-gui.jpg)

![STechDrive 3DGS Utils workflow](images/stechdrive-3dgs-workflow-en.png)

## What You Can Do

### 1. SfM Preprocessing for 360° and Normal Images

Register 360° video from Insta360 / Osmo 360 or similar cameras, normal video from smartphones or mirrorless cameras, and still-image folders in the same scene. Review keep/drop decisions in Step 2, then mask people, the camera operator, tripods, sky, stitch seams, blown-out highlights, and similar areas in Step 3 before sending the images to Metashape, COLMAP, COLMAP spherical SfM, or RealityScan.

After Metashape SfM, create a NeRF-style JSON/PLY dataset with profile-specific names such as `transforms_postshot.json` / `pointcloud_postshot.ply`, a COLMAP-format dataset, or cubemap/XMP data for RealityScan realignment. In Step 5, choose the output format based on the training app you plan to use, such as LichtFeld Studio, Postshot, or Brush.

### 2. Run SfM Inside the App

If you are not using Metashape, Step 4 can run COLMAP routes directly. The standard COLMAP route expands 360° images into cubemap rigs while keeping normal images as normal cameras, so it is the better route for mixed sources. The COLMAP spherical route keeps same-resolution equirectangular 360° images as native `EQUIRECTANGULAR` cameras and requires COLMAP 4.1 or newer.

### 3. RealityScan to LichtFeld

After RealityScan realignment, convert RealityScan CSV/PLY exports into a COLMAP-format dataset that LichtFeld can open as a Dataset. Cubemap-derived PINHOLE images are referenced with links, and only normal-camera images that still have lens distortion are undistorted when needed.

### 4. Mask Preprocessing for Normal Photos or Video Frames

For video or image sequences from DSLR, mirrorless, smartphone, or other normal cameras, Step 3 can generate fast YOLO/SAM2.1 masks for people, vehicles, and other selectable object types, YOLO26-sem Cityscapes semantic masks, higher-accuracy SAM3.1 prompt masks for people and sky, plus overexposure masks. Mixed 360° and normal sources are processed according to their image type.

## Highlights

- Register 360° video, normal video, and still-image sequences as input sources in the same scene. Videos are extracted into frames, and still-image folders are copied into `images/` so later review, masking, and SfM steps treat them consistently.
- Review extracted frames in a large single-image view or a thumbnail list, then mark unwanted frames as keep/drop decisions. Blur candidates are split into automatic drops and review-only warnings. If usable-looking images are marked as blur, Step 2 can switch blur detection between Standard and Low sensitivity. For 360° images, the 90° FOV perspective view lets you inspect details in a normal-camera-like view.
- Generate masks for people, the camera operator, tripods, hands, vehicles, sky, blown-out highlights, and stitch seams. Use YOLO/SAM2.1 when you want fast person-focused masks, YOLO26-sem for urban Cityscapes semantic targets, or SAM3.1 when you want higher-accuracy prompt masks plus cleanup after generation.
- Preview mask results before saving and inspect them in the thumbnail list. When only a few frames have misses or false detections, regenerate just those frames instead of rerunning the whole image set.
- With SAM3.1, add missed targets such as tripods or subtract false detections such as signs and logos from existing masks. This reduces the amount of manual mask painting needed after the first pass.
- YOLO26-sem starts with `person` and `sky`; add vehicles, vegetation, or other Cityscapes classes only when the source material needs them.
- Use the same mask-preparation workflow for normal-camera video after Step 1 extraction and for normal photo or image-sequence sets, not only 360° images. This is useful before sending images to SfM software.
- In Step 4, choose how camera poses and sparse points will be prepared: use an existing SfM result, run COLMAP cubemap-rig or COLMAP spherical SfM from this app, or create RealityScan realignment data from a Metashape result.
- In Step 5, convert Metashape, COLMAP spherical, RealityScan, or COLMAP results into NeRF-style JSON/PLY datasets, COLMAP-format datasets, LichtFeld-ready RealityScan conversions, or AprilTag scale-adjusted outputs.
- Step 5 `Mask Output` keeps the Step 3 SfM masks by default, or rebuilds training masks from the Step 3 SfM input images when training should use different masks. Cubemap output splits those masks into cubemap views, while 3DGUT/equirect output writes matching dataset masks.
- Inspect SfM results and datasets in Scene Preview, with the point cloud, camera positions, selected camera image, and matching masks in one view. Open it from Step 4's viewer card.
- If you print and place AprilTags before capture, Step 5 `Scale Adjustment` can estimate metric scale from an existing dataset. After reviewing the estimate, you can apply the same scale to the target dataset camera positions and point cloud.
- Prepare the Windows environment with setup scripts that handle Python, FFmpeg/FFprobe, and the main Python packages. Normal use starts from `run_gui.bat`, and release updates run through `update.bat`.

## Easy Setup

For a normal release ZIP, extract it and run:

```bat
setup_windows.bat
run_gui.bat
```

The first `setup_windows.bat` run can take a while. It checks Python 3.12, FFmpeg/FFprobe, GPU-oriented Python packages, and prepares missing pieces where it can.

Python packages are installed into a virtual environment dedicated to this app, so your everyday Python environment is less likely to be affected. After setup completes, normal use is just running `run_gui.bat` to launch the GUI.

### Setup Details

`setup_windows.bat` looks for Python 3.12 and FFmpeg/FFprobe and can install missing system dependencies through winget when needed. It then creates this app's dedicated virtual environment under `.venv/`, installs packages such as PyTorch CUDA wheels, OpenCV, Pillow, Open3D, ultralytics, PySide6, and the SAM3.1 runtime, and verifies the environment.

Python packages are kept inside `.venv/`, so they are not normally installed into the system-wide Python environment or other projects. `.venv/` is an internal working directory, and you usually do not need to edit it manually.

### Updating the App or Environment

To update an extracted release, close the GUI and run:

```bat
update.bat
```

`update.bat` updates the app files from the official GitHub release and only updates `.venv/` when the current environment does not match the release's recommended dependencies. It also removes obsolete app-managed files from older releases while preserving `.venv/`, `.cache/`, `models/`, scene folders, and other user folders. Use `update.bat --app-only` for app files only or `update.bat --deps-only` for dependencies only. To recreate the environment from scratch, run `setup_windows.bat --force`.

If you are updating an older extracted release that does not yet have `update.bat`, close the GUI, open the new ZIP, enter its top-level `stechdrive-3dgs-utils-v...` folder, copy that folder's contents into your existing app folder with overwrite enabled, then run `update.bat` once from the existing app folder.

YOLO/SAM2.1, YOLO26-sem, and SAM3.1 model weights may be downloaded on first use. Local YOLO/SAM and YOLO26-sem weights can be placed under `models/ultralytics/`; the default semantic model file is `yolo26s-sem.pt`. SAM3.1 prompt masking uses `models/sam3.1/sam3.1_multiplex.pt`. Model weights are not bundled with the app and are governed by separate license terms; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

### Mask Generation Model Guide

- Use YOLO/SAM2.1 when you want fast person-only masks.
- Use YOLO26-sem for urban street-scene semantic masks. It defaults to `person` and `sky`; add vehicles, vegetation, or other Cityscapes classes only when needed.
- Use SAM3.1 when you want the highest practical accuracy for prompt-controlled targets. Because it is prompt-controlled, you can add missed targets after generation or subtract false detections.

### SAM3.1 Prompt Masks

`setup_windows.bat` installs the SAM3.1 runtime package, but the checkpoint is not bundled because access requires your Hugging Face account and SAM License acceptance.

This app uses the official `facebook/sam3.1` `sam3.1_multiplex.pt` checkpoint. SAM3.1 is a CUDA-GPU-oriented model. Running it on an NVIDIA GPU environment is recommended.

If GPU memory runs out during SAM3.1 batch processing, completed masks remain saved. Rerun with the same settings to resume from unfinished images.

When mask accuracy is the priority, SAM3.1 is recommended over YOLO/SAM2.1. Use SAM3.1 when you want more accurate prompt-controlled masks, especially for sky masks or targeted cleanup. After generating masks once, you can select only the images that need correction and use SAM3.1 prompts to add missed regions such as `tripod`, `hand`, `selfie stick`, or `cell phone`, or subtract false detections such as `male icon`, `female icon`, `logo`, or `sign`.

1. Create or sign in to a [Hugging Face account](https://huggingface.co/join).
2. Open Meta's [facebook/sam3.1](https://huggingface.co/facebook/sam3.1) Hugging Face repository and request access/accept the SAM License. Hugging Face gated model requests are tied to an individual user account and may require sharing your username/email with the model author.
   - Hugging Face gated models can use automatic or manual approval. If you can open the Files tab or download `sam3.1_multiplex.pt` from `facebook/sam3.1` in the browser after accepting the terms, your account already has access and you do not need to wait for an email reply. If the page shows a pending/approval-waiting state, wait for the model author approval.
3. Create a Hugging Face access token from your account settings.
   - App downloads require a `Read` token created by the same Hugging Face account that has access. Browser login state is not used by this app.
   - Copy the token value immediately after creating it. Hugging Face may not show existing token values again from the token list. If you missed the value, create a new `Read` token or use `Invalidate and refresh` to issue a new value. Refreshing invalidates the old token.
   - Treat access tokens as secrets equivalent to passwords. Do not paste them into README files, issues, chats, screenshots, or logs. `Read` permission is enough for downloading the SAM3.1 checkpoint. Prefer creating a dedicated token for SAM3.1, and delete or refresh it from Hugging Face settings when you no longer need it.
4. In Step 3, choose `SAM3.1`. If `models/sam3.1/sam3.1_multiplex.pt` is missing, the app asks for the token and downloads the checkpoint. The token is passed only to that download request. The app does not save the token for automatic reuse and does not write it to app settings, the scene folder, or execution logs. This reduces the risk of a token leaking from local files or being reused unintentionally. Enter a token again if you need to download the checkpoint again.

You can also place the checkpoint manually at `models/sam3.1/sam3.1_multiplex.pt`.

## GUI Workflow

If the scene folder path contains non-ASCII characters, an extremely long path, control characters, or `"`, the GUI stops before running. These paths are likely to fail in OpenCV or external 3DGS/SfM tools. Spaces and OneDrive paths are not blocked by themselves. Use a short ASCII working path, for example `D:\work\scene01`.

```text
360° video / normal video / still-image sequences
  -> Step 1: frame extraction
  -> Step 2: frame review and keep/drop decisions
  -> Step 3: mask generation
  -> Step 4: SfM
      -> use an existing Metashape / RealityScan / COLMAP / COLMAP spherical result
      -> run COLMAP cubemap-rig or COLMAP spherical SfM from this app
      -> create RealityScan realignment data from a Metashape result
  -> Step 5: dataset
      -> create JSON/PLY or COLMAP-format datasets for training apps
      -> convert RealityScan CSV/PLY to LichtFeld COLMAP format
      -> apply AprilTag scale to a dataset
  -> Step 6: training
      -> launch LichtFeld Studio / Postshot / Brush / gsplat when a compatible CLI is available
```

| Step | Purpose | Current Default |
| --- | --- | --- |
| 1. Frame Extraction | Extract video frames or register a still-image folder into the scene | Fixed interval + motion adjustment |
| 2. Frame Review | Review extracted frames in single/thumbnail views and apply keep/drop decisions to CSV | Review low-quality candidates and unwanted frames |
| 3. Mask Generation | Generate model-based masks plus optional stitch seam, overexposure, and custom masks | YOLO/SAM2.1, High quality |
| 4. SfM | Choose how camera poses and sparse points are prepared | Existing SfM result / COLMAP / COLMAP spherical |
| 5. Dataset | Create a training-app dataset from SfM results | Metashape / RealityScan / COLMAP spherical / COLMAP / Scale |
| 6. Training | Launch a compatible CLI for an external 3DGS application with an existing dataset | LichtFeld Studio / Postshot / Brush / gsplat |

## Related Tools

- [COLMAP](https://github.com/colmap/colmap): SfM/MVS tool used by the COLMAP cubemap-rig route, native `EQUIRECTANGULAR` spherical SfM route (4.1+), and COLMAP-format dataset workflows.
- [LichtFeld Studio](https://lichtfeld.io/): 3DGS training app supported by the LichtFeld dataset presets and Step 6 CLI launcher.
- [Postshot](https://www.jawset.com/): 3DGS training app supported by Postshot dataset presets and Step 6 CLI launcher.
- [Brush](https://github.com/ArthurBrussee/brush): open-source Gaussian Splatting trainer that can use the cubemap-style outputs.
- [gsplat](https://github.com/nerfstudio-project/gsplat): Python 3DGS library that can train from COLMAP-format datasets.

## External Training Apps

This app does not bundle LichtFeld Studio, Postshot, Brush, or gsplat itself. Step 6 is a launcher for passing the Step 5 dataset to training apps or Python environments that you provide.

- LichtFeld Studio: use a v0.5.3-compatible CLI from the official build or from your own build.
- Postshot: use a Release Build that includes `postshot-cli.exe`, matching the v1.0/v1.1 CLI behavior.
- Brush: select a `brush.exe` from GitHub Releases or your own local build.
- gsplat: this is not an EXE app. Prepare a Python environment with gsplat and the dependencies for `examples/simple_trainer.py`, then select that `python.exe` and the `simple_trainer.py` script in Step 6.

### Using the Dataset in Training Apps

The main output of this app is the 3DGS dataset created in Step 5. Open the Step 5 dataset folder directly in 3DGS applications such as LichtFeld Studio, Postshot, and Brush. This is the normal path when you want to inspect and tune image quality, model settings, step counts, masks, and export options inside the training app.

Step 5 mask output is controlled separately from Step 3 SfM mask generation. `Keep Masks Unchanged` uses the Step 3 masks for training, `Rebuild Training Masks` creates training-only masks from the Step 3 SfM input images, and `No Masks` omits mask links from the dataset. In rebuild mode, the app normally regenerates only masks that are missing or affected by changed settings; turn on `Force overwrite` only when every existing training mask should be written again.

| Step 5 route | Dataset folder |
| --- | --- |
| Metashape + cubemap | `output/metashape_cubemap/` |
| Metashape + ERP 360° / GUT | `output/metashape_3dgut/` |
| COLMAP Spherical + cubemap | `output/colmap_equirect_cubemap/` |
| COLMAP Spherical + ERP 360° / GUT | `output/colmap_equirect_3dgut/` |
| COLMAP Rig | `output/colmap_rig/` |
| Metashape + COLMAP | `output/metashape_colmap/` |
| RealityScan + LichtFeld COLMAP | `output/realityscan/lfs_colmap/` |

Step 6 is a launch shortcut for training apps that provide a compatible CLI. With a LichtFeld Studio v0.5.3-compatible CLI, Postshot v1.0/v1.1 Release Build CLI, Brush CLI, or gsplat Python trainer, the GUI can build the command for repeat runs or headless training. If you are not using CLI training, load the Step 5 output dataset directly in the training app.

Detailed GUI docs:

| Step | Docs |
| --- | --- |
| Step 1 Frame Extraction | [EN](doc/extract_frames_gui.md) / [JP](doc/extract_frames_gui.ja.md) |
| Step 2 Frame Review | [EN](doc/review_frames_gui.md) / [JP](doc/review_frames_gui.ja.md) |
| Step 3 Mask Generation | [EN](doc/mask_tools_gui.md) / [JP](doc/mask_tools_gui.ja.md) |
| Step 4 SfM / Step 5 Dataset | [EN](doc/cubemap_tools_gui.md) / [JP](doc/cubemap_tools_gui.ja.md) |
| Step 6 Training | [EN](doc/training_gui.md) / [JP](doc/training_gui.ja.md) |
| Scene Import | [EN](doc/scene_import.md) / [JP](doc/scene_import.ja.md) |

## Recommended Workflow: Metashape Route

1. Prepare 360° video from an Insta360 / Osmo 360 or similar camera. Add normal video or still-image folders to the same scene when needed.
2. Extract SfM-friendly frames or register still-image folders in Step 1.
3. Review low-quality or unnecessary frames in Step 2.
4. Generate masks for people, camera operators, tripods, sky, or similar SfM-unfriendly regions in Step 3. `Quality: High` is the recommended starting point.
5. If masks still leak through, switch only the affected images to `Quality: Best`, use YOLO26-sem for Cityscapes semantic targets such as sky or vegetation, or regenerate them with SAM3.1 prompts.
6. Enable stitch seam, overexposure, and custom masks when they match the source material.
7. Import the generated `masks/` folder into Metashape as per-image masks, then run SfM. Mixed sources can be aligned in Metashape as usual.
8. Export Metashape cameras as Agisoft XML and sparse points as Stanford PLY. Saving both files in the scene folder is recommended; otherwise select them manually in the GUI.
9. In Step 4, choose `Use Existing SfM Result`. If Metashape already produced camera poses and sparse points, there is usually nothing else to run in this step.
10. In Step 5, use the Metashape XML/PLY result to create the dataset format your training app expects: NeRF-style JSON/PLY, a COLMAP-format dataset, or RealityScan realignment data. In `Mask Output`, keep the Step 3 SfM masks for the default workflow, or choose `Rebuild Training Masks` when training should exclude a different set of regions than SfM.
11. To estimate scale with AprilTags, print and place the tags before capture. After creating a cubemap or COLMAP-style dataset, use Step 5 `Scale Adjustment`, enter the printed tag size and IDs, and apply the scale only when the estimate looks reasonable.
12. Load the Step 5 output in LichtFeld Studio, Postshot, Brush, or another training app. When you want repeat runs or headless training through a compatible CLI, use Step 6 to launch LichtFeld Studio, Postshot, Brush, or gsplat with the dataset you just created.

## Recommended Workflow: Metashape -> RealityScan -> LichtFeld

Use this route when Metashape aligns the base 360° images well, but you want RealityScan to realign the cubemap result and attach additional normal-camera images before training in LichtFeld.

1. Run Steps 1-3 and Metashape SfM as in the Metashape route.
2. Export Agisoft XML and Stanford PLY from Metashape, preferably into the scene folder.
3. In Step 4, run `Metashape -> RealityScan Data`. The app writes RealityScan input under `output/realityscan/`.
4. In RealityScan, add `output/realityscan/images/` first and run Align until cameras and sparse points are generated. Cubemap images live in its `_geometry` layer and masks live in its `_mask` layer.
5. Add `output/realityscan/extra_images/` only after the cubemap component is stable, then run Align again. Extra images use the same `_geometry` / `_mask` layer layout. This usually gives more reliable normal-image registration than importing every image at once.
6. Confirm the component you want to train from, then export the RealityScan camera CSV and PLY into `output/realityscan/`.
7. In Step 5, run `RealityScan -> COLMAP Dataset`. The app merges CSV-registered images from `images/_geometry` and `extra_images/_geometry`, with matching `_mask` layers, into `output/realityscan/lfs_colmap/`.
8. Open `output/realityscan/lfs_colmap/` in LichtFeld Studio as a Dataset with `GUT` off.

## COLMAP Route

1. Use Steps 1-3 in the same way as the Metashape route.
2. In Step 4, choose `Run COLMAP SfM`. 360° images are expanded into cubemap rigs, while normal images remain normal cameras.
3. Confirm the [COLMAP](https://github.com/colmap/colmap) launcher or GLOMAP executable, matcher, and mapper, then run it. For an official Windows COLMAP package, select its top-level `COLMAP.bat`.
4. After completion, pass `output/colmap_rig/` as a COLMAP dataset to COLMAP-compatible 3DGS tools. When no extra conversion is needed, you can skip Step 5 and continue to training.

## COLMAP Spherical SfM Route

1. Use Steps 1-3 in the same way as the Metashape route. For COLMAP spherical SfM, use same-resolution equirectangular 360° images only.
2. In Step 4, choose `Run COLMAP Spherical SfM` and select an official COLMAP 4.1+ launcher. COLMAP 4.2 or newer is recommended. With the official Windows package, select the top-level `COLMAP.bat`; if you select its `bin/colmap.exe`, the app automatically uses the adjacent batch launcher so packaged libraries are available.
3. On RTX 50-series GPUs, older CUDA builds can stop during GPU SIFT. If that happens, select a COLMAP build made with a CUDA architecture that supports the GPU.
4. Start with `Matcher: Sequential` and `SfM Quality: Standard`. Before processing all images, the app checks the selected feature, matcher, and mapper options and runs a one-image GPU SIFT preflight.
5. In Step 5, choose `COLMAP Spherical -> NeRF Dataset (JSON/PLY)`, then choose PINHOLE cubemap output or ERP 360° data for LichtFeld.
6. After completion, pass `output/colmap_equirect_3dgut/` or `output/colmap_equirect_cubemap/` to downstream apps. COLMAP spherical SfM working files stay under `output/colmap_equirect/`.

### COLMAP Compatibility Quick Reference

COLMAP is an external application and is not installed by `setup_windows.bat`.

| Check | Guidance |
| --- | --- |
| Spherical SfM version | COLMAP 4.1 is the supported minimum. COLMAP 4.2 or newer is recommended, especially for the `Quality` preset that uses spherical guided matching. |
| Official Windows package | Select the top-level `COLMAP.bat`. Selecting that package's `bin/colmap.exe` is also safe because the app switches to the adjacent batch launcher automatically. |
| PATH or custom build | Leaving the field blank searches for `COLMAP.bat`, then `colmap.exe` on Windows. A standalone `colmap.exe` remains supported when it has all required runtime libraries and CLI options. |
| Before a full run | The app verifies the version and exact options needed by the selected preset, then tests GPU SIFT with one image. Passing this preflight confirms startup compatibility, not that every scene image will register. |

Existing successful COLMAP 4.1 sparse models do not need to be rebuilt only because COLMAP 4.2 is available. See the [Step 4 / Step 5 guide](doc/cubemap_tools_gui.md#run-colmap-spherical-sfm) for migration and troubleshooting details.

## Mask Preprocessing for Normal Images

For normal-camera video from DSLR, mirrorless, smartphone, or similar cameras, extract frames in Step 1. For existing image sequences, add a still-image folder to Step 1 `Input Sources`; the images are copied into the scene and registered for later steps. Step 3 detects the image type from Step 1 records, external image registration, or image headers. Normal images keep model-based masking and overexposure masking available while disabling stitch seam masking and 360° pole projection assist.

Use this when you want to exclude people, vehicles, blown-out regions, or similar areas before importing images into SfM software.

## Mask Tuning Notes

- Start with `Quality: High`.
- Use `Quality: Standard` for faster test runs.
- If people leak through, try `Quality: Best` or raise `Expand` slightly.
- `Quality: Best` prioritizes accuracy and takes longer, so it is best used to regenerate only images where misses remain.
- When you find a miss in preview, adjust settings and use `Regenerate Mask` to save only that image back to `masks/` using the current model and enabled extra masks. In thumbnail mode, use `Ctrl` / `Shift` selection to regenerate multiple selected images together. SAM3.1 can also add or subtract prompt detections against existing saved masks.
- Stitch seam masks are useful when the seam position is stable in the equirectangular image. If FlowState stabilization, direction lock, AI stitching, or similar processing moves the seam, verify it in the preview before using it.

## Requirements

- Windows 10/11
- Python 3.12 (3.12.10 confirmed)
- CUDA-capable GPU
- CUDA Toolkit 12.8
- FFmpeg / FFprobe (`setup_windows.bat` installs Gyan.FFmpeg through winget when missing)
- External COLMAP installation only when running an in-app COLMAP route (4.1+ required for spherical SfM; 4.2+ recommended)

Main Python packages resolved by `setup_windows.bat`:

```text
torch / torchvision / torchaudio from the CUDA 12.8 wheel index
numpy, opencv-python, Pillow, open3d, ultralytics, tqdm, PySide6, sam3, timm, huggingface-hub, pycocotools
```

`setup_windows.bat` uses the pinned verified package set under `requirements/` for reproducible first-time setup. `update.bat` keeps the app and the existing `.venv/` aligned with the current release; pass `--latest-deps` only when you explicitly want to try the latest compatible dependency versions. For normal release users, `update.bat` is the only update command.

## License

MIT License. See [LICENSE](LICENSE).

Mask generation features use third-party libraries and model weights with separate license terms. See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
