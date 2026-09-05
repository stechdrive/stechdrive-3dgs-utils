from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.job_payload_validation import (
    require_bool,
    require_finite_float,
    require_int_range,
    require_kind,
    require_mapping,
    require_schema_version,
    require_str,
    require_views,
)
from core.spheresfm_cli_contract import SPHERESFM_MATCHERS, SPHERESFM_QUALITY_PRESETS

WORKFLOW_JOB_SCHEMA_VERSION = 1

JOB_KIND_METASHAPE_PREPROCESS = "metashape_preprocess"
JOB_KIND_CUBEMAP_CONVERSION = "cubemap_conversion"
JOB_KIND_TRANSFORMS_TO_COLMAP = "transforms_to_colmap"
JOB_KIND_SPHERESFM_PREFLIGHT = "spheresfm_preflight"
JOB_KIND_SPHERESFM_PREPARE = "spheresfm_prepare"
JOB_KIND_SPHERESFM_TRANSFORMS = "spheresfm_transforms"

WORKFLOW_JOB_KINDS = {
    JOB_KIND_METASHAPE_PREPROCESS,
    JOB_KIND_CUBEMAP_CONVERSION,
    JOB_KIND_TRANSFORMS_TO_COLMAP,
    JOB_KIND_SPHERESFM_PREFLIGHT,
    JOB_KIND_SPHERESFM_PREPARE,
    JOB_KIND_SPHERESFM_TRANSFORMS,
}


def metashape_preprocess_job(
    *,
    images_dir: str | Path,
    xml_path: str | Path,
    output_dir: str | Path,
    scale: float,
    use_ply: bool,
    ply_path: str | Path | None,
    no_fix_rotation: bool,
    lichtfeld_camera_y180: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_METASHAPE_PREPROCESS,
        "images_dir": str(images_dir),
        "xml_path": str(xml_path),
        "output_dir": str(output_dir),
        "scale": float(scale),
        "use_ply": bool(use_ply),
        "ply_path": str(ply_path) if ply_path else "",
        "no_fix_rotation": bool(no_fix_rotation),
        "lichtfeld_camera_y180": bool(lichtfeld_camera_y180),
    }


def cubemap_conversion_job(
    *,
    input_dir: str | Path,
    output_dir: str | Path,
    views: list[dict[str, Any]],
    fov: float,
    output_scale: float,
    axis_mode: str,
    image_only: bool,
    colmap_rig: bool,
    invert_masks: bool,
    write_images: bool,
    write_masks: bool,
    yaw_offset_per_frame: float,
    output_format: str,
    output_bit_depth: str,
    jpg_quality: int,
    input_json: str = "transforms.json",
    image_dir: str | Path | None = None,
    mask_dir: str | Path | None = None,
    final_orientation: str = "none",
    colmap_rig_name: str = "rig1",
    allow_duplicate: bool = False,
    mask_from_alpha: bool = False,
    workers: str = "auto",
    remap_cache_limit: str = "auto",
    realityscan_xmp: bool = False,
    realityscan_pose_prior: str = "exact",
    realityscan_calibration_prior: str = "exact",
    realityscan_coordinates: str = "auto",
    realityscan_rig_name: str = "stechdrive-cubemap",
    realityscan_include_rig: bool = False,
    realityscan_mask_layers: bool = True,
    realityscan_unposed_scene_dir: str | Path | None = None,
    realityscan_unposed_images: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_CUBEMAP_CONVERSION,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "input_json": str(input_json),
        "image_dir": str(image_dir) if image_dir else "",
        "mask_dir": str(mask_dir) if mask_dir else "",
        "views": [dict(view) for view in views],
        "fov": float(fov),
        "output_scale": float(output_scale),
        "axis_mode": str(axis_mode),
        "image_only": bool(image_only),
        "colmap_rig": bool(colmap_rig),
        "colmap_rig_name": str(colmap_rig_name),
        "allow_duplicate": bool(allow_duplicate),
        "mask_from_alpha": bool(mask_from_alpha),
        "invert_masks": bool(invert_masks),
        "write_images": bool(write_images),
        "write_masks": bool(write_masks),
        "yaw_offset_per_frame": float(yaw_offset_per_frame),
        "output_format": str(output_format),
        "output_bit_depth": str(output_bit_depth),
        "jpg_quality": int(jpg_quality),
        "workers": str(workers),
        "remap_cache_limit": str(remap_cache_limit),
        "final_orientation": str(final_orientation),
        "realityscan_xmp": bool(realityscan_xmp),
        "realityscan_pose_prior": str(realityscan_pose_prior),
        "realityscan_calibration_prior": str(realityscan_calibration_prior),
        "realityscan_coordinates": str(realityscan_coordinates),
        "realityscan_rig_name": str(realityscan_rig_name),
        "realityscan_include_rig": bool(realityscan_include_rig),
        "realityscan_mask_layers": bool(realityscan_mask_layers),
        "realityscan_unposed_scene_dir": str(realityscan_unposed_scene_dir) if realityscan_unposed_scene_dir else "",
        "realityscan_unposed_images": bool(realityscan_unposed_images),
    }


