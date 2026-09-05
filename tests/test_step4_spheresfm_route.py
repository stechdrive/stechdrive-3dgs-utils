from __future__ import annotations

from tests.helpers.step4 import (
    STEP4_SETTINGS_VERSION,
    CubemapStep,
    Path,
    QMessageBox,
    _app,
    _ready_step,
    _workflow_job,
    _write_spheresfm_sparse_stub,
    _write_test_image,
    i18n,
    json,
    os,
    pytest,
    step4_export_settings_path,
    step4_views_config_path,
)


def test_spheresfm_output_shape_change_keeps_conversion_tab_focused() -> None:
    _app()
    step = CubemapStep(Path.cwd())
    step._set_export_method("spheresfm")
    step.settings_tabs.setCurrentIndex(step.spheresfm_convert_tab_index)

    direct_idx = step.spheresfm_output_shape_combo.findData("equirect_3dgut")
    projected_idx = step.spheresfm_output_shape_combo.findData("projected")
    assert direct_idx >= 0
    assert projected_idx >= 0

    step.spheresfm_output_shape_combo.setCurrentIndex(direct_idx)
    assert step.settings_tabs.currentIndex() == step.spheresfm_convert_tab_index

    step.spheresfm_output_shape_combo.setCurrentIndex(projected_idx)
    assert step.settings_tabs.currentIndex() == step.spheresfm_convert_tab_index


def test_spheresfm_erp_output_is_disabled_outside_lichtfeld_profile(tmp_path: Path) -> None:
    step = _ready_step(tmp_path)
    step._set_export_method("spheresfm")
    direct_idx = step.spheresfm_output_shape_combo.findData("equirect_3dgut")
    postshot_idx = step.spheresfm_profile_combo.findData("postshot")
    lichtfeld_idx = step.spheresfm_profile_combo.findData("lichtfeld")
    assert direct_idx >= 0
    assert postshot_idx >= 0
    assert lichtfeld_idx >= 0

    assert step.spheresfm_output_shape_combo.isItemEnabled(direct_idx)
    step.spheresfm_profile_combo.setCurrentIndex(postshot_idx)

    assert step.spheresfm_output_shape_combo.currentData() == "projected"
    assert step.spheresfm_profile_combo.currentData() == "postshot"
    assert not step.spheresfm_output_shape_combo.isItemEnabled(direct_idx)
    assert step.spheresfm_output_shape_combo.itemToolTip(direct_idx) == i18n.tip("OUTPUT_SHAPE_EQUIRECT_3DGUT_DISABLED")

    step.spheresfm_output_shape_combo.setCurrentIndex(direct_idx)
    assert step.spheresfm_output_shape_combo.currentData() == "projected"
    assert step.spheresfm_profile_combo.currentData() == "postshot"

    step.spheresfm_profile_combo.setCurrentIndex(lichtfeld_idx)
    assert step.spheresfm_output_shape_combo.isItemEnabled(direct_idx)
    assert step.spheresfm_output_shape_combo.itemToolTip(direct_idx) == i18n.tip("OUTPUT_SHAPE_EQUIRECT_3DGUT")


def test_spheresfm_visible_tabs_follow_projection_conversion_sfm_order() -> None:
    _app()
    step = CubemapStep(Path.cwd())

    step._set_export_method("spheresfm")

    assert [step.settings_tabs.tabText(i) for i in range(step.settings_tabs.count())] == [
        i18n.t("STEP4_TAB_INPUT"),
        i18n.t("STEP4_TAB_OUTPUT"),
        i18n.t("STEP4_TAB_DETAILS"),
    ]
    assert step.metashape_section.isHidden()
    assert step.metashape_sfm_input_widget.isHidden()
    assert step.colmap_section.isHidden()
    assert step.colmap_sfm_input_widget.isHidden()
    assert not step.spheresfm_sfm_input_widget.isHidden()
    assert not step.spheresfm_section.isHidden()
    assert not step.spheresfm_convert_section.isHidden()
    assert step.settings_tabs.isTabEnabled(step.input_tab_index)
    assert step.settings_tabs.isTabEnabled(step.output_tab_index)


