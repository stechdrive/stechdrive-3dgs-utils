"""SfM route selection and in-app SfM execution step."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui import i18n
from gui.common.browse_widget import BrowseWidget
from gui.common.external_link import make_external_link
from gui.common.form_rows import add_tooltip_row
from gui.common.runner_types import StepCommandQueue
from gui.steps.base_step import BaseStepWidget
from gui.steps.sfm_route_specs import (
    SFM_ROUTE_COLMAP,
    SFM_ROUTE_METASHAPE,
    SFM_ROUTE_SPHERESFM,
    get_sfm_route_spec,
    normalize_sfm_route,
)
from gui.steps.step4_contracts import (
    _COLMAP_MAPPER_GLOMAP,
    _OUTPUT_SHAPE_PROJECTED,
    _PIPELINE_STAGE_CONVERSION,
    _PIPELINE_STAGE_SFM,
    _PROFILE_REALITYSCAN,
)
from gui.steps.workflow_cards import WorkflowCardGrid, WorkflowCardSpec

if TYPE_CHECKING:
    from gui.scene_preview.window import ScenePreviewWidget
    from gui.steps.step4_cubemap import CubemapStep

_PAGE_MENU = "menu"
_PAGE_COLMAP = SFM_ROUTE_COLMAP
_PAGE_SPHERESFM = SFM_ROUTE_SPHERESFM
_PAGE_REALITYSCAN = "realityscan_realign"
_PAGE_VIEWER = "viewer"
_CARD_VIEWER = "viewer"
_DATASET_MENU_ROUTE = "dataset_menu"
_RUNNABLE_PAGES = {_PAGE_COLMAP, _PAGE_SPHERESFM, _PAGE_REALITYSCAN}


class SfmStep(BaseStepWidget):
    """Lets Step 4 either run in-app SfM or hand off external SfM results."""

    route_requested = Signal(str)

    def __init__(self, base_dir: Path, cubemap_step: CubemapStep, parent: QWidget | None = None) -> None:
        super().__init__(base_dir, parent)
        self.cubemap_step = cubemap_step
        self._page = _PAGE_MENU
        self._page_indices: dict[str, int] = {}
        self._syncing_controls = False
        self.scene_preview: ScenePreviewWidget | None = None
        self._scene_preview_refresh_token = 0
        self._opengl_surface_anchor: QOpenGLWidget | None = None
        self._build_ui()
        self._connect_child_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        self._page_indices[_PAGE_MENU] = self.stack.addWidget(self._build_menu_page())
        self._page_indices[_PAGE_COLMAP] = self.stack.addWidget(
            self._wrap_detail_page(
                i18n.t("SFM_COLMAP_DETAIL_TITLE"),
                i18n.t("SFM_COLMAP_DETAIL_DESC"),
                self._build_colmap_detail(),
            )
        )
        self._page_indices[_PAGE_SPHERESFM] = self.stack.addWidget(
            self._wrap_detail_page(
                i18n.t("SFM_SPHERESFM_DETAIL_TITLE"),
                i18n.t("SFM_SPHERESFM_DETAIL_DESC"),
                self._build_spheresfm_detail(),
            )
        )
        self._page_indices[_PAGE_REALITYSCAN] = self.stack.addWidget(self._build_realityscan_detail_page())
        self._install_opengl_surface_anchor()
        root.addWidget(self.stack)

    def _install_opengl_surface_anchor(self) -> None:
        """Ensure the main window's native surface is OpenGL-ready before it is shown."""
        anchor = QOpenGLWidget()
        anchor.setObjectName("sfmOpenGLSurfaceAnchor")
        anchor.setFixedSize(1, 1)
        anchor.hide()
        self._opengl_surface_anchor = anchor
        self.stack.addWidget(anchor)

    def _ensure_scene_preview(self) -> ScenePreviewWidget:
        if self.scene_preview is not None:
            return self.scene_preview
        from gui.scene_preview.window import ScenePreviewWidget

        preview = ScenePreviewWidget(parent=self, show_scene_controls=False)
        self.scene_preview = preview
        self._page_indices[_PAGE_VIEWER] = self.stack.addWidget(preview)
        return preview

    def _build_menu_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        description = QLabel(i18n.t("SFM_MENU_DESC"))
        description.setObjectName("workflowNote")
        description.setWordWrap(True)
        layout.addWidget(description)

        specs = (
            WorkflowCardSpec(
                SFM_ROUTE_METASHAPE,
                i18n.t("SFM_ROUTE_EXTERNAL_TITLE"),
                i18n.t("SFM_ROUTE_EXTERNAL_BODY"),
                i18n.t("SFM_ROUTE_EXTERNAL_FOOTER"),
                i18n.tip("SFM_ROUTE_EXTERNAL"),
            ),
            WorkflowCardSpec(
                _PAGE_REALITYSCAN,
                i18n.t("SFM_ROUTE_REALITYSCAN_TITLE"),
                i18n.t("SFM_ROUTE_REALITYSCAN_BODY"),
                i18n.t("SFM_ROUTE_REALITYSCAN_FOOTER"),
                i18n.tip("SFM_ROUTE_REALITYSCAN"),
            ),
            WorkflowCardSpec(
                SFM_ROUTE_COLMAP,
                i18n.t("SFM_ROUTE_COLMAP_TITLE"),
                i18n.t("SFM_ROUTE_COLMAP_BODY"),
                i18n.t("SFM_ROUTE_COLMAP_FOOTER"),
                i18n.tip("SFM_ROUTE_COLMAP"),
            ),
            WorkflowCardSpec(
                SFM_ROUTE_SPHERESFM,
                i18n.t("SFM_ROUTE_SPHERESFM_TITLE"),
                i18n.t("SFM_ROUTE_SPHERESFM_BODY"),
                i18n.t("SFM_ROUTE_SPHERESFM_FOOTER"),
                i18n.tip("SFM_ROUTE_SPHERESFM"),
            ),
            WorkflowCardSpec(
                _CARD_VIEWER,
                i18n.t("SFM_ROUTE_VIEWER_TITLE"),
                i18n.t("SFM_ROUTE_VIEWER_BODY"),
                i18n.t("SFM_ROUTE_VIEWER_FOOTER"),
                i18n.tip("SFM_ROUTE_VIEWER"),
            ),
        )
        self.card_grid = WorkflowCardGrid(specs)
        self.card_grid.buttons[SFM_ROUTE_METASHAPE].clicked.connect(
            lambda _checked=False: self.route_requested.emit(_DATASET_MENU_ROUTE)
        )
        self.card_grid.buttons[_PAGE_REALITYSCAN].clicked.connect(
            lambda _checked=False: self.show_realityscan_realign()
        )
        self.card_grid.buttons[SFM_ROUTE_COLMAP].clicked.connect(
            lambda _checked=False: self.show_route(SFM_ROUTE_COLMAP)
        )
        self.card_grid.buttons[SFM_ROUTE_SPHERESFM].clicked.connect(
            lambda _checked=False: self.show_route(SFM_ROUTE_SPHERESFM)
        )
        self.card_grid.buttons[_CARD_VIEWER].clicked.connect(lambda _checked=False: self.show_viewer())
        layout.addWidget(self.card_grid)
        layout.addStretch()
        return page

    def _wrap_detail_page(self, title: str, description: str, body: QWidget) -> QWidget:
        page = QWidget()
        page.setAccessibleName(title)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        note = QLabel(description)
        note.setObjectName("workflowNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(body, stretch=1)
        return page

    def _build_realityscan_detail_page(self) -> QWidget:
        page = QWidget()
        page.setAccessibleName(i18n.t("SFM_REALITYSCAN_DETAIL_TITLE"))
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        note = QLabel(i18n.t("SFM_REALITYSCAN_DETAIL_DESC"))
        note.setObjectName("workflowNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.realityscan_cubemap_layout = layout
        layout.addStretch()
        return page

    def _build_colmap_detail(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(6)

        self.colmap_scale_combo = self._clone_combo(self.cubemap_step.scale_combo)
        self.colmap_scale_combo.setFixedWidth(120)
        add_tooltip_row(form, i18n.t("OUTPUT_SCALE"), self.colmap_scale_combo, i18n.tip("OUTPUT_SCALE"))

        exe_filter = "Executable (*.exe);;All (*.*)" if os.name == "nt" else "All (*)"
        colmap_filter = "COLMAP launcher (*.bat *.cmd *.exe);;All (*.*)" if os.name == "nt" else "All (*)"
        self.colmap_exec_browse = BrowseWidget(
            mode="file",
            filter_str=colmap_filter,
            placeholder="COLMAP.bat / colmap.exe" if os.name == "nt" else "colmap",
        )
        self.colmap_exec_browse.setToolTip(i18n.tip("COLMAP_EXECUTABLE"))
        add_tooltip_row(
            form,
            i18n.t("COLMAP_EXECUTABLE"),
            self.colmap_exec_browse,
            i18n.tip("COLMAP_EXECUTABLE"),
        )

        self.colmap_matcher_combo = self._clone_combo(self.cubemap_step.colmap_matcher_combo)
        self.colmap_mapper_combo = self._clone_combo(self.cubemap_step.colmap_mapper_combo)
        pipeline_row = QWidget()
        pipeline_layout = QHBoxLayout(pipeline_row)
        pipeline_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_layout.setSpacing(8)
        pipeline_layout.addWidget(QLabel(i18n.t("COLMAP_MATCHER_COMPACT")))
        pipeline_layout.addWidget(self.colmap_matcher_combo)
        pipeline_layout.addWidget(QLabel(i18n.t("COLMAP_MAPPER_COMPACT")))
        pipeline_layout.addWidget(self.colmap_mapper_combo)
        pipeline_layout.addStretch()
        form.addRow(pipeline_row)

        self.glomap_exec_browse = BrowseWidget(
            mode="file",
            filter_str=exe_filter,
            placeholder="glomap.exe" if os.name == "nt" else "glomap",
        )
        self.glomap_exec_browse.setToolTip(i18n.tip("GLOMAP_EXECUTABLE"))
        self.glomap_exec_row_label = QLabel(i18n.t("GLOMAP_EXECUTABLE"))
        self.glomap_exec_row_label.setToolTip(i18n.tip("GLOMAP_EXECUTABLE"))
        form.addRow(self.glomap_exec_row_label, self.glomap_exec_browse)

        # Normal-image intrinsics are intentionally not exposed as free-form UI.
        # Most users only have smartphone/JPEG/video frames, not calibrated
        # per-source/per-resolution fx/fy/cx/cy/distortion values. A visible
        # manual field made the common workflow look riskier than it is. The
        # lower-level normal_camera_metadata contract remains for imported
        # calibrated metadata; reintroduce UI only as a group-aware or
        # calibration-file import flow, not as a scene-wide params textbox.

        layout.addLayout(form)
        layout.addStretch()
        self.colmap_repo_link = self._build_route_official_link(SFM_ROUTE_COLMAP, "sfmColmapRepositoryLink")
        layout.addWidget(self.colmap_repo_link, alignment=Qt.AlignLeft)
        return page

    def _build_spheresfm_detail(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(6)

        colmap_filter = "COLMAP launcher (*.bat *.cmd *.exe);;All (*.*)" if os.name == "nt" else "All (*)"
        self.spheresfm_exec_browse = BrowseWidget(
            mode="file",
            filter_str=colmap_filter,
            placeholder="COLMAP.bat / colmap.exe" if os.name == "nt" else "colmap",
        )
        self.spheresfm_exec_browse.setToolTip(i18n.tip("SPHERESFM_EXECUTABLE"))
        add_tooltip_row(
            form,
            i18n.t("SPHERESFM_EXECUTABLE"),
            self.spheresfm_exec_browse,
            i18n.tip("SPHERESFM_EXECUTABLE"),
        )

        self.spheresfm_use_masks_cb = QCheckBox(i18n.t("SPHERESFM_USE_MASKS"))
        self.spheresfm_use_masks_cb.setToolTip(i18n.tip("SPHERESFM_USE_MASKS"))
        form.addRow("", self.spheresfm_use_masks_cb)

        self.spheresfm_matcher_combo = self._clone_combo(self.cubemap_step.spheresfm_matcher_combo)
        self.spheresfm_quality_combo = self._clone_combo(self.cubemap_step.spheresfm_quality_combo)
        pipeline_row = QWidget()
        pipeline_layout = QHBoxLayout(pipeline_row)
        pipeline_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_layout.setSpacing(8)
        pipeline_layout.addWidget(QLabel(i18n.t("COLMAP_MATCHER_COMPACT")))
        pipeline_layout.addWidget(self.spheresfm_matcher_combo)
        pipeline_layout.addWidget(QLabel(i18n.t("SPHERESFM_QUALITY_COMPACT")))
        pipeline_layout.addWidget(self.spheresfm_quality_combo)
        pipeline_layout.addStretch()
        form.addRow(pipeline_row)

        self.spheresfm_pose_browse = BrowseWidget(
            mode="file",
            filter_str="Text (*.txt *.csv);;All (*.*)",
            placeholder="POS.txt",
        )
        self.spheresfm_pose_browse.setToolTip(i18n.tip("SPHERESFM_POSE_FILE"))

        layout.addLayout(form)
        layout.addStretch()
        self.spheresfm_repo_link = self._build_route_official_link(
            SFM_ROUTE_SPHERESFM,
            "sfmSpheresfmRepositoryLink",
        )
        layout.addWidget(self.spheresfm_repo_link, alignment=Qt.AlignLeft)
        return page

    @staticmethod
    def _build_route_official_link(route_id: str, object_name: str) -> QLabel:
        spec = get_sfm_route_spec(route_id)
        return make_external_link(
            i18n.t(spec.official_link_key),
            spec.official_url,
            i18n.tip(spec.official_link_key),
            object_name,
        )

    def _connect_child_signals(self) -> None:
        self.cubemap_step.primary_action_state_changed.connect(self.primary_action_state_changed)
        for widget in (
            self.colmap_exec_browse,
            self.glomap_exec_browse,
            self.spheresfm_exec_browse,
            self.spheresfm_pose_browse,
        ):
            widget.path_changed.connect(self._on_detail_control_changed)
        for combo in (
            self.colmap_scale_combo,
            self.colmap_matcher_combo,
            self.colmap_mapper_combo,
            self.spheresfm_matcher_combo,
            self.spheresfm_quality_combo,
        ):
            combo.currentIndexChanged.connect(self._on_detail_control_changed)
        self.colmap_mapper_combo.currentIndexChanged.connect(self._sync_colmap_glomap_visibility)
        self.spheresfm_use_masks_cb.toggled.connect(self._on_detail_control_changed)

    @staticmethod
    def _clone_combo(source: QComboBox) -> QComboBox:
        combo = QComboBox()
        for index in range(source.count()):
            combo.addItem(source.itemText(index), source.itemData(index))
        combo.setCurrentIndex(source.currentIndex())
        combo.setToolTip(source.toolTip())
        combo.setFixedWidth(max(120, source.width() or source.sizeHint().width()))
        return combo

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = SfmStep._find_combo_data(combo, value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _find_combo_data(combo: QComboBox, value: object) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                return index
        return -1

    def _sync_from_cubemap(self) -> None:
        self._sync_cubemap_scene()
        self._syncing_controls = True
        try:
            self.colmap_exec_browse.set_text(self.cubemap_step.colmap_exec_browse.text())
            self.glomap_exec_browse.set_text(self.cubemap_step.glomap_exec_browse.text())
            self._set_combo_data(self.colmap_scale_combo, self.cubemap_step.scale_combo.currentData())
            self._set_combo_data(self.colmap_matcher_combo, self.cubemap_step.colmap_matcher_combo.currentData())
            self._set_combo_data(self.colmap_mapper_combo, self.cubemap_step.colmap_mapper_combo.currentData())

            self.spheresfm_exec_browse.set_text(self.cubemap_step.spheresfm_exec_browse.text())
            self.spheresfm_use_masks_cb.setChecked(self.cubemap_step.spheresfm_use_masks_cb.isChecked())
            self._set_combo_data(self.spheresfm_matcher_combo, self.cubemap_step.spheresfm_matcher_combo.currentData())
            self._set_combo_data(self.spheresfm_quality_combo, self.cubemap_step.spheresfm_quality_combo.currentData())
            self.spheresfm_pose_browse.set_text(self.cubemap_step.spheresfm_pose_browse.text())
        finally:
            self._syncing_controls = False
        self._sync_colmap_glomap_visibility()

    def _apply_to_cubemap(self) -> None:
        self.cubemap_step.colmap_exec_browse.set_text(self.colmap_exec_browse.text())
        self.cubemap_step.glomap_exec_browse.set_text(self.glomap_exec_browse.text())
        self.cubemap_step._set_combo_data(self.cubemap_step.scale_combo, self.colmap_scale_combo.currentData())
        self.cubemap_step._set_combo_data(
            self.cubemap_step.colmap_matcher_combo,
            self.colmap_matcher_combo.currentData(),
        )
        self.cubemap_step._set_combo_data(
            self.cubemap_step.colmap_mapper_combo,
            self.colmap_mapper_combo.currentData(),
        )

        self.cubemap_step.spheresfm_exec_browse.set_text(self.spheresfm_exec_browse.text())
        self.cubemap_step.spheresfm_use_masks_cb.setChecked(self.spheresfm_use_masks_cb.isChecked())
        self.cubemap_step._set_combo_data(
            self.cubemap_step.spheresfm_matcher_combo,
            self.spheresfm_matcher_combo.currentData(),
        )
        self.cubemap_step._set_combo_data(
            self.cubemap_step.spheresfm_quality_combo,
            self.spheresfm_quality_combo.currentData(),
        )
        self.cubemap_step.spheresfm_pose_browse.set_text(self.spheresfm_pose_browse.text())

    def _on_detail_control_changed(self, *_args) -> None:
        if self._syncing_controls:
            return
        if self._page in {_PAGE_COLMAP, _PAGE_SPHERESFM}:
            self._apply_to_cubemap()
            self._prepare_current_route()
        self.primary_action_state_changed.emit()

    def _prepare_current_route(self) -> None:
        if self._page == _PAGE_COLMAP:
            self._prepare_colmap_route()
        elif self._page == _PAGE_SPHERESFM:
            self._prepare_spheresfm_route()
        elif self._page == _PAGE_REALITYSCAN:
            self._prepare_realityscan_route()

    def _prepare_colmap_route(self) -> None:
        self.cubemap_step.disable_dataset_mask_settings()
        self.cubemap_step._set_export_method(SFM_ROUTE_COLMAP)
        self.cubemap_step.export_images_cb.setChecked(True)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_SFM, True)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION, True)
        self.cubemap_step.activate_pipeline_stage(_PIPELINE_STAGE_SFM)

    def _prepare_spheresfm_route(self) -> None:
        self.cubemap_step.disable_dataset_mask_settings()
        self.cubemap_step._set_export_method(SFM_ROUTE_SPHERESFM)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_SFM, True)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION, False)
        self.cubemap_step.activate_pipeline_stage(_PIPELINE_STAGE_SFM)

    def _prepare_realityscan_route(self) -> None:
        self.cubemap_step.disable_dataset_mask_settings()
        self._attach_realityscan_cubemap_step()
        self.cubemap_step.export_method_row.setVisible(False)
        self._set_realityscan_profile_visible(True)
        self.cubemap_step._set_export_method(SFM_ROUTE_METASHAPE)
        self.cubemap_step._set_combo_data(self.cubemap_step.profile_combo, _PROFILE_REALITYSCAN)
        self.cubemap_step._set_combo_data(self.cubemap_step.output_shape_combo, _OUTPUT_SHAPE_PROJECTED)
        self.cubemap_step.export_colmap_cb.setChecked(False)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_SFM, False)
        self.cubemap_step.set_pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION, True)
        self.cubemap_step.activate_pipeline_stage(_PIPELINE_STAGE_SFM)
        self._set_realityscan_profile_controls_visible(False)

    def _attach_realityscan_cubemap_step(self) -> None:
        if self.realityscan_cubemap_layout.indexOf(self.cubemap_step) >= 0:
            return
        self.realityscan_cubemap_layout.insertWidget(
            max(1, self.realityscan_cubemap_layout.count() - 1),
            self.cubemap_step,
            stretch=1,
        )

    def _set_realityscan_profile_visible(self, visible: bool) -> None:
        index = self.cubemap_step.profile_combo.findData(_PROFILE_REALITYSCAN)
        if index >= 0:
            self.cubemap_step.profile_combo.view().setRowHidden(index, not visible)

    def _set_realityscan_profile_controls_visible(self, visible: bool) -> None:
        self.cubemap_step.profile_combo.setVisible(visible)
        if self.cubemap_step.profile_label is not None:
            self.cubemap_step.profile_label.setVisible(visible)

    def _sync_colmap_glomap_visibility(self, *_args) -> None:
        visible = self.colmap_mapper_combo.currentData() == _COLMAP_MAPPER_GLOMAP
        self.glomap_exec_row_label.setVisible(visible)
        self.glomap_exec_browse.setVisible(visible)

    def _sync_cubemap_scene(self) -> None:
        if self.cubemap_step.scene_dir != self.scene_dir:
            self.cubemap_step.set_scene_dir(self.scene_dir)

    def _sync_route_scene(self) -> None:
        if self._page not in _RUNNABLE_PAGES:
            return
        self._sync_cubemap_scene()

    def set_scene_dir(self, path: str) -> None:
        super().set_scene_dir(path)
        if self.scene_preview is not None:
            self.scene_preview.set_scene_dir(Path(path) if path else None, refresh=False)
            if self._page == _PAGE_VIEWER:
                self._defer_scene_preview_refresh()
        self._sync_route_scene()

    def on_activated(self) -> None:
        if self._page in _RUNNABLE_PAGES:
            self._prepare_current_route()
            self._sync_route_scene()
            if self._page in {_PAGE_COLMAP, _PAGE_SPHERESFM}:
                self._sync_from_cubemap()
            if self._page == _PAGE_REALITYSCAN:
                self.cubemap_step.on_activated()
        elif self._page == _PAGE_VIEWER:
            preview = self._ensure_scene_preview()
            preview.set_scene_dir(Path(self.scene_dir) if self.scene_dir else None, refresh=False)
            self._defer_scene_preview_refresh()
        self.primary_action_state_changed.emit()

    def show_menu(self) -> None:
        self._page = _PAGE_MENU
        self.stack.setCurrentIndex(self._page_indices[_PAGE_MENU])
        self.primary_action_state_changed.emit()

    def show_route(self, route_id: str) -> None:
        if route_id == _PAGE_REALITYSCAN:
            self.show_realityscan_realign()
            return
        route = normalize_sfm_route(route_id)
        if route not in {_PAGE_COLMAP, _PAGE_SPHERESFM}:
            self.route_requested.emit(route)
            return
        self._page = route
        self.stack.setCurrentIndex(self._page_indices[route])
        self._prepare_current_route()
        self._sync_route_scene()
        self._sync_from_cubemap()
        self.primary_action_state_changed.emit()

    def current_route(self) -> str:
        return self._page if self._page in _RUNNABLE_PAGES else ""

    def show_realityscan_realign(self) -> None:
        self._page = _PAGE_REALITYSCAN
        self.stack.setCurrentIndex(self._page_indices[_PAGE_REALITYSCAN])
        self._prepare_realityscan_route()
        self._sync_route_scene()
        self.cubemap_step.on_activated()
        self.primary_action_state_changed.emit()

    def show_viewer(self) -> None:
        scene_preview = self._ensure_scene_preview()
        scene_preview.set_scene_dir(Path(self.scene_dir) if self.scene_dir else None, refresh=False)
        self._page = _PAGE_VIEWER
        self.stack.setCurrentIndex(self._page_indices[_PAGE_VIEWER])
        self.primary_action_state_changed.emit()
        self._defer_scene_preview_refresh()

    def _defer_scene_preview_refresh(self) -> None:
        self._scene_preview_refresh_token += 1
        token = self._scene_preview_refresh_token
        QTimer.singleShot(0, lambda: self._refresh_scene_preview_if_current(token))

    def _refresh_scene_preview_if_current(self, token: int) -> None:
        if token != self._scene_preview_refresh_token:
            return
        if self._page != _PAGE_VIEWER or self.scene_preview is None:
            return
        self.scene_preview.refresh()

    def header_title(self) -> str:
        if self._page == _PAGE_COLMAP:
            return i18n.t("SFM_COLMAP_DETAIL_TITLE")
        if self._page == _PAGE_SPHERESFM:
            return i18n.t("SFM_SPHERESFM_DETAIL_TITLE")
        if self._page == _PAGE_REALITYSCAN:
            return i18n.t("SFM_REALITYSCAN_DETAIL_TITLE")
        if self._page == _PAGE_VIEWER:
            return i18n.t("SFM_ROUTE_VIEWER_TITLE")
        return i18n.t("SFM_MENU_TITLE")

    def header_back_enabled(self) -> bool:
        return self._page != _PAGE_MENU

    def header_back_tooltip(self) -> str:
        return i18n.tip("SFM_BACK_TO_ROUTES")

    def header_back(self) -> None:
        self.show_menu()

    def open_scene_preview(self) -> None:
        if self._page in {_PAGE_COLMAP, _PAGE_SPHERESFM}:
            self._apply_to_cubemap()
            self._prepare_current_route()
        self.show_viewer()

    def primary_action_text(self) -> str:
        if self._page == _PAGE_COLMAP:
            return i18n.t("SFM_RUN_COLMAP")
        if self._page == _PAGE_SPHERESFM:
            return i18n.t("SFM_RUN_SPHERESFM")
        if self._page == _PAGE_REALITYSCAN:
            return i18n.t("SFM_RUN_REALITYSCAN")
        if self._page == _PAGE_VIEWER:
            return i18n.t("SFM_OPEN_VIEWER")
        return i18n.t("SFM_SELECT_ROUTE")

    def primary_action_tooltip(self) -> str:
        if self._page == _PAGE_COLMAP:
            return i18n.tip("SFM_RUN_COLMAP")
        if self._page == _PAGE_SPHERESFM:
            return i18n.tip("SFM_RUN_SPHERESFM")
        if self._page == _PAGE_REALITYSCAN:
            return i18n.tip("SFM_RUN_REALITYSCAN")
        if self._page == _PAGE_VIEWER:
            return i18n.tip("SFM_OPEN_VIEWER")
        return i18n.tip("SFM_SELECT_ROUTE")

    def primary_action_enabled(self) -> bool:
        if self._page in {_PAGE_MENU, _PAGE_VIEWER}:
            return False
        self._sync_route_scene()
        return self.cubemap_step.primary_action_enabled()

    def build_commands(self) -> StepCommandQueue:
        if self._page in {_PAGE_MENU, _PAGE_VIEWER}:
            return []
        self._sync_route_scene()
        if self._page in {_PAGE_COLMAP, _PAGE_SPHERESFM}:
            self._apply_to_cubemap()
        self._prepare_current_route()
        return self.cubemap_step.build_commands()

    def confirm_commands(self, commands: StepCommandQueue) -> bool:
        return self.cubemap_step.confirm_commands(commands)

    def process_log_dir(self) -> Path | None:
        return self.cubemap_step.process_log_dir() if self._page in _RUNNABLE_PAGES else None

    def phase_display_name(self, phase: str) -> str:
        return self.cubemap_step.phase_display_name(phase) if self._page in _RUNNABLE_PAGES else phase

    def phase_status_text(self, phase: str, queue_index: int, queue_total: int) -> str:
        if self._page not in _RUNNABLE_PAGES:
            return super().phase_status_text(phase, queue_index, queue_total)
        return self.cubemap_step.phase_status_text(phase, queue_index, queue_total)

    def on_line(self, line: str) -> tuple[int, int] | None:
        return self.cubemap_step.on_line(line) if self._page in _RUNNABLE_PAGES else None

    def on_phase_started(self, phase: str) -> tuple[int, int] | None:
        return self.cubemap_step.on_phase_started(phase) if self._page in _RUNNABLE_PAGES else None

    def on_phase_log_started(self, phase: str, path: str) -> None:
        if self._page in _RUNNABLE_PAGES:
            self.cubemap_step.on_phase_log_started(phase, path)

    def on_phase_finished(self, phase: str, exit_code: int, canceled: bool) -> None:
        if self._page in _RUNNABLE_PAGES:
            self.cubemap_step.on_phase_finished(phase, exit_code, canceled)

    def on_queue_finished(self, success: bool) -> None:
        if self._page in _RUNNABLE_PAGES:
            self.cubemap_step.on_queue_finished(success)
