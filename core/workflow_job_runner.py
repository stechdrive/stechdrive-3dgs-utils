from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from core.cancellation import CancellationToken, raise_if_cancelled
from core.colmap_cli import build_colmap_command
from core.colmap_rig_export import prepare_views_for_colmap, write_rig_config_json
from core.cubemap_export_metadata import (
    collect_image_files,
    infer_image_only_frame_output_sizes,
    infer_image_only_sizes,
    write_colmap_rig_metadata,
    write_image_only_metadata,
)
from core.cubemap_image_conversion import convert_images, convert_images_colmap_rig
from core.cubemap_transform_export import frame_output_sizes_from_transforms, frame_yaw_offset, transform_json
from core.dataset_writer_colmap import replace_file_with_link_or_copy
from core.metashape_preprocess import export_metashape_equirectangular_dataset
from core.orientation_correction import FINAL_ORIENTATION_NONE
from core.realityscan_layout import primary_geometry_dir, primary_mask_dir
from core.realityscan_xmp import (
    append_realityscan_unposed_scene_images,
    write_realityscan_mask_layers,
    write_realityscan_xmp_sidecars,
)
from core.spheresfm_gpu_preflight import (
    build_feature_command as build_spheresfm_preflight_feature_command,
)
from core.spheresfm_gpu_preflight import (
    reset_preflight_workspace,
)
from core.spheresfm_gpu_preflight import (
    run_colmap_command as run_spheresfm_preflight_colmap_command,
)
from core.spheresfm_project import (
    iter_images as iter_spheresfm_images,
)
from core.spheresfm_project import (
    prepare_masks as prepare_spheresfm_masks,
)
from core.spheresfm_project import (
    validate_spheresfm_colmap,
)
from core.spheresfm_to_transforms import convert as convert_spheresfm_to_transforms
from core.transforms_to_colmap import convert as convert_transforms_to_colmap
from core.workflow_job_spec import (
    JOB_KIND_CUBEMAP_CONVERSION,
    JOB_KIND_METASHAPE_PREPROCESS,
    JOB_KIND_SPHERESFM_PREFLIGHT,
    JOB_KIND_SPHERESFM_PREPARE,
    JOB_KIND_SPHERESFM_TRANSFORMS,
    JOB_KIND_TRANSFORMS_TO_COLMAP,
    load_workflow_job,
    validate_workflow_job_payload,
)


def _progress_log_callback(cancel_event: CancellationToken | None = None) -> Callable[[int, int], None]:
    last_bucket = -1
    last_pair: tuple[int, int] | None = None

    def callback(done: int, total: int) -> None:
        nonlocal last_bucket, last_pair
        raise_if_cancelled(cancel_event)
        done = max(0, int(done))
        total = max(0, int(total))
        if total <= 0:
            return
        pair = (min(done, total), total)
        if pair == last_pair:
            return
        bucket = int((pair[0] / float(total)) * 100.0)
        if pair[0] == 0 or pair[0] >= total or bucket != last_bucket:
            print(f"[progress] {pair[0]}/{total}", flush=True)
            last_bucket = bucket
            last_pair = pair

    return callback


def run_workflow_job_file(path: str | Path, *, cancel_event: CancellationToken | None = None) -> None:
    run_workflow_job_payload(load_workflow_job(path), cancel_event=cancel_event)