def transforms_to_colmap_job(
    *,
    input_dir: str | Path,
    output_dir: str | Path,
    ply_path: str | Path | None,
    json_name: str = "transforms.json",
    image_prefix: str = "images",
    dataset_root: str | Path | None = None,
    asset_input_dir: str | Path | None = None,
    copy_images: bool = False,
    copy_masks: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_TRANSFORMS_TO_COLMAP,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "ply_path": str(ply_path) if ply_path else "",
        "json_name": str(json_name),
        "image_prefix": str(image_prefix),
        "dataset_root": str(dataset_root) if dataset_root else "",
        "asset_input_dir": str(asset_input_dir) if asset_input_dir else "",
        "copy_images": bool(copy_images),
        "copy_masks": bool(copy_masks),
    }


def spheresfm_preflight_job(
    *,
    colmap: str,
    images_dir: str | Path,
    work_dir: str | Path,
    camera_params: str,
    matcher: str,
    quality_preset: str,
    use_masks: bool,
    loop_detection: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_SPHERESFM_PREFLIGHT,
        "colmap": str(colmap),
        "images_dir": str(images_dir),
        "work_dir": str(work_dir),
        "camera_params": str(camera_params),
        "matcher": str(matcher),
        "quality_preset": str(quality_preset),
        "loop_detection": bool(loop_detection),
        "use_masks": bool(use_masks),
    }


def spheresfm_prepare_job(
    *,
    colmap: str,
    images_dir: str | Path,
    source_masks_dir: str | Path,
    output_masks_dir: str | Path,
    use_masks: bool,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_SPHERESFM_PREPARE,
        "colmap": str(colmap),
        "images_dir": str(images_dir),
        "source_masks_dir": str(source_masks_dir),
        "output_masks_dir": str(output_masks_dir),
        "use_masks": bool(use_masks),
    }


def spheresfm_transforms_job(
    *,
    sparse_dir: str | Path,
    output_dir: str | Path,
    images_dir: str | Path,
    image_path_mode: str,
    opengl_camera: bool = True,
    write_pointcloud: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_JOB_SCHEMA_VERSION,
        "kind": JOB_KIND_SPHERESFM_TRANSFORMS,
        "sparse_dir": str(sparse_dir),
        "output_dir": str(output_dir),
        "images_dir": str(images_dir),
        "image_path_mode": str(image_path_mode),
        "opengl_camera": bool(opengl_camera),
        "write_pointcloud": bool(write_pointcloud),
    }


def write_workflow_job(path: str | Path, payload: dict[str, Any]) -> Path:
    job_path = Path(path)
    validate_workflow_job_payload(payload)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return job_path


def load_workflow_job(path: str | Path, *, expected_kind: str = "") -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Workflow job must be a JSON object: {path}")
    validate_workflow_job_payload(payload)
    if expected_kind and payload["kind"] != expected_kind:
        raise ValueError(f"Workflow job kind must be {expected_kind}: {payload['kind']}")
    return payload


def validate_workflow_job_payload(payload: dict[str, Any]) -> None:
    data = require_mapping(payload, label="workflow")
    require_schema_version(data, expected=WORKFLOW_JOB_SCHEMA_VERSION, label="workflow")
    kind = require_kind(data, allowed=WORKFLOW_JOB_KINDS, label="workflow")
    if kind == JOB_KIND_METASHAPE_PREPROCESS:
        _validate_metashape_preprocess_job(data)
    elif kind == JOB_KIND_CUBEMAP_CONVERSION:
        _validate_cubemap_conversion_job(data)
    elif kind == JOB_KIND_TRANSFORMS_TO_COLMAP:
        _validate_transforms_to_colmap_job(data)
    elif kind == JOB_KIND_SPHERESFM_PREFLIGHT:
        _validate_spheresfm_preflight_job(data)
    elif kind == JOB_KIND_SPHERESFM_PREPARE:
        _validate_spheresfm_prepare_job(data)
    elif kind == JOB_KIND_SPHERESFM_TRANSFORMS:
        _validate_spheresfm_transforms_job(data)


