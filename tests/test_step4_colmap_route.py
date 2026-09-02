from __future__ import annotations

from tests.helpers.step4 import (
    STEP4_SETTINGS_VERSION,
    AppJob,
    CubemapStep,
    Path,
    QMessageBox,
    _app,
    _ready_step,
    _workflow_job,
    _write_test_image,
    i18n,
    json,
    pytest,
    save_normal_camera_default,
    source_image_sets_path,
    step4_export_settings_path,
    step4_meta_dir,
)


def test_colmap_export_method_uses_image_only_conversion(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))

    step._set_export_method("colmap")

    assert not step.metashape_section.isVisible()
    assert step.export_method_buttons["colmap"].isChecked()
    assert step.yaw_per_frame_edit.value() == 0.0
    assert not step.yaw_per_frame_edit.isEnabled()
    assert step.yaw_per_frame_edit.toolTip() == i18n.t("YAW_OFFSET_PER_FRAME_COLMAP_HINT")
    commands = step.build_commands()
    assert [phase for phase, _cmd in commands] == ["colmap_rig_export"]
    cmd = commands[0][1]
    job = _workflow_job(cmd)
    assert job["image_only"] is True
    assert job["colmap_rig"] is True
    assert job["yaw_offset_per_frame"] == 0.0
    assert job["final_orientation"] == "none"
    assert job["write_images"] is True
    assert job["write_masks"] is True


def test_colmap_export_method_prepares_normal_only_project(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "perspective_0001.jpg", size=(40, 30))
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == ["colmap_mixed_prepare"]
    cmd = commands[0][1]
    assert isinstance(cmd, AppJob)
    assert cmd.job_type == "sfm"
    job = cmd.payload
    assert job["scene_dir"] == str(tmp_path)
    assert job["output_dir"] == str(tmp_path / "output")
    assert job["views"]


def test_colmap_export_method_prepares_multi_resolution_erp_project(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "pano_large.jpg", size=(64, 32))
    _write_test_image(images / "pano_small.jpg", size=(32, 16))
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == ["colmap_mixed_prepare"]
    cmd = commands[0][1]
    assert isinstance(cmd, AppJob)
    assert cmd.job_type == "sfm"


def test_colmap_export_can_queue_mixed_erp_and_normal_sfm(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "pano_0001.jpg", size=(64, 32))
    _write_test_image(images / "perspective_0001.jpg", size=(40, 30))
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_mixed_prepare",
        "colmap_feature_rig",
        "colmap_rig_config",
        "colmap_feature_normal",
        "colmap_match",
        "colmap_mapper",
    ]
    assert isinstance(commands[0][1], AppJob)
    assert commands[0][1].job_type == "sfm"
    rig_feature = commands[1][1]
    normal_feature = commands[3][1]
    assert rig_feature[1] == "feature_extractor"
    assert rig_feature[rig_feature.index("--ImageReader.camera_model") + 1] == "PINHOLE"
    assert rig_feature[rig_feature.index("--image_list_path") + 1] == str(
        tmp_path / "output" / "colmap_rig" / "rig_image_list.txt"
    )
    assert normal_feature[1] == "feature_extractor"
    assert normal_feature[normal_feature.index("--ImageReader.camera_model") + 1] == "SIMPLE_RADIAL"
    assert normal_feature[normal_feature.index("--image_list_path") + 1] == str(
        tmp_path / "output" / "colmap_rig" / "normal_image_list_unknown_40x30_simple_radial.txt"
    )


def test_colmap_export_can_queue_normal_only_sfm_without_rig_config(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "perspective_0001.jpg", size=(40, 30))
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_mixed_prepare",
        "colmap_feature_normal",
        "colmap_match",
        "colmap_mapper",
    ]
    assert isinstance(commands[0][1], AppJob)
    assert commands[0][1].job_type == "sfm"
    assert all(phase != "colmap_rig_config" for phase, _cmd in commands)
    normal_feature = commands[1][1]
    assert normal_feature[normal_feature.index("--ImageReader.camera_model") + 1] == "SIMPLE_RADIAL"
    assert "--Mapper.ba_refine_sensor_from_rig" not in commands[-1][1]