def test_spheresfm_conversion_rows_keep_axis_transform_internal_only() -> None:
    _app()
    step = CubemapStep(Path.cwd())
    form = step.spheresfm_convert_section.layout().itemAt(0).layout()

    profile_row, _profile_role = form.getWidgetPosition(step.spheresfm_profile_combo)
    shape_row, _shape_role = form.getWidgetPosition(step.spheresfm_output_shape_combo)
    axis_row, _axis_role = form.getWidgetPosition(step.spheresfm_axis_transform_combo)
    axis_label = form.labelForField(step.spheresfm_axis_transform_combo)

    assert profile_row < shape_row < axis_row
    assert step.spheresfm_axis_transform_combo.toolTip() == i18n.tip("SPHERESFM_AXIS_TRANSFORM")
    assert step.spheresfm_axis_transform_combo.isHidden()
    assert axis_label is not None
    assert axis_label.toolTip() == i18n.tip("SPHERESFM_AXIS_TRANSFORM")
    assert axis_label.isHidden()


def test_spheresfm_method_can_queue_3dgut_export_without_projection_views(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    images.mkdir()
    masks.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    _write_test_image(masks / "frame_0001.png")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step._set_combo_data(step.spheresfm_output_shape_combo, "equirect_3dgut")
    step.spheresfm_exec_browse.set_text(str(fake_colmap))

    assert step.sfm_path_summary_value.full_text() == "output/colmap_equirect/"
    assert step.cubemap_path_summary_value.full_text() == "output/colmap_equirect_3dgut/"
    assert not step.export_targets_row.isEnabled()
    assert not step.view_config.settings_widget.isEnabled()

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "spheresfm_preflight",
        "spheresfm_prepare",
        "spheresfm_database",
        "spheresfm_feature",
        "spheresfm_match",
        "spheresfm_mapper",
        "spheresfm_transforms",
    ]
    preflight_job = _workflow_job(commands[0][1])
    prepare_job = _workflow_job(commands[1][1])
    transforms_job = _workflow_job(commands[6][1])
    assert preflight_job["colmap"] == str(fake_colmap)
    assert preflight_job["matcher"] == "sequential"
    assert preflight_job["quality_preset"] == "standard"
    assert preflight_job["use_masks"] is True
    assert prepare_job["use_masks"] is True
    assert commands[3][1][commands[3][1].index("--ImageReader.camera_model") + 1] == "EQUIRECTANGULAR"
    assert commands[3][1][commands[3][1].index("--ImageReader.camera_params") + 1] == "64,32"
    assert commands[3][1][commands[3][1].index("--ImageReader.mask_path") + 1] == str(
        tmp_path / "output" / "colmap_equirect" / "masks_colmap"
    )
    assert commands[4][1][commands[4][1].index("--SequentialMatching.overlap") + 1] == "10"
    assert "--Mapper.sphere_camera" not in commands[5][1]
    assert commands[5][1][commands[5][1].index("--Mapper.multiple_models") + 1] == "0"
    assert "--Mapper.ba_global_max_num_iterations" not in commands[5][1]
    assert "--Mapper.ba_global_frames_ratio" not in commands[5][1]
    assert "--Mapper.ba_global_images_ratio" not in commands[5][1]
    assert transforms_job["sparse_dir"] == str(tmp_path / "output" / "colmap_equirect" / "sparse")
    assert transforms_job["output_dir"] == str(tmp_path / "output" / "colmap_equirect_3dgut")
    assert transforms_job["image_path_mode"] == "images-prefix"
    assert os.path.samefile(
        images / "frame_0001.jpg",
        tmp_path / "output" / "colmap_equirect_3dgut" / "images" / "frame_0001.jpg",
    )
    assert os.path.samefile(
        masks / "frame_0001.png",
        tmp_path / "output" / "colmap_equirect_3dgut" / "masks" / "frame_0001.png",
    )


