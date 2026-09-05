"""Command builders for Step 4 cubemap export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.app_job import AppJob, dataset_app_job, sfm_app_job
from core.colmap_cli import build_colmap_command
from core.dataset_job_spec import load_dataset_job
from core.sfm_job_spec import load_sfm_job
from core.spheresfm_cli_contract import (
    spheresfm_feature_options,
    spheresfm_mapper_options,
    spheresfm_matcher_subcommand,
    spheresfm_matching_options,
    spheresfm_sequential_options,
)
from gui.common.runner_types import ExternalCommandQueue


@dataclass(frozen=True)
class MetashapeNerfCommand:
    job: Path


@dataclass(frozen=True)
class ColmapMixedPrepareCommand:
    job: Path


@dataclass(frozen=True)
class ColmapNormalFeatureGroup:
    image_list: Path
    camera_model: str
    camera_params: str = ""
    phase: str = ""


@dataclass(frozen=True)
class ColmapRigFeatureGroup:
    image_list: Path
    camera_params: str
    phase: str = ""


@dataclass(frozen=True)
class ColmapSfmCommand:
    colmap: str
    glomap: str
    rig_dir: Path
    images_dir: Path
    masks_dir: Path
    database: Path
    sparse: Path
    camera_params: str
    writes_images: bool
    writes_masks: bool
    matcher: str
    mapper: str
    use_existing_masks: bool = True
    run_rig_feature: bool = True
    run_rig_config: bool = True
    run_normal_feature: bool = False
    rig_image_list: Path | None = None
    normal_image_list: Path | None = None
    normal_camera_model: str = "SIMPLE_RADIAL"
    rig_feature_groups: tuple[ColmapRigFeatureGroup, ...] = ()
    normal_feature_groups: tuple[ColmapNormalFeatureGroup, ...] = ()
    skip_rig_same_frame: bool = False


@dataclass(frozen=True)
class SphereSfmCommand:
    colmap: str
    images_dir: Path
    prepared_masks_dir: Path
    database: Path
    sparse: Path
    camera_params: str
    use_masks: bool
    matcher: str
    quality_preset: str
    loop_detection: bool = False


def build_metashape_nerf_cmd(options: MetashapeNerfCommand) -> AppJob:
    return dataset_app_job(load_dataset_job(options.job), options.job)


def build_colmap_mixed_prepare_cmd(options: ColmapMixedPrepareCommand) -> AppJob:
    return sfm_app_job(load_sfm_job(options.job), options.job)


def build_colmap_sfm_commands(options: ColmapSfmCommand) -> ExternalCommandQueue:
    if not options.writes_images and not options.images_dir.is_dir():
        raise ValueError(f"COLMAP Rig画像フォルダが見つかりません: {options.images_dir}")

    options.sparse.mkdir(parents=True, exist_ok=True)
    rig_config = options.rig_dir / "rig_config.json"

    steps: ExternalCommandQueue = []
    has_mixed_feature_split = options.run_rig_feature and options.run_normal_feature

    if options.run_rig_feature and options.rig_feature_groups:
        for index, group in enumerate(options.rig_feature_groups, start=1):
            feature_cmd = _rig_feature_cmd(
                options,
                camera_params=group.camera_params or options.camera_params,
                image_list=group.image_list,
            )
            if group.phase:
                phase = group.phase
            elif len(options.rig_feature_groups) == 1:
                phase = "colmap_feature_rig" if has_mixed_feature_split else "colmap_feature"
            else:
                phase = f"colmap_feature_rig_{index}"
            steps.append((phase, feature_cmd))
    elif options.run_rig_feature:
        feature_cmd = _rig_feature_cmd(options, camera_params=options.camera_params, image_list=options.rig_image_list)
        phase = "colmap_feature_rig" if has_mixed_feature_split else "colmap_feature"
        steps.append((phase, feature_cmd))

    if options.run_rig_config:
        rig_cmd = build_colmap_command(
            options.colmap,
            "rig_configurator",
            "--database_path",
            str(options.database),
            "--rig_config_path",
            str(rig_config),
        )
        steps.append(("colmap_rig_config", rig_cmd))

    if options.run_normal_feature and options.normal_feature_groups:
        for index, group in enumerate(options.normal_feature_groups, start=1):
            normal_cmd = _normal_feature_cmd(options, group.camera_model, image_list=group.image_list)
            if group.camera_params:
                normal_cmd.extend(["--ImageReader.camera_params", group.camera_params])
            phase = group.phase or ("colmap_feature_normal" if len(options.normal_feature_groups) == 1 else f"colmap_feature_normal_{index}")
            steps.append((phase, normal_cmd))
    elif options.run_normal_feature:
        normal_cmd = _normal_feature_cmd(options, options.normal_camera_model, image_list=options.normal_image_list)
        steps.append(("colmap_feature_normal", normal_cmd))

    matcher_name = "exhaustive_matcher" if options.matcher == "exhaustive" else "sequential_matcher"
    matcher_cmd = build_colmap_command(
        options.colmap,
        matcher_name,
        "--database_path",
        str(options.database),
    )
    if options.run_rig_config:
        matcher_cmd.extend([
            "--FeatureMatching.rig_verification", "1",
            "--FeatureMatching.skip_image_pairs_in_same_frame", "1" if options.skip_rig_same_frame else "0",
        ])

    if options.mapper == "global":
        mapper_cmd = build_colmap_command(
            options.colmap,
            "global_mapper",
            "--database_path",
            str(options.database),
            "--image_path",
            str(options.images_dir),
            "--output_path",
            str(options.sparse),
            "--GlobalMapper.multiple_models",
            "0",
        )
    elif options.mapper == "glomap":
        mapper_cmd = [
            options.glomap,
            "mapper",
            "--database_path",
            str(options.database),
            "--image_path",
            str(options.images_dir),
            "--output_path",
            str(options.sparse),
        ]
    else:
        mapper_cmd = build_colmap_command(
            options.colmap,
            "mapper",
            "--database_path",
            str(options.database),
            "--image_path",
            str(options.images_dir),
            "--output_path",
            str(options.sparse),
        )
    if options.run_rig_config and options.mapper != "glomap":
        prefix = "GlobalMapper" if options.mapper == "global" else "Mapper"
        sensor_option = "refine_sensor_from_rig" if options.mapper == "global" else "ba_refine_sensor_from_rig"
        mapper_cmd.extend([f"--{prefix}.{sensor_option}", "0"])
        # Global COLMAP has no per-camera constant-intrinsics CLI list.
        # Keep ordinary-photo calibration available in mixed projects.
        if not options.run_normal_feature:
            for parameter in ("focal_length", "principal_point", "extra_params"):
                mapper_cmd.extend([f"--{prefix}.ba_refine_{parameter}", "0"])

    steps.extend(
        [
            ("colmap_match", matcher_cmd),
            ("colmap_mapper", mapper_cmd),
        ]
    )
    return steps


def _rig_feature_cmd(
    options: ColmapSfmCommand,
    *,
    camera_params: str,
    image_list: Path | None,
) -> list[str]:
    cmd = build_colmap_command(
        options.colmap,
        "feature_extractor",
        "--database_path",
        str(options.database),
        "--image_path",
        str(options.images_dir),
        "--ImageReader.single_camera_per_folder",
        "1",
        "--ImageReader.camera_model",
        "PINHOLE",
        "--ImageReader.camera_params",
        camera_params,
        "--SiftExtraction.max_num_features",
        "8192",
    )
    if image_list is not None:
        cmd.extend(["--image_list_path", str(image_list)])
    if _should_use_colmap_masks(options):
        cmd.extend(["--ImageReader.mask_path", str(options.masks_dir)])
    return cmd


def _normal_feature_cmd(
    options: ColmapSfmCommand,
    camera_model: str,
    *,
    image_list: Path | None,
) -> list[str]:
    cmd = build_colmap_command(
        options.colmap,
        "feature_extractor",
        "--database_path",
        str(options.database),
        "--image_path",
        str(options.images_dir),
        "--ImageReader.single_camera_per_folder",
        "1",
        "--ImageReader.camera_model",
        camera_model,
    )
    if image_list is not None:
        cmd.extend(["--image_list_path", str(image_list)])
    if _should_use_colmap_masks(options):
        cmd.extend(["--ImageReader.mask_path", str(options.masks_dir)])
    return cmd


def _should_use_colmap_masks(options: ColmapSfmCommand) -> bool:
    return options.writes_masks or (options.use_existing_masks and options.masks_dir.is_dir())


def build_spheresfm_commands(options: SphereSfmCommand) -> ExternalCommandQueue:
    options.sparse.mkdir(parents=True, exist_ok=True)
    options.database.parent.mkdir(parents=True, exist_ok=True)

    database_cmd = build_colmap_command(
        options.colmap,
        "database_creator",
        "--database_path",
        str(options.database),
    )

    feature_cmd = build_colmap_command(
        options.colmap,
        "feature_extractor",
        "--database_path",
        str(options.database),
        "--image_path",
        str(options.images_dir),
        "--ImageReader.camera_model",
        "EQUIRECTANGULAR",
        "--ImageReader.camera_params",
        options.camera_params,
        "--ImageReader.single_camera",
        "1",
    )
    if options.use_masks:
        feature_cmd.extend(["--ImageReader.mask_path", str(options.prepared_masks_dir)])
    input_size = tuple(int(value.strip()) for value in options.camera_params.split(","))
    feature_cmd.extend(spheresfm_feature_options(options.quality_preset, input_size))
    matcher_cmd = build_colmap_command(
        options.colmap, spheresfm_matcher_subcommand(options.matcher),
        "--database_path", str(options.database),
        *spheresfm_matching_options(options.quality_preset),
        *spheresfm_sequential_options(options.loop_detection),
    )

    mapper_cmd = build_colmap_command(
        options.colmap,
        "mapper",
        "--database_path",
        str(options.database),
        "--image_path",
        str(options.images_dir),
        "--output_path",
        str(options.sparse),
    )
    mapper_cmd.extend(spheresfm_mapper_options(options.quality_preset))

    return [
        ("spheresfm_database", database_cmd),
        ("spheresfm_feature", feature_cmd),
        ("spheresfm_match", matcher_cmd),
        ("spheresfm_mapper", mapper_cmd),
    ]


def views_config_payload(views: list[dict]) -> dict:
    return {
        "fov": 90.0,
        "views": [
            {"name": v["name"], "yaw": float(v["yaw"]), "pitch": float(v["pitch"]), "enabled": bool(v["enabled"])}
            for v in views
        ],
    }


def write_views_config(output_dir: Path, views: list[dict]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "views_config.json"
    path.write_text(json.dumps(views_config_payload(views), indent=2), encoding="utf-8")
    return path