def _validate_metashape_preprocess_job(payload: Mapping[str, Any]) -> None:
    for key in ("images_dir", "xml_path", "output_dir"):
        require_str(payload, key, label="workflow")
    require_bool(payload, "use_ply", label="workflow")
    require_str(payload, "ply_path", label="workflow", allow_empty=not bool(payload.get("use_ply")))
    require_bool(payload, "no_fix_rotation", label="workflow")
    require_finite_float(payload, "scale", label="workflow", min_value=0.0, min_inclusive=False)


def _validate_cubemap_conversion_job(payload: Mapping[str, Any]) -> None:
    for key in (
        "input_dir",
        "output_dir",
        "input_json",
        "axis_mode",
        "output_format",
        "output_bit_depth",
        "workers",
        "remap_cache_limit",
        "final_orientation",
        "realityscan_pose_prior",
        "realityscan_calibration_prior",
        "realityscan_coordinates",
        "realityscan_rig_name",
    ):
        require_str(payload, key, label="workflow")
    require_str(payload, "image_dir", label="workflow", allow_empty=True)
    require_str(payload, "mask_dir", label="workflow", allow_empty=True)
    require_str(payload, "colmap_rig_name", label="workflow", allow_empty=False)
    require_str(payload, "realityscan_unposed_scene_dir", label="workflow", allow_empty=True)
    require_views(payload, label="workflow")
    require_finite_float(payload, "fov", label="workflow", min_value=0.0, max_value=180.0, min_inclusive=False, max_inclusive=False)
    require_finite_float(payload, "output_scale", label="workflow", min_value=0.0, max_value=1.0, min_inclusive=False)
    require_finite_float(payload, "yaw_offset_per_frame", label="workflow")
    require_int_range(payload, "jpg_quality", label="workflow", min_value=1, max_value=100)
    for key in (
        "image_only",
        "colmap_rig",
        "allow_duplicate",
        "mask_from_alpha",
        "invert_masks",
        "write_images",
        "write_masks",
        "realityscan_xmp",
        "realityscan_include_rig",
        "realityscan_mask_layers",
        "realityscan_unposed_images",
    ):
        require_bool(payload, key, label="workflow")


def _validate_transforms_to_colmap_job(payload: Mapping[str, Any]) -> None:
    for key in ("input_dir", "output_dir", "json_name", "image_prefix"):
        require_str(payload, key, label="workflow", allow_empty=key == "image_prefix")
    require_str(payload, "ply_path", label="workflow", allow_empty=True)
    require_str(payload, "dataset_root", label="workflow", allow_empty=True)
    require_str(payload, "asset_input_dir", label="workflow", allow_empty=True)
    require_bool(payload, "copy_images", label="workflow")
    require_bool(payload, "copy_masks", label="workflow")


def _validate_spheresfm_preflight_job(payload: Mapping[str, Any]) -> None:
    for key in ("colmap", "images_dir", "work_dir", "camera_params"):
        require_str(payload, key, label="workflow")
    matcher = require_str(payload, "matcher", label="workflow")
    if matcher not in SPHERESFM_MATCHERS:
        raise ValueError(f"Unsupported workflow matcher: {matcher}")
    quality_preset = require_str(payload, "quality_preset", label="workflow")
    if quality_preset not in SPHERESFM_QUALITY_PRESETS:
        raise ValueError(f"Unsupported workflow quality preset: {quality_preset}")
    require_bool(payload, "use_masks", label="workflow")
    if "loop_detection" in payload:
        require_bool(payload, "loop_detection", label="workflow")


def _validate_spheresfm_prepare_job(payload: Mapping[str, Any]) -> None:
    for key in ("colmap", "images_dir", "source_masks_dir", "output_masks_dir"):
        require_str(payload, key, label="workflow")
    require_bool(payload, "use_masks", label="workflow")


def _validate_spheresfm_transforms_job(payload: Mapping[str, Any]) -> None:
    for key in ("sparse_dir", "output_dir", "images_dir", "image_path_mode"):
        require_str(payload, key, label="workflow")
    require_bool(payload, "opengl_camera", label="workflow")
    require_bool(payload, "write_pointcloud", label="workflow")