def test_spheresfm_method_can_queue_projected_cubemap_export(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    images.mkdir()
    masks.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    _write_test_image(masks / "frame_0001.png")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.spheresfm_exec_browse.set_text(str(fake_colmap))

    assert step.sfm_path_summary_value.full_text() == "output/colmap_equirect/"
    assert step.cubemap_path_summary_value.full_text() == "output/colmap_equirect_cubemap/"
    assert step.export_targets_row.isEnabled()
    assert step.view_config.settings_widget.isEnabled()

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "spheresfm_preflight",
        "spheresfm_prepare",
        "spheresfm_database",
        "spheresfm_feature",
        "spheresfm_match",
        "spheresfm_mapper",
        "spheresfm_transforms",
        "spheresfm_cubemap",
    ]
    transform_cmd = commands[6][1]
    cubemap_cmd = commands[7][1]
    transform_job = _workflow_job(transform_cmd)
    cubemap_job = _workflow_job(cubemap_cmd)
    assert transform_job["output_dir"] == str(tmp_path / "output" / "colmap_equirect" / "equirect")
    assert transform_job["image_path_mode"] == "relative"
    assert cubemap_job["input_dir"] == str(tmp_path / "output" / "colmap_equirect" / "equirect")
    assert cubemap_job["output_dir"] == str(tmp_path / "output" / "colmap_equirect_cubemap")
    assert step4_views_config_path(tmp_path).is_file()
    assert cubemap_job["image_dir"] == str(images)
    assert cubemap_job["mask_dir"] == str(masks)
    assert cubemap_job["axis_mode"] == "none"
    assert cubemap_job["final_orientation"] == "lichtfeld"


