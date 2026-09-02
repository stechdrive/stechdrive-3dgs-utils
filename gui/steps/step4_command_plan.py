"""Step 4 command planning and executable resolution."""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

from core.colmap_cli import prefer_official_windows_launcher
from core.colmap_mixed_project import COLMAP_MIXED_MANIFEST, colmap_erp_rig_groups_for_images
from core.colmap_normal_camera_contract import normal_camera_groups_for_images
from core.dataset_job_spec import metashape_nerf_job, write_dataset_job
from core.metashape_nerf_dataset import (
    analyze_metashape_nerf_compatibility,
    metashape_model_requires_mixed_nerf_writer,
)
from core.orientation_correction import (
    FINAL_ORIENTATION_LICHTFELD,
    FINAL_ORIENTATION_NONE,
    FINAL_ORIENTATION_REALITYSCAN,
)
from core.scene_inventory import build_scene_inventory
from core.scene_layout import jobs_dir, step4_meta_dir
from core.sfm_input_plan import (
    SFM_ACTION_EXPAND_ERP_TO_RIG_VIEWS,
    SFM_ACTION_LINK_OR_COPY_NORMAL_IMAGE,
    SfmInputPlan,
    build_colmap_mixed_sfm_input_plan,
)
from core.sfm_job_spec import colmap_mixed_project_job, write_sfm_job
from core.workflow_job_spec import (
    cubemap_conversion_job,
    metashape_preprocess_job,
    spheresfm_preflight_job,
    spheresfm_prepare_job,
    spheresfm_transforms_job,
    transforms_to_colmap_job,
    write_workflow_job,
)
from gui import i18n
from gui.common.runner_types import StepCommand, StepCommandQueue
from gui.cubemap.view_config import _BLOCK_ENABLED_VIEWS
from gui.steps.cubemap_commands import (
    ColmapMixedPrepareCommand,
    ColmapNormalFeatureGroup,
    ColmapRigFeatureGroup,
    ColmapSfmCommand,
    MetashapeNerfCommand,
    SphereSfmCommand,
    build_colmap_mixed_prepare_cmd,
    build_colmap_sfm_commands,
    build_metashape_nerf_cmd,
    build_spheresfm_commands,
)
from gui.steps.step4_contracts import (
    _COLMAP_MAPPER_GLOMAP,
    _COLMAP_MAPPER_INCREMENTAL,
    _COLMAP_MATCHER_SEQUENTIAL,
    _PIPELINE_STAGE_CONVERSION,
    _PIPELINE_STAGE_SFM,
    _PROFILE_LICHTFELD,
    _PROFILE_REALITYSCAN,
)
from gui.steps.workflow_job_commands import build_workflow_job_cmd


