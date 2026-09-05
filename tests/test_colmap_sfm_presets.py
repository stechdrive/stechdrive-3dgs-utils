from dataclasses import replace
from pathlib import Path

import pytest

from core.spheresfm_cli_contract import (
    normalize_spheresfm_preset,
    required_spheresfm_options,
    spheresfm_feature_options,
)
from core.workflow_job_spec import spheresfm_preflight_job, validate_workflow_job_payload
from gui.steps.cubemap_commands import (
    ColmapSfmCommand,
    SphereSfmCommand,
    build_colmap_sfm_commands,
    build_spheresfm_commands,
)


def _value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


@pytest.mark.parametrize("width,height", [(7680, 3840), (8192, 4096), (3840, 1920), (64, 32)])
@pytest.mark.parametrize("preset,divisor,features", [
    ("standard", 1, 32768), ("light", 2, 16384), ("lightest", 4, 8192),
])
@pytest.mark.parametrize("loop_detection", [False, True])
def test_erp_budgets_and_execution_match_preflight_contract(
    tmp_path: Path, width: int, height: int, preset: str, divisor: int, features: int, loop_detection: bool,
) -> None:
    options = SphereSfmCommand(
        "colmap.exe", tmp_path / "images", tmp_path / "masks", tmp_path / "database.db",
        tmp_path / "sparse", f"{width},{height}", True, "sequential", preset, loop_detection,
    )
    commands = dict(build_spheresfm_commands(options))
    feature = commands["spheresfm_feature"]
    match = commands["spheresfm_match"]
    mapper = commands["spheresfm_mapper"]
    assert _value(feature, "--ImageReader.camera_params") == f"{width},{height}"
    assert _value(feature, "--FeatureExtraction.max_image_size") == str(width // divisor)
    assert _value(feature, "--SiftExtraction.max_num_features") == str(features)
    assert _value(match, "--FeatureMatching.max_num_matches") == str(features)
    assert _value(match, "--SequentialMatching.loop_detection") == str(int(loop_detection))
    assert _value(match, "--SequentialMatching.overlap") == "10"
    assert _value(match, "--FeatureMatching.guided_matching") == "0"
    assert match[1] == "sequential_matcher"
    assert mapper == dict(build_spheresfm_commands(replace(options, quality_preset="standard")))["spheresfm_mapper"]
    required = required_spheresfm_options(
        matcher="sequential", quality_preset=preset, use_masks=True, loop_detection=loop_detection,
    )
    for command in (feature, match, mapper):
        assert set(required[command[1]]) == {argument for argument in command if argument.startswith("--")}


@pytest.mark.parametrize("size", [(0, 10), (-1, 2), (10,), (1.5, 2)])
def test_erp_rejects_invalid_dimensions(size) -> None:
    with pytest.raises(ValueError):
        spheresfm_feature_options("standard", size)


def test_erp_rejects_unknown_preset() -> None:
    with pytest.raises(ValueError):
        normalize_spheresfm_preset("unlimited")


def test_loop_detection_job_roundtrip_and_validation(tmp_path: Path) -> None:
    job = spheresfm_preflight_job(
        colmap="colmap.exe", images_dir=tmp_path, work_dir=tmp_path / "work",
        camera_params="7680,3840", matcher="sequential", quality_preset="light",
        use_masks=False, loop_detection=True,
    )
    validate_workflow_job_payload(job)
    assert job["loop_detection"] is True
    job["loop_detection"] = "false"
    with pytest.raises(ValueError):
        validate_workflow_job_payload(job)
    del job["loop_detection"]
    validate_workflow_job_payload(job)  # Old saved jobs have no loop setting.


@pytest.mark.parametrize("mapper", ["incremental", "global", "glomap"])
@pytest.mark.parametrize("normal,rig", [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize("skip_same_frame", [False, True])
def test_rig_constraints_do_not_freeze_ordinary_cameras(
    tmp_path: Path, mapper: str, normal: bool, rig: bool, skip_same_frame: bool,
) -> None:
    options = ColmapSfmCommand(
        "colmap.exe", "glomap.exe", tmp_path, tmp_path / "images", tmp_path / "masks",
        tmp_path / "database.db", tmp_path / "sparse", "960,960,959.5,959.5",
        True, False, "sequential", mapper, run_rig_feature=rig,
        run_rig_config=rig, run_normal_feature=normal, skip_rig_same_frame=skip_same_frame,
    )
    commands = dict(build_colmap_sfm_commands(options))
    match = commands["colmap_match"]
    mapping = commands["colmap_mapper"]
    if rig:
        assert _value(match, "--FeatureMatching.rig_verification") == "1"
        assert _value(match, "--FeatureMatching.skip_image_pairs_in_same_frame") == str(int(skip_same_frame))
        feature = commands["colmap_feature_rig" if normal else "colmap_feature"]
        assert _value(feature, "--SiftExtraction.max_num_features") == "8192"
    else:
        assert "--FeatureMatching.rig_verification" not in match
    if rig and mapper != "glomap":
        prefix = "GlobalMapper" if mapper == "global" else "Mapper"
        sensor = "refine_sensor_from_rig" if mapper == "global" else "ba_refine_sensor_from_rig"
        assert _value(mapping, f"--{prefix}.{sensor}") == "0"
        for parameter in ("focal_length", "principal_point", "extra_params"):
            flag = f"--{prefix}.ba_refine_{parameter}"
            if normal:
                assert flag not in mapping
            else:
                assert _value(mapping, flag) == "0"
    else:
        assert not any("refine_" in arg for arg in mapping)