def test_spheresfm_method_can_queue_sfm_only(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    images.mkdir()
    masks.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    _write_test_image(masks / "frame_0001.png")
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.set_pipeline_stage_intent("conversion", False)
    step.spheresfm_exec_browse.set_text(str(fake_colmap))

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == [
        "spheresfm_preflight",
        "spheresfm_prepare",
        "spheresfm_database",
        "spheresfm_feature",
        "spheresfm_match",
        "spheresfm_mapper",
    ]
    assert not step.settings_tabs.isTabEnabled(step.spheresfm_convert_tab_index)


def test_spheresfm_convert_only_requires_existing_sparse(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.set_pipeline_stage_intent("sfm", False)

    with pytest.raises(ValueError, match="sparse"):
        step.build_commands()


def test_spheresfm_convert_only_queues_3dgut_without_colmap_binary(tmp_path: Path) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    sparse_model = _write_spheresfm_sparse_stub(tmp_path)

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.set_pipeline_stage_intent("sfm", False)
    step._set_combo_data(step.spheresfm_output_shape_combo, "equirect_3dgut")

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == ["spheresfm_transforms"]
    job = _workflow_job(commands[0][1])
    assert job["sparse_dir"] == str(sparse_model)
    assert job["output_dir"] == str(tmp_path / "output" / "colmap_equirect_3dgut")
    assert job["image_path_mode"] == "images-prefix"
    assert sparse_model.is_dir()


def test_spheresfm_open_gui_warns_when_selected_binary_has_no_gui_support(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    sparse_model = _write_spheresfm_sparse_stub(tmp_path)
    fake_colmap = tmp_path / "colmap.exe"
    fake_colmap.write_text("", encoding="utf-8")
    warnings: list[tuple[str, str]] = []

    class FakeGuiLessQProcess:
        MergedChannels = object()
        NormalExit = object()

        def __init__(self, parent=None) -> None:
            self.parent = parent
            self.program = ""
            self.arguments: list[str] = []

        def setProgram(self, program: str) -> None:
            self.program = program

        def setArguments(self, arguments: list[str]) -> None:
            self.arguments = arguments

        def setProcessChannelMode(self, _mode) -> None:
            pass

        def start(self) -> None:
            pass

        def waitForStarted(self, _msecs: int) -> bool:
            return True

        def waitForFinished(self, _msecs: int) -> bool:
            return True

        def readAllStandardOutput(self) -> bytes:
            return b"ERROR: Cannot start colmap GUI; colmap was built without GUI support or QT dependency is missing."

        def readAllStandardError(self) -> bytes:
            return b""

        def errorString(self) -> str:
            return ""

        def exitStatus(self):
            return self.NormalExit

        def exitCode(self) -> int:
            return 1

    monkeypatch.setattr(
        CubemapStep,
        "_create_spheresfm_gui_process",
        lambda self: FakeGuiLessQProcess(self),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step.spheresfm_exec_browse.set_text(str(fake_colmap))

    step._open_spheresfm_result()

    assert len(warnings) == 1
    assert warnings[0][0] == i18n.t("SPHERESFM_OPEN_GUI")
    assert str(fake_colmap) in warnings[0][1]
    assert str(sparse_model) in warnings[0][1]
    assert "Qt GUI" in warnings[0][1]


def test_spheresfm_3dgut_convert_only_confirms_output_dataset_targets(tmp_path: Path, monkeypatch) -> None:
    _app()
    images = tmp_path / "images"
    masks = tmp_path / "masks"
    images.mkdir()
    masks.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    _write_test_image(masks / "frame_0001.png")
    sparse_model = _write_spheresfm_sparse_stub(tmp_path)
    gut_output = tmp_path / "output" / "colmap_equirect_3dgut"
    transforms = gut_output / "transforms.json"
    pointcloud = gut_output / "pointcloud.ply"
    old_linked_image = gut_output / "images" / "old.jpg"
    old_linked_mask = gut_output / "masks" / "old.png"
    old_linked_image.parent.mkdir(parents=True)
    old_linked_mask.parent.mkdir(parents=True)
    transforms.write_text("old", encoding="utf-8")
    pointcloud.write_text("old", encoding="utf-8")
    old_linked_image.write_text("old", encoding="utf-8")
    old_linked_mask.write_text("old", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.set_pipeline_stage_intent("sfm", False)
    step._set_combo_data(step.spheresfm_output_shape_combo, "equirect_3dgut")

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == ["spheresfm_transforms"]
    assert not transforms.exists()
    assert not pointcloud.exists()
    assert not old_linked_image.exists()
    assert not old_linked_mask.exists()
    assert os.path.samefile(images / "frame_0001.jpg", gut_output / "images" / "frame_0001.jpg")
    assert os.path.samefile(masks / "frame_0001.png", gut_output / "masks" / "frame_0001.png")
    assert sparse_model.is_dir()
    assert images.is_dir()
    assert masks.is_dir()


def test_spheresfm_convert_only_resets_conversion_outputs_only(tmp_path: Path, monkeypatch) -> None:
    _app()
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    sparse_model = _write_spheresfm_sparse_stub(tmp_path)
    database = tmp_path / "output" / "colmap_equirect" / "database.db"
    database.write_text("db", encoding="utf-8")
    old_equirect = tmp_path / "output" / "colmap_equirect" / "equirect" / "old.txt"
    old_views = step4_views_config_path(tmp_path)
    old_images = tmp_path / "output" / "colmap_equirect_cubemap" / "images" / "old.jpg"
    old_masks = tmp_path / "output" / "colmap_equirect_cubemap" / "masks" / "old.png"
    old_equirect.parent.mkdir(parents=True)
    old_views.parent.mkdir(parents=True)
    old_images.parent.mkdir(parents=True)
    old_masks.parent.mkdir(parents=True)
    old_equirect.write_text("old", encoding="utf-8")
    old_views.write_text("old", encoding="utf-8")
    old_images.write_text("old", encoding="utf-8")
    old_masks.write_text("old", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step._set_export_method("spheresfm")
    step.set_pipeline_stage_intent("sfm", False)

    commands = step.build_commands()

    assert [phase for phase, _cmd in commands] == ["spheresfm_transforms", "spheresfm_cubemap"]
    assert not old_equirect.exists()
    assert old_views.is_file()
    assert old_views.read_text(encoding="utf-8") != "old"
    assert not old_images.exists()
    assert not old_masks.exists()
    assert sparse_model.is_dir()
    assert database.is_file()


@pytest.mark.parametrize("saved, expected", [
    ("quality", "standard"), ("robust", "standard"), ("standard", "standard"),
    ("fast", "lightest"), ("light", "light"), ("lightest", "lightest"),
])
def test_spheresfm_user_preferences_restore_quality_preset(
    tmp_path: Path,
    monkeypatch,
    saved: str,
    expected: str,
) -> None:
    _app()
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("STECHDRIVE_USER_SETTINGS_PATH", str(settings_path))
    settings_path.write_text(
        json.dumps({"step4_colmap": {"spheresfm_quality_preset": saved, "spheresfm_matcher": "exhaustive"}}),
        encoding="utf-8",
    )

    step = CubemapStep(Path.cwd())
    step.enable_user_preferences()

    assert step.spheresfm_quality_combo.currentData() == expected
    assert not step.spheresfm_loop_detection_cb.isChecked()
    assert not hasattr(step, "spheresfm_matcher_combo")


def test_spheresfm_scene_settings_restore_stage_intents(tmp_path: Path) -> None:
    _app()
    settings_path = step4_export_settings_path(tmp_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "settings_version": STEP4_SETTINGS_VERSION,
                "export_method": "spheresfm",
                "spheresfm": {"run_scope": "convert_only"},
            }
        ),
        encoding="utf-8",
    )

    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))

    assert step._export_method() == "spheresfm"
    assert step.pipeline_stage_intent("sfm") is False
    assert step.pipeline_stage_intent("conversion") is True
    assert step._spheresfm_run_scope() == "convert_only"


def test_spherical_loop_and_budget_sync_persist_and_reach_commands(tmp_path: Path, monkeypatch) -> None:
    from gui.steps.sfm_step import SfmStep

    _app()
    monkeypatch.setenv("STECHDRIVE_USER_SETTINGS_PATH", str(tmp_path / "user-settings.json"))
    images = tmp_path / "images"
    images.mkdir()
    _write_test_image(images / "frame_0001.jpg")
    executable = tmp_path / "colmap.exe"
    executable.touch()
    step = CubemapStep(Path.cwd())
    step.set_scene_dir(str(tmp_path))
    step.enable_user_preferences()
    step.spheresfm_exec_browse.set_text(str(executable))
    surface = SfmStep(Path.cwd(), step)
    surface.set_scene_dir(str(tmp_path))
    surface.show_route("spheresfm")
    surface.spheresfm_use_masks_cb.setChecked(False)
    surface._set_combo_data(surface.spheresfm_quality_combo, "light")
    surface.spheresfm_loop_detection_cb.setChecked(True)
    assert step._spheresfm_quality_preset() == "light"
    assert step.spheresfm_loop_detection_cb.isChecked()
    commands = dict(step.build_commands())
    assert _workflow_job(commands["spheresfm_preflight"])["loop_detection"] is True
    feature = commands["spheresfm_feature"]
    assert feature[feature.index("--FeatureExtraction.max_image_size") + 1] == "32"
    match = commands["spheresfm_match"]
    assert match[match.index("--SequentialMatching.loop_detection") + 1] == "1"
    step._write_export_settings()
    restored = CubemapStep(Path.cwd())
    restored.set_scene_dir(str(tmp_path))
    assert restored._spheresfm_quality_preset() == "light"
    assert restored.spheresfm_loop_detection_cb.isChecked()
    preferences = CubemapStep(Path.cwd())
    preferences.enable_user_preferences()
    assert preferences._spheresfm_quality_preset() == "light"
    assert preferences.spheresfm_loop_detection_cb.isChecked()