class Step4CommandPlanMixin:
    def build_commands(self) -> StepCommandQueue:
        if self._is_spheresfm_method():
            self._reset_spheresfm_rtx50_diagnostics()
            run_sfm = self._spheresfm_runs_sfm()
            run_conversion = self._spheresfm_runs_conversion()
            if run_sfm or run_conversion:
                self._validate_spheresfm_export()
            if run_conversion and not run_sfm:
                self._require_spheresfm_sparse_model()
                self._validate_spheresfm_conversion_export()
                if not self._prepare_spheresfm_run_outputs(include_project=False, include_conversion=True):
                    return []
                return [
                    *self._dataset_mask_pre_commands(),
                    *self._build_spheresfm_conversion_commands(),
                    *self._dataset_mask_followup_commands(),
                ]

            steps: StepCommandQueue = []
            if run_sfm:
                if not self._prepare_spheresfm_run_outputs(
                    include_project=True,
                    include_conversion=run_conversion,
                ):
                    return []
                steps.extend(self._build_spheresfm_sfm_commands())
            if run_conversion:
                self._validate_spheresfm_conversion_export()
                steps.extend(self._dataset_mask_pre_commands())
                steps.extend(self._build_spheresfm_conversion_commands())
                steps.extend(self._dataset_mask_followup_commands())
            return steps

        if self._is_colmap_method():
            run_conversion = self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION)
            run_sfm = self.pipeline_stage_intent(_PIPELINE_STAGE_SFM)
            plan: SfmInputPlan | None = None
            if run_conversion or run_sfm:
                self._validate_image_only_export()
                plan = self._validate_colmap_source_plan()
            if run_conversion and not self._prepare_colmap_rig_dir():
                return []
            steps: StepCommandQueue = []
            if run_conversion:
                steps.extend(self._dataset_mask_pre_commands())
                if self._colmap_plan_has_normal_images(plan) or self._colmap_plan_has_multi_resolution_erp(plan):
                    steps.append(("colmap_mixed_prepare", self._build_colmap_mixed_prepare_cmd()))
                else:
                    steps.append(("colmap_rig_export", self._build_cubemap_cmd(image_only=True, colmap_rig=True)))
            if run_sfm:
                if not run_conversion and not self._colmap_rig_images_dir().is_dir():
                    raise ValueError(i18n.t("STEP4_PIPELINE_DETAIL_COLMAP_NEEDS_RIG"))
                if not run_conversion and not self._prepare_colmap_sfm_outputs():
                    return []
                steps.extend(self._build_colmap_sfm_commands(plan=plan, prepared_this_run=run_conversion))
            return steps

        run_conversion = self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION)
        if run_conversion:
            self._validate_bundle()
            if self._uses_metashape_nerf_dataset_writer():
                if self.export_colmap_cb.isChecked():
                    raise ValueError(i18n.t("METASHAPE_MIXED_NERF_COLMAP_OPTION_UNSUPPORTED"))
                nerf_cmd = self._build_metashape_nerf_cmd()
                if not self._prepare_output_dir():
                    return []
                self._write_views_config(
                    step4_meta_dir(Path(self.scene_dir)),
                    self.view_config.collect_views(include_disabled=True),
                )
                return [
                    *self._dataset_mask_pre_commands(),
                    ("metashape_nerf", nerf_cmd),
                    *self._dataset_mask_followup_commands(),
                ]
            if self._uses_direct_equirect_output() and self._metashape_model_requires_projected_writer():
                raise ValueError(i18n.t("METASHAPE_MIXED_NERF_DIRECT_OUTPUT_UNSUPPORTED"))
            preprocess_cmd = self._build_preprocess_cmd()

        if not run_conversion:
            return []

        if self._uses_direct_equirect_output():
            if not self._prepare_3dgut_output_dir():
                return []
            return [
                *self._dataset_mask_pre_commands(),
                ("metashape", preprocess_cmd),
                *self._dataset_mask_followup_commands(),
            ]

        if not self._prepare_output_dir():
            return []
        self._prepare_metashape_import_work_dir()

        steps = [*self._dataset_mask_pre_commands(), ("metashape", preprocess_cmd)]
        steps.append(("cubemap", self._build_cubemap_cmd()))
        if self.export_colmap_cb.isChecked():
            steps.append(("colmap", self._build_colmap_cmd()))
        steps.extend(self._dataset_mask_followup_commands())
        return steps

    def _dataset_mask_pre_commands(self) -> StepCommandQueue:
        if (
            not getattr(self, "_dataset_mask_settings_context_enabled", False)
            or getattr(self, "_dataset_mask_step", None) is None
        ):
            return []
        self._dataset_mask_step.set_dataset_projection(self._dataset_output_projection())
        if self.scene_dir and self._dataset_mask_step.scene_dir != self.scene_dir:
            self._dataset_mask_step.set_scene_dir(self.scene_dir)
        return self._dataset_mask_step.build_source_mask_commands()

    def _dataset_mask_followup_commands(self) -> StepCommandQueue:
        if (
            not getattr(self, "_dataset_mask_settings_context_enabled", False)
            or getattr(self, "_dataset_mask_step", None) is None
        ):
            return []
        self._dataset_mask_step.set_dataset_projection(self._dataset_output_projection())
        if self.scene_dir and self._dataset_mask_step.scene_dir != self.scene_dir:
            self._dataset_mask_step.set_scene_dir(self.scene_dir)
        commands = self._dataset_mask_step.build_followup_commands(require_existing_images=not self._writes_images())
        if self._dataset_mask_needs_output_sync():
            return [self._dataset_mask_step.build_output_mask_sync_command(), *commands]
        return commands

    def _uses_metashape_nerf_dataset_writer(self) -> bool:
        return (
            self._is_metashape_method()
            and self._effective_profile() != _PROFILE_REALITYSCAN
            and not self._uses_direct_equirect_output()
        )

    def _metashape_model_requires_projected_writer(self) -> bool:
        if not self._is_metashape_method() or self._effective_profile() == _PROFILE_REALITYSCAN:
            return False
        self._refresh_metashape_auto_inputs_if_empty()
        xml = self.ms_xml_browse.text().strip()
        if not xml or not Path(xml).is_file():
            return False
        try:
            return metashape_model_requires_mixed_nerf_writer(xml)
        except Exception:
            return False

    def _validate_colmap_source_plan(self) -> SfmInputPlan:
        inventory = build_scene_inventory(Path(self.scene_dir))
        plan = build_colmap_mixed_sfm_input_plan(inventory)
        if plan.issues:
            details = "\n".join(f"- {issue.message}" for issue in plan.issues)
            raise ValueError(i18n.t("COLMAP_MIXED_PREFLIGHT_FAILED").format(details=details))
        return plan

    @staticmethod
    def _colmap_plan_has_normal_images(plan: SfmInputPlan | None) -> bool:
        return bool(plan and plan.items_for_action(SFM_ACTION_LINK_OR_COPY_NORMAL_IMAGE))

    @staticmethod
    def _colmap_plan_has_erp_images(plan: SfmInputPlan | None) -> bool:
        return bool(plan and plan.items_for_action(SFM_ACTION_EXPAND_ERP_TO_RIG_VIEWS))

    def _colmap_plan_has_multi_resolution_erp(self, plan: SfmInputPlan | None) -> bool:
        if not self._colmap_plan_has_erp_images(plan) or not self.scene_dir:
            return False
        inventory = build_scene_inventory(Path(self.scene_dir))
        sizes = {image.size for image in inventory.equirectangular_images() if image.size is not None}
        return len(sizes) > 1

    def _build_preprocess_cmd(self) -> StepCommand:
        self._refresh_metashape_auto_inputs_if_empty()
        scene = Path(self.scene_dir)
        if not scene.is_dir():
            raise ValueError(f"シーンフォルダが見つかりません: {scene}")

        images = str(self._metashape_images_dir())
        xml = self.ms_xml_browse.text()
        if not images or not Path(images).is_dir():
            raise ValueError(f"Metashape画像フォルダが見つかりません: {images}")
        if not xml or not Path(xml).is_file():
            raise ValueError(f"Metashape XMLが見つかりません: {xml}")
        if self._metashape_input_output_path_issue(Path(xml)):
            raise ValueError(i18n.t("METASHAPE_INPUT_IN_OUTPUT_ERROR").format(path=xml))

        scale = float(self.ms_scale_edit.text().strip())
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("スケール係数は正の有限値である必要があります")

        ply = ""
        if self._preprocess_uses_ply():
            ply = self.ms_ply_browse.text()
            if not ply or not Path(ply).is_file():
                raise ValueError(f"PLYファイルが見つかりません: {ply}")
            if self._metashape_input_output_path_issue(Path(ply)):
                raise ValueError(i18n.t("METASHAPE_INPUT_IN_OUTPUT_ERROR").format(path=ply))
        job_path = jobs_dir(scene) / "metashape_preprocess_job.json"
        write_workflow_job(
            job_path,
            metashape_preprocess_job(
                images_dir=Path(images),
                xml_path=xml,
                output_dir=(
                    self._display_output_dir()
                    if self._uses_direct_equirect_output()
                    else self._metashape_import_work_dir()
                ),
                scale=scale,
                use_ply=self._preprocess_uses_ply(),
                ply_path=ply if ply else None,
                no_fix_rotation=self.ms_no_fix_rot_cb.isChecked(),
                lichtfeld_camera_y180=self._uses_lichtfeld_final_correction(),
            ),
        )
        return build_workflow_job_cmd(self.base_dir, job_path)

    def _build_cubemap_cmd(self, image_only: bool = False, colmap_rig: bool = False) -> StepCommand:
        scene = Path(self.scene_dir)
        if not scene.is_dir():
            raise ValueError(f"シーンフォルダが見つかりません: {scene}")

        output = self._display_output_dir() if (not image_only and self._is_metashape_method()) else self._output_dir()
        input_dir = scene
        image_dir = None
        mask_dir = None
        if not image_only and self._is_metashape_method():
            input_dir = self._metashape_import_work_dir()
            image_dir = scene
            mask_dir = self._dataset_input_mask_dir_for_conversion(require_existing=False)
        elif image_only and colmap_rig:
            mask_dir = self._dataset_input_mask_dir_for_conversion(require_existing=False)

        views = self.view_config.collect_views(include_disabled=True)
        enabled = sum(1 for v in views if v["enabled"])
        if enabled <= 0:
            raise ValueError("少なくとも1つのビューを有効にしてください")
        if enabled > _BLOCK_ENABLED_VIEWS:
            raise ValueError(f"ビュー数が多すぎます ({enabled})。{_BLOCK_ENABLED_VIEWS} 以下にしてください。")

        _views_json = self._write_views_config(step4_meta_dir(scene), views)

        if colmap_rig or self._effective_profile() == _PROFILE_REALITYSCAN:
            yaw_step = 0.0
        else:
            yaw_step = float(self.yaw_per_frame_edit.value())

        out_fmt = self.output_format_combo.currentData() or "auto"
        out_depth = self.output_bit_depth_combo.currentData() or "8"

        try:
            jpgq = int(self.jpg_quality_edit.text().strip())
        except ValueError as exc:
            raise ValueError("JPG/WebP 品質は整数で指定してください") from exc
        if not 1 <= jpgq <= 100:
            raise ValueError("JPG/WebP 品質は 1-100 の範囲で指定してください")
        suffix = "colmap_rig" if colmap_rig else ("image_only" if image_only else "cubemap")
        job_path = jobs_dir(scene) / f"{suffix}_conversion_job.json"
        write_workflow_job(
            job_path,
            cubemap_conversion_job(
                input_dir=input_dir,
                output_dir=output,
                views=views,
                fov=90.0,
                output_scale=float(self.scale_combo.currentData()),
                axis_mode=self._axis_transform_mode(),
                image_only=image_only,
                colmap_rig=colmap_rig,
                invert_masks=self.invert_masks_cb.isChecked(),
                write_images=self._writes_images(),
                write_masks=self._writes_masks(),
                yaw_offset_per_frame=yaw_step,
                output_format=out_fmt,
                output_bit_depth=out_depth,
                jpg_quality=jpgq,
                input_json="transforms.json",
                image_dir=image_dir,
                mask_dir=mask_dir,
                final_orientation=self._cubemap_final_orientation(),
                realityscan_xmp=self._is_metashape_method() and self._effective_profile() == _PROFILE_REALITYSCAN,
                realityscan_pose_prior=self.realityscan_pose_prior_combo.currentData() or "exact",
                realityscan_calibration_prior=self.realityscan_calibration_prior_combo.currentData() or "exact",
                realityscan_coordinates="auto",
                realityscan_include_rig=self.realityscan_include_rig_cb.isChecked(),
                realityscan_unposed_scene_dir=scene if self._effective_profile() == _PROFILE_REALITYSCAN else None,
                realityscan_unposed_images=self._is_metashape_method()
                and self._effective_profile() == _PROFILE_REALITYSCAN,
            ),
        )
        return build_workflow_job_cmd(self.base_dir, job_path)

    def _build_metashape_nerf_cmd(self) -> StepCommand:
        scene = Path(self.scene_dir)
        if not scene.is_dir():
            raise ValueError(f"シーンフォルダが見つかりません: {scene}")
        images = self._metashape_images_dir()
        if not images.is_dir():
            raise ValueError(f"Metashape画像フォルダが見つかりません: {images}")
        xml = self.ms_xml_browse.text().strip()
        if not xml or not Path(xml).is_file():
            raise ValueError(f"Metashape XMLが見つかりません: {xml}")
        if self._metashape_input_output_path_issue(Path(xml)):
            raise ValueError(i18n.t("METASHAPE_INPUT_IN_OUTPUT_ERROR").format(path=xml))

        ply = self.ms_ply_browse.text().strip()
        if self._preprocess_uses_ply() and not ply:
            raise ValueError("PLYファイルが見つかりません")
        if ply and not Path(ply).is_file():
            raise ValueError(f"PLYファイルが見つかりません: {ply}")
        if ply and self._metashape_input_output_path_issue(Path(ply)):
            raise ValueError(i18n.t("METASHAPE_INPUT_IN_OUTPUT_ERROR").format(path=ply))

        views = self.view_config.collect_views(include_disabled=True)
        enabled = sum(1 for v in views if v["enabled"])
        if enabled <= 0:
            raise ValueError("少なくとも1つのビューを有効にしてください")
        if enabled > _BLOCK_ENABLED_VIEWS:
            raise ValueError(f"ビュー数が多すぎます ({enabled})。{_BLOCK_ENABLED_VIEWS} 以下にしてください。")

        try:
            jpgq = int(self.jpg_quality_edit.text().strip())
        except ValueError as exc:
            raise ValueError("JPG/WebP 品質は整数で指定してください") from exc
        if not 1 <= jpgq <= 100:
            raise ValueError("JPG/WebP 品質は 1-100 の範囲で指定してください")

        masks = self._dataset_input_mask_dir_for_conversion(require_existing=False)
        if self._effective_profile() == _PROFILE_LICHTFELD:
            compatibility = analyze_metashape_nerf_compatibility(
                scene_dir=scene,
                images_dir=images,
                masks_dir=masks,
                xml_path=Path(xml),
                views=views,
                output_scale=float(self.scale_combo.currentData()),
                undistort_alpha=1.0,
            )
            if not compatibility.lichtfeld_nerf_supported:
                raise ValueError(
                    i18n.t("METASHAPE_LICHTFELD_NERF_MULTICAMERA_UNSUPPORTED").format(
                        groups=compatibility.camera_group_count,
                        frames=compatibility.frame_count,
                    )
                )
        job_path = jobs_dir(scene) / "metashape_nerf_job.json"
        write_dataset_job(
            job_path,
            metashape_nerf_job(
                scene_dir=scene,
                images_dir=images,
                masks_dir=masks,
                xml_path=Path(xml),
                ply_path=Path(ply) if ply else None,
                output_dir=self._display_output_dir(),
                views=views,
                output_scale=float(self.scale_combo.currentData()),
                output_format=self.output_format_combo.currentData() or "auto",
                output_bit_depth=self.output_bit_depth_combo.currentData() or "8",
                jpg_quality=jpgq,
                undistort_alpha=1.0,
                axis_transform=self._axis_transform_mode(),
                final_orientation=self._cubemap_final_orientation(),
                write_images=self._writes_images(),
                write_masks=self._writes_masks(),
            ),
        )
        return build_metashape_nerf_cmd(
            MetashapeNerfCommand(
                job=job_path,
            )
        )

    def _build_colmap_mixed_prepare_cmd(self) -> StepCommand:
        scene = Path(self.scene_dir)
        if not scene.is_dir():
            raise ValueError(f"シーンフォルダが見つかりません: {scene}")
        views = self.view_config.collect_views(include_disabled=True)
        enabled = sum(1 for v in views if v["enabled"])
        if enabled <= 0:
            raise ValueError("少なくとも1つのビューを有効にしてください")
        if enabled > _BLOCK_ENABLED_VIEWS:
            raise ValueError(f"ビュー数が多すぎます ({enabled})。{_BLOCK_ENABLED_VIEWS} 以下にしてください。")
        _views_json = self._write_views_config(step4_meta_dir(scene), views)
        job_path = jobs_dir(scene) / "colmap_mixed_project_job.json"
        write_sfm_job(
            job_path,
            colmap_mixed_project_job(
                scene_dir=scene,
                output_dir=self._output_dir(),
                views=views,
                output_scale=float(self.scale_combo.currentData()),
                output_format=self.output_format_combo.currentData() or "auto",
                output_bit_depth=self.output_bit_depth_combo.currentData() or "8",
                jpg_quality=int(self.jpg_quality_edit.text().strip()),
                write_images=self._writes_images(),
                write_masks=self._writes_masks(),
                invert_masks=self.invert_masks_cb.isChecked(),
                source_masks_dir=self._dataset_input_mask_dir_for_conversion(require_existing=False),
                workers="auto",
                remap_cache_limit="auto",
                rig_name="rig1",
            ),
        )
        return build_colmap_mixed_prepare_cmd(
            ColmapMixedPrepareCommand(
                job=job_path,
            )
        )

    def _cubemap_final_orientation(self) -> str:
        if self._is_realityscan_profile():
            return FINAL_ORIENTATION_REALITYSCAN
        if self._uses_lichtfeld_final_correction():
            return FINAL_ORIENTATION_LICHTFELD
        return FINAL_ORIENTATION_NONE

    def _build_colmap_cmd(self) -> StepCommand:
        output = self._display_output_dir()
        colmap_dir = output / "colmap"

        ply_path: Path | None = None
        ply = output / "pointcloud.ply"
        if ply.is_file():
            ply_path = ply
        else:
            # cubemap 出力ディレクトリ内の任意 .ply をフォールバック
            plys = sorted([p for p in output.glob("*.ply") if p.is_file()])
            if plys:
                ply_path = plys[0]
        job_path = jobs_dir(Path(self.scene_dir)) / "transforms_to_colmap_job.json"
        write_workflow_job(
            job_path,
            transforms_to_colmap_job(
                input_dir=output,
                output_dir=colmap_dir,
                ply_path=ply_path,
                json_name="transforms.json",
                image_prefix="images",
            ),
        )
        return build_workflow_job_cmd(self.base_dir, job_path)

    def _default_glomap_executable(self) -> str:
        return "glomap.exe" if os.name == "nt" else "glomap"

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        return any(sep in value for sep in ("/", "\\")) or Path(value).is_absolute()

    def _resolve_executable(self, raw: str, default_name: str, message_key: str) -> str:
        value = raw.strip() or default_name
        if self._looks_like_path(value):
            path = Path(value)
            if not path.is_file():
                raise ValueError(i18n.t(message_key).format(path=value))
            return str(path)
        found = shutil.which(value)
        if not found:
            raise ValueError(i18n.t(message_key).format(path=value))
        return found

    def _resolve_colmap_launcher(self, raw: str, message_key: str) -> str:
        value = raw.strip()
        if value:
            resolved = self._resolve_executable(value, "colmap.exe" if os.name == "nt" else "colmap", message_key)
            return prefer_official_windows_launcher(resolved)

        default_names = ("COLMAP.bat", "colmap.exe") if os.name == "nt" else ("colmap",)
        for default_name in default_names:
            found = shutil.which(default_name)
            if found:
                return prefer_official_windows_launcher(found)
        raise ValueError(i18n.t(message_key).format(path=" / ".join(default_names)))

    def _resolve_colmap_executable(self) -> str:
        return self._resolve_colmap_launcher(self.colmap_exec_browse.text(), "COLMAP_EXEC_NOT_FOUND")

    def _resolve_spheresfm_executable(self) -> str:
        return self._resolve_colmap_launcher(self.spheresfm_exec_browse.text(), "SPHERESFM_EXEC_NOT_FOUND")

    def _resolve_glomap_executable(self) -> str:
        return self._resolve_executable(
            self.glomap_exec_browse.text(),
            self._default_glomap_executable(),
            "GLOMAP_EXEC_NOT_FOUND",
        )

    def _build_colmap_sfm_commands(
        self,
        *,
        plan: SfmInputPlan | None = None,
        prepared_this_run: bool = False,
    ) -> StepCommandQueue:
        colmap = self._resolve_colmap_executable()
        rig_dir = self._colmap_rig_dir()
        images_dir = self._colmap_rig_images_dir()
        masks_dir = self._colmap_rig_masks_dir()
        database = self._colmap_database_path()
        sparse = self._colmap_sparse_dir()

        matcher = self.colmap_matcher_combo.currentData() or _COLMAP_MATCHER_SEQUENTIAL
        mapper = self.colmap_mapper_combo.currentData() or _COLMAP_MAPPER_INCREMENTAL
        glomap = (
            self._resolve_glomap_executable() if mapper == _COLMAP_MAPPER_GLOMAP else self._default_glomap_executable()
        )
        normal_list = self._colmap_normal_image_list_path()
        rig_list = self._colmap_rig_image_list_path()
        has_normal = self._colmap_plan_has_normal_images(plan) or self._image_list_has_entries(normal_list)
        has_erp = self._colmap_plan_has_erp_images(plan) or self._image_list_has_entries(rig_list)
        if prepared_this_run and self._colmap_plan_has_normal_images(plan):
            has_erp = self._colmap_plan_has_erp_images(plan)
            has_normal = True
        if has_normal and not prepared_this_run and not self._image_list_has_entries(normal_list):
            raise ValueError(i18n.t("STEP4_PIPELINE_DETAIL_COLMAP_NEEDS_RIG"))
        use_split_lists = has_normal and (prepared_this_run or self._image_list_has_entries(normal_list))
        rig_feature_groups = self._colmap_rig_feature_groups(plan=plan, prepared_this_run=prepared_this_run)
        normal_feature_groups = self._colmap_normal_feature_groups(plan=plan, prepared_this_run=prepared_this_run)
        return build_colmap_sfm_commands(
            ColmapSfmCommand(
                colmap=colmap,
                glomap=glomap,
                rig_dir=rig_dir,
                images_dir=images_dir,
                masks_dir=masks_dir,
                database=database,
                sparse=sparse,
                camera_params=self._colmap_camera_params_arg(),
                writes_images=self._writes_images(),
                writes_masks=self._writes_masks(),
                use_existing_masks=not prepared_this_run,
                matcher=matcher,
                mapper=mapper,
                run_rig_feature=not use_split_lists or has_erp,
                run_rig_config=not use_split_lists or has_erp,
                run_normal_feature=has_normal,
                rig_image_list=rig_list if use_split_lists and has_erp else None,
                normal_image_list=normal_list if has_normal else None,
                rig_feature_groups=rig_feature_groups,
                normal_feature_groups=normal_feature_groups,
            )
        )

    def _colmap_rig_image_list_path(self) -> Path:
        return self._colmap_rig_dir() / "rig_image_list.txt"

    def _colmap_normal_image_list_path(self) -> Path:
        return self._colmap_rig_dir() / "normal_image_list.txt"

    @staticmethod
    def _image_list_has_entries(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            return any(line.strip() for line in path.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False

    def _colmap_normal_feature_groups(
        self,
        *,
        plan: SfmInputPlan | None,
        prepared_this_run: bool,
    ) -> tuple[ColmapNormalFeatureGroup, ...]:
        if prepared_this_run and self._colmap_plan_has_normal_images(plan):
            inventory = build_scene_inventory(Path(self.scene_dir))
            groups = normal_camera_groups_for_images(list(inventory.normal_images()))
            return tuple(
                ColmapNormalFeatureGroup(
                    image_list=self._colmap_rig_dir() / f"normal_image_list_{group.group_id}.txt",
                    camera_model=group.camera_model,
                    camera_params=self._colmap_camera_params_text(group.camera_params),
                )
                for group in groups
            )
        return self._colmap_normal_feature_groups_from_manifest()

    def _colmap_rig_feature_groups(
        self,
        *,
        plan: SfmInputPlan | None,
        prepared_this_run: bool,
    ) -> tuple[ColmapRigFeatureGroup, ...]:
        if prepared_this_run and self._colmap_plan_has_erp_images(plan):
            inventory = build_scene_inventory(Path(self.scene_dir))
            erp_images = list(inventory.equirectangular_images())
            views = [dict(view) for view in self.view_config.collect_views(include_disabled=True) if view.get("enabled", True)]
            groups = colmap_erp_rig_groups_for_images(
                inventory,
                erp_images,
                views=views,
                output_scale=float(self.scale_combo.currentData()),
                output_format=str(self.output_format_combo.currentData() or "auto"),
            )
            return tuple(
                ColmapRigFeatureGroup(
                    image_list=self._colmap_rig_dir() / group.image_list_name,
                    camera_params=self._colmap_camera_params_text(group.camera_params),
                )
                for group in groups
            )
        return self._colmap_rig_feature_groups_from_manifest()

    def _colmap_rig_feature_groups_from_manifest(self) -> tuple[ColmapRigFeatureGroup, ...]:
        path = step4_meta_dir(Path(self.scene_dir)) / "sfm" / COLMAP_MIXED_MANIFEST
        if not path.is_file():
            return ()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        raw_groups = data.get("rig_camera_groups")
        if not isinstance(raw_groups, list):
            return ()
        groups: list[ColmapRigFeatureGroup] = []
        for item in raw_groups:
            if not isinstance(item, dict):
                continue
            image_list = str(item.get("image_list") or "").strip()
            if not image_list:
                continue
            groups.append(
                ColmapRigFeatureGroup(
                    image_list=self._colmap_rig_dir() / image_list,
                    camera_params=self._colmap_camera_params_text(item.get("camera_params")),
                )
            )
        return tuple(groups)

    def _colmap_normal_feature_groups_from_manifest(self) -> tuple[ColmapNormalFeatureGroup, ...]:
        path = step4_meta_dir(Path(self.scene_dir)) / "sfm" / COLMAP_MIXED_MANIFEST
        if not path.is_file():
            return ()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        raw_groups = data.get("normal_camera_groups")
        if not isinstance(raw_groups, list):
            return ()
        groups: list[ColmapNormalFeatureGroup] = []
        for item in raw_groups:
            if not isinstance(item, dict):
                continue
            image_list = str(item.get("image_list") or "").strip()
            camera_model = str(item.get("camera_model") or "").strip().upper()
            if not image_list or not camera_model:
                continue
            groups.append(
                ColmapNormalFeatureGroup(
                    image_list=self._colmap_rig_dir() / image_list,
                    camera_model=camera_model,
                    camera_params=self._colmap_camera_params_text(item.get("camera_params")),
                )
            )
        return tuple(groups)

    @staticmethod
    def _colmap_camera_params_text(value: object) -> str:
        if not isinstance(value, (list, tuple)):
            return ""
        try:
            params = [float(item) for item in value]
        except (TypeError, ValueError):
            return ""
        return ",".join(f"{param:.12g}" for param in params)

    def _build_spheresfm_sfm_commands(self) -> StepCommandQueue:
        matcher = self.spheresfm_matcher_combo.currentData() or _COLMAP_MATCHER_SEQUENTIAL
        quality_preset = self._spheresfm_quality_preset()
        use_masks = self._spheresfm_uses_masks()

        colmap = self._resolve_spheresfm_executable()
        scene = Path(self.scene_dir)
        preflight_job_path = jobs_dir(scene) / "spheresfm_preflight_job.json"
        prepare_job_path = jobs_dir(scene) / "spheresfm_prepare_job.json"
        write_workflow_job(
            preflight_job_path,
            spheresfm_preflight_job(
                colmap=colmap,
                images_dir=self._metashape_images_dir(),
                work_dir=self._spheresfm_preflight_dir(),
                camera_params=self._spheresfm_camera_params_arg(),
                matcher=matcher,
                quality_preset=quality_preset,
                use_masks=use_masks,
            ),
        )
        write_workflow_job(
            prepare_job_path,
            spheresfm_prepare_job(
                colmap=colmap,
                images_dir=self._metashape_images_dir(),
                source_masks_dir=self._mask_dir(),
                output_masks_dir=self._spheresfm_masks_dir(),
                use_masks=use_masks,
            ),
        )
        steps = build_spheresfm_commands(
            SphereSfmCommand(
                colmap=colmap,
                images_dir=self._metashape_images_dir(),
                prepared_masks_dir=self._spheresfm_masks_dir(),
                database=self._spheresfm_database_path(),
                sparse=self._spheresfm_sparse_dir(),
                camera_params=self._spheresfm_camera_params_arg(),
                use_masks=use_masks,
                matcher=matcher,
                quality_preset=quality_preset,
            )
        )
        return [
            ("spheresfm_preflight", build_workflow_job_cmd(self.base_dir, preflight_job_path)),
            ("spheresfm_prepare", build_workflow_job_cmd(self.base_dir, prepare_job_path)),
            *steps,
        ]

    def _build_spheresfm_conversion_commands(self) -> StepCommandQueue:
        steps: StepCommandQueue = []
        transforms_output = (
            self._spheresfm_3dgut_dir() if self._uses_spheresfm_3dgut_output() else self._spheresfm_equirect_dir()
        )
        image_path_mode = "images-prefix" if self._uses_spheresfm_3dgut_output() else "relative"
        job_path = jobs_dir(Path(self.scene_dir)) / "spheresfm_transforms_job.json"
        write_workflow_job(
            job_path,
            spheresfm_transforms_job(
                sparse_dir=self._spheresfm_sparse_model_for_conversion(),
                output_dir=transforms_output,
                images_dir=self._metashape_images_dir(),
                image_path_mode=image_path_mode,
            ),
        )
        steps.append(
            (
                "spheresfm_transforms",
                build_workflow_job_cmd(self.base_dir, job_path),
            )
        )
        if self._uses_spheresfm_projected_output():
            steps.append(("spheresfm_cubemap", self._build_spheresfm_cubemap_cmd()))
        return steps

    def _build_spheresfm_cubemap_cmd(self) -> StepCommand:
        views = self.view_config.collect_views(include_disabled=True)
        enabled = sum(1 for v in views if v["enabled"])
        if enabled <= 0:
            raise ValueError("少なくとも1つのビューを有効にしてください")
        if enabled > _BLOCK_ENABLED_VIEWS:
            raise ValueError(f"ビュー数が多すぎます ({enabled})。{_BLOCK_ENABLED_VIEWS} 以下にしてください。")

        output = self._spheresfm_cubemap_dir()
        _views_json = self._write_views_config(step4_meta_dir(Path(self.scene_dir)), views)
        out_fmt = self.output_format_combo.currentData() or "auto"
        out_depth = self.output_bit_depth_combo.currentData() or "8"

        try:
            jpgq = int(self.jpg_quality_edit.text().strip())
        except ValueError as exc:
            raise ValueError("JPG/WebP 品質は整数で指定してください") from exc
        if not 1 <= jpgq <= 100:
            raise ValueError("JPG/WebP 品質は 1-100 の範囲で指定してください")

        mask_dir = self._dataset_input_mask_dir_for_conversion(require_existing=False)
        job_path = jobs_dir(Path(self.scene_dir)) / "spheresfm_cubemap_conversion_job.json"
        write_workflow_job(
            job_path,
            cubemap_conversion_job(
                input_dir=self._spheresfm_equirect_dir(),
                output_dir=output,
                views=views,
                fov=90.0,
                output_scale=float(self.scale_combo.currentData()),
                axis_mode=self._spheresfm_axis_transform_mode(),
                image_only=False,
                colmap_rig=False,
                invert_masks=self.invert_masks_cb.isChecked(),
                write_images=self._writes_images(),
                write_masks=self._writes_masks(),
                yaw_offset_per_frame=float(self.yaw_per_frame_edit.value()),
                output_format=out_fmt,
                output_bit_depth=out_depth,
                jpg_quality=jpgq,
                final_orientation=(
                    FINAL_ORIENTATION_LICHTFELD
                    if self._uses_spheresfm_lichtfeld_final_correction()
                    else FINAL_ORIENTATION_NONE
                ),
                image_dir=self._metashape_images_dir(),
                mask_dir=mask_dir,
            ),
        )
        return build_workflow_job_cmd(self.base_dir, job_path)
