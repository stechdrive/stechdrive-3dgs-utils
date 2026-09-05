# Step 1 Frame Extraction GUI

Step 1 turns 360° video, normal video, or an existing still-image folder into scene images for SfM and 3DGS. The `images/` folder and `_stechdrive/frames/selected_frames.csv` created here become the input for Step 2 review, Step 3 mask generation, and downstream SfM in Metashape, COLMAP, COLMAP spherical SfM, or another tool.

Choose a scene folder, then add videos or still-image folders to `Input Sources` on the right. Videos are extracted at the specified interval. Still-image folders are copied into the scene `images/` folder and registered. `Motion` is on by default; it reduces redundant near-duplicate candidates and adds candidates where viewpoint change is useful. Turn `Motion` off when you want faster extraction.

## Required Video Tools

Video extraction requires **FFmpeg 7 or newer and its bundled FFprobe**. If either tool is missing, run `setup_windows.bat` to install the current package through winget. Existing older builds must be updated; for a winget installation, use `winget upgrade --id Gyan.FFmpeg --exact --source winget`, then reopen the terminal and rerun setup.

If you chose executable paths in Step 1, select the updated copies as well. The selected versions are checked before video analysis or changes to existing scene images. Release builds with a recognizable version number are supported. Existing still-image folders can be imported without FFmpeg.

Frame extraction uses FFmpeg's file-backed filter syntax and per-stream frame-rate mode, so it also works with FFmpeg 9, which removed the old options. Large frame selections stay in a temporary file to avoid Windows command-length limits.

## Extraction Approach

This step is not meant to create as many still images as possible from video. It is a preprocessing step for creating an SfM-friendly image set with enough frames, but not excessive frames.

The source footage quality matters most. If the video is strongly blurred during capture, badly exposed, low in usable features, or filmed along a poor path, frame extraction cannot fundamentally fix it. This step can only select SfM-friendly candidates from good footage and make suspicious frames easier to review.

The goal is to preserve the viewpoint change and coverage SfM needs while reducing near-duplicate frames and keeping compute cost under control. A fixed interval gives stable whole-video coverage. Motion adjustment can then drop redundant candidates in slow sections and add candidates where movement is faster.

Choosing only the sharpest nearby frame is not enough for SfM. A frame can be sharp but still too similar to the last kept frame, weak in features, or poorly overlapped for reconstruction. This step therefore considers sharpness together with change from the last kept frame, sparse feature tracking, and low-texture checks.

The design focuses expensive decisions where they matter. It does not run a high-resolution, high-cost search for the sharpest image everywhere. Instead, it starts from a fixed interval and pays extra attention to candidates that look too similar, lack viewpoint change, or may be blurred. This keeps candidate quality reviewable while helping reduce processing time, output count, and downstream SfM cost.

The main capture assumptions are walking footage and drone footage. Even within walking footage, nearby indoor subjects and wider park or plaza scenes produce different parallax for the same movement. `Capture Profile` chooses the base interval, min/max gaps, and automatic motion thresholds together.

## First Choice

| Goal | Recommended settings |
| --- | --- |
| Create normal SfM-ready frames | `Capture Profile: Walk: Standard`, `Motion ON` |
| Quickly cut frames without analysis | `Quick extract ON` |
| Nearby walls, exhibits, furniture, or narrow interiors | `Capture Profile: Walk: Close` |
| Wide walking footage such as parks, plazas, or exteriors | `Capture Profile: Walk: Wide` |
| Aerial or distant-view footage | `Capture Profile: Drone: Distant` |
| Rebuild the same video with new settings | `Extraction Target: Re-extract Selected` |
| Add multiple videos into one scene | `Extraction Target: Add Unextracted Videos` |
| Start from numbered still images you already have | Add a `Still Folder` to `Input Sources` |

The GUI stops before running when the scene folder path contains non-ASCII characters, an extremely long path, control characters, or `"`. Use a short ASCII working path because external tools often fail on problematic paths.

## Basic Flow

1. First choose `Scene Folder`. Output images are written under `images/` inside it.
2. Check `Input Sources` on the right. Videos inside the scene folder are registered automatically.
3. If the material you want is not listed, press `Add Videos` or `Add Still Folder`. Adding keeps the existing list, so videos and still folders from other folders can be added later.
4. Videos and still-image folders can be mixed in the same list. The run processes the list from top to bottom, extracting video frames or importing still images as needed.
5. Choose `Capture Profile`. Start with `Walk: Standard` for normal walking footage.
6. Keep `Motion` on for normal extraction. Turn `Quick extract` on only when you want a fast fixed-interval cut.
7. Choose `Extraction Target`. `Add Unextracted Videos` is fine for the first run or for adding different videos.
8. When the preflight status says the run is ready, press `Extract Frames`.
9. After extraction finishes, continue to Step 2.