def run_workflow_job_payload(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    validate_workflow_job_payload(job)
    raise_if_cancelled(cancel_event)
    kind = str(job["kind"])
    if kind == JOB_KIND_METASHAPE_PREPROCESS:
        _run_metashape_preprocess(job, cancel_event=cancel_event)
    elif kind == JOB_KIND_CUBEMAP_CONVERSION:
        _run_cubemap_conversion(job, cancel_event=cancel_event)
    elif kind == JOB_KIND_TRANSFORMS_TO_COLMAP:
        _run_transforms_to_colmap(job, cancel_event=cancel_event)
    elif kind == JOB_KIND_SPHERESFM_PREFLIGHT:
        _run_spheresfm_preflight(job, cancel_event=cancel_event)
    elif kind == JOB_KIND_SPHERESFM_PREPARE:
        _run_spheresfm_prepare(job, cancel_event=cancel_event)
    elif kind == JOB_KIND_SPHERESFM_TRANSFORMS:
        _run_spheresfm_transforms(job, cancel_event=cancel_event)
    else:
        raise ValueError(f"Unsupported workflow job kind: {kind}")


def _run_metashape_preprocess(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    result = export_metashape_equirectangular_dataset(
        images_dir=Path(str(job["images_dir"])),
        xml_path=Path(str(job["xml_path"])),
        output_dir=Path(str(job["output_dir"])),
        ply_path=Path(str(job["ply_path"])) if bool(job.get("use_ply")) and str(job.get("ply_path") or "") else None,
        fix_upside_down=not bool(job.get("no_fix_rotation")),
        lichtfeld_camera_y180=bool(job.get("lichtfeld_camera_y180", True)),
        scale=float(job.get("scale", 1.0)),
        verbose=True,
        progress_callback=_progress_log_callback(cancel_event),
    )
    print(f"Metashape frames: {result.num_frames}", flush=True)
    print(f"Metashape skipped: {result.num_skipped}", flush=True)
    print(f"Metashape camera model: {result.camera_model}", flush=True)
    raise_if_cancelled(cancel_event)


def _run_cubemap_conversion(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    input_dir = Path(str(job["input_dir"]))
    output_dir = Path(str(job["output_dir"]))
    image_dir = Path(str(job.get("image_dir") or input_dir))
    mask_dir = Path(str(job.get("mask_dir") or (input_dir / "masks")))
    views = [dict(view) for view in job.get("views", []) if isinstance(view, dict) and bool(view.get("enabled", True))]
    if not views:
        raise ValueError("No views to export")
    fov = float(job.get("fov", 90.0))
    output_scale = float(job.get("output_scale", 0.5))
    if fov <= 0.0 or fov >= 180.0:
        raise ValueError("fov must be in (0, 180)")
    if output_scale <= 0.0 or output_scale > 1.0:
        raise ValueError("output_scale must be in (0, 1.0]")

    for view in views:
        print(f"{view['name']}: yaw={view['yaw']},pitch={view['pitch']}", flush=True)

    image_only = bool(job.get("image_only"))
    colmap_rig = bool(job.get("colmap_rig"))
    if colmap_rig:
        image_only = True
    if image_only and str(job.get("final_orientation") or FINAL_ORIENTATION_NONE) != FINAL_ORIENTATION_NONE:
        raise ValueError("final_orientation requires transforms.json conversion, not image-only conversion")
    if image_only and bool(job.get("realityscan_xmp")):
        raise ValueError("RealityScan XMP requires transforms.json conversion, not image-only conversion")

    realityscan_xmp_enabled = bool(job.get("realityscan_xmp"))
    realityscan_output_image_dir = primary_geometry_dir(output_dir)
    realityscan_output_mask_dir = primary_mask_dir(output_dir)
    if image_only:
        source_image_dir = input_dir / "images"
        if not source_image_dir.is_dir():
            raise FileNotFoundError(f"images directory not found: {source_image_dir}")
        image_files = collect_image_files(str(source_image_dir))
        if not image_files:
            raise FileNotFoundError(f"no images found in {source_image_dir}")
        input_size, output_size = infer_image_only_sizes(str(source_image_dir), image_files, output_scale)
        frame_output_sizes = infer_image_only_frame_output_sizes(str(source_image_dir), image_files, output_scale)
        if colmap_rig:
            if len(set(frame_output_sizes)) > 1:
                raise ValueError("COLMAP rig image-only export requires one ERP resolution; use the mixed COLMAP route")
            frame_yaw_offsets = [0.0 for _ in image_files]
            prepared_views = prepare_views_for_colmap([{**view, "fov": fov} for view in views])
            rig_path = write_rig_config_json(
                str(output_dir),
                prepared_views,
                (output_size, output_size),
                rig_name=str(job.get("colmap_rig_name") or "rig1"),
            )
            write_colmap_rig_metadata(
                output_dir=str(output_dir),
                image_dir=str(source_image_dir),
                mask_dir=str(mask_dir),
                image_files=image_files,
                prepared_views=prepared_views,
                fov=fov,
                output_scale=output_scale,
                input_size=input_size,
                output_size=output_size,
                rig_name=str(job.get("colmap_rig_name") or "rig1"),
                export_images=bool(job.get("write_images", True)),
                export_masks=bool(job.get("write_masks", True)),
            )
            print(f"COLMAP rig export: {len(image_files)} source images", flush=True)
            print(f"Saved rig_config.json: {rig_path}", flush=True)
            views = prepared_views
        else:
            frame_yaw_offsets = [
                frame_yaw_offset(i, float(job.get("yaw_offset_per_frame", 0.0))) for i in range(len(image_files))
            ]
            write_image_only_metadata(
                output_dir=str(output_dir),
                image_dir=str(source_image_dir),
                mask_dir=str(mask_dir),
                image_files=image_files,
                views=views,
                fov=fov,
                output_scale=output_scale,
                input_size=input_size,
                output_size=output_size,
                yaw_offset_per_frame=float(job.get("yaw_offset_per_frame", 0.0)),
                export_images=bool(job.get("write_images", True)),
                export_masks=bool(job.get("write_masks", True)),
                frame_output_sizes=frame_output_sizes,
            )
            print(f"Image-only export: {len(image_files)} source images", flush=True)
        image_dir = source_image_dir
    else:
        raise_if_cancelled(cancel_event)
        axis_mode = str(job.get("axis_mode") or "postshot")
        image_files, frame_yaw_offsets, input_size, output_size = transform_json(
            input_dir=str(input_dir),
            input_json=str(job.get("input_json") or "transforms.json"),
            image_dir=str(image_dir),
            output_dir=str(output_dir),
            views=views,
            fov=fov,
            output_scale=output_scale,
            no_transform=axis_mode == "none",
            allow_duplicate=bool(job.get("allow_duplicate")),
            brush_mode=axis_mode == "brush",
            yaw_offset_per_frame=float(job.get("yaw_offset_per_frame", 0.0)),
            final_orientation=str(job.get("final_orientation") or FINAL_ORIENTATION_NONE),
            output_format=str(job.get("output_format") or "auto"),
            output_file_dir="images/_geometry" if realityscan_xmp_enabled else None,
        )
        if not image_files:
            raise ValueError("No frames were converted from transforms.json")
        frame_output_sizes = frame_output_sizes_from_transforms(output_dir / "transforms.json", image_files)
        if not frame_output_sizes:
            frame_output_sizes = [output_size for _ in image_files]

    raise_if_cancelled(cancel_event)
    realityscan_manifest = None
    if realityscan_xmp_enabled:
        realityscan_manifest = write_realityscan_xmp_sidecars(
            output_dir,
            pose_prior=str(job.get("realityscan_pose_prior") or "exact"),
            calibration_prior=str(job.get("realityscan_calibration_prior") or "exact"),
            coordinates=str(job.get("realityscan_coordinates") or "auto"),
            rig_name=str(job.get("realityscan_rig_name") or "stechdrive-cubemap"),
            include_rig=bool(job.get("realityscan_include_rig")),
        )
        print(f"RealityScan XMP sidecars: {realityscan_manifest['xmp_count']}", flush=True)

    raise_if_cancelled(cancel_event)
    if float(job.get("yaw_offset_per_frame", 0.0)) != 0.0 and not colmap_rig:
        unique_offsets = sorted({round(y, 3) for y in frame_yaw_offsets})
        print(
            f"Per-frame yaw rotation: step={float(job.get('yaw_offset_per_frame', 0.0)):g}deg, "
            f"unique offsets={len(unique_offsets)}",
            flush=True,
        )

    export_images = bool(job.get("write_images", True))
    export_masks = bool(job.get("write_masks", True))
    if export_images or export_masks:
        common = {
            "image_files": image_files,
            "input_size": input_size,
            "output_size": output_size,
            "views": views,
            "fov": fov,
            "image_dir": str(image_dir),
            "mask_dir": str(mask_dir),
            "mask_from_alpha": bool(job.get("mask_from_alpha")),
            "invert_masks": bool(job.get("invert_masks")),
            "output_format": str(job.get("output_format") or "auto"),
            "output_bit_depth": str(job.get("output_bit_depth") or "8"),
            "jpg_quality": int(job.get("jpg_quality", 95)),
            "export_images": export_images,
            "export_masks": export_masks,
            "workers": str(job.get("workers") or "auto"),
            "remap_cache_limit": str(job.get("remap_cache_limit") or "auto"),
        }
        if colmap_rig:
            convert_images_colmap_rig(
                **common,
                output_dir=str(output_dir),
                rig_name=str(job.get("colmap_rig_name") or "rig1"),
                cancel_event=cancel_event,
            )
            return
        convert_images(
            **common,
            output_image_dir=str(realityscan_output_image_dir if realityscan_xmp_enabled else output_dir / "images"),
            output_mask_dir=str(realityscan_output_mask_dir if realityscan_xmp_enabled else output_dir / "masks"),
            frame_yaw_offsets=frame_yaw_offsets,
            frame_output_sizes=frame_output_sizes,
            cancel_event=cancel_event,
        )

    raise_if_cancelled(cancel_event)
    if realityscan_xmp_enabled and bool(job.get("realityscan_mask_layers", True)) and export_masks:
        realityscan_manifest = write_realityscan_mask_layers(output_dir, manifest=realityscan_manifest)
        print(f"RealityScan mask layers: {realityscan_manifest['mask_layer_count']}", flush=True)

    raise_if_cancelled(cancel_event)
    unposed_scene = str(job.get("realityscan_unposed_scene_dir") or "").strip()
    if realityscan_xmp_enabled and bool(job.get("realityscan_unposed_images")) and unposed_scene:
        realityscan_manifest = append_realityscan_unposed_scene_images(
            output_dir,
            scene_dir=Path(unposed_scene),
            exclude_source_files=image_files,
            exclude_root=image_dir,
            include_masks=export_masks,
            manifest=realityscan_manifest,
        )
        print(f"RealityScan unposed images: {realityscan_manifest['unposed_image_count']}", flush=True)


def _run_transforms_to_colmap(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    result = convert_transforms_to_colmap(
        input_dir=Path(str(job["input_dir"])),
        json_name=str(job.get("json_name") or "transforms.json"),
        output_dir=Path(str(job["output_dir"])),
        ply_path=Path(str(job["ply_path"])) if str(job.get("ply_path") or "") else None,
        image_prefix=str(job.get("image_prefix") or "images"),
        progress_callback=_progress_log_callback(cancel_event),
    )
    dataset_root_text = str(job.get("dataset_root") or "").strip()
    if dataset_root_text:
        dataset_root = Path(dataset_root_text)
        asset_input_dir = Path(str(job.get("asset_input_dir") or job["input_dir"]))
        if bool(job.get("copy_images")):
            count = _link_or_copy_tree(
                asset_input_dir / "images",
                dataset_root / "images",
                cancel_event=cancel_event,
                progress_callback=_progress_log_callback(cancel_event),
            )
            print(f"Dataset images: {count}", flush=True)
        if bool(job.get("copy_masks")):
            count = _link_or_copy_tree(
                asset_input_dir / "masks",
                dataset_root / "masks",
                cancel_event=cancel_event,
                progress_callback=_progress_log_callback(cancel_event),
            )
            print(f"Dataset masks: {count}", flush=True)
    print(f"Wrote cameras.txt, images.txt, points3D.txt to {result['output_dir']}", flush=True)
    print(f"  Camera model: {result['camera_model']}", flush=True)
    print(f"  Images: {result['num_images']}", flush=True)
    print(f"  3D points: {result['num_points']}", flush=True)
    raise_if_cancelled(cancel_event)


def _link_or_copy_tree(
    source_dir: Path,
    destination_dir: Path,
    *,
    cancel_event: CancellationToken | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    source = Path(source_dir)
    if not source.is_dir():
        return 0
    destination = Path(destination_dir)
    source_files = sorted(
        (source_file for source_file in source.rglob("*") if source_file.is_file()),
        key=lambda path: str(path).lower(),
    )
    total = len(source_files)
    if total <= 0:
        return 0
    if progress_callback is not None:
        progress_callback(0, total)
    copied = 0
    for source_file in source_files:
        raise_if_cancelled(cancel_event)
        rel = source_file.relative_to(source)
        replace_file_with_link_or_copy(source_file, destination / rel)
        copied += 1
        if progress_callback is not None:
            progress_callback(copied, total)
    return copied


def _run_spheresfm_preflight(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    colmap = str(job["colmap"])
    images_dir = Path(str(job["images_dir"]))
    work_dir = Path(str(job["work_dir"]))
    if not images_dir.is_dir():
        raise FileNotFoundError(f"Images folder not found: {images_dir}")
    images = iter_spheresfm_images(images_dir)
    if not images:
        raise FileNotFoundError(f"No supported images found: {images_dir}")
    validate_spheresfm_colmap(
        colmap,
        matcher=str(job["matcher"]),
        quality_preset=str(job["quality_preset"]),
        use_masks=bool(job["use_masks"]),
    )

    preflight_images = reset_preflight_workspace(work_dir)
    source = images[0]
    target = preflight_images / f"preflight_000001{source.suffix.lower()}"
    shutil.copy2(source, target)
    print(f"COLMAP spherical GPU preflight image: {source}", flush=True)

    raise_if_cancelled(cancel_event)
    database = work_dir / "database.db"
    run_spheresfm_preflight_colmap_command(
        build_colmap_command(colmap, "database_creator", "--database_path", str(database)),
        "COLMAP spherical preflight database_creator",
        cancel_event=cancel_event,
    )
    run_spheresfm_preflight_colmap_command(
        build_spheresfm_preflight_feature_command(colmap, database, preflight_images, str(job["camera_params"])),
        "COLMAP spherical preflight feature_extractor",
        cancel_event=cancel_event,
    )
    print("COLMAP spherical GPU preflight passed.", flush=True)
    print("[progress] 1/1", flush=True)
    raise_if_cancelled(cancel_event)


def _run_spheresfm_prepare(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    colmap = str(job["colmap"])
    images_dir = Path(str(job["images_dir"]))
    if not images_dir.is_dir():
        raise FileNotFoundError(f"Images folder not found: {images_dir}")
    images = iter_spheresfm_images(images_dir)
    if not images:
        raise FileNotFoundError(f"No supported images found: {images_dir}")
    validate_spheresfm_colmap(colmap, check_capabilities=False)

    if bool(job.get("use_masks")):
        source_masks_dir = Path(str(job["source_masks_dir"]))
        if not source_masks_dir.is_dir():
            raise FileNotFoundError(f"Masks folder not found: {source_masks_dir}")
        copied, missing = prepare_spheresfm_masks(
            images_dir,
            source_masks_dir,
            Path(str(job["output_masks_dir"])),
        )
        print(f"Prepared COLMAP spherical masks: copied={copied}, missing={missing}", flush=True)
    else:
        print("COLMAP spherical masks disabled.", flush=True)
        print(f"[progress] {len(images)}/{len(images)}", flush=True)
    raise_if_cancelled(cancel_event)


def _run_spheresfm_transforms(job: dict, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    result = convert_spheresfm_to_transforms(
        Path(str(job["sparse_dir"])),
        Path(str(job["output_dir"])),
        Path(str(job["images_dir"])),
        image_path_mode=str(job.get("image_path_mode") or "relative"),
        opengl_camera=bool(job.get("opengl_camera", True)),
        write_pointcloud=bool(job.get("write_pointcloud", True)),
    )
    print(f"Using sparse model: {result['model_dir']}", flush=True)
    print(f"Saved transforms.json: {result['transforms']}", flush=True)
    if result["pointcloud"]:
        print(f"Saved pointcloud.ply: {result['pointcloud']}", flush=True)
    print(f"Images: {result['num_images']}", flush=True)
    print(f"Points: {result['num_points']}", flush=True)
    print(f"Result: {json.dumps(result, ensure_ascii=False, sort_keys=True)}", flush=True)
    raise_if_cancelled(cancel_event)
