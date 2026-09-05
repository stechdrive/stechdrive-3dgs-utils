"""Step 4 settings and run-manifest persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from core.colmap_mixed_project import COLMAP_MIXED_MANIFEST
from core.dataset_mask_policy import dataset_mask_mode_from_legacy_write_masks
from core.nerf_dataset_paths import pointcloud_name_for_profile, transforms_name_for_profile
from core.orientation_correction import (
    FINAL_ORIENTATION_LICHTFELD,
    FINAL_ORIENTATION_NONE,
    FINAL_ORIENTATION_REALITYSCAN,
    FINAL_ORIENTATION_STAGE_CUBEMAP_CLI,
    FINAL_ORIENTATION_STAGE_DIRECT_FINALIZE,
    FINAL_ORIENTATION_STAGE_NONE,
    REALITYSCAN_FINAL_ORIENTATION_MATRIX,
)
from core.scene_layout import STEP4_META_DIR_NAME, STEP4_VIEWS_CONFIG_JSON, step4_export_settings_path, step4_meta_dir
from core.scene_project import (
    append_step4_dataset_run,
    append_step4_sfm_run,
    append_step4_training_run,
    file_identity,
    scene_relative,
    utc_now_iso,
)
from core.workflow_artifacts import (
    DATASET_KIND_REALITYSCAN_REALIGN_INPUT,
    SFM_KIND_COLMAP_SPARSE,
    SFM_KIND_METASHAPE_XML_PLY,
    SFM_KIND_SPHERESFM_SPARSE,
    register_dataset_artifact,
    register_sfm_artifact,
)
from gui import i18n
from gui.steps.cubemap_commands import views_config_payload, write_views_config
from gui.steps.step4_contracts import (
    _AXIS_BRUSH,
    _AXIS_POSTSHOT,
    _COLMAP_MAPPER_INCREMENTAL,
    _COLMAP_MATCHER_SEQUENTIAL,
    _COLMAP_PROJECT_MANIFEST_NAME,
    _EXPORT_SETTINGS_NAME,
    _LICHTFELD_FINAL_CORRECTION,
    _METHOD_COLMAP,
    _METHOD_SPHERESFM,
    _PROFILE_REALITYSCAN,
    _SPHERESFM_PROJECT_MANIFEST_NAME,
)
from gui.steps.step4_settings import STEP4_SETTINGS_VERSION, load_step4_export_settings, write_step4_export_settings
from gui.steps.training_backends import TrainingDataset
from gui.version import APP_VERSION


class Step4ManifestMixin:
    def _write_views_config(self, output_dir: Path, views: list[dict]) -> Path:
        return write_views_config(output_dir, views)

    @staticmethod
    def _views_config_payload(views: list[dict]) -> dict:
        return views_config_payload(views)

    def _export_settings_path(self) -> Path:
        if not self.scene_dir:
            raise ValueError(i18n.t("SCENE_REQUIRED_ACTION_HINT"))
        return step4_export_settings_path(Path(self.scene_dir))

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _collect_export_settings(self) -> dict:
        views = self.view_config.collect_views(include_disabled=True)
        scale = float(self.scale_combo.currentData())
        direct = self._uses_direct_equirect_output()
        spheresfm = self._is_spheresfm_method()
        spheresfm_runs_conversion = self._spheresfm_runs_conversion()
        spheresfm_3dgut = spheresfm_runs_conversion and self._uses_spheresfm_3dgut_output()
        spheresfm_projected = spheresfm_runs_conversion and self._uses_spheresfm_projected_output()
        direct_source_output = direct or spheresfm_3dgut
        yaw_step = (
            0.0
            if self._export_method() == _METHOD_COLMAP or direct_source_output
            else float(self.yaw_per_frame_edit.value())
        )
        jpg_quality = int(self.jpg_quality_edit.text().strip())
        if not self.scene_dir:
            raise ValueError(i18n.t("SCENE_REQUIRED_ACTION_HINT"))
        scene = Path(self.scene_dir)
        output = self._display_output_dir()
        profile = self._spheresfm_profile_id() if spheresfm else self._profile_id()
        effective_profile = self._spheresfm_effective_profile() if spheresfm else self._effective_profile()
        if effective_profile == _PROFILE_REALITYSCAN:
            yaw_step = 0.0
        axis_transform = self._spheresfm_axis_transform_mode() if spheresfm else self._axis_transform_mode()
        route_uses_view_export = not direct_source_output and (not spheresfm or spheresfm_projected)
        views_config_snapshot = self._views_config_payload(views) if route_uses_view_export else None
        views_config_path = ""
        if route_uses_view_export:
            views_config_path = f"{STEP4_META_DIR_NAME}/{STEP4_VIEWS_CONFIG_JSON}"
        writes_view_images = route_uses_view_export and self._writes_images()
        writes_view_masks = route_uses_view_export and self._writes_masks()
        dataset_mask_mode = self._dataset_mask_mode_for_settings()
        dataset_source_masks = self._dataset_input_mask_dir_for_conversion(require_existing=False)
        if dataset_mask_mode in {"none", "reuse_existing"}:
            dataset_source_masks = None
        portable_dataset_kind = "3dgut" if direct_source_output else "projection_views"
        uses_lichtfeld_final_orientation = (
            self._uses_lichtfeld_final_correction() or self._uses_spheresfm_lichtfeld_final_correction()
        )
        uses_realityscan_final_orientation = (
            self._is_metashape_method() and effective_profile == _PROFILE_REALITYSCAN and route_uses_view_export
        )
        final_orientation_matrix = None
        if uses_realityscan_final_orientation:
            final_orientation = FINAL_ORIENTATION_REALITYSCAN
            final_orientation_stage = FINAL_ORIENTATION_STAGE_CUBEMAP_CLI
            final_orientation_matrix = REALITYSCAN_FINAL_ORIENTATION_MATRIX.tolist()
        elif not uses_lichtfeld_final_orientation:
            final_orientation = FINAL_ORIENTATION_NONE
            final_orientation_stage = FINAL_ORIENTATION_STAGE_NONE
        elif direct_source_output:
            final_orientation = FINAL_ORIENTATION_LICHTFELD
            final_orientation_stage = FINAL_ORIENTATION_STAGE_DIRECT_FINALIZE
            final_orientation_matrix = _LICHTFELD_FINAL_CORRECTION.tolist()
        elif route_uses_view_export:
            final_orientation = FINAL_ORIENTATION_LICHTFELD
            final_orientation_stage = FINAL_ORIENTATION_STAGE_CUBEMAP_CLI
            final_orientation_matrix = _LICHTFELD_FINAL_CORRECTION.tolist()
        else:
            final_orientation = FINAL_ORIENTATION_LICHTFELD
            final_orientation_stage = FINAL_ORIENTATION_STAGE_NONE
            final_orientation_matrix = _LICHTFELD_FINAL_CORRECTION.tolist()
        if direct_source_output:
            input_transforms_json = output / "transforms.json"
        elif self._is_metashape_method():
            input_transforms_json = self._metashape_import_work_dir() / "transforms.json"
        else:
            input_transforms_json = scene / "transforms.json"
        profile_transforms_json = "transforms.json"
        profile_pointcloud = "pointcloud.ply"
        profile_raw_pointcloud = ""
        if self._is_metashape_method() and route_uses_view_export and effective_profile != _PROFILE_REALITYSCAN:
            nerf_profile = self._metashape_nerf_output_profile(axis_transform, final_orientation)
            profile_transforms_json = transforms_name_for_profile(nerf_profile)
            profile_pointcloud = pointcloud_name_for_profile(nerf_profile)
            if axis_transform in {_AXIS_POSTSHOT, _AXIS_BRUSH}:
                profile_raw_pointcloud = profile_pointcloud

        return {
            "app": "stechdrive-3dgs-utils",
            "app_version": APP_VERSION,
            "settings_version": STEP4_SETTINGS_VERSION,
            "created_at": self._utc_now_iso(),
            "scene_dir": str(scene),
            "output_dir": str(output),
            "portable_output": {
                "root": scene_relative(scene, output),
                "dataset_kind": portable_dataset_kind,
                "active": True,
            },
            "export_method": self._export_method(),
            "output_shape": self._output_shape(),
            "target_profile": profile,
            "effective_profile": effective_profile,
            "axis_transform": axis_transform,
            "fov": 90.0,
            "image_size": {
                "label": self.scale_combo.currentText(),
                "scale": scale,
            },
            "view_config": {
                "mode": self.view_config.view_mode(),
                "yaw_offset": self.view_config.yaw_offset(),
                "yaw_slots": self.view_config.yaw_slot_count(),
                "pitch_rows": self.view_config.pitch_values(),
                "pitch_rows_text": self.view_config.pitch_rows_text(),
                "cube6_drop_top": False,
                "cube6_drop_bottom": False,
                "views": [
                    {
                        "name": v["name"],
                        "yaw": float(v["yaw"]),
                        "pitch": float(v["pitch"]),
                        "enabled": bool(v["enabled"]),
                    }
                    for v in views
                ],
            },
            "views_config_path": views_config_path,
            "views_config_snapshot": views_config_snapshot,
            "conversion": {
                "yaw_offset_per_frame": yaw_step,
                "output_format": self.output_format_combo.currentData() or "auto",
                "output_bit_depth": self.output_bit_depth_combo.currentData() or "8",
                "jpg_quality": jpg_quality,
                "invert_masks": self.invert_masks_cb.isChecked(),
                "write_images": writes_view_images,
                "write_masks": writes_view_masks,
                "no_image": direct_source_output or not route_uses_view_export or not self._writes_any_view_assets(),
                "uses_source_images": direct_source_output,
                "uses_source_masks": direct_source_output and dataset_source_masks is not None,
                "export_colmap": self._is_metashape_method() and self.export_colmap_cb.isChecked(),
            },
            "dataset_masks": {
                "mode": dataset_mask_mode,
                "images_dir": "images" if route_uses_view_export or direct_source_output else "",
                "masks_dir": "masks" if dataset_mask_mode != "none" else "",
                "source_masks_dir": str(dataset_source_masks or ""),
                "sfm_masks_dir": str(self._mask_dir()),
                "generated_source_masks_dir": str(
                    self._dataset_mask_step.generated_source_masks_dir()
                    if getattr(self, "_dataset_mask_step", None) is not None
                    else ""
                ),
                "write_converted_sfm_masks": writes_view_masks,
            },
            "postprocess": {
                "final_orientation": final_orientation,
                "final_orientation_stage": final_orientation_stage,
                "final_orientation_matrix": final_orientation_matrix,
                "lichtfeld_final_orientation_correction": uses_lichtfeld_final_orientation,
                "lichtfeld_final_orientation_stage": final_orientation_stage
                if uses_lichtfeld_final_orientation
                else FINAL_ORIENTATION_STAGE_NONE,
                "lichtfeld_final_orientation_matrix": _LICHTFELD_FINAL_CORRECTION.tolist()
                if uses_lichtfeld_final_orientation
                else None,
                "realityscan_final_orientation_correction": uses_realityscan_final_orientation,
                "realityscan_final_orientation_stage": final_orientation_stage
                if uses_realityscan_final_orientation
                else FINAL_ORIENTATION_STAGE_NONE,
                "realityscan_final_orientation_matrix": REALITYSCAN_FINAL_ORIENTATION_MATRIX.tolist()
                if uses_realityscan_final_orientation
                else None,
            },
            "metashape_import": {
                "enabled": self._is_metashape_method(),
                "use_ply": self._preprocess_uses_ply(),
                "images_dir": str(self._metashape_images_dir()),
                "xml": self.ms_xml_browse.text(),
                "ply": self.ms_ply_browse.text() if self._is_metashape_method() and self._preprocess_uses_ply() else "",
                "ply_approved": self._metashape_ply_approved,
                "scale": float(self.ms_scale_edit.text().strip()),
                "no_fix_rotation": self.ms_no_fix_rot_cb.isChecked(),
            },
            "realityscan": {
                "enabled": self._is_metashape_method() and effective_profile == _PROFILE_REALITYSCAN,
                "output_dir": str(self._display_output_dir()) if effective_profile == _PROFILE_REALITYSCAN else "",
                "xmp": effective_profile == _PROFILE_REALITYSCAN,
                "pose_prior": self.realityscan_pose_prior_combo.currentData() or "exact",
                "calibration_prior": self.realityscan_calibration_prior_combo.currentData() or "exact",
                "coordinates": "relative"
                if (self.realityscan_pose_prior_combo.currentData() or "exact") == "exact"
                else "absolute",
                "include_rig": self.realityscan_include_rig_cb.isChecked(),
                "mask_layers": self._writes_masks(),
            },
            "colmap_rig": {
                "enabled": self._export_method() == _METHOD_COLMAP,
                "dir": str(self._colmap_rig_dir()),
                "project_dir": str(self._colmap_project_dir()),
                "images_dir": str(self._colmap_rig_images_dir()),
                "masks_dir": str(self._colmap_rig_masks_dir()),
                "rig_config": str(self._colmap_rig_dir() / "rig_config.json"),
                "database": str(self._colmap_database_path()),
                "sparse_dir": str(self._colmap_sparse_dir()),
                "sparse_model_dir": str(self._find_colmap_sparse_model() or ""),
                "selected_sparse_model_dir": (
                    self.colmap_sparse_browse.text() if self._colmap_sparse_user_edited else ""
                ),
                "run_sfm": self._colmap_sfm_intent,
                "colmap_executable": self.colmap_exec_browse.text(),
                "glomap_executable": self.glomap_exec_browse.text(),
                "matcher": self.colmap_matcher_combo.currentData() or _COLMAP_MATCHER_SEQUENTIAL,
                "mapper": self.colmap_mapper_combo.currentData() or _COLMAP_MAPPER_INCREMENTAL,
                "per_frame_yaw_forced_zero": self._export_method() == _METHOD_COLMAP,
            },
            "spheresfm": {
                "enabled": spheresfm,
                "project_dir": str(self._spheresfm_project_dir()),
                "images_dir": str(self._metashape_images_dir()),
                "source_masks_dir": str(self._mask_dir()),
                "prepared_masks_dir": str(self._spheresfm_masks_dir()),
                "database": str(self._spheresfm_database_path()),
                "sparse_dir": str(self._spheresfm_sparse_dir()),
                "sparse_model_dir": str(self._find_spheresfm_sparse_model() or ""),
                "selected_sparse_model_dir": (
                    self.spheresfm_sparse_browse.text() if self._spheresfm_sparse_user_edited else ""
                ),
                "use_masks": self._spheresfm_uses_masks(),
                "colmap_executable": self.spheresfm_exec_browse.text(),
                "matcher": _COLMAP_MATCHER_SEQUENTIAL,
                "loop_detection": self.spheresfm_loop_detection_cb.isChecked(),
                "quality_preset": self._spheresfm_quality_preset(),
                "run_scope": self._spheresfm_run_scope(),
                "pose_path": self.spheresfm_pose_browse.text(),
                "camera_model": "EQUIRECTANGULAR",
                "camera_params": self._spheresfm_camera_params_arg() if spheresfm else "",
                "output_shape": self._output_shape() if spheresfm else "",
                "target_profile": self._spheresfm_profile_id() if spheresfm else "",
                "effective_profile": self._spheresfm_effective_profile() if spheresfm else "",
                "axis_transform": self._spheresfm_axis_transform_mode() if spheresfm else "",
                "equirect_dir": str(self._spheresfm_equirect_dir()) if spheresfm else "",
                "cubemap_dir": str(self._spheresfm_cubemap_dir()) if spheresfm else "",
                "gut_dir": str(self._spheresfm_3dgut_dir()) if spheresfm else "",
            },
            "training": self._collect_training_settings(),
            "inputs": {
                "transforms_json": str(input_transforms_json),
                "masks_dir": str(self._mask_dir()),
                "ply_source": str(self._resolve_ply_source() or ""),
            },
            "output_files": {
                "settings": f"{STEP4_META_DIR_NAME}/{_EXPORT_SETTINGS_NAME}",
                "views_config": views_config_path,
                "transforms_json": ""
                if spheresfm and not spheresfm_runs_conversion
                else profile_transforms_json,
                "images_dir": "images",
                "masks_dir": "masks",
                "pointcloud": profile_pointcloud
                if direct
                or spheresfm_3dgut
                or spheresfm_projected
                or (self._is_metashape_method() and route_uses_view_export and effective_profile != _PROFILE_REALITYSCAN)
                or (route_uses_view_export and final_orientation == FINAL_ORIENTATION_LICHTFELD)
                else "",
                "raw_metashape_pointcloud": profile_raw_pointcloud,
                "colmap_rig_dir": "colmap_rig",
                "colmap_rig_config": "colmap_rig/rig_config.json",
                "colmap_project_manifest": f"{STEP4_META_DIR_NAME}/sfm/{_COLMAP_PROJECT_MANIFEST_NAME}",
                "spheresfm_project_dir": "colmap_equirect",
                "spheresfm_project_manifest": f"{STEP4_META_DIR_NAME}/sfm/{_SPHERESFM_PROJECT_MANIFEST_NAME}",
            },
        }

    @staticmethod
    def _metashape_nerf_output_profile(axis_transform: str, final_orientation: str) -> str:
        if axis_transform in {_AXIS_POSTSHOT, _AXIS_BRUSH}:
            return axis_transform
        if final_orientation == FINAL_ORIENTATION_LICHTFELD:
            return "lichtfeld"
        return "custom"

    def _collect_training_settings(self) -> dict:
        if hasattr(self, "lfs_strategy_combo"):
            self._save_lfs_active_state()
        dataset = self._training_dataset() if self.scene_dir else TrainingDataset(dataset_root=Path(""))
        return {
            "enabled": self.run_training_cb.isChecked(),
            "backend": self._training_backend(),
            "executable": self.training_executable_browse.text(),
            "executables": self._training_executables_for_settings(),
            "dataset_root": str(dataset.dataset_root),
            "images_dir": str(dataset.images_dir or ""),
            "masks_dir": str(dataset.masks_dir or ""),
            "colmap_sparse_dir": str(dataset.colmap_sparse_dir or ""),
            "output_dir": str(self._training_output_dir()) if self.scene_dir else "",
            "lichtfeld_config": str(self._training_config_path()) if self.scene_dir else "",
            "lichtfeld": {
                "strategy": self.lfs_strategy_combo.currentData() or "mrnf",
                "iterations": self.lfs_iterations_edit.text().strip(),
                "max_gaussians": self.lfs_max_gaussians_edit.text().strip(),
                "output_name": self.lfs_output_name_edit.text().strip(),
                "sh_degree": self.lfs_sh_degree_combo.currentData(),
                "steps_scaler": self.lfs_steps_scaler_edit.text().strip(),
                "auto_steps_scaler": self.lfs_auto_steps_scaler_cb.isChecked(),
                "image_count": self._training_image_count(dataset) if self.scene_dir else 0,
                "bilateral_grid": self.lfs_bilateral_grid_cb.isChecked(),
                "mask_mode": self.lfs_mask_mode_combo.currentData() or "none",
                "depth_loss": self.lfs_depth_loss_cb.isChecked(),
                "depth_loss_mode": self.lfs_depth_loss_mode_combo.currentData() or "adaptive-warped-l1",
                "depth_loss_weight": self.lfs_depth_loss_weight_edit.text().strip(),
                "invert_masks": self.lfs_invert_masks_cb.isChecked(),
                "mask_threshold": self.lfs_mask_threshold_edit.text().strip(),
                "use_alpha_as_mask": self.lfs_use_alpha_as_mask_cb.isChecked(),
                "mask_opacity_penalty_weight": self.lfs_mask_opacity_penalty_weight_edit.text().strip(),
                "mask_opacity_penalty_power": self.lfs_mask_opacity_penalty_power_edit.text().strip(),
                "sparsity": self.lfs_sparsity_cb.isChecked(),
                "gut": self.lfs_gut_cb.isChecked(),
                "undistort": self.lfs_undistort_cb.isChecked(),
                "mip_filter": self.lfs_mip_filter_cb.isChecked(),
                "ppisp": self.lfs_ppisp_cb.isChecked(),
                "ppisp_freeze_from_sidecar": self.lfs_ppisp_freeze_from_sidecar_cb.isChecked(),
                "ppisp_use_controller": self.lfs_ppisp_use_controller_cb.isChecked(),
                "ppisp_controller_activation_step": self.lfs_ppisp_controller_activation_step_edit.text().strip(),
                "ppisp_controller_lr": self.lfs_ppisp_controller_lr_edit.text().strip(),
                "ppisp_freeze_gaussians_on_distill": self.lfs_ppisp_freeze_gaussians_on_distill_cb.isChecked(),
                "background_mode": self.lfs_bg_mode_combo.currentData() or "solid_color",
                "background_color": [
                    self.lfs_bg_r_edit.text().strip(),
                    self.lfs_bg_g_edit.text().strip(),
                    self.lfs_bg_b_edit.text().strip(),
                ],
                "background_image": self.lfs_bg_image_browse.text().strip(),
                "advanced": {
                    "numbers": {key: edit.text().strip() for key, edit in self.lfs_advanced_edits.items()},
                    "checks": {key: cb.isChecked() for key, cb in self.lfs_advanced_checks.items()},
                    "ppisp_sidecar_path": self.lfs_ppisp_sidecar_browse.text().strip(),
                },
                "headless": self.training_headless_cb.isChecked(),
            },
            "postshot": {
                "project_name": self.postshot_project_name_edit.text().strip(),
                "profile": self.postshot_profile_combo.currentData() or "Splat3",
                "ksteps": self.postshot_ksteps_edit.text().strip(),
                "auto_ksteps": self.postshot_ksteps_auto_cb.isChecked(),
                "max_image_size": self.postshot_max_image_size_edit.text().strip(),
                "camera_poses": self.postshot_camera_poses_combo.currentData() or "import",
                "import_masks": self.postshot_import_masks_cb.isChecked(),
                "mask_mode": self.postshot_mask_mode_combo.currentData() or "background",
                "image_select": self.postshot_image_select_combo.currentData() or "all",
                "num_train_images": self.postshot_num_train_images_edit.text().strip(),
                "pose_quality": self.postshot_pose_quality_combo.currentData(),
                "gpu_index": self.postshot_gpu_index_edit.text().strip(),
                "splat_density": self.postshot_splat_density_edit.text().strip(),
                "max_num_splats": self.postshot_max_num_splats_edit.text().strip(),
                "anti_aliasing": self.postshot_anti_aliasing_combo.currentData() or "default",
                "max_sh_degree": self.postshot_max_sh_degree_combo.currentData(),
                "create_sky_model": self.postshot_create_sky_model_cb.isChecked(),
                "store_training_context": self.postshot_store_training_context_cb.isChecked(),
                "show_train_error": self.postshot_show_train_error_cb.isChecked(),
                "no_recenter_points": self.postshot_no_recenter_points_cb.isChecked(),
                "crop_box": self.postshot_crop_box_combo.currentData() or "none",
                "crop_box_min": self.postshot_crop_box_min_edit.text().strip(),
                "crop_box_max": self.postshot_crop_box_max_edit.text().strip(),
                "roi_box": self.postshot_roi_box_combo.currentData() or "none",
                "roi_box_min": self.postshot_roi_box_min_edit.text().strip(),
                "roi_box_max": self.postshot_roi_box_max_edit.text().strip(),
                "export_splat": self.postshot_export_splat_edit.text().strip(),
            },
            "brush": {
                "export_name": self.brush_export_name_edit.text().strip(),
                "iterations": self.brush_iterations_edit.text().strip(),
                "export_every": self.brush_export_every_edit.text().strip(),
                "max_resolution": self.brush_max_resolution_edit.text().strip(),
                "sh_degree": self.brush_sh_degree_combo.currentData(),
                "render_mode": self.brush_render_mode_combo.currentData() or "auto",
                "alpha_mode": self.brush_alpha_mode_combo.currentData() or "auto",
                "with_viewer": self.brush_with_viewer_cb.isChecked(),
                "refine_every": self.brush_refine_every_edit.text().strip(),
                "max_splats": self.brush_max_splats_edit.text().strip(),
                "eval_split_every": self.brush_eval_split_every_edit.text().strip(),
                "subsample_frames": self.brush_subsample_frames_edit.text().strip(),
                "subsample_points": self.brush_subsample_points_edit.text().strip(),
            },
            "gsplat": {
                "script_path": self.gsplat_script_browse.text().strip(),
                "result_name": self.gsplat_result_name_edit.text().strip(),
                "strategy": self.gsplat_strategy_combo.currentData() or "default",
                "max_steps": self.gsplat_max_steps_edit.text().strip(),
                "data_factor": self.gsplat_data_factor_edit.text().strip(),
                "test_every": self.gsplat_test_every_edit.text().strip(),
                "save_ply": self.gsplat_save_ply_cb.isChecked(),
                "disable_viewer": self.gsplat_disable_viewer_cb.isChecked(),
                "with_3dgut": self.gsplat_3dgut_cb.isChecked(),
            },
        }

    def _dataset_mask_mode_for_settings(self) -> str:
        if (
            getattr(self, "_dataset_mask_settings_context_enabled", False)
            and getattr(self, "_dataset_mask_step", None) is not None
        ):
            return self._dataset_mask_step.mask_mode()
        return dataset_mask_mode_from_legacy_write_masks(self.export_masks_cb.isChecked())

    def _write_export_settings(self) -> None:
        payload = self._collect_export_settings()
        write_step4_export_settings(Path(self.scene_dir), payload)

    @staticmethod
    def _step4_run_id(prefix: str) -> str:
        return f"{prefix}_{utc_now_iso().replace(':', '').replace('-', '')}"

    def _current_export_settings_snapshot(self) -> dict:
        if not self.scene_dir:
            return {}
        return load_step4_export_settings(Path(self.scene_dir))

    def _step4_artifact_snapshot(self, root: Path) -> dict:
        scene = Path(self.scene_dir)
        settings = self._current_export_settings_snapshot()
        realityscan = settings.get("effective_profile") == _PROFILE_REALITYSCAN
        output_files = settings.get("output_files") if isinstance(settings.get("output_files"), dict) else {}
        transforms_name = str(output_files.get("transforms_json") or "transforms.json")
        pointcloud_name = str(output_files.get("pointcloud") or "pointcloud.ply")
        raw_pointcloud_name = str(output_files.get("raw_metashape_pointcloud") or "metashape.ply")
        masks_dir = root / "images" / "_mask" if realityscan else root / "masks"
        return {
            "root": scene_relative(scene, root),
            "transforms_json": file_identity(root / transforms_name),
            "pointcloud": file_identity(root / pointcloud_name),
            "raw_metashape_pointcloud": file_identity(root / raw_pointcloud_name),
            "images_dir": file_identity(root / "images"),
            "masks_dir": file_identity(masks_dir),
            "colmap_sparse_dir": file_identity(root / "sparse"),
        }

    def _dataset_artifact_metadata(self, root: Path, settings: dict) -> dict:
        output_files = settings.get("output_files") if isinstance(settings.get("output_files"), dict) else {}
        conversion = settings.get("conversion") if isinstance(settings.get("conversion"), dict) else {}
        dataset_masks = settings.get("dataset_masks") if isinstance(settings.get("dataset_masks"), dict) else {}
        return {
            "schema_version": 1,
            "export_method": settings.get("export_method", ""),
            "output_shape": settings.get("output_shape", ""),
            "target_profile": settings.get("target_profile", ""),
            "effective_profile": settings.get("effective_profile", ""),
            "axis_transform": settings.get("axis_transform", ""),
            "transforms_json": output_files.get("transforms_json", ""),
            "pointcloud": output_files.get("pointcloud", ""),
            "raw_metashape_pointcloud": output_files.get("raw_metashape_pointcloud", ""),
            "images_dir": "images" if (root / "images").exists() else "",
            "masks_dir": self._dataset_masks_dir(root, settings),
            "sparse_dir": "sparse/0" if (root / "sparse" / "0").exists() else "",
            "view_config": settings.get("view_config", {}),
            "conversion": {
                "yaw_offset_per_frame": conversion.get("yaw_offset_per_frame", 0.0),
                "output_format": conversion.get("output_format", ""),
                "output_bit_depth": conversion.get("output_bit_depth", ""),
                "write_images": conversion.get("write_images", True),
                "write_masks": conversion.get("write_masks", True),
            },
            "dataset_masks": dataset_masks,
        }

    @staticmethod
    def _dataset_masks_dir(root: Path, settings: dict) -> str:
        if settings.get("effective_profile") == _PROFILE_REALITYSCAN and (root / "images" / "_mask").exists():
            return "images/_mask"
        return "masks" if (root / "masks").exists() else ""

    def _current_dataset_root_for_manifest(self) -> Path:
        if self._is_spheresfm_method():
            if self._uses_spheresfm_3dgut_output():
                return self._spheresfm_3dgut_dir()
            if self._spheresfm_runs_conversion():
                return self._spheresfm_cubemap_dir()
            return self._spheresfm_project_dir()
        if self._is_colmap_method():
            return self._colmap_project_dir()
        if self._uses_direct_equirect_output():
            return self._direct_output_dir()
        return self._display_output_dir()

    def _record_step4_sfm_run(self, mode: str) -> None:
        if not self.scene_dir:
            return
        scene = Path(self.scene_dir)
        route = self._export_method()
        if route == _METHOD_COLMAP:
            project_dir = self._colmap_project_dir()
            sparse_model = self._find_colmap_sparse_model()
        elif route == _METHOD_SPHERESFM:
            project_dir = self._spheresfm_project_dir()
            sparse_model = self._find_spheresfm_sparse_model()
        else:
            project_dir = scene
            sparse_model = self._resolve_ply_source()
        run_id = self._step4_run_id("sfm")
        settings = self._current_export_settings_snapshot()
        append_step4_sfm_run(
            scene,
            {
                "id": run_id,
                "created_at": self._utc_now_iso(),
                "route": route,
                "mode": mode,
                "project_dir": scene_relative(scene, project_dir),
                "sparse_model_dir": scene_relative(scene, sparse_model) if sparse_model else "",
                "ready_for_conversion": sparse_model is not None,
                "settings": settings,
            },
        )
        self._register_step4_sfm_artifact(run_id, route, project_dir, sparse_model, settings)

    def _record_step4_dataset_run(self) -> None:
        if not self.scene_dir:
            return
        scene = Path(self.scene_dir)
        root = self._current_dataset_root_for_manifest()
        run_id = self._step4_run_id("dataset")
        settings = self._current_export_settings_snapshot()
        append_step4_dataset_run(
            scene,
            {
                "id": run_id,
                "created_at": self._utc_now_iso(),
                "route": self._export_method(),
                "output_shape": self._output_shape(),
                "target_profile": self._spheresfm_profile_id() if self._is_spheresfm_method() else self._profile_id(),
                "dataset_root": scene_relative(scene, root),
                "artifacts": self._step4_artifact_snapshot(root),
                "settings": settings,
            },
        )
        dataset_kind = (
            DATASET_KIND_REALITYSCAN_REALIGN_INPUT
            if self._is_metashape_method() and self._effective_profile() == _PROFILE_REALITYSCAN
            else ""
        )
        register_dataset_artifact(
            scene,
            artifact_id=run_id,
            root=root,
            kind=dataset_kind,
            settings=settings,
            metadata=self._dataset_artifact_metadata(root, settings),
        )

    def _register_step4_sfm_artifact(
        self,
        artifact_id: str,
        route: str,
        project_dir: Path,
        sparse_model: Path | None,
        settings: dict,
    ) -> None:
        scene = Path(self.scene_dir)
        if route == _METHOD_COLMAP:
            files = {
                "images_dir": self._colmap_rig_images_dir(),
                "masks_dir": self._colmap_rig_masks_dir(),
                "database": self._colmap_database_path(),
                "sparse_dir": self._colmap_sparse_dir(),
                "rig_config": self._colmap_rig_dir() / "rig_config.json",
            }
            if sparse_model is not None:
                files["sparse_model_dir"] = sparse_model
            register_sfm_artifact(
                scene,
                artifact_id=artifact_id,
                kind=SFM_KIND_COLMAP_SPARSE,
                root=project_dir,
                files=files,
                settings=settings,
                metadata=self._load_colmap_mixed_project_manifest(scene),
            )
        elif route == _METHOD_SPHERESFM:
            files = {
                "images_dir": self._metashape_images_dir(),
                "source_masks_dir": self._mask_dir(),
                "prepared_masks_dir": self._spheresfm_masks_dir(),
                "database": self._spheresfm_database_path(),
                "sparse_dir": self._spheresfm_sparse_dir(),
            }
            if sparse_model is not None:
                files["sparse_model_dir"] = sparse_model
            register_sfm_artifact(
                scene,
                artifact_id=artifact_id,
                kind=SFM_KIND_SPHERESFM_SPARSE,
                root=project_dir,
                files=files,
                settings=settings,
            )
        else:
            register_sfm_artifact(
                scene,
                artifact_id=artifact_id,
                kind=SFM_KIND_METASHAPE_XML_PLY,
                root=scene,
                files={
                    "images_dir": self._metashape_images_dir(),
                    "masks_dir": self._mask_dir(),
                    "xml": self.ms_xml_browse.text(),
                    "ply": self.ms_ply_browse.text(),
                },
                settings=settings,
            )

    def _record_step4_training_run(self) -> None:
        if not self.scene_dir or not self.run_training_cb.isChecked():
            return
        scene = Path(self.scene_dir)
        dataset = self._training_dataset()
        append_step4_training_run(
            scene,
            {
                "id": self._step4_run_id("training"),
                "created_at": self._utc_now_iso(),
                "backend": self._training_backend(),
                "dataset_root": scene_relative(scene, dataset.dataset_root),
                "output_dir": scene_relative(scene, self._training_output_dir()),
                "logs": self._training_log_snapshot(scene),
                "settings": self._collect_training_settings(),
            },
        )

    def _training_log_snapshot(self, scene: Path) -> dict[str, object]:
        log_dir = self.training_process_log_dir()
        return {
            "log_dir": scene_relative(scene, log_dir) if log_dir is not None else "",
            "phase_logs": {
                phase: scene_relative(scene, path) for phase, path in sorted(self._training_phase_logs.items())
            },
        }

    def _record_step4_runs(self, *, sfm_mode: str | None, dataset: bool) -> None:
        if sfm_mode:
            self._record_step4_sfm_run(sfm_mode)
        if dataset:
            self._record_step4_dataset_run()

    def _write_colmap_project_manifest(self) -> None:
        project = self._colmap_project_dir()
        sparse_model = self._find_colmap_sparse_model()
        manifest_path = step4_meta_dir(Path(self.scene_dir)) / "sfm" / _COLMAP_PROJECT_MANIFEST_NAME
        mixed_manifest = self._load_colmap_mixed_project_manifest(Path(self.scene_dir))
        payload = {
            "app": "stechdrive-3dgs-utils",
            "app_version": APP_VERSION,
            "export_type": "colmap_project",
            "created_at": self._utc_now_iso(),
            "project_dir": str(project),
            "images_dir": "images",
            "masks_dir": "masks",
            "sparse_dir": "sparse",
            "sparse_model_dir": self._path_text_relative_to(sparse_model, project) if sparse_model else "",
            "ready_for_import": sparse_model is not None,
            "database": "database.db",
            "rig_config": "rig_config.json",
            "run_sfm": self._colmap_sfm_intent,
            "matcher": self.colmap_matcher_combo.currentData() or _COLMAP_MATCHER_SEQUENTIAL,
            "mapper": self.colmap_mapper_combo.currentData() or _COLMAP_MAPPER_INCREMENTAL,
            "camera_model": "PINHOLE",
            "camera_params": self._colmap_camera_params_arg(),
        }
        if mixed_manifest:
            payload["input_project"] = {
                "export_type": mixed_manifest.get("export_type", ""),
                "erp_source_count": mixed_manifest.get("erp_source_count", 0),
                "normal_source_count": mixed_manifest.get("normal_source_count", 0),
                "rig_image_count": mixed_manifest.get("rig_image_count", 0),
                "normal_image_count": mixed_manifest.get("normal_image_count", 0),
                "normal_camera_model": mixed_manifest.get("normal_camera_model", ""),
                "normal_camera_groups": mixed_manifest.get("normal_camera_groups", []),
                "warnings": mixed_manifest.get("warnings", []),
            }
        project.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_colmap_mixed_project_manifest(scene: Path) -> dict[str, object]:
        path = step4_meta_dir(scene) / "sfm" / COLMAP_MIXED_MANIFEST
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_spheresfm_project_manifest(self) -> None:
        project = self._spheresfm_project_dir()
        sparse_model = self._find_spheresfm_sparse_model()
        manifest_path = step4_meta_dir(Path(self.scene_dir)) / "sfm" / _SPHERESFM_PROJECT_MANIFEST_NAME
        payload = {
            "app": "stechdrive-3dgs-utils",
            "app_version": APP_VERSION,
            "export_type": "spheresfm_project",
            "created_at": self._utc_now_iso(),
            "project_dir": str(project),
            "images_dir": str(self._metashape_images_dir()),
            "source_masks_dir": str(self._mask_dir()),
            "prepared_masks_dir": "masks_colmap",
            "sparse_dir": "sparse",
            "sparse_model_dir": self._path_text_relative_to(sparse_model, project) if sparse_model else "",
            "ready_for_import": sparse_model is not None,
            "database": "database.db",
            "use_masks": self._spheresfm_uses_masks(),
            "matcher": _COLMAP_MATCHER_SEQUENTIAL,
            "loop_detection": self.spheresfm_loop_detection_cb.isChecked(),
            "quality_preset": self._spheresfm_quality_preset(),
            "run_scope": self._spheresfm_run_scope(),
            "pose_path": self.spheresfm_pose_browse.text(),
            "camera_model": "EQUIRECTANGULAR",
            "camera_params": self._spheresfm_camera_params_arg(),
            "output_shape": self._output_shape(),
            "target_profile": self._spheresfm_profile_id(),
            "effective_profile": self._spheresfm_effective_profile(),
            "axis_transform": self._spheresfm_axis_transform_mode(),
            "equirect_dir": "equirect",
            "cubemap_dir": str(self._spheresfm_cubemap_dir()),
            "gut_dir": str(self._spheresfm_3dgut_dir()),
        }
        project.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
