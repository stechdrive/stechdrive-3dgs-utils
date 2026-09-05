"""Step 4: 視点画像書き出し (Metashape / COLMAP modes)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.scene_layout import (
    step4_meta_dir,
)
from gui import i18n
from gui.common.browse_widget import BrowseWidget
from gui.common.collapsible_section import CollapsibleSection
from gui.common.drag_spinbox import DragDoubleSpinBox
from gui.common.external_link import make_external_link
from gui.common.form_rows import add_tooltip_row
from gui.common.icons import scene_preview_icon
from gui.cubemap.preview_renderer import PreviewWidget
from gui.cubemap.view_config import ViewConfigWidget
from gui.steps.base_step import (
    SETTINGS_PANE_MARGINS,
    SETTINGS_PANE_WIDTH,
    BaseStepWidget,
)
from gui.steps.dataset_mask_step import DatasetMaskStep
from gui.steps.sfm_route_selector import SfmRouteSelector
from gui.steps.step4_activation import Step4ActivationMixin
from gui.steps.step4_apriltag import Step4AprilTagMixin
from gui.steps.step4_command_plan import Step4CommandPlanMixin
from gui.steps.step4_contracts import (
    _AXIS_BRUSH,
    _AXIS_NONE,
    _AXIS_POSTSHOT,
    _COLMAP_MAPPER_GLOBAL,
    _COLMAP_MAPPER_GLOMAP,
    _COLMAP_MAPPER_INCREMENTAL,
    _COLMAP_MATCHER_EXHAUSTIVE,
    _COLMAP_MATCHER_SEQUENTIAL,
    _COLMAP_REPOSITORY_URL,
    _METHOD_METASHAPE,
    _NORMAL_OUTPUT_SCALE,
    _OUTPUT_SHAPE_EQUIRECT_3DGUT,
    _OUTPUT_SHAPE_PROJECTED,
    _PROFILE_BRUSH,
    _PROFILE_CUSTOM,
    _PROFILE_LICHTFELD,
    _PROFILE_POSTSHOT,
    _PROFILE_REALITYSCAN,
    _SPHERESFM_QUALITY_LIGHT,
    _SPHERESFM_QUALITY_LIGHTEST,
    _SPHERESFM_QUALITY_STANDARD,
    _SPHERESFM_REPOSITORY_URL,
    is_colmap_gui_unavailable_output,  # noqa: F401 - re-exported for existing tests/imports
    is_spheresfm_rtx50_cuda_error_line,  # noqa: F401 - re-exported for existing tests/imports
)
from gui.steps.step4_manifest import Step4ManifestMixin
from gui.steps.step4_output_shape_selector import OutputShapeSelector
from gui.steps.step4_paths import Step4PathMixin
from gui.steps.step4_pipeline import Step4PipelineMixin
from gui.steps.step4_preview_counts import Step4PreviewCountsMixin
from gui.steps.step4_profile_output import Step4ProfileOutputMixin
from gui.steps.step4_project_settings import Step4ProjectSettingsMixin
from gui.steps.step4_route_state import Step4RouteStateMixin
from gui.steps.step4_runtime import Step4RuntimeMixin
from gui.steps.step4_training import Step4TrainingMixin
from gui.steps.step4_widgets import ElidedPathLabel, make_output_image_controls
from gui.steps.training_backend_specs import (
    TRAINING_BACKEND_LICHTFELD as _TRAINING_BACKEND_LICHTFELD,
)

_CONVERT_RE = re.compile(r"^Converting\s+(\d+)\s+(?:images|files)\.\.\.$")
_PROGRESS_RE = re.compile(r"^\[progress\]\s+(\d+)\s*/\s*(\d+)")
_COLMAP_FEATURE_RE = re.compile(r"Processed file \[(\d+)/(\d+)\]")
_COLMAP_MATCH_IMAGE_RE = re.compile(r"Matching image \[(\d+)/(\d+)\]")
_COLMAP_MATCH_BLOCK_RE = re.compile(r"Matching block \[(\d+)/(\d+),\s*(\d+)/(\d+)\]")
_COLMAP_GLOBAL_BA_FIXED_RE = re.compile(
    r"Global bundle adjustment iteration\s+(\d+)\s*/\s*(\d+),\s*fixed-rotation stage finished"
)
_COLMAP_GLOBAL_BA_DONE_RE = re.compile(r"Global bundle adjustment iteration\s+(\d+)\s*/\s*(\d+)\s+finished")
_COLMAP_RETRIANGULATION_START_RE = re.compile(r"=== Running iterative retriangulation and refinement ===")
_COLMAP_RETRIANGULATION_DONE_RE = re.compile(r"Iterative retriangulation and refinement done")
_COLMAP_RECONSTRUCTION_DONE_RE = re.compile(r"Reconstruction done")


class CubemapStep(
    Step4RuntimeMixin,
    Step4TrainingMixin,
    Step4PipelineMixin,
    Step4ActivationMixin,
    Step4ProjectSettingsMixin,
    Step4RouteStateMixin,
    Step4ProfileOutputMixin,
    Step4PreviewCountsMixin,
    Step4CommandPlanMixin,
    Step4ManifestMixin,
    Step4PathMixin,
    Step4AprilTagMixin,
    BaseStepWidget,
):
    def __init__(self, base_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(base_dir, parent)
        self._converted_total = 0
        self._processed = 0
        self._explicit_progress = False
        self._colmap_ba_iterations = 0
        self._syncing_profile_controls = False
        self._syncing_output_shape_controls = False
        self._syncing_user_preferences = False
        self._syncing_project_settings = False
        self._user_preferences_enabled = False
        self._export_method_value = _METHOD_METASHAPE
        self._conversion_intent = True
        self._colmap_sfm_intent = False
        self._spheresfm_sfm_intent = True
        self._spheresfm_conversion_intent = True
        self._pipeline_notice_text = ""
        self._saved_projected_export_targets: tuple[bool, bool] | None = None
        self._input_image_count = 0
        self._metashape_preview_action_counts: dict[str, int] | None = None
        self._spheresfm_phase_logs: dict[str, Path] = {}
        self._training_phase_logs: dict[str, Path] = {}
        self._spheresfm_rtx50_cuda_error_seen = False
        self._spheresfm_rtx50_cuda_error_phase: str | None = None
        self._spheresfm_rtx50_cuda_error_shown = False
        self._spheresfm_gui_processes: list[QProcess] = []
        self._active_runner_phase = ""
        self._preview_render_pending = False
        self._training_backend_value = _TRAINING_BACKEND_LICHTFELD
        self._training_dataset_user_edited = False
        self._training_output_user_edited = False
        self._syncing_training_paths = False
        self._lfs_output_name_user_edited = False
        self._syncing_lfs_output_name = False
        self._postshot_project_name_user_edited = False
        self._syncing_postshot_project_name = False
        self._brush_export_name_user_edited = False
        self._syncing_brush_export_name = False
        self._gsplat_result_name_user_edited = False
        self._syncing_gsplat_result_name = False
        self._syncing_lfs_auto_fields = False
        self._yaw_per_frame_non_colmap_value = 30.0
        self._metashape_auto_xml_candidates: tuple[Path, ...] = ()
        self._metashape_auto_ply_candidates: tuple[Path, ...] = ()
        self._syncing_metashape_auto_inputs = False
        self._syncing_scene_dir = False
        self._metashape_ply_approved = False
        self._metashape_ply_auto_candidate = False
        self._metashape_preview_targets_cache_key: tuple | None = None
        self._metashape_preview_targets_cache = None
        self._init_apriltag_state()
        self._colmap_sparse_user_edited = False
        self._spheresfm_sparse_user_edited = False
        self._syncing_sfm_input_paths = False
        self._scene_preview_window = None
        self._dataset_mask_step: DatasetMaskStep | None = None
        self._dataset_mask_tab_index: int | None = None
        self._dataset_mask_settings_context_enabled = False
        self._preview_render_timer = QTimer(self)
        self._preview_render_timer.setSingleShot(True)
        self._preview_render_timer.setInterval(50)
        self._preview_render_timer.timeout.connect(self._flush_scheduled_render_preview)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左パネル: 固定ヘッダー/タブ + 固定サマリー
        left_pane = QWidget()
        left_pane.setFixedWidth(SETTINGS_PANE_WIDTH)
        left_pane_layout = QVBoxLayout(left_pane)
        left_pane_layout.setContentsMargins(0, 0, 0, 0)
        left_pane_layout.setSpacing(0)

        top = QWidget()
        top.setObjectName("settingsPane")
        top.setFixedWidth(SETTINGS_PANE_WIDTH)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(*SETTINGS_PANE_MARGINS)
        top_layout.setSpacing(8)
        left_layout = top_layout  # 既存コードとの互換用エイリアス

        self.export_method_label = QLabel(i18n.t("EXPORT_METHOD_COMPACT"))
        self.export_method_label.setToolTip(i18n.tip("EXPORT_METHOD"))
        self.export_method_label.setVisible(False)
        self.export_method_selector = SfmRouteSelector()
        self.export_method_selector.route_changed.connect(self._set_export_method)
        self.export_method_row = self.export_method_selector
        self.export_method_row.setMaximumWidth(SETTINGS_PANE_WIDTH - SETTINGS_PANE_MARGINS[2] - 18)
        self.export_method_buttons = self.export_method_selector.route_buttons

        self.export_targets_row = QWidget()
        self.export_targets_row.setToolTip(i18n.tip("EXPORT_TARGETS"))
        export_targets_layout = QHBoxLayout(self.export_targets_row)
        export_targets_layout.setContentsMargins(0, 0, 0, 0)
        export_targets_layout.setSpacing(12)
        self.export_images_cb = QCheckBox(i18n.t("EXPORT_IMAGES"))
        self.export_images_cb.setToolTip(i18n.tip("EXPORT_IMAGES"))
        self.export_images_cb.setChecked(True)
        export_targets_layout.addWidget(self.export_images_cb)
        self.export_masks_cb = QCheckBox(i18n.t("EXPORT_MASKS"))
        self.export_masks_cb.setToolTip(i18n.tip("EXPORT_MASKS"))
        self.export_masks_cb.setChecked(True)
        export_targets_layout.addWidget(self.export_masks_cb)
        export_targets_layout.addStretch()

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("step4SettingsTabs")
        self.settings_tabs.tabBar().setUsesScrollButtons(False)
        self.settings_tabs.tabBar().setExpanding(False)

        (
            self.sfm_path_summary_row,
            self.sfm_path_summary_kind,
            self.sfm_path_summary_value,
        ) = self._make_tab_path_summary_row()
        (
            self.cubemap_path_summary_row,
            self.cubemap_path_summary_kind,
            self.cubemap_path_summary_value,
        ) = self._make_tab_path_summary_row()

        colmap_section = QWidget()
        self.colmap_section = colmap_section
        colmap_section_layout = QVBoxLayout(colmap_section)
        colmap_section_layout.setContentsMargins(8, 8, 8, 8)
        colmap_section_layout.setSpacing(6)
        colmap_form = QFormLayout()
        colmap_form.setSpacing(6)

        exe_filter = "Executable (*.exe);;All (*.*)" if os.name == "nt" else "All (*)"
        colmap_filter = "COLMAP launcher (*.bat *.cmd *.exe);;All (*.*)" if os.name == "nt" else "All (*)"
        self.colmap_exec_browse = BrowseWidget(
            mode="file",
            filter_str=colmap_filter,
            placeholder="COLMAP.bat / colmap.exe" if os.name == "nt" else "colmap",
        )
        self.colmap_exec_browse.setToolTip(i18n.tip("COLMAP_EXECUTABLE"))
        add_tooltip_row(
            colmap_form,
            i18n.t("COLMAP_EXECUTABLE"),
            self.colmap_exec_browse,
            i18n.tip("COLMAP_EXECUTABLE"),
        )

        self.colmap_pipeline_row = QWidget()
        pipeline_layout = QHBoxLayout(self.colmap_pipeline_row)
        pipeline_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_layout.setSpacing(8)
        self.colmap_matcher_combo = QComboBox()
        self.colmap_matcher_combo.setToolTip(i18n.tip("COLMAP_MATCHER"))
        self.colmap_matcher_combo.addItem(i18n.t("COLMAP_MATCHER_SEQUENTIAL"), _COLMAP_MATCHER_SEQUENTIAL)
        self.colmap_matcher_combo.addItem(i18n.t("COLMAP_MATCHER_EXHAUSTIVE"), _COLMAP_MATCHER_EXHAUSTIVE)
        self.colmap_matcher_combo.setFixedWidth(120)
        self.colmap_mapper_combo = QComboBox()
        self.colmap_mapper_combo.setToolTip(i18n.tip("COLMAP_MAPPER"))
        self.colmap_mapper_combo.addItem(i18n.t("COLMAP_MAPPER_GLOBAL"), _COLMAP_MAPPER_GLOBAL)
        self.colmap_mapper_combo.addItem(i18n.t("COLMAP_MAPPER_INCREMENTAL"), _COLMAP_MAPPER_INCREMENTAL)
        self.colmap_mapper_combo.addItem(i18n.t("COLMAP_MAPPER_GLOMAP"), _COLMAP_MAPPER_GLOMAP)
        self.colmap_mapper_combo.setFixedWidth(150)
        self.colmap_mapper_combo.currentIndexChanged.connect(self._on_colmap_mapper_changed)
        pipeline_layout.addWidget(QLabel(i18n.t("COLMAP_MATCHER_COMPACT")))
        pipeline_layout.addWidget(self.colmap_matcher_combo)
        pipeline_layout.addWidget(QLabel(i18n.t("COLMAP_MAPPER_COMPACT")))
        pipeline_layout.addWidget(self.colmap_mapper_combo)
        pipeline_layout.addStretch()
        colmap_form.addRow(self.colmap_pipeline_row)

        self.glomap_exec_browse = BrowseWidget(
            mode="file",
            filter_str=exe_filter,
            placeholder="glomap.exe" if os.name == "nt" else "glomap",
        )
        self.glomap_exec_browse.setToolTip(i18n.tip("GLOMAP_EXECUTABLE"))
        self.glomap_exec_row_label = QLabel(i18n.t("GLOMAP_EXECUTABLE"))
        self.glomap_exec_row_label.setToolTip(i18n.tip("GLOMAP_EXECUTABLE"))
        colmap_form.addRow(self.glomap_exec_row_label, self.glomap_exec_browse)

        colmap_section_layout.addLayout(colmap_form)
        colmap_section_layout.addStretch()
        self.colmap_repo_link = make_external_link(
            i18n.t("COLMAP_REPOSITORY_LINK"),
            _COLMAP_REPOSITORY_URL,
            i18n.tip("COLMAP_REPOSITORY_LINK"),
            "colmapRepositoryLink",
        )
        colmap_section_layout.addWidget(self.colmap_repo_link, alignment=Qt.AlignLeft)

        spheresfm_section = QWidget()
        self.spheresfm_section = spheresfm_section
        spheresfm_layout = QVBoxLayout(spheresfm_section)
        spheresfm_layout.setContentsMargins(8, 8, 8, 8)
        spheresfm_layout.setSpacing(6)
        spheresfm_form = QFormLayout()
        spheresfm_form.setSpacing(6)

        self.spheresfm_exec_browse = BrowseWidget(
            mode="file",
            filter_str=colmap_filter,
            placeholder="COLMAP.bat / colmap.exe" if os.name == "nt" else "colmap",
        )
        self.spheresfm_exec_browse.setToolTip(i18n.tip("SPHERESFM_EXECUTABLE"))
        add_tooltip_row(
            spheresfm_form,
            i18n.t("SPHERESFM_EXECUTABLE"),
            self.spheresfm_exec_browse,
            i18n.tip("SPHERESFM_EXECUTABLE"),
        )

        self.spheresfm_use_masks_cb = QCheckBox(i18n.t("SPHERESFM_USE_MASKS"))
        self.spheresfm_use_masks_cb.setToolTip(i18n.tip("SPHERESFM_USE_MASKS"))
        self.spheresfm_use_masks_cb.setChecked(True)
        spheresfm_form.addRow("", self.spheresfm_use_masks_cb)

        self.spheresfm_loop_detection_cb = QCheckBox(i18n.t("SPHERESFM_LOOP_DETECTION"))
        self.spheresfm_loop_detection_cb.setToolTip(i18n.tip("SPHERESFM_LOOP_DETECTION"))

        self.spheresfm_quality_combo = QComboBox()
        self.spheresfm_quality_combo.setToolTip(i18n.tip("SPHERESFM_QUALITY_PRESET"))
        self.spheresfm_quality_combo.addItem(i18n.t("SPHERESFM_QUALITY_STANDARD"), _SPHERESFM_QUALITY_STANDARD)
        self.spheresfm_quality_combo.addItem(i18n.t("SPHERESFM_QUALITY_LIGHT"), _SPHERESFM_QUALITY_LIGHT)
        self.spheresfm_quality_combo.addItem(i18n.t("SPHERESFM_QUALITY_LIGHTEST"), _SPHERESFM_QUALITY_LIGHTEST)
        self.spheresfm_quality_combo.setFixedWidth(150)

        self.spheresfm_pipeline_row = QWidget()
        spheresfm_pipeline_layout = QHBoxLayout(self.spheresfm_pipeline_row)
        spheresfm_pipeline_layout.setContentsMargins(0, 0, 0, 0)
        spheresfm_pipeline_layout.setSpacing(8)
        spheresfm_pipeline_layout.addWidget(QLabel(i18n.t("SPHERESFM_QUALITY_COMPACT")))
        spheresfm_pipeline_layout.addWidget(self.spheresfm_quality_combo)
        spheresfm_pipeline_layout.addWidget(self.spheresfm_loop_detection_cb)
        spheresfm_pipeline_layout.addStretch()
        spheresfm_form.addRow(self.spheresfm_pipeline_row)

        self.spheresfm_pose_browse = BrowseWidget(
            mode="file",
            filter_str="Text (*.txt *.csv);;All (*.*)",
            placeholder="POS.txt",
        )
        self.spheresfm_pose_browse.setToolTip(i18n.tip("SPHERESFM_POSE_FILE"))

        spheresfm_layout.addLayout(spheresfm_form)
        spheresfm_layout.addStretch()
        self.spheresfm_repo_link = make_external_link(
            i18n.t("SPHERESFM_REPOSITORY_LINK"),
            _SPHERESFM_REPOSITORY_URL,
            i18n.tip("SPHERESFM_REPOSITORY_LINK"),
            "spheresfmRepositoryLink",
        )
        spheresfm_layout.addWidget(self.spheresfm_repo_link, alignment=Qt.AlignLeft)

        spheresfm_convert_section = QWidget()
        self.spheresfm_convert_section = spheresfm_convert_section
        spheresfm_convert_layout = QVBoxLayout(spheresfm_convert_section)
        spheresfm_convert_layout.setContentsMargins(8, 8, 8, 8)
        spheresfm_convert_layout.setSpacing(6)
        spheresfm_convert_form = QFormLayout()
        spheresfm_convert_form.setSpacing(6)

        self.spheresfm_output_shape_combo = OutputShapeSelector()
        self.spheresfm_output_shape_combo.setToolTip(i18n.tip("SPHERESFM_OUTPUT_SHAPE"))
        self.spheresfm_output_shape_combo.addItem(i18n.t("OUTPUT_SHAPE_PROJECTED"), _OUTPUT_SHAPE_PROJECTED)
        self.spheresfm_output_shape_combo.addItem(i18n.t("OUTPUT_SHAPE_EQUIRECT_3DGUT"), _OUTPUT_SHAPE_EQUIRECT_3DGUT)
        self.spheresfm_output_shape_combo.currentIndexChanged.connect(self._on_output_shape_changed)

        self.spheresfm_profile_combo = QComboBox()
        self.spheresfm_profile_combo.setToolTip(i18n.tip("SPHERESFM_TARGET_PROFILE"))
        self.spheresfm_profile_combo.addItem(i18n.PROFILE_POSTSHOT, _PROFILE_POSTSHOT)
        self.spheresfm_profile_combo.addItem(i18n.PROFILE_BRUSH, _PROFILE_BRUSH)
        self.spheresfm_profile_combo.addItem(i18n.PROFILE_LICHTFELD, _PROFILE_LICHTFELD)
        self.spheresfm_profile_combo.addItem(i18n.PROFILE_CUSTOM, _PROFILE_CUSTOM)
        self.spheresfm_profile_combo.currentIndexChanged.connect(self._on_spheresfm_profile_changed)
        add_tooltip_row(
            spheresfm_convert_form,
            i18n.TARGET_PROFILE,
            self.spheresfm_profile_combo,
            i18n.tip("SPHERESFM_TARGET_PROFILE"),
        )
        add_tooltip_row(
            spheresfm_convert_form,
            i18n.t("OUTPUT_SHAPE"),
            self.spheresfm_output_shape_combo,
            i18n.tip("SPHERESFM_OUTPUT_SHAPE"),
        )

        self.spheresfm_axis_transform_combo = QComboBox()
        self.spheresfm_axis_transform_combo.setToolTip(i18n.tip("SPHERESFM_AXIS_TRANSFORM"))
        self.spheresfm_axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_POSTSHOT"), _AXIS_POSTSHOT)
        self.spheresfm_axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_BRUSH"), _AXIS_BRUSH)
        self.spheresfm_axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_NONE"), _AXIS_NONE)
        self.spheresfm_axis_transform_combo.setFixedWidth(180)
        self.spheresfm_axis_transform_combo.currentIndexChanged.connect(self._on_spheresfm_profile_option_changed)
        add_tooltip_row(
            spheresfm_convert_form,
            i18n.t("AXIS_TRANSFORM"),
            self.spheresfm_axis_transform_combo,
            i18n.tip("SPHERESFM_AXIS_TRANSFORM"),
        )
        self.spheresfm_axis_transform_label = spheresfm_convert_form.labelForField(
            self.spheresfm_axis_transform_combo
        )
        self.spheresfm_axis_transform_combo.setVisible(False)
        if self.spheresfm_axis_transform_label is not None:
            self.spheresfm_axis_transform_label.setVisible(False)

        self.spheresfm_profile_hint = QLabel("")
        self.spheresfm_profile_hint.setStyleSheet("color: #8888aa; font-size: 9pt;")
        self.spheresfm_profile_hint.setVisible(False)
        spheresfm_convert_form.addRow("", self.spheresfm_profile_hint)

        spheresfm_convert_layout.addLayout(spheresfm_convert_form)
        spheresfm_convert_layout.addStretch()

        # Metashapeインポート設定
        self.metashape_section = QWidget()
        self.metashape_section.setLayout(QVBoxLayout())
        preprocess = QWidget()
        self.metashape_sfm_input_widget = preprocess
        preprocess_layout = QVBoxLayout(preprocess)
        preprocess_layout.setContentsMargins(8, 8, 8, 8)
        preprocess_layout.setSpacing(6)
        profile_form = QFormLayout()
        profile_form.setSpacing(6)

        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip(i18n.tip("TARGET_PROFILE"))
        self.profile_combo.addItem(i18n.PROFILE_POSTSHOT, _PROFILE_POSTSHOT)
        self.profile_combo.addItem(i18n.PROFILE_BRUSH, _PROFILE_BRUSH)
        self.profile_combo.addItem(i18n.PROFILE_LICHTFELD, _PROFILE_LICHTFELD)
        self.profile_combo.addItem(i18n.t("PROFILE_REALITYSCAN"), _PROFILE_REALITYSCAN)
        self.profile_combo.addItem(i18n.PROFILE_CUSTOM, _PROFILE_CUSTOM)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        add_tooltip_row(profile_form, i18n.TARGET_PROFILE, self.profile_combo, i18n.tip("TARGET_PROFILE"))
        self.profile_label = profile_form.labelForField(self.profile_combo)

        self.output_shape_combo = OutputShapeSelector()
        self.output_shape_combo.setToolTip(i18n.tip("OUTPUT_SHAPE"))
        self.output_shape_combo.addItem(i18n.t("OUTPUT_SHAPE_PROJECTED"), _OUTPUT_SHAPE_PROJECTED)
        self.output_shape_combo.addItem(i18n.t("OUTPUT_SHAPE_EQUIRECT_3DGUT"), _OUTPUT_SHAPE_EQUIRECT_3DGUT)
        self.output_shape_combo.currentIndexChanged.connect(self._on_output_shape_changed)
        add_tooltip_row(profile_form, i18n.t("OUTPUT_SHAPE"), self.output_shape_combo, i18n.tip("OUTPUT_SHAPE"))

        self.profile_hint = QLabel("")
        self.profile_hint.setStyleSheet("color: #8888aa; font-size: 9pt;")
        self.profile_hint.setVisible(False)
        profile_form.addRow("", self.profile_hint)

        self.axis_transform_combo = QComboBox()
        self.axis_transform_combo.setToolTip(i18n.tip("AXIS_TRANSFORM"))
        self.axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_POSTSHOT"), _AXIS_POSTSHOT)
        self.axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_BRUSH"), _AXIS_BRUSH)
        self.axis_transform_combo.addItem(i18n.t("AXIS_TRANSFORM_NONE"), _AXIS_NONE)
        self._axis_brush_index = self.axis_transform_combo.findData(_AXIS_BRUSH)
        self.axis_transform_combo.setFixedWidth(180)
        self.axis_transform_combo.currentIndexChanged.connect(self._on_profile_option_changed)
        add_tooltip_row(profile_form, i18n.t("AXIS_TRANSFORM"), self.axis_transform_combo, i18n.tip("AXIS_TRANSFORM"))
        self.axis_transform_label = profile_form.labelForField(self.axis_transform_combo)
        self.axis_transform_combo.setVisible(False)
        if self.axis_transform_label is not None:
            self.axis_transform_label.setVisible(False)

        self.export_colmap_cb = QCheckBox(i18n.t("EXPORT_COLMAP"))
        self.export_colmap_cb.setToolTip(i18n.t("EXPORT_COLMAP_HINT"))
        self.export_colmap_cb.setVisible(False)

        self.realityscan_options_row = QWidget()
        realityscan_options_layout = QHBoxLayout(self.realityscan_options_row)
        realityscan_options_layout.setContentsMargins(0, 0, 0, 0)
        realityscan_options_layout.setSpacing(6)
        realityscan_options_layout.setAlignment(Qt.AlignVCenter)
        self.realityscan_pose_prior_label = QLabel(i18n.t("REALITYSCAN_POSE_PRIOR_COMPACT"))
        self.realityscan_pose_prior_label.setToolTip(i18n.tip("REALITYSCAN_POSE_PRIOR"))
        self.realityscan_pose_prior_label.setAlignment(Qt.AlignVCenter)
        realityscan_options_layout.addWidget(self.realityscan_pose_prior_label, 0, Qt.AlignVCenter)
        self.realityscan_pose_prior_combo = QComboBox()
        self.realityscan_pose_prior_combo.setToolTip(i18n.tip("REALITYSCAN_POSE_PRIOR"))
        self.realityscan_pose_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_INITIAL"), "initial")
        self.realityscan_pose_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_EXACT"), "exact")
        self.realityscan_pose_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_LOCKED"), "locked")
        self.realityscan_pose_prior_combo.setCurrentIndex(self.realityscan_pose_prior_combo.findData("exact"))
        self.realityscan_pose_prior_combo.setFixedWidth(82)
        realityscan_options_layout.addWidget(self.realityscan_pose_prior_combo, 0, Qt.AlignVCenter)
        self.realityscan_calibration_prior_label = QLabel(i18n.t("REALITYSCAN_CALIBRATION_PRIOR_COMPACT"))
        self.realityscan_calibration_prior_label.setToolTip(i18n.tip("REALITYSCAN_CALIBRATION_PRIOR"))
        self.realityscan_calibration_prior_label.setAlignment(Qt.AlignVCenter)
        realityscan_options_layout.addWidget(self.realityscan_calibration_prior_label, 0, Qt.AlignVCenter)
        self.realityscan_calibration_prior_combo = QComboBox()
        self.realityscan_calibration_prior_combo.setToolTip(i18n.tip("REALITYSCAN_CALIBRATION_PRIOR"))
        self.realityscan_calibration_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_INITIAL"), "initial")
        self.realityscan_calibration_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_EXACT"), "exact")
        self.realityscan_calibration_prior_combo.addItem(i18n.t("REALITYSCAN_PRIOR_LOCKED"), "locked")
        self.realityscan_calibration_prior_combo.setCurrentIndex(
            self.realityscan_calibration_prior_combo.findData("exact")
        )
        self.realityscan_calibration_prior_combo.setFixedWidth(82)
        realityscan_options_layout.addWidget(self.realityscan_calibration_prior_combo, 0, Qt.AlignVCenter)
        self.realityscan_include_rig_cb = QCheckBox(i18n.t("REALITYSCAN_INCLUDE_RIG"))
        self.realityscan_include_rig_cb.setToolTip(i18n.tip("REALITYSCAN_INCLUDE_RIG"))
        realityscan_options_layout.addWidget(self.realityscan_include_rig_cb, 0, Qt.AlignVCenter)
        realityscan_options_layout.addStretch()
        self.realityscan_options_row.setVisible(False)
        profile_form.addRow(i18n.t("REALITYSCAN_XMP_OPTIONS"), self.realityscan_options_row)
        self.realityscan_options_label = profile_form.labelForField(self.realityscan_options_row)
        if self.realityscan_options_label is not None:
            self.realityscan_options_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.realityscan_options_label.setVisible(False)

        self.metashape_output_section = QWidget()
        self.metashape_output_section.setLayout(profile_form)
        pp_form = QFormLayout()

        self.ms_images_path_label = ElidedPathLabel("-")
        self.ms_images_path_label.setToolTip(i18n.tip("MS_IMAGES"))
        add_tooltip_row(pp_form, i18n.t("MS_IMAGES_LABEL"), self.ms_images_path_label, i18n.tip("MS_IMAGES"))

        self.ms_xml_browse = BrowseWidget(
            mode="file",
            filter_str="XML (*.xml);;すべて (*.*)",
            placeholder=i18n.t("MS_XML_PLACEHOLDER"),
        )
        self.ms_xml_browse.setToolTip(i18n.tip("MS_XML"))
        self.ms_xml_browse.line_edit.setToolTip(i18n.tip("MS_XML"))
        add_tooltip_row(pp_form, i18n.METASHAPE_XML, self.ms_xml_browse, i18n.tip("MS_XML"))

        self.ms_ply_browse = BrowseWidget(
            mode="file",
            filter_str="PLY (*.ply);;すべて (*.*)",
            placeholder=i18n.t("MS_PLY_PLACEHOLDER"),
        )
        self.ms_ply_browse.setToolTip(i18n.tip("MS_PLY"))
        self.ms_ply_browse.line_edit.setToolTip(i18n.tip("MS_PLY"))
        add_tooltip_row(pp_form, i18n.METASHAPE_PLY, self.ms_ply_browse, i18n.tip("MS_PLY"))

        self.ms_xml_browse.path_changed.connect(self._on_metashape_input_path_changed)
        self.ms_ply_browse.path_changed.connect(self._on_metashape_input_path_changed)
        self.ms_ply_browse.line_edit.textEdited.connect(self._on_metashape_ply_text_edited)

        import_advanced = CollapsibleSection(i18n.t("ADVANCED_SETTINGS"), expanded=False)
        import_adv_form = QFormLayout()
        import_adv_form.setSpacing(6)

        self.metashape_import_options_row = QWidget()
        import_option_row = QHBoxLayout(self.metashape_import_options_row)
        import_option_row.setContentsMargins(0, 0, 0, 0)
        import_option_row.setSpacing(8)
        self.ms_scale_label = QLabel(i18n.t("SCALE_FACTOR_COMPACT"))
        self.ms_scale_label.setToolTip(i18n.tip("SCALE_FACTOR"))
        import_option_row.addWidget(self.ms_scale_label)

        self.ms_scale_edit = QLineEdit("1.0")
        self.ms_scale_edit.setFixedWidth(72)
        self.ms_scale_edit.setToolTip(i18n.tip("SCALE_FACTOR"))
        self.ms_scale_edit.textEdited.connect(self._on_profile_option_changed)
        import_option_row.addWidget(self.ms_scale_edit)

        self.ms_use_ply_cb = QCheckBox(i18n.t("MS_USE_PLY"))
        self.ms_use_ply_cb.setToolTip(i18n.tip("MS_USE_PLY"))
        self.ms_use_ply_cb.toggled.connect(self._on_profile_option_changed)
        import_option_row.addWidget(self.ms_use_ply_cb)

        self.ms_no_fix_rot_cb = QCheckBox(i18n.NO_FIX_ROTATION)
        self.ms_no_fix_rot_cb.setToolTip(i18n.tip("NO_FIX_ROTATION"))
        self.ms_no_fix_rot_cb.toggled.connect(self._on_profile_option_changed)
        import_option_row.addWidget(self.ms_no_fix_rot_cb)
        import_option_row.addStretch()
        import_adv_form.addRow(self.metashape_import_options_row)
        import_advanced.content_layout.addLayout(import_adv_form)

        preprocess_layout.addLayout(pp_form)
        preprocess_layout.addWidget(import_advanced)
        preprocess_layout.addStretch()

        self.colmap_sfm_input_widget = QWidget()
        colmap_sfm_input_layout = QVBoxLayout(self.colmap_sfm_input_widget)
        colmap_sfm_input_layout.setContentsMargins(8, 8, 8, 8)
        colmap_sfm_input_layout.setSpacing(6)
        colmap_sfm_input_form = QFormLayout()
        colmap_sfm_input_form.setSpacing(6)
        self.colmap_sparse_browse = BrowseWidget(
            mode="dir",
            placeholder=i18n.t("SFM_SPARSE_MODEL_PLACEHOLDER"),
        )
        self.colmap_sparse_browse.setToolTip(i18n.tip("COLMAP_SPARSE_MODEL"))
        self.colmap_sparse_browse.line_edit.setToolTip(i18n.tip("COLMAP_SPARSE_MODEL"))
        add_tooltip_row(
            colmap_sfm_input_form,
            i18n.t("SFM_SPARSE_MODEL"),
            self.colmap_sparse_browse,
            i18n.tip("COLMAP_SPARSE_MODEL"),
        )
        colmap_sfm_input_layout.addLayout(colmap_sfm_input_form)
        colmap_sfm_input_layout.addStretch()

        self.spheresfm_sfm_input_widget = QWidget()
        spheresfm_sfm_input_layout = QVBoxLayout(self.spheresfm_sfm_input_widget)
        spheresfm_sfm_input_layout.setContentsMargins(8, 8, 8, 8)
        spheresfm_sfm_input_layout.setSpacing(6)
        spheresfm_sfm_input_form = QFormLayout()
        spheresfm_sfm_input_form.setSpacing(6)
        self.spheresfm_sparse_browse = BrowseWidget(
            mode="dir",
            placeholder=i18n.t("SFM_SPARSE_MODEL_PLACEHOLDER"),
        )
        self.spheresfm_sparse_browse.setToolTip(i18n.tip("SPHERESFM_SPARSE_MODEL"))
        self.spheresfm_sparse_browse.line_edit.setToolTip(i18n.tip("SPHERESFM_SPARSE_MODEL"))
        add_tooltip_row(
            spheresfm_sfm_input_form,
            i18n.t("SFM_SPARSE_MODEL"),
            self.spheresfm_sparse_browse,
            i18n.tip("SPHERESFM_SPARSE_MODEL"),
        )
        spheresfm_sfm_input_layout.addLayout(spheresfm_sfm_input_form)
        spheresfm_sfm_input_layout.addStretch()

        self.colmap_sparse_browse.path_changed.connect(self._on_colmap_sparse_path_changed)
        self.spheresfm_sparse_browse.path_changed.connect(self._on_spheresfm_sparse_path_changed)

        self.sfm_input_section = QWidget()
        sfm_input_layout = QVBoxLayout(self.sfm_input_section)
        sfm_input_layout.setContentsMargins(0, 0, 0, 0)
        sfm_input_layout.setSpacing(4)
        self.sfm_input_title = QLabel(i18n.t("SFM_INPUT_SECTION"))
        self.sfm_input_title.setToolTip(i18n.tip("SFM_INPUT_SECTION"))
        sfm_input_layout.addWidget(self.sfm_input_title)
        sfm_input_layout.addWidget(self.metashape_sfm_input_widget)
        sfm_input_layout.addWidget(self.colmap_sfm_input_widget)
        sfm_input_layout.addWidget(self.spheresfm_sfm_input_widget)

        self.view_config = ViewConfigWidget(show_settings=False, show_summary=False)
        self.view_config.views_changed.connect(self._on_views_changed)
        self.view_config.hovered_view_changed.connect(lambda _name: self._render_preview())

        # 視点書き出し設定
        adv_output = QWidget()
        self.advanced_output_section = adv_output
        adv_output_layout = QVBoxLayout(adv_output)
        adv_output_layout.setContentsMargins(8, 8, 8, 8)
        adv_output_layout.setSpacing(6)
        adv_form = QFormLayout()
        adv_form.setSpacing(6)

        self.scale_combo = QComboBox()
        self.scale_combo.setToolTip(i18n.tip("OUTPUT_SCALE"))
        self.scale_combo.addItem("Full", 1.0)
        self.scale_combo.addItem("Normal", _NORMAL_OUTPUT_SCALE)
        self.scale_combo.addItem("Half", 0.5)
        normal_scale_index = self.scale_combo.findData(_NORMAL_OUTPUT_SCALE)
        if normal_scale_index >= 0:
            self.scale_combo.setCurrentIndex(normal_scale_index)
        self.scale_combo.setFixedWidth(90)

        self.yaw_per_frame_edit = DragDoubleSpinBox(
            minimum=-180.0,
            maximum=180.0,
            step=1.0,
            decimals=1,
            value=30.0,
            drag_pixels_per_step=6.0,
        )
        self.yaw_per_frame_edit.setFixedWidth(76)
        self.yaw_per_frame_edit.setToolTip(i18n.t("YAW_OFFSET_PER_FRAME_HINT"))
        self.yaw_per_frame_row = QWidget()
        yaw_per_frame_layout = QHBoxLayout(self.yaw_per_frame_row)
        yaw_per_frame_layout.setContentsMargins(0, 0, 0, 0)
        yaw_per_frame_layout.setSpacing(8)
        self.yaw_per_frame_label = QLabel(i18n.t("YAW_OFFSET_PER_FRAME"))
        self.yaw_per_frame_label.setToolTip(i18n.t("YAW_OFFSET_PER_FRAME_HINT"))
        self.view_config.angle_row.addWidget(self.yaw_per_frame_label)
        self.view_config.angle_row.addWidget(self.yaw_per_frame_edit)
        self.view_config.angle_row.addStretch()

        self.output_scale_row = QWidget()
        output_scale_layout = QHBoxLayout(self.output_scale_row)
        output_scale_layout.setContentsMargins(0, 0, 0, 0)
        output_scale_layout.setSpacing(8)
        self.output_scale_label = QLabel(i18n.OUTPUT_SCALE + ":")
        self.output_scale_label.setToolTip(i18n.tip("OUTPUT_SCALE"))
        output_scale_layout.addWidget(self.output_scale_label)
        output_scale_layout.addWidget(self.scale_combo)
        output_scale_layout.addStretch()
        self.view_config.extra_controls_layout.addWidget(self.output_scale_row)

        adv_form.addRow(self.view_config.settings_widget)

        output_details = QWidget()
        self.output_details_section = output_details
        output_details_layout = QVBoxLayout(output_details)
        output_details_layout.setContentsMargins(0, 0, 0, 0)
        output_details_layout.setSpacing(8)

        self.output_image_controls = make_output_image_controls(output_details)
        self.output_format_combo = self.output_image_controls.output_format_combo
        self.output_bit_depth_combo = self.output_image_controls.output_bit_depth_combo
        self.output_format_label = self.output_image_controls.output_format_label
        self.output_bit_depth_label = self.output_image_controls.output_bit_depth_label
        self.invert_masks_cb = self.output_image_controls.invert_masks_cb
        self.jpg_quality_edit = self.output_image_controls.jpg_quality_edit
        self.jpg_quality_label = self.output_image_controls.jpg_quality_label
        output_details_layout.addWidget(self.output_image_controls.widget)
        output_details_layout.addStretch()

        adv_output_layout.addLayout(adv_form)
        adv_output_layout.addStretch()

        self.training_section = self._build_training_section(exe_filter)

        input_tab = QWidget()
        self.input_tab = input_tab
        input_layout = QVBoxLayout(input_tab)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(6)
        input_layout.addWidget(self.sfm_path_summary_row)
        input_layout.addWidget(self.export_method_row)
        input_layout.addWidget(self.sfm_input_section)
        input_layout.addWidget(self.colmap_section)
        input_layout.addWidget(self.spheresfm_section)
        input_layout.addStretch()

        output_tab = QWidget()
        self.output_tab = output_tab
        output_layout = QVBoxLayout(output_tab)
        output_layout.setContentsMargins(8, 8, 8, 8)
        output_layout.setSpacing(6)
        output_layout.addWidget(self.cubemap_path_summary_row)
        output_layout.addWidget(self.export_targets_row)
        output_layout.addWidget(self.metashape_output_section)
        output_layout.addWidget(self.spheresfm_convert_section)
        output_layout.addWidget(self.advanced_output_section)
        output_layout.addStretch()

        details_tab = QWidget()
        self.details_tab = details_tab
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(8, 8, 8, 8)
        details_layout.setSpacing(6)
        details_layout.addWidget(self.output_details_section)
        details_layout.addStretch()

        self.apriltag_tab_index: int | None = None
        self.apriltag_tab = self._build_apriltag_scale_tab()

        self.input_tab_index = self.settings_tabs.addTab(
            self._make_tab_scroll_area(self.input_tab),
            i18n.t("STEP4_TAB_INPUT"),
        )
        self.output_tab_index = self.settings_tabs.addTab(
            self._make_tab_scroll_area(self.output_tab),
            i18n.t("STEP4_TAB_OUTPUT"),
        )
        self.details_tab_index = self.settings_tabs.addTab(
            self._make_tab_scroll_area(self.details_tab),
            i18n.t("STEP4_TAB_DETAILS"),
        )
        self.metashape_tab_index = self.input_tab_index
        self.colmap_tab_index = self.input_tab_index
        self.spheresfm_tab_index = self.input_tab_index
        self.view_export_tab_index = self.output_tab_index
        self.spheresfm_convert_tab_index = self.output_tab_index
        self.settings_tabs.currentChanged.connect(self._on_settings_tab_changed)
        left_layout.addWidget(self.settings_tabs, stretch=1)

        left_layout.addStretch()

        self.export_summary_bar = QWidget()
        self.export_summary_bar.setObjectName("stickySummaryBar")
        summary_layout = QHBoxLayout(self.export_summary_bar)
        summary_layout.setContentsMargins(0, 6, SETTINGS_PANE_MARGINS[2], 2)
        summary_layout.setSpacing(0)
        self.export_summary_label = QLabel(self.view_config.summary_text())
        self.export_summary_label.setObjectName("stickySummaryLabel")
        self.export_summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.export_summary_label.setWordWrap(False)
        self.view_config.summary_changed.connect(self.export_summary_label.setText)
        summary_layout.addStretch()
        summary_layout.addWidget(self.export_summary_label)

        # 右パネル: プレビュー
        preview_pane = QWidget()
        preview_pane.setObjectName("workPane")
        preview_layout = QVBoxLayout(preview_pane)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(8)
        preview_title = QLabel(i18n.t("CUBEMAP_PREVIEW_SECTION"))
        preview_title.setObjectName("paneTitle")
        self.preview = PreviewWidget()
        self.preview.mask_overlay_changed.connect(lambda: self._schedule_render_preview())
        self.preview.current_image_changed.connect(lambda: self._schedule_render_preview())
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(8)
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        self.scene_preview_btn = QToolButton()
        self.scene_preview_btn.setObjectName("iconToolButton")
        self.scene_preview_btn.setIcon(scene_preview_icon())
        self.scene_preview_btn.setIconSize(QSize(18, 18))
        self.scene_preview_btn.setFixedSize(28, 28)
        self.scene_preview_btn.setAccessibleName(i18n.t("SCENE_PREVIEW_OPEN"))
        self.scene_preview_btn.setToolTip(i18n.tip("SCENE_PREVIEW_OPEN"))
        self.scene_preview_btn.clicked.connect(self._open_scene_preview)
        preview_header.addWidget(self.preview.projection_toggle_btn)
        preview_header.addWidget(self.scene_preview_btn)
        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.preview, stretch=1)
        self.cubemap_preview_pane = preview_pane
        self.work_stack = QStackedWidget()
        self.work_stack.addWidget(preview_pane)

        left_pane_layout.addWidget(top, stretch=1)
        left_pane_layout.addWidget(self.export_summary_bar)
        splitter.addWidget(left_pane)
        splitter.addWidget(self.work_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([SETTINGS_PANE_WIDTH, 760])
        layout.addWidget(splitter)

        lichtfeld_index = self.profile_combo.findData(_PROFILE_LICHTFELD)
        if lichtfeld_index >= 0:
            self.profile_combo.setCurrentIndex(lichtfeld_index)
        spheresfm_lichtfeld_index = self.spheresfm_profile_combo.findData(_PROFILE_LICHTFELD)
        if spheresfm_lichtfeld_index >= 0:
            self.spheresfm_profile_combo.setCurrentIndex(spheresfm_lichtfeld_index)
        self._on_profile_changed(self.profile_combo.currentIndex())
        self._on_spheresfm_profile_changed(self.spheresfm_profile_combo.currentIndex())
        self._on_output_shape_changed(self.output_shape_combo.currentIndex())
        self._on_colmap_mapper_changed()
        self._sync_colmap_sfm_controls()
        self._set_export_method(_METHOD_METASHAPE)

    def _make_tab_scroll_area(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("step4TabScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _make_tab_path_summary_row(self) -> tuple[QWidget, QLabel, ElidedPathLabel]:
        row = QWidget()
        row.setObjectName("tabPathSummary")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        kind = QLabel("-")
        kind.setObjectName("tabPathSummaryKind")
        kind.setWordWrap(False)
        value = ElidedPathLabel("-")
        value.setObjectName("tabPathSummaryValue")
        layout.addWidget(kind)
        layout.addWidget(value, stretch=1)
        return row, kind, value

    def _make_training_path_summary_row(
        self,
    ) -> tuple[QWidget, QLabel, ElidedPathLabel, QLabel, ElidedPathLabel]:
        row = QWidget()
        row.setObjectName("tabPathSummary")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        dataset_kind = QLabel(i18n.t("STEP4_SUMMARY_INPUT"))
        dataset_kind.setObjectName("tabPathSummaryKind")
        dataset_value = ElidedPathLabel("-")
        dataset_value.setObjectName("tabPathSummaryValue")
        output_kind = QLabel(i18n.t("STEP4_SUMMARY_OUTPUT"))
        output_kind.setObjectName("tabPathSummaryKind")
        output_value = ElidedPathLabel("-")
        output_value.setObjectName("tabPathSummaryValue")
        layout.addWidget(dataset_kind)
        layout.addWidget(dataset_value, stretch=1)
        layout.addWidget(output_kind)
        layout.addWidget(output_value, stretch=1)
        return row, dataset_kind, dataset_value, output_kind, output_value

    def enable_dataset_mask_settings(self) -> None:
        self._set_dataset_mask_context_enabled(True)

    def disable_dataset_mask_settings(self) -> None:
        self._set_dataset_mask_context_enabled(False)

    def _set_dataset_mask_context_enabled(self, enabled: bool) -> None:
        if enabled:
            self._ensure_dataset_mask_step()
        self._dataset_mask_settings_context_enabled = bool(enabled)
        self._sync_dataset_mask_context_ui()
        self._on_settings_tab_changed(self.settings_tabs.currentIndex())

    def _ensure_dataset_mask_step(self) -> DatasetMaskStep:
        if self._dataset_mask_step is not None:
            return self._dataset_mask_step
        step = DatasetMaskStep(
            self.base_dir,
            dataset_root_provider=self._current_dataset_root_for_manifest,
            source_images_dir_provider=self._metashape_images_dir,
            source_masks_dir_provider=self._mask_dir,
            generated_source_masks_dir_provider=self._dataset_training_source_masks_dir,
            parent=self,
        )
        step.primary_action_state_changed.connect(self.primary_action_state_changed)
        step.settings_scroll.setObjectName("step4TabScroll")
        if self.scene_dir:
            step.set_scene_dir(self.scene_dir)
        self._dataset_mask_step = step
        self._dataset_mask_tab_index = self.settings_tabs.addTab(
            step.settings_scroll,
            i18n.t("STEP4_TAB_MASK_SETTINGS"),
        )
        self.work_stack.addWidget(step.preview_pane)
        step.hide()
        return step

    def _dataset_training_source_masks_dir(self) -> Path:
        if not self.scene_dir:
            raise ValueError(i18n.t("SCENE_REQUIRED_ACTION_HINT"))
        return step4_meta_dir(Path(self.scene_dir)) / "dataset_masks" / "training_source_masks"

    def _sync_dataset_mask_context_ui(self) -> None:
        enabled = self._dataset_mask_settings_context_enabled and self._dataset_mask_tab_index is not None
        if self._dataset_mask_tab_index is not None:
            self.settings_tabs.setTabVisible(self._dataset_mask_tab_index, enabled)
            self.settings_tabs.setTabEnabled(self._dataset_mask_tab_index, enabled)
            if not enabled and self.settings_tabs.currentIndex() == self._dataset_mask_tab_index:
                self.settings_tabs.setCurrentIndex(self.output_tab_index)
        self.export_masks_cb.setVisible(not enabled)
        self.sfm_path_summary_row.setVisible(not enabled)
        self.cubemap_path_summary_row.setVisible(not enabled)
        self.export_targets_row.setToolTip(
            i18n.tip("DATASET_EXPORT_TARGETS") if enabled else i18n.tip("EXPORT_TARGETS")
        )
        self.export_images_cb.setToolTip(i18n.tip("DATASET_EXPORT_IMAGES") if enabled else i18n.tip("EXPORT_IMAGES"))
        self.export_masks_cb.setToolTip(i18n.tip("EXPORT_MASKS"))

    def _dataset_mask_tab_selected(self) -> bool:
        return (
            self._dataset_mask_settings_context_enabled
            and self._dataset_mask_tab_index is not None
            and self.settings_tabs.currentIndex() == self._dataset_mask_tab_index
        )

    def _on_settings_tab_changed(self, _index: int) -> None:
        if self._dataset_mask_tab_selected() and self._dataset_mask_step is not None:
            self.work_stack.setCurrentWidget(self._dataset_mask_step.preview_pane)
            self._dataset_mask_step.set_dataset_projection(self._dataset_output_projection())
            self._dataset_mask_step.on_activated()
        elif hasattr(self, "work_stack"):
            self.work_stack.setCurrentWidget(self.cubemap_preview_pane)
        self.primary_action_state_changed.emit()

    def _dataset_output_projection(self) -> str:
        if self._uses_direct_equirect_output() or self._uses_spheresfm_3dgut_output():
            return "equirect"
        return "normal"

    def set_scene_dir(self, path: str) -> None:
        super().set_scene_dir(path)
        self._syncing_scene_dir = True
        self._metashape_preview_targets_cache_key = None
        self._metashape_preview_targets_cache = None
        if self._scene_preview_window is not None:
            self._scene_preview_window.set_scene_dir(Path(path) if path else None, refresh=False)
            self._defer_scene_preview_window_refresh()
        try:
            if not path:
                self.ms_images_path_label.setToolTip(i18n.tip("MS_IMAGES"))
                self.ms_images_path_label.set_full_text("-")
                self.ms_xml_browse.set_text("")
                self.ms_ply_browse.set_text("")
                self._metashape_auto_xml_candidates = ()
                self._metashape_auto_ply_candidates = ()
                self._set_metashape_ply_approved(False)
                self._colmap_sparse_user_edited = False
                self._spheresfm_sparse_user_edited = False
                self._sync_sfm_input_paths(force=True)
                self._update_metashape_input_hint()
                self.preview.set_scene_dir("")
                if self._dataset_mask_step is not None:
                    self._dataset_mask_step.set_scene_dir("")
                self.preview.set_perspective_supported_paths(())
                self._refresh_input_image_count()
                self._training_dataset_user_edited = False
                self._training_output_user_edited = False
                self._lfs_output_name_user_edited = False
                self._postshot_project_name_user_edited = False
                self._brush_export_name_user_edited = False
                self._gsplat_result_name_user_edited = False
                self._update_training_paths(force=True)
                self._update_path_labels()
                self._update_lfs_output_name(force=True)
                self._update_postshot_project_name(force=True)
                self._update_brush_export_name(force=True)
                self._update_gsplat_result_name(force=True)
                return
            p = Path(path)
            images_dir = str(self._metashape_images_dir())
            self._update_path_labels()
            self.ms_images_path_label.setToolTip(f"{i18n.tip('MS_IMAGES')}\n{images_dir}")
            self.ms_images_path_label.set_full_text(images_dir)
            if self._is_metashape_method():
                self._apply_metashape_auto_inputs(p)
            else:
                self._syncing_metashape_auto_inputs = True
                try:
                    self.ms_xml_browse.set_text("")
                    self.ms_ply_browse.set_text("")
                finally:
                    self._syncing_metashape_auto_inputs = False
                self._metashape_auto_xml_candidates = ()
                self._metashape_auto_ply_candidates = ()
                self._set_metashape_ply_approved(False)
            self._colmap_sparse_user_edited = False
            self._spheresfm_sparse_user_edited = False
            self._sync_sfm_input_paths(force=True)
            self._training_dataset_user_edited = False
            self._training_output_user_edited = False
            self._lfs_output_name_user_edited = False
            self._postshot_project_name_user_edited = False
            self._brush_export_name_user_edited = False
            self._gsplat_result_name_user_edited = False
            restored = self._restore_project_settings(p)
            self.preview.set_scene_dir(path, refresh=False)
            if self._dataset_mask_step is not None:
                self._dataset_mask_step.set_scene_dir(path)
                self._dataset_mask_step.set_dataset_projection(self._dataset_output_projection())
            self._input_image_count = 0
            self._update_training_paths(force=not restored)
            self._update_lfs_output_name(force=not restored)
            self._update_postshot_project_name(force=not restored)
            self._update_brush_export_name(force=not restored)
            self._update_gsplat_result_name(force=not restored)
            self._update_lfs_auto_steps_scaler()
            self._update_metashape_input_hint()
        finally:
            self._syncing_scene_dir = False

    # -- コマンド構築 --

    def process_log_dir(self) -> Path | None:
        if not self._is_spheresfm_method():
            return None
        try:
            return step4_meta_dir(Path(self.scene_dir)) / "logs" / "colmap_equirect"
        except ValueError:
            return None

    def training_process_log_dir(self) -> Path | None:
        if not self.scene_dir:
            return None
        try:
            return step4_meta_dir(Path(self.scene_dir)) / "logs" / "training"
        except ValueError:
            return None

    def _reset_spheresfm_rtx50_diagnostics(self) -> None:
        self._spheresfm_phase_logs.clear()
        self._spheresfm_rtx50_cuda_error_seen = False
        self._spheresfm_rtx50_cuda_error_phase = None
        self._spheresfm_rtx50_cuda_error_shown = False