The input source list is where you confirm the material that will be processed. Video rows show extraction status, 360°/normal detection, resolution, fps, duration, and estimated frame count. Still-folder rows show the target image count. If a source was added by mistake, select its row and remove it. The original video file or still-image folder is not deleted.

When a still-image folder is added, Step 1 imports supported images into the scene `images/` folder and writes the same review metadata used by video extraction. This lets Step 2 and Step 3 handle pre-existing frame sequences without a manual workaround.

## Fixed Interval And Motion

### Fixed Interval

`Base Interval` is the baseline spacing between extracted candidates. At 30fps, `1.5` seconds means roughly one candidate every 45 frames.

Increasing the value reduces the frame count. Decreasing it increases the count. For SfM, a stable fixed cadence is easier to reason about than a fully variable extraction interval.

The fixed interval is not the only quality decision. It is the baseline that covers the whole video consistently; motion analysis then adjusts candidates based on actual viewpoint change and blur risk.

### Motion

`Motion` adds SfM-oriented decisions on top of the fixed interval. It compares candidates with the last kept frame and looks at the remaining image change after yaw alignment, rather than treating pure camera heading changes as useful motion. It can:

- drop candidates as `Drop: similar frame` when they are too redundant
- add candidates as `Added: viewpoint change` before the next fixed-cadence point
- replace dropped blur candidates from the range up to `Max` and mark them as `Added: blur replacement`
- keep safety candidates as `Added: preserved spacing` when the gap would become too large
- split blur into `Drop: blur` and `Review: possible blur`, then flag low texture or weak feature tracking for Step 2 review

### Quick Extract

`Quick extract` skips analysis and cuts frames directly at the requested `Base Interval`. It is fast, but it does not create motion-adjustment decisions or Step 2 review labels.

Use it for a fast content check or when you only need frames immediately. For production SfM input, normal extraction with `Motion` is usually safer.

## Interval Settings

| Setting | Meaning | Starting point |
| --- | --- | --- |
| `Base Interval` | Baseline candidate spacing | `Walk: Standard`: `1.5` sec |
| `Min` | Minimum spacing for inserted candidates | `Walk: Standard`: `0.8` sec |
| `Max` | Safety spacing so low-motion sections do not become too sparse | `Walk: Standard`: `4.0` sec |

If the output has too many frames, raise `Base Interval`. If camera motion is fast and useful viewpoints are missing, lower `Base Interval` or `Min`.

## Capture Profile

`Capture Profile` chooses the assumption used by the automatic motion thresholds and also sets the starting values for `Base Interval`, `Min`, and `Max`. It does not lock the workflow to a capture genre; it tells the analyzer how much useful image change to expect for the same camera movement.

- `Walk: Standard`: facilities, streets, and normal walking footage. Start here when unsure.
- `Walk: Close`: nearby walls, exhibits, furniture, and narrow corridors.
- `Walk: Wide`: parks, plazas, building exteriors, and other walking footage with more distant subjects.
- `Drone: Distant`: aerial or distant-view footage.

You can still edit `Base Interval`, `Min`, and `Max` manually after choosing a profile.

## Analysis Width And JPEG Quality

`Analysis Width` controls how much detail motion analysis, blur checks, and feature tracking inspect. Larger values can make some fine-detail decisions more stable, but processing becomes slower. It does not change the resolution of files written to `images/`. The default is usually sufficient; adjust it only when decisions are clearly unstable for the source material.

`JPEG Quality` controls the balance between saved image quality and file size. Lower values mean higher quality and larger files. The default `2` is already high quality, so it usually does not need to change.

## Outputs

| Output | Meaning |
| --- | --- |
| `images/` | Extracted or imported scene images |
| `_stechdrive/frames/selected_frames.csv` | Keep/drop candidates and source metadata for Step 2 |
| `_stechdrive/frames/extract_report.json` | Extraction settings and run summary |
| `extract_cache.npz` | Cache used to speed up re-analysis |

Step 2 turns `_stechdrive/frames/selected_frames.csv` decisions into visible review labels. If there are too many added, dropped, or review-target frames, adjust Step 1 intervals or capture profile and extract again.

## Common Decisions

- Start with `Capture Profile: Walk: Standard` and `Motion ON`.
- If there are too many frames, raise `Base Interval`.
- If many frames are similar, review examples in Step 2, then consider raising `Base Interval` or trying `Walk: Wide`.
- If many frames are dropped or flagged for blur, inspect the source footage first. Extraction searches nearby replacement candidates for clear blur, but footage that is blurred overall cannot be fundamentally rescued. Step 2 can still keep borderline frames that look acceptable.
- Use `Reset and Overwrite` when rebuilding the same video with new settings.
- `Quick extract` is convenient, but normal extraction is better for production selection because it creates Step 2 review labels.