def test_colmap_export_uses_normal_camera_metadata_for_feature_group(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "perspective_0001.jpg", size=(40, 30))
    source_sets = source_image_sets_path(tmp_path)
    source_sets.parent.mkdir(parents=True, exist_ok=True)
    source_sets.write_text(
        json.dumps(
            {
                "version": 1,
                "image_sets": [
                    {
                        "id": "cam_a",
                        "source_type": "image_sequence",
                        "projection": "normal",
                        "files": [
                            {
                                "scene_path": "images/perspective_0001.jpg",
                                "camera": {
                                    "model": "PINHOLE",
                                    "params": [20.0, 21.0, 19.5, 14.5],
                                    "source": "manual",
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    normal_feature = commands[1][1]
    assert normal_feature[normal_feature.index("--ImageReader.camera_model") + 1] == "PINHOLE"
    assert normal_feature[normal_feature.index("--ImageReader.camera_params") + 1] == "20,21,19.5,14.5"


def test_colmap_export_uses_normal_camera_default_for_feature_group(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "perspective_0001.jpg", size=(40, 30))
    save_normal_camera_default(
        tmp_path,
        camera_model="PINHOLE",
        camera_params=(20.0, 21.0, 19.5, 14.5),
        camera_source="test_default",
    )
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    normal_feature = commands[1][1]
    assert normal_feature[normal_feature.index("--ImageReader.camera_model") + 1] == "PINHOLE"
    assert normal_feature[normal_feature.index("--ImageReader.camera_params") + 1] == "20,21,19.5,14.5"


def test_colmap_export_method_restores_yaw_step_when_leaving_route(tmp_path: Path) -> None:
    step = _ready_step(tmp_path)
    step.yaw_per_frame_edit.setValue(45.0)

    step._set_export_method("colmap")

    assert step.yaw_per_frame_edit.value() == 0.0
    assert not step.yaw_per_frame_edit.isEnabled()

    step._set_export_method("metashape")

    assert step.yaw_per_frame_edit.isEnabled()
    assert step.yaw_per_frame_edit.value() == 45.0
    assert step.yaw_per_frame_edit.toolTip() == i18n.t("YAW_OFFSET_PER_FRAME_HINT")


def test_colmap_export_method_validates_images_before_resetting_output(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "output"
    output.mkdir(parents=True)
    old_file = output / "old.txt"
    old_file.write_text("old", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("confirmation should not open")),
    )

    with pytest.raises(ValueError, match="画像フォルダ"):
        step.build_commands()

    assert old_file.is_file()


def test_colmap_export_finalize_writes_export_method_settings(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")

    commands = step.build_commands()
    assert [phase for phase, _cmd in commands] == ["colmap_rig_export"]
    step._finalize_bundle()

    settings_path = step4_export_settings_path(tmp_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["export_method"] == "colmap"
    assert settings["conversion"]["no_image"] is False
    assert settings["conversion"]["export_colmap"] is False
    assert settings["conversion"]["yaw_offset_per_frame"] == 0.0
    assert settings["colmap_rig"]["enabled"] is True
    assert settings["colmap_rig"]["dir"] == str(tmp_path / "output" / "colmap_rig")
    assert settings["colmap_rig"]["project_dir"] == str(tmp_path / "output" / "colmap_rig")

    manifest_path = step4_meta_dir(tmp_path) / "sfm" / "stechdrive_colmap_project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["export_type"] == "colmap_project"
    assert manifest["project_dir"] == str(tmp_path / "output" / "colmap_rig")
    assert manifest["ready_for_import"] is False


def test_colmap_export_manifest_marks_sparse_project_ready(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    sparse_model = tmp_path / "output" / "colmap_rig" / "sparse" / "0"
    sparse_model.mkdir(parents=True)
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (sparse_model / name).write_bytes(b"model")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")

    step._finalize_bundle()

    manifest = json.loads(
        (step4_meta_dir(tmp_path) / "sfm" / "stechdrive_colmap_project.json").read_text(encoding="utf-8")
    )
    assert manifest["ready_for_import"] is True
    assert manifest["sparse_model_dir"] == "sparse/0"


def test_colmap_export_method_displays_colmap_project_folder_summary(tmp_path: Path) -> None:
    _app()
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))

    assert step.cubemap_path_summary_value.full_text() == "output/metashape_cubemap/"

    step._set_export_method("colmap")

    assert step.sfm_path_summary_kind.text() == i18n.t("STEP4_SUMMARY_INPUT")
    assert step.sfm_path_summary_value.full_text() == "output/colmap_rig/sparse/"

    step.set_pipeline_stage_intent("sfm", True)

    assert step.sfm_path_summary_kind.text() == i18n.t("STEP4_SUMMARY_OUTPUT")
    assert step.sfm_path_summary_value.full_text() == "output/colmap_rig/"
    assert step.cubemap_path_summary_value.full_text() == "output/colmap_rig/"


def test_colmap_export_can_queue_colmap_sfm_with_custom_executable(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_rig_export",
        "colmap_feature",
        "colmap_rig_config",
        "colmap_match",
        "colmap_mapper",
    ]
    assert commands[1][1][0] == str(fake_colmap)
    assert commands[1][1][1] == "feature_extractor"
    assert "--ImageReader.single_camera_per_folder" in commands[1][1]
    assert commands[1][1][commands[1][1].index("--ImageReader.camera_params") + 1] == "10,10,9.5,9.5"
    assert commands[2][1][1] == "rig_configurator"
    assert commands[3][1][1] == "sequential_matcher"
    assert commands[4][1][1] == "global_mapper"


def test_colmap_conversion_sfm_does_not_reuse_stale_masks_when_mask_output_is_off(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    stale_masks = tmp_path / "output" / "colmap_rig" / "masks" / "rig1" / "cam01"
    stale_masks.mkdir(parents=True)
    _write_test_image(stale_masks / "frame_00001.jpg.png")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))
    step.export_masks_cb.setChecked(False)

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_rig_export",
        "colmap_feature",
        "colmap_rig_config",
        "colmap_match",
        "colmap_mapper",
    ]
    feature_cmd = commands[1][1]
    assert "--ImageReader.mask_path" not in feature_cmd


def test_colmap_sfm_only_resets_stale_database_and_sparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    rig = tmp_path / "output" / "colmap_rig"
    rig_images = rig / "images"
    rig_images.mkdir(parents=True)
    _write_test_image(rig_images / "frame_0001.jpg")
    database = rig / "database.db"
    database.write_bytes(b"stale")
    stale_sparse = rig / "sparse" / "0" / "old.txt"
    stale_sparse.parent.mkdir(parents=True)
    stale_sparse.write_text("stale", encoding="utf-8")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: prompts.append(_args[2]) or QMessageBox.Yes,
    )
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step._set_colmap_stage_intents(run_sfm=True, run_conversion=False)
    step.colmap_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_feature",
        "colmap_rig_config",
        "colmap_match",
        "colmap_mapper",
    ]
    assert prompts
    assert not database.exists()
    assert not stale_sparse.exists()
    assert rig_images.is_dir()
    assert (rig / "sparse").is_dir()


def test_colmap_export_can_queue_colmap_global_mapper(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))
    idx = step.colmap_mapper_combo.findData("global")
    assert idx >= 0
    step.colmap_mapper_combo.setCurrentIndex(idx)

    commands = step.build_commands()

    assert commands[-1][1][0] == str(fake_colmap)
    assert commands[-1][1][1] == "global_mapper"
    assert commands[-1][1][commands[-1][1].index("--GlobalMapper.multiple_models") + 1] == "0"


def test_colmap_user_preferences_restore_executable_and_pipeline_choices(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _app()
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("STECHDRIVE_USER_SETTINGS_PATH", str(settings_path))

    first = CubemapStep(Path.cwd())
    first.enable_user_preferences()
    first.colmap_exec_browse.set_text(str(tmp_path / "colmap.exe"))
    first.glomap_exec_browse.set_text(str(tmp_path / "glomap.exe"))
    matcher_idx = first.colmap_matcher_combo.findData("exhaustive")
    mapper_idx = first.colmap_mapper_combo.findData("incremental")
    assert matcher_idx >= 0
    assert mapper_idx >= 0
    first.colmap_matcher_combo.setCurrentIndex(matcher_idx)
    first.colmap_mapper_combo.setCurrentIndex(mapper_idx)

    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["step4_colmap"]["colmap_executable"].endswith("colmap.exe")
    assert stored["step4_colmap"]["glomap_executable"].endswith("glomap.exe")
    assert stored["step4_colmap"]["matcher"] == "exhaustive"
    assert stored["step4_colmap"]["mapper"] == "incremental"

    second = CubemapStep(Path.cwd())
    second.enable_user_preferences()

    assert second.colmap_exec_browse.text().endswith("colmap.exe")
    assert second.glomap_exec_browse.text().endswith("glomap.exe")
    assert second.colmap_matcher_combo.currentData() == "exhaustive"
    assert second.colmap_mapper_combo.currentData() == "incremental"


def test_colmap_scene_settings_restore_stage_intents(tmp_path: Path) -> None:
    _app()
    settings_path = step4_export_settings_path(tmp_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "settings_version": STEP4_SETTINGS_VERSION,
                "export_method": "colmap",
                "colmap_rig": {"run_sfm": True},
            }
        ),
        encoding="utf-8",
    )

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))

    assert step._export_method() == "colmap"
    assert step.pipeline_stage_intent("sfm") is True
    assert step.pipeline_stage_intent("conversion") is True
    assert step.colmap_exec_browse.isEnabled()
    assert step.take_pipeline_notice() == ""


def test_colmap_route_splits_conversion_and_step5_postshot_training(tmp_path: Path) -> None:
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    images.mkdir()
    masks.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    _write_test_image(masks / "frame_0001.png")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    fake_postshot = tmp_path / "postshot-cli.exe"
    fake_postshot.write_text("", encoding="utf-8")

    _app()
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("colmap")
    step.set_pipeline_stage_intent("sfm", True)
    step.colmap_exec_browse.set_text(str(fake_colmap))
    step._set_training_backend("postshot")
    assert step.postshot_project_name_edit.text() == f"{tmp_path.name}.psht"
    step.training_executable_browse.set_text(str(fake_postshot))
    step.run_training_cb.setChecked(True)
    step.postshot_project_name_edit.setText("scene.psht")
    step.postshot_ksteps_auto_cb.setChecked(False)
    step.postshot_ksteps_edit.setText("42")
    step.postshot_max_image_size_edit.setText("2048")

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "colmap_rig_export",
        "colmap_feature",
        "colmap_rig_config",
        "colmap_match",
        "colmap_mapper",
    ]
    assert all(not phase.startswith("training_") for phase, _cmd in commands)

    rig_images = tmp_path / "output" / "colmap_rig" / "images"
    rig_images.mkdir(parents=True, exist_ok=True)
    _write_test_image(rig_images / "frame_0001.jpg")
    sparse = tmp_path / "output" / "colmap_rig" / "sparse" / "0"
    sparse.mkdir(parents=True, exist_ok=True)
    (sparse / "cameras.txt").write_text("", encoding="utf-8")
    (sparse / "images.txt").write_text("", encoding="utf-8")
    (sparse / "points3D.txt").write_text("", encoding="utf-8")

    cmd = step.build_training_launch_commands()[0][1]
    assert cmd == [
        str(fake_postshot),
        "train",
        "--import",
        str(tmp_path / "output" / "colmap_rig" / "images"),
        str(tmp_path / "output" / "colmap_rig" / "sparse" / "0" / "cameras.txt"),
        str(tmp_path / "output" / "colmap_rig" / "sparse" / "0" / "images.txt"),
        str(tmp_path / "output" / "colmap_rig" / "sparse" / "0" / "points3D.txt"),
        "--output",
        str(tmp_path / "output" / "scene.psht"),
        "--profile",
        "Splat3",
        "-s",
        "42",
        "--max-image-size",
        "2048",
        "--image-select",
        "all",
        "--max-sh-degree",
        "3",
    ]
