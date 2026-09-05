import json
from pathlib import Path

from core.spheresfm_project import prepare_masks
from gui.steps.cubemap_commands import (
    ColmapRigFeatureGroup,
    ColmapSfmCommand,
    SphereSfmCommand,
    build_colmap_sfm_commands,
    build_spheresfm_commands,
    write_views_config,
)
from gui.steps.mask_commands import MaskCommandContext, build_sam31_prompt_cmd
from gui.steps.mask_image_import import import_external_images


def _mask_context(base_dir: Path) -> MaskCommandContext:
    return MaskCommandContext(
        python_executable="python.exe",
        base_dir=base_dir,
        projection="equirect",
        quality="high",
        yolo_expand="2",
        sky_inference_size="768",
        sky_min_score="0.25",
        sky_min_area_ratio="0.01",
        sky_top_connected=False,
        stitch_boundary_width=5.0,
        stitch_workers="4",
        overexposure_threshold="254",
        overexposure_dilate="1",
        mask_merge_mode="replace",
    )


def test_mask_command_builder_keeps_sam31_safe_batch_directory_only(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image_file = images / "frame_0001.jpg"
    image_file.write_bytes(b"image")
    masks = tmp_path / "masks"

    dir_cmd = build_sam31_prompt_cmd(
        _mask_context(tmp_path),
        images,
        masks,
        prompts=["person", "sky"],
    )
    file_cmd = build_sam31_prompt_cmd(
        _mask_context(tmp_path),
        image_file,
        masks,
        prompts=["person"],
    )

    assert dir_cmd[0:4] == ["python.exe", "-u", "-m", "core.sky_mask"]
    assert dir_cmd[dir_cmd.index("--backend") + 1] == "sam31"
    assert "--replace" in dir_cmd
    assert "--safe-batch" in dir_cmd
    assert "--safe-batch" not in file_cmd


def test_external_image_import_helper_skips_existing_names(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "scene" / "images"
    (source / "a.JPG").write_bytes(b"a")
    (source / "b.png").write_bytes(b"b")
    (source / "ignore.txt").write_text("ignore", encoding="utf-8")

    assert import_external_images(source, target) == (2, 0)
    assert import_external_images(source, target) == (0, 2)
    assert sorted(path.name for path in target.iterdir()) == ["a.JPG", "b.png"]


def test_cubemap_views_config_writes_normalized_payload(tmp_path: Path) -> None:
    views_json = write_views_config(
        tmp_path / "output",
        [{"name": "px", "yaw": 0, "pitch": 0, "enabled": True}],
    )

    payload = json.loads(views_json.read_text(encoding="utf-8"))
    assert payload["views"][0] == {"name": "px", "yaw": 0.0, "pitch": 0.0, "enabled": True}


def test_colmap_sfm_builder_keeps_mapper_contract(tmp_path: Path) -> None:
    images = tmp_path / "rig" / "images"
    masks = tmp_path / "rig" / "masks"
    sparse = tmp_path / "rig" / "sparse"
    images.mkdir(parents=True)

    commands = build_colmap_sfm_commands(
        ColmapSfmCommand(
            colmap="colmap.exe",
            glomap="glomap.exe",
            rig_dir=tmp_path / "rig",
            images_dir=images,
            masks_dir=masks,
            database=tmp_path / "rig" / "database.db",
            sparse=sparse,
            camera_params="16,16,8,8",
            writes_images=True,
            writes_masks=False,
            matcher="exhaustive",
            mapper="incremental",
        )
    )

    assert [phase for phase, _cmd in commands] == [
        "colmap_feature",
        "colmap_rig_config",
        "colmap_match",
        "colmap_mapper",
    ]
    assert commands[2][1][1] == "exhaustive_matcher"
    assert commands[3][1][0:2] == ["colmap.exe", "mapper"]
    assert sparse.is_dir()


def test_colmap_sfm_builder_runs_rig_feature_groups_with_group_camera_params(tmp_path: Path) -> None:
    images = tmp_path / "rig" / "images"
    masks = tmp_path / "rig" / "masks"
    sparse = tmp_path / "rig" / "sparse"
    images.mkdir(parents=True)
    list_a = tmp_path / "rig" / "rig_image_list_rig1.txt"
    list_b = tmp_path / "rig" / "rig_image_list_rig2.txt"
    list_a.write_text("rig1/cam01/frame_00001.jpg\n", encoding="utf-8")
    list_b.write_text("rig2/cam01/frame_00001.jpg\n", encoding="utf-8")

    commands = build_colmap_sfm_commands(
        ColmapSfmCommand(
            colmap="colmap.exe",
            glomap="glomap.exe",
            rig_dir=tmp_path / "rig",
            images_dir=images,
            masks_dir=masks,
            database=tmp_path / "rig" / "database.db",
            sparse=sparse,
            camera_params="fallback",
            writes_images=True,
            writes_masks=False,
            matcher="sequential",
            mapper="incremental",
            rig_feature_groups=(
                ColmapRigFeatureGroup(image_list=list_a, camera_params="8,8,7.5,7.5"),
                ColmapRigFeatureGroup(image_list=list_b, camera_params="10,10,9.5,9.5"),
            ),
        )
    )

    assert [phase for phase, _cmd in commands][:3] == [
        "colmap_feature_rig_1",
        "colmap_feature_rig_2",
        "colmap_rig_config",
    ]
    first = commands[0][1]
    second = commands[1][1]
    assert first[first.index("--image_list_path") + 1] == str(list_a)
    assert first[first.index("--ImageReader.camera_params") + 1] == "8,8,7.5,7.5"
    assert second[second.index("--image_list_path") + 1] == str(list_b)
    assert second[second.index("--ImageReader.camera_params") + 1] == "10,10,9.5,9.5"


def test_spheresfm_builder_uses_spherical_camera_and_mask_path(tmp_path: Path) -> None:
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    prepared_masks = tmp_path / "project" / "masks_colmap"
    sparse = tmp_path / "project" / "sparse"
    images.mkdir()
    masks.mkdir()

    commands = build_spheresfm_commands(
        SphereSfmCommand(
            colmap="spheresfm_colmap.exe",
            images_dir=images,
            prepared_masks_dir=prepared_masks,
            database=tmp_path / "project" / "database.db",
            sparse=sparse,
            camera_params="64,32",
            use_masks=True,
            matcher="spatial",
            quality_preset="quality",
        )
    )

    assert [phase for phase, _cmd in commands] == [
        "spheresfm_database",
        "spheresfm_feature",
        "spheresfm_match",
        "spheresfm_mapper",
    ]
    feature_cmd = commands[1][1]
    assert feature_cmd[0:2] == ["spheresfm_colmap.exe", "feature_extractor"]
    assert feature_cmd[feature_cmd.index("--ImageReader.camera_model") + 1] == "EQUIRECTANGULAR"
    assert feature_cmd[feature_cmd.index("--ImageReader.camera_params") + 1] == "64,32"
    assert feature_cmd[feature_cmd.index("--ImageReader.mask_path") + 1] == str(prepared_masks)
    assert feature_cmd[feature_cmd.index("--FeatureExtraction.max_image_size") + 1] == "64"
    assert feature_cmd[feature_cmd.index("--SiftExtraction.max_num_features") + 1] == "32768"
    assert commands[2][1][commands[2][1].index("--FeatureMatching.guided_matching") + 1] == "0"
    assert commands[2][1][1] == "sequential_matcher"
    assert "--Mapper.sphere_camera" not in commands[3][1]
    assert commands[3][1][commands[3][1].index("--Mapper.multiple_models") + 1] == "0"
    assert "--Mapper.ba_global_max_num_iterations" not in commands[3][1]
    assert "--Mapper.ba_global_images_ratio" not in commands[3][1]
    assert sparse.is_dir()


def test_spheresfm_standard_preset_uses_colmap_mapper_defaults(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    commands = build_spheresfm_commands(
        SphereSfmCommand(
            colmap="colmap.exe",
            images_dir=images,
            prepared_masks_dir=tmp_path / "masks_colmap",
            database=tmp_path / "project" / "database.db",
            sparse=tmp_path / "project" / "sparse",
            camera_params="64,32",
            use_masks=False,
            matcher="sequential",
            quality_preset="standard",
        )
    )

    mapper_cmd = commands[-1][1]
    assert "--Mapper.ba_global_frames_ratio" not in mapper_cmd
    assert "--Mapper.ba_global_images_ratio" not in mapper_cmd


def test_prepare_spheresfm_masks_converts_to_colmap_extension_names(tmp_path: Path) -> None:
    images = tmp_path / "images"
    source_masks = tmp_path / "masks"
    output_masks = tmp_path / "colmap_equirect" / "masks_colmap"
    (images / "sub").mkdir(parents=True)
    (source_masks / "sub").mkdir(parents=True)
    (images / "frame_0001.jpg").write_bytes(b"jpg")
    (images / "sub" / "frame_0002.png").write_bytes(b"png")
    (source_masks / "frame_0001.png").write_bytes(b"mask1")
    (source_masks / "sub" / "frame_0002.png.png").write_bytes(b"mask2")

    copied, missing = prepare_masks(images, source_masks, output_masks)

    assert (copied, missing) == (2, 0)
    assert (output_masks / "frame_0001.jpg.png").read_bytes() == b"mask1"
    assert (output_masks / "sub" / "frame_0002.png.png").read_bytes() == b"mask2"
