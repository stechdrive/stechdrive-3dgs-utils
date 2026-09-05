"""Step 4 project settings restore and user-preference helpers."""

from __future__ import annotations

from pathlib import Path

from gui.steps.sfm_route_specs import normalize_sfm_route
from gui.steps.step4_contracts import (
    _AXIS_NONE,
    _COLMAP_MAPPER_GLOBAL,
    _COLMAP_MATCHER_SEQUENTIAL,
    _OUTPUT_SHAPE_EQUIRECT_3DGUT,
    _OUTPUT_SHAPE_PROJECTED,
    _PROFILE_LICHTFELD,
    _SPHERESFM_RUN_CONVERT_ONLY,
    _SPHERESFM_RUN_SFM_ONLY,
    _USER_SETTINGS_SECTION,
    _normalize_spheresfm_quality_preset,
)
from gui.steps.step4_settings import load_step4_export_settings
from gui.user_settings import load_user_settings_section, update_user_settings_section


class Step4ProjectSettingsMixin:
    def _restore_project_settings(self, scene: Path) -> bool:
        settings = load_step4_export_settings(scene)
        if not settings:
            return False

        self._syncing_project_settings = True
        self._syncing_user_preferences = True
        try:
            self._apply_project_settings(scene, settings)
        finally:
            self._syncing_user_preferences = False
            self._syncing_project_settings = False
        return True

    def _apply_project_settings(self, scene: Path, settings: dict) -> None:
        route = normalize_sfm_route(str(settings.get("export_method", "")))
        external_import = self._settings_origin_kind(settings) == "external_import"
        self._set_export_method(route)
        if external_import:
            self._conversion_intent = False
            self._colmap_sfm_intent = False
            self._spheresfm_sfm_intent = False
            self._spheresfm_conversion_intent = False

        self._restore_conversion_settings(settings)
        self._restore_route_settings(scene, settings)
        self._restore_training_settings(scene, settings)
        if external_import:
            self._arm_external_import_metashape_defaults_if_ready()

        self._sync_output_shape_controls()
        self._sync_yaw_per_frame_control()
        self._sync_settings_tabs()
        self._update_path_labels()

    @staticmethod
    def _settings_origin_kind(settings: dict) -> str:
        origin = settings.get("origin")
        if not isinstance(origin, dict):
            return ""
        return str(origin.get("kind") or "").strip()

    def _arm_external_import_metashape_defaults_if_ready(self) -> None:
        if not self._is_metashape_method() or not self._external_import_metashape_inputs_ready():
            return

        self._conversion_intent = True
        self._colmap_sfm_intent = False
        self._spheresfm_sfm_intent = False
        self._spheresfm_conversion_intent = False
        self.export_images_cb.setChecked(True)
        self.export_masks_cb.setChecked(True)
        self.export_colmap_cb.setChecked(False)
        self._set_combo_data(self.output_shape_combo, _OUTPUT_SHAPE_PROJECTED)
        self.view_config.apply_settings_snapshot({"mode": "cube6", "yaw_offset": 0.0})
        self._set_combo_data(self.profile_combo, _PROFILE_LICHTFELD)
        self._sync_profile_defaults(_PROFILE_LICHTFELD)
        self._set_metashape_ply_approved(True, auto_candidate=False)
        self._sync_ply_browse_enabled()

    def _external_import_metashape_inputs_ready(self) -> bool:
        xml_text = self.ms_xml_browse.text().strip()
        ply_text = self.ms_ply_browse.text().strip()
        if not xml_text or not ply_text:
            return False
        xml = Path(xml_text)
        ply = Path(ply_text)
        if not xml.is_file() or not ply.is_file():
            return False
        return (
            self._metashape_input_output_path_issue(xml) is None
            and self._metashape_input_output_path_issue(ply) is None
        )

    def _restore_conversion_settings(self, settings: dict) -> None:
        image_size = settings.get("image_size") if isinstance(settings.get("image_size"), dict) else {}
        scale = image_size.get("scale")
        if scale is not None:
            try:
                self._set_combo_data(self.scale_combo, float(scale))
            except (TypeError, ValueError):
                pass

        view_config = settings.get("view_config")
        if isinstance(view_config, dict):
            self.view_config.apply_settings_snapshot(view_config)

        conversion = settings.get("conversion") if isinstance(settings.get("conversion"), dict) else {}
        restore_view_export_targets = not self._settings_uses_direct_source_output(settings, conversion)
        if restore_view_export_targets:
            if "write_images" in conversion:
                self.export_images_cb.setChecked(bool(conversion.get("write_images")))
            if "write_masks" in conversion:
                self.export_masks_cb.setChecked(bool(conversion.get("write_masks")))
        else:
            self.export_images_cb.setChecked(True)
            self.export_masks_cb.setChecked(True)
        if "yaw_offset_per_frame" in conversion and not self._is_colmap_method():
            try:
                self.yaw_per_frame_edit.setValue(float(conversion.get("yaw_offset_per_frame")))
            except (TypeError, ValueError):
                pass
        output_format = str(conversion.get("output_format", "")).strip()
        output_bit_depth = str(conversion.get("output_bit_depth", "")).strip()
        if output_format:
            self._set_combo_data(self.output_format_combo, output_format)
        if output_bit_depth:
            self._set_combo_data(self.output_bit_depth_combo, output_bit_depth)
        if "jpg_quality" in conversion:
            self.jpg_quality_edit.setText(str(conversion.get("jpg_quality")))
        if "invert_masks" in conversion:
            self.invert_masks_cb.setChecked(bool(conversion.get("invert_masks")))

    @staticmethod
    def _settings_uses_direct_source_output(settings: dict, conversion: dict) -> bool:
        output_shape = str(settings.get("output_shape", "")).strip()
        return output_shape == _OUTPUT_SHAPE_EQUIRECT_3DGUT or conversion.get("uses_source_images") is True

    def _restore_route_settings(self, scene: Path, settings: dict) -> None:
        target_profile = str(settings.get("target_profile", "")).strip()
        axis_transform = str(settings.get("axis_transform", "")).strip()
        if self._is_spheresfm_method():
            if target_profile:
                self._set_combo_data(self.spheresfm_profile_combo, target_profile)
            if axis_transform:
                self._set_combo_data(self.spheresfm_axis_transform_combo, axis_transform)
        else:
            if target_profile:
                self._set_combo_data(self.profile_combo, target_profile)
            if axis_transform:
                self._set_combo_data(self.axis_transform_combo, axis_transform)

        output_shape = str(settings.get("output_shape", "")).strip()
        if output_shape:
            combo = self.spheresfm_output_shape_combo if self._is_spheresfm_method() else self.output_shape_combo
            self._set_combo_data(combo, output_shape)

        metashape = settings.get("metashape_import")
        if isinstance(metashape, dict):
            xml = self._settings_path_text(scene, metashape.get("xml"), require_file=True)
            ply = self._settings_path_text(scene, metashape.get("ply"), require_file=True)
            if xml:
                self.ms_xml_browse.set_text(xml)
            if ply:
                self.ms_ply_browse.set_text(ply)
                self._set_metashape_ply_approved(True)
            if "use_ply" in metashape:
                self.ms_use_ply_cb.setChecked(bool(metashape.get("use_ply")))
            if "scale" in metashape:
                self.ms_scale_edit.setText(str(metashape.get("scale")))
            if "no_fix_rotation" in metashape:
                self.ms_no_fix_rot_cb.setChecked(bool(metashape.get("no_fix_rotation")))

        realityscan = settings.get("realityscan")
        if isinstance(realityscan, dict):
            self._set_combo_data(
                self.realityscan_pose_prior_combo,
                str(realityscan.get("pose_prior", "")).strip(),
            )
            self._set_combo_data(
                self.realityscan_calibration_prior_combo,
                str(realityscan.get("calibration_prior", "")).strip(),
            )
            if "include_rig" in realityscan:
                self.realityscan_include_rig_cb.setChecked(bool(realityscan.get("include_rig")))

        colmap = settings.get("colmap_rig")
        if isinstance(colmap, dict):
            if "run_sfm" in colmap:
                self._set_colmap_stage_intents(
                    run_sfm=bool(colmap.get("run_sfm")),
                    run_conversion=self._conversion_intent or bool(colmap.get("run_sfm")),
                )
            self._set_combo_data(self.colmap_matcher_combo, str(colmap.get("matcher", "")).strip())
            self._set_combo_data(self.colmap_mapper_combo, str(colmap.get("mapper", "")).strip())
            colmap_exec = self._settings_text(colmap.get("colmap_executable"))
            glomap_exec = self._settings_text(colmap.get("glomap_executable"))
            if colmap_exec:
                self.colmap_exec_browse.set_text(colmap_exec)
            if glomap_exec:
                self.glomap_exec_browse.set_text(glomap_exec)
            sparse = self._settings_path_text(
                scene,
                colmap.get("selected_sparse_model_dir"),
            )
            if sparse:
                self.colmap_sparse_browse.set_text(sparse)
                self._colmap_sparse_user_edited = True

        spheresfm = settings.get("spheresfm")
        if isinstance(spheresfm, dict):
            if "use_masks" in spheresfm:
                self.spheresfm_use_masks_cb.setChecked(bool(spheresfm.get("use_masks")))
            self.spheresfm_loop_detection_cb.setChecked(bool(spheresfm.get("loop_detection", False)))
            self._set_combo_data(
                self.spheresfm_quality_combo,
                _normalize_spheresfm_quality_preset(str(spheresfm.get("quality_preset", "")).strip()),
            )
            run_scope = str(spheresfm.get("run_scope", "")).strip()
            if run_scope:
                run_scope = self._normalize_spheresfm_run_scope(run_scope)
                self._set_spheresfm_stage_intents(
                    run_sfm=run_scope != _SPHERESFM_RUN_CONVERT_ONLY,
                    run_conversion=run_scope != _SPHERESFM_RUN_SFM_ONLY,
                )
            pose = self._settings_path_text(scene, spheresfm.get("pose_path"), require_file=True)
            if pose:
                self.spheresfm_pose_browse.set_text(pose)
            spheresfm_exec = self._settings_text(spheresfm.get("colmap_executable"))
            if spheresfm_exec:
                self.spheresfm_exec_browse.set_text(spheresfm_exec)
            sparse = self._settings_path_text(
                scene,
                spheresfm.get("selected_sparse_model_dir"),
            )
            if sparse:
                self.spheresfm_sparse_browse.set_text(sparse)
                self._spheresfm_sparse_user_edited = True

    @staticmethod
    def _settings_text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _settings_path_text(scene: Path, value: object, *, require_file: bool = False) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(text)
        if not path.is_absolute():
            path = scene / path
        if require_file and not path.is_file():
            return ""
        return str(path)

    # -- ユーザー設定 --

    def enable_user_preferences(self) -> None:
        if self._user_preferences_enabled:
            return
        self._user_preferences_enabled = True
        self._load_user_preferences()
        self.colmap_exec_browse.path_changed.connect(lambda _path: self._save_user_preferences())
        self.glomap_exec_browse.path_changed.connect(lambda _path: self._save_user_preferences())
        self.colmap_matcher_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.colmap_mapper_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.spheresfm_exec_browse.path_changed.connect(lambda _path: self._save_user_preferences())
        self.spheresfm_loop_detection_cb.toggled.connect(lambda _checked: self._save_user_preferences())
        self.spheresfm_quality_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.spheresfm_output_shape_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.spheresfm_profile_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.spheresfm_axis_transform_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.realityscan_pose_prior_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.realityscan_calibration_prior_combo.currentIndexChanged.connect(lambda _idx: self._save_user_preferences())
        self.realityscan_include_rig_cb.toggled.connect(lambda _checked: self._save_user_preferences())
    def _load_user_preferences(self) -> None:
        settings = load_user_settings_section(_USER_SETTINGS_SECTION)
        self._syncing_user_preferences = True
        try:
            colmap_exec = str(settings.get("colmap_executable", "")).strip()
            glomap_exec = str(settings.get("glomap_executable", "")).strip()
            if colmap_exec:
                self.colmap_exec_browse.set_text(colmap_exec)
            if glomap_exec:
                self.glomap_exec_browse.set_text(glomap_exec)
            spheresfm_exec = str(settings.get("spheresfm_executable", "")).strip()
            if spheresfm_exec:
                self.spheresfm_exec_browse.set_text(spheresfm_exec)

            matcher = str(settings.get("matcher", "")).strip()
            mapper = str(settings.get("mapper", "")).strip()
            if matcher:
                self._set_combo_data(self.colmap_matcher_combo, matcher)
            if mapper:
                self._set_combo_data(self.colmap_mapper_combo, mapper)
            spheresfm_quality = str(settings.get("spheresfm_quality_preset", "")).strip()
            spheresfm_output_shape = str(settings.get("spheresfm_output_shape", "")).strip()
            spheresfm_profile = str(settings.get("spheresfm_profile", "")).strip()
            spheresfm_axis = str(settings.get("spheresfm_axis_transform", "")).strip()
            realityscan_pose_prior = str(settings.get("realityscan_pose_prior", "")).strip()
            realityscan_calibration_prior = str(settings.get("realityscan_calibration_prior", "")).strip()
            realityscan_include_rig = settings.get("realityscan_include_rig")
            self.spheresfm_loop_detection_cb.setChecked(bool(settings.get("spheresfm_loop_detection", False)))
            if spheresfm_quality:
                self._set_combo_data(
                    self.spheresfm_quality_combo,
                    _normalize_spheresfm_quality_preset(spheresfm_quality),
                )
            if spheresfm_output_shape:
                self._set_combo_data(self.spheresfm_output_shape_combo, spheresfm_output_shape)
            if spheresfm_profile:
                self._set_combo_data(self.spheresfm_profile_combo, spheresfm_profile)
            if spheresfm_axis:
                self._set_combo_data(self.spheresfm_axis_transform_combo, spheresfm_axis)
            if realityscan_pose_prior:
                self._set_combo_data(self.realityscan_pose_prior_combo, realityscan_pose_prior)
            if realityscan_calibration_prior:
                self._set_combo_data(self.realityscan_calibration_prior_combo, realityscan_calibration_prior)
            if realityscan_include_rig is not None:
                self.realityscan_include_rig_cb.setChecked(bool(realityscan_include_rig))

            training_backend = str(settings.get("training_backend", "")).strip()
            self._restore_training_executables(settings.get("training_executables"))
            if training_backend:
                self._set_training_backend(training_backend)
            training_executable = str(settings.get("training_executable", "")).strip()
            training_output = str(settings.get("training_output", "")).strip()
            if training_executable:
                self._training_executable_by_backend[self._training_backend()] = training_executable
                self._apply_training_executable_for_backend(self._training_backend())
            if training_output:
                self.training_output_browse.set_text(training_output)
                self._training_output_user_edited = True
        finally:
            self._syncing_user_preferences = False
        self._on_colmap_mapper_changed()

    def _save_user_preferences(self) -> None:
        if self._syncing_user_preferences or self._syncing_project_settings:
            return
        update_user_settings_section(
            _USER_SETTINGS_SECTION,
            {
                "colmap_executable": self.colmap_exec_browse.text(),
                "glomap_executable": self.glomap_exec_browse.text(),
                "matcher": self.colmap_matcher_combo.currentData() or _COLMAP_MATCHER_SEQUENTIAL,
                "mapper": self.colmap_mapper_combo.currentData() or _COLMAP_MAPPER_GLOBAL,
                "spheresfm_executable": self.spheresfm_exec_browse.text(),
                "spheresfm_loop_detection": self.spheresfm_loop_detection_cb.isChecked(),
                "spheresfm_quality_preset": self._spheresfm_quality_preset(),
                "spheresfm_output_shape": self.spheresfm_output_shape_combo.currentData() or _OUTPUT_SHAPE_PROJECTED,
                "spheresfm_profile": self.spheresfm_profile_combo.currentData() or _PROFILE_LICHTFELD,
                "spheresfm_axis_transform": self.spheresfm_axis_transform_combo.currentData() or _AXIS_NONE,
                "realityscan_pose_prior": self.realityscan_pose_prior_combo.currentData() or "exact",
                "realityscan_calibration_prior": self.realityscan_calibration_prior_combo.currentData() or "exact",
                "realityscan_include_rig": self.realityscan_include_rig_cb.isChecked(),
                "training_backend": self._training_backend(),
                "training_executable": self.training_executable_browse.text(),
                "training_executables": self._training_executables_for_settings(),
                "training_output": self.training_output_browse.text(),
            },
        )
