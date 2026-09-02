"""Step 4 runtime finalization, progress parsing, and input discovery."""

from __future__ import annotations

import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox

from core.colmap_cli import build_colmap_command, colmap_batch_qprocess_native_arguments
from core.orientation_correction import (
    FINAL_ORIENTATION_LICHTFELD,
    FINAL_ORIENTATION_STAGE_DIRECT_FINALIZE,
    apply_final_orientation_to_dataset,
)
from core.safe_xml import parse_xml_file
from core.scene_import_contracts import IMAGE_EXTS
from core.scene_inventory import resolve_scene_image_label
from core.scene_layout import scene_images_dir
from gui import i18n
from gui.steps.step4_contracts import (
    _GENERATED_POINTCLOUD_NAME,
    _PIPELINE_STAGE_CONVERSION,
    _PIPELINE_STAGE_SFM,
    is_colmap_gui_unavailable_output,
    is_spheresfm_rtx50_cuda_error_line,
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


class Step4RuntimeMixin:
    def _open_spheresfm_result(self) -> None:
        if not self.scene_dir:
            return
        model = self._find_spheresfm_sparse_model()
        if model is None:
            QMessageBox.warning(
                self,
                i18n.t("SPHERESFM_OPEN_GUI"),
                i18n.t("SPHERESFM_RESULT_NOT_FOUND").format(path=str(self._spheresfm_sparse_dir())),
            )
            return
        try:
            colmap = self._resolve_spheresfm_executable()
        except ValueError as exc:
            QMessageBox.warning(self, i18n.t("SPHERESFM_OPEN_GUI"), str(exc))
            return
        command = build_colmap_command(
            colmap,
            "gui",
            "--database_path",
            str(self._spheresfm_database_path()),
            "--image_path",
            str(self._metashape_images_dir()),
            "--import_path",
            str(model),
        )
        process = self._create_spheresfm_gui_process()
        process.setProgram(command[0])
        native_arguments = colmap_batch_qprocess_native_arguments(command)
        if native_arguments is None:
            process.setArguments(command[1:])
        else:
            process.setNativeArguments(native_arguments)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.start()
        if not process.waitForStarted(3000):
            detail = process.errorString().strip() or "-"
            QMessageBox.warning(
                self,
                i18n.t("SPHERESFM_OPEN_GUI"),
                i18n.t("SPHERESFM_OPEN_GUI_FAILED_DETAIL").format(
                    exe=colmap,
                    model=str(model),
                    detail=detail,
                ),
            )
            return
        if process.waitForFinished(1500):
            detail = self._qprocess_output_text(process) or process.errorString().strip() or "-"
            if is_colmap_gui_unavailable_output(detail):
                QMessageBox.warning(
                    self,
                    i18n.t("SPHERESFM_OPEN_GUI"),
                    i18n.t("SPHERESFM_OPEN_GUI_UNAVAILABLE").format(
                        exe=colmap,
                        model=str(model),
                        detail=self._message_detail_tail(detail),
                    ),
                )
                return
            if process.exitStatus() != QProcess.NormalExit or process.exitCode() != 0:
                QMessageBox.warning(
                    self,
                    i18n.t("SPHERESFM_OPEN_GUI"),
                    i18n.t("SPHERESFM_OPEN_GUI_FAILED_DETAIL").format(
                        exe=colmap,
                        model=str(model),
                        detail=self._message_detail_tail(detail),
                    ),
                )
            return

        self._spheresfm_gui_processes.append(process)
        process.finished.connect(
            lambda _exit_code, _exit_status, proc=process, exe=colmap, model_path=str(model): (
                self._on_spheresfm_gui_process_finished(proc, exe, model_path)
            )
        )
        if process.state() == QProcess.NotRunning:
            self._on_spheresfm_gui_process_finished(process, colmap, str(model))

    def _create_spheresfm_gui_process(self) -> QProcess:
        return QProcess(self)

    @staticmethod
    def _qprocess_output_text(process: QProcess) -> str:
        raw = bytes(process.readAllStandardOutput()) + bytes(process.readAllStandardError())
        return raw.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _message_detail_tail(detail: str, limit: int = 1800) -> str:
        text = detail.strip()
        if len(text) <= limit:
            return text or "-"
        return "...\n" + text[-limit:]

    def _on_spheresfm_gui_process_finished(self, process: QProcess, colmap: str, model: str) -> None:
        if not self._forget_spheresfm_gui_process(process):
            return
        detail = self._qprocess_output_text(process) or process.errorString().strip() or "-"
        if is_colmap_gui_unavailable_output(detail):
            QMessageBox.warning(
                self,
                i18n.t("SPHERESFM_OPEN_GUI"),
                i18n.t("SPHERESFM_OPEN_GUI_UNAVAILABLE").format(
                    exe=colmap,
                    model=model,
                    detail=self._message_detail_tail(detail),
                ),
            )

    def _forget_spheresfm_gui_process(self, process: QProcess) -> bool:
        if not any(p is process for p in self._spheresfm_gui_processes):
            return False
        self._spheresfm_gui_processes = [p for p in self._spheresfm_gui_processes if p is not process]
        process.deleteLater()
        return True

    def on_phase_log_started(self, phase: str, path: str) -> None:
        if phase.startswith("spheresfm_"):
            self._spheresfm_phase_logs[phase] = Path(path)
        elif phase.startswith("training_"):
            self._training_phase_logs[phase] = Path(path)

    def on_phase_finished(self, phase: str, exit_code: int, canceled: bool) -> None:
        if self._dataset_mask_phase(phase) and self._dataset_mask_step is not None:
            self._dataset_mask_step.on_phase_finished(phase, exit_code, canceled)
        if (
            phase.startswith("spheresfm_")
            and exit_code != 0
            and not canceled
            and self._spheresfm_rtx50_cuda_error_seen
            and self._spheresfm_rtx50_cuda_error_phase == phase
            and not self._spheresfm_rtx50_cuda_error_shown
        ):
            self._show_spheresfm_rtx50_cuda_error(phase)

    def _show_spheresfm_rtx50_cuda_error(self, phase: str) -> None:
        self._spheresfm_rtx50_cuda_error_shown = True
        log_path = self._spheresfm_phase_logs.get(phase)
        log_text = str(log_path) if log_path is not None else "-"
        QMessageBox.warning(
            self,
            i18n.t("SPHERESFM_RTX50_CUDA_ERROR_TITLE"),
            i18n.t("SPHERESFM_RTX50_CUDA_ERROR_BODY").format(log_path=log_text),
        )

    def on_queue_finished(self, success: bool) -> None:
        if self._dataset_mask_step is not None:
            self._dataset_mask_step.on_queue_finished(success)
        if success:
            try:
                self._finalize_bundle()
            except Exception:
                pass

    def _finalize_bundle(self) -> None:
        if self._is_spheresfm_method():
            if self._uses_spheresfm_projected_output():
                if not self._uses_spheresfm_lichtfeld_final_correction():
                    source_ply = self._spheresfm_equirect_dir() / "pointcloud.ply"
                    dest_ply = self._spheresfm_cubemap_dir() / "pointcloud.ply"
                    if source_ply.is_file():
                        dest_ply.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_ply, dest_ply)
                        transforms = self._spheresfm_cubemap_dir() / "transforms.json"
                        if transforms.is_file():
                            data = json.loads(transforms.read_text(encoding="utf-8"))
                            data["ply_file_path"] = dest_ply.name
                            transforms.write_text(json.dumps(data, indent=2), encoding="utf-8")
            elif self._uses_spheresfm_3dgut_output() and self._uses_spheresfm_lichtfeld_final_correction():
                self._apply_lichtfeld_final_correction(self._spheresfm_3dgut_dir())
            self._write_export_settings()
            self._write_spheresfm_project_manifest()
            self._record_step4_runs(
                sfm_mode="spheresfm" if self._spheresfm_runs_sfm() else None,
                dataset=self._spheresfm_runs_conversion(),
            )
            return

        if self._is_colmap_method():
            self._write_export_settings()
            self._write_colmap_project_manifest()
            self._record_step4_runs(
                sfm_mode="colmap" if self.pipeline_stage_intent(_PIPELINE_STAGE_SFM) else None,
                dataset=self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION),
            )
            return

        if self._uses_direct_equirect_output():
            if self._uses_lichtfeld_final_correction():
                self._apply_lichtfeld_final_correction(self._direct_output_dir())
            self._write_export_settings()
            self._record_step4_runs(
                sfm_mode="metashape_import" if self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION) else None,
                dataset=self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION),
            )
            return

        output = self._display_output_dir()
        output.mkdir(parents=True, exist_ok=True)

        if (
            not self._uses_lichtfeld_final_correction()
            and not self._is_realityscan_profile()
            and not self._uses_metashape_nerf_dataset_writer()
        ):
            source = self._resolve_ply_source()
            if source is not None:
                dest = output / source.name
                if source.resolve() != dest.resolve():
                    shutil.copy2(source, dest)

                transforms = output / "transforms.json"
                if transforms.is_file():
                    data = json.loads(transforms.read_text(encoding="utf-8"))
                    data["ply_file_path"] = dest.name
                    transforms.write_text(json.dumps(data, indent=2), encoding="utf-8")

        if self._writes_any_view_assets() or self._uses_metashape_nerf_dataset_writer():
            self._write_export_settings()
        self._record_step4_runs(
            sfm_mode="metashape_import" if self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION) else None,
            dataset=self.pipeline_stage_intent(_PIPELINE_STAGE_CONVERSION),
        )

    def _apply_lichtfeld_final_correction(self, output: Path) -> None:
        apply_final_orientation_to_dataset(
            output,
            FINAL_ORIENTATION_LICHTFELD,
            stage=FINAL_ORIENTATION_STAGE_DIRECT_FINALIZE,
        )

    # -- プログレス --

    def phase_display_name(self, phase: str) -> str:
        labels = {
            "metashape": "PHASE_METASHAPE_IMPORT",
            "metashape_nerf": "PHASE_METASHAPE_NERF",
            "colmap_rig_export": "PHASE_COLMAP_RIG_EXPORT",
            "colmap_mixed_prepare": "PHASE_COLMAP_MIXED_PREPARE",
            "colmap_feature": "PHASE_COLMAP_FEATURE",
            "colmap_feature_rig": "PHASE_COLMAP_FEATURE_RIG",
            "colmap_feature_normal": "PHASE_COLMAP_FEATURE_NORMAL",
            "colmap_rig_config": "PHASE_COLMAP_RIG_CONFIG",
            "colmap_match": "PHASE_COLMAP_MATCH",
            "colmap_mapper": "PHASE_COLMAP_MAPPER",
            "spheresfm_preflight": "PHASE_SPHERESFM_PREFLIGHT",
            "spheresfm_prepare": "PHASE_SPHERESFM_PREPARE",
            "spheresfm_database": "PHASE_SPHERESFM_DATABASE",
            "spheresfm_feature": "PHASE_SPHERESFM_FEATURE",
            "spheresfm_match": "PHASE_SPHERESFM_MATCH",
            "spheresfm_mapper": "PHASE_SPHERESFM_MAPPER",
            "spheresfm_transforms": "PHASE_SPHERESFM_TRANSFORMS",
            "spheresfm_cubemap": "PHASE_SPHERESFM_CUBEMAP",
            "training_lichtfeld": "PHASE_TRAINING_LICHTFELD",
            "training_postshot": "PHASE_TRAINING_POSTSHOT",
            "training_brush": "PHASE_TRAINING_BRUSH",
            "training_gsplat": "PHASE_TRAINING_GSPLAT",
            "dataset_mask_paths": "PHASE_DATASET_MASK_PATHS",
        }
        if self._dataset_mask_phase(phase) and self._dataset_mask_step is not None:
            return self._dataset_mask_step.phase_display_name(phase)
        if phase.startswith("colmap_feature_rig_"):
            return i18n.t("PHASE_COLMAP_FEATURE_RIG")
        if phase.startswith("colmap_feature_normal_"):
            return i18n.t("PHASE_COLMAP_FEATURE_NORMAL")
        key = labels.get(phase)
        return i18n.t(key) if key else phase

    def on_phase_started(self, phase: str) -> tuple[int, int] | None:
        self._active_runner_phase = phase
        if self._dataset_mask_phase(phase) and self._dataset_mask_step is not None:
            return self._dataset_mask_step.on_phase_started(phase)
        if phase == "colmap_rig_export":
            self._converted_total = 0
            self._processed = 0
            self._explicit_progress = False
            return None
        if phase == "colmap_mixed_prepare":
            self._converted_total = 0
            self._processed = 0
            self._explicit_progress = False
            return None
        if phase == "metashape_nerf":
            self._converted_total = 0
            self._processed = 0
            self._explicit_progress = False
            return None
        if phase == "spheresfm_cubemap":
            self._converted_total = 0
            self._processed = 0
            self._explicit_progress = False
            return None
        if phase == "colmap_feature":
            total = self._count_colmap_rig_images()
            return 0, total if total > 0 else 0
        if phase == "colmap_feature_rig":
            total = self._count_colmap_image_list(self._colmap_rig_dir() / "rig_image_list.txt")
            return 0, total if total > 0 else 0
        if phase == "colmap_feature_normal":
            total = self._count_colmap_image_list(self._colmap_rig_dir() / "normal_image_list.txt")
            return 0, total if total > 0 else 0
        if phase == "spheresfm_prepare":
            total = self._count_source_images()
            return 0, total if total > 0 else 0
        if phase == "spheresfm_preflight":
            return 0, 1
        if phase == "spheresfm_feature":
            total = self._count_source_images()
            return 0, total if total > 0 else 0
        if phase in {"colmap_rig_config", "colmap_match", "colmap_mapper"}:
            self._colmap_ba_iterations = 0
            return 0, 0
        if phase in {"spheresfm_database", "spheresfm_match", "spheresfm_mapper", "spheresfm_transforms"}:
            self._colmap_ba_iterations = 0
            return 0, 0
        return None

    def on_line(self, line: str) -> tuple[int, int] | None:
        if self._dataset_mask_phase(self._active_runner_phase) and self._dataset_mask_step is not None:
            progress = self._dataset_mask_step.on_line(line)
            if progress is not None:
                return progress
        if self._is_spheresfm_method() and is_spheresfm_rtx50_cuda_error_line(line):
            self._spheresfm_rtx50_cuda_error_seen = True
            if self._active_runner_phase.startswith("spheresfm_"):
                self._spheresfm_rtx50_cuda_error_phase = self._active_runner_phase

        colmap_feature = _COLMAP_FEATURE_RE.search(line)
        if colmap_feature:
            return int(colmap_feature.group(1)), int(colmap_feature.group(2))

        colmap_match_image = _COLMAP_MATCH_IMAGE_RE.search(line)
        if colmap_match_image:
            return int(colmap_match_image.group(1)), int(colmap_match_image.group(2))

        colmap_match_block = _COLMAP_MATCH_BLOCK_RE.search(line)
        if colmap_match_block:
            block_row = int(colmap_match_block.group(1))
            block_rows = int(colmap_match_block.group(2))
            block_col = int(colmap_match_block.group(3))
            block_cols = int(colmap_match_block.group(4))
            total = max(1, block_rows * block_cols)
            done = min(total, max(1, (block_row - 1) * block_cols + block_col))
            return done, total

        colmap_ba_fixed = _COLMAP_GLOBAL_BA_FIXED_RE.search(line)
        if colmap_ba_fixed:
            return self._colmap_global_ba_progress(
                int(colmap_ba_fixed.group(1)),
                int(colmap_ba_fixed.group(2)),
                fixed_rotation=True,
            )

        colmap_ba_done = _COLMAP_GLOBAL_BA_DONE_RE.search(line)
        if colmap_ba_done:
            return self._colmap_global_ba_progress(
                int(colmap_ba_done.group(1)),
                int(colmap_ba_done.group(2)),
                fixed_rotation=False,
            )

        if _COLMAP_RETRIANGULATION_START_RE.search(line):
            return self._colmap_retriangulation_progress(done=False)

        if _COLMAP_RETRIANGULATION_DONE_RE.search(line) or _COLMAP_RECONSTRUCTION_DONE_RE.search(line):
            return self._colmap_retriangulation_progress(done=True)

        progress = _PROGRESS_RE.match(line)
        if progress:
            self._processed = int(progress.group(1))
            self._converted_total = int(progress.group(2))
            self._explicit_progress = True
            return self._processed, self._converted_total

        m = _CONVERT_RE.match(line)
        if m:
            self._converted_total = int(m.group(1))
            self._processed = 0
            self._explicit_progress = False
            return 0, self._converted_total

        if line.startswith("Processing:") and self._converted_total > 0 and not self._explicit_progress:
            self._processed += 1
            return self._processed, self._converted_total

        return None

    @staticmethod
    def _dataset_mask_phase(phase: str) -> bool:
        return phase in {
            "yolo",
            "yolo_equirect",
            "yolo_normal",
            "stitch",
            "stitch_equirect",
            "overexposure",
            "custom",
            "init_masks",
        }

    def _colmap_global_ba_progress(
        self,
        iteration: int,
        total_iterations: int,
        *,
        fixed_rotation: bool,
    ) -> tuple[int, int]:
        total_iterations = max(1, total_iterations)
        iteration = min(max(1, iteration), total_iterations)
        self._colmap_ba_iterations = max(self._colmap_ba_iterations, total_iterations)
        total_units = total_iterations * 2 + 2
        done_units = (iteration - 1) * 2 + (1 if fixed_rotation else 2)
        return done_units, total_units

    def _colmap_retriangulation_progress(self, *, done: bool) -> tuple[int, int]:
        iterations = max(1, self._colmap_ba_iterations)
        total_units = iterations * 2 + 2
        return (total_units if done else total_units - 1), total_units

    def _count_colmap_rig_images(self) -> int:
        images_dir = self._colmap_rig_images_dir()
        return self._count_images_in_dir(images_dir)

    @staticmethod
    def _count_colmap_image_list(path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            return 0

    def _count_source_images(self) -> int:
        if not self.scene_dir:
            return 0
        images_dir = self._metashape_images_dir()
        return self._count_images_in_dir(images_dir)

    # -- ヘルパー --

    @staticmethod
    def _format_candidate_names(paths: tuple[Path, ...] | list[Path]) -> str:
        names = [p.name for p in paths]
        if len(names) > 4:
            names = names[:4] + [f"+{len(names) - 4}"]
        return ", ".join(names)

    @staticmethod
    def _path_is_same_or_descendant(path: Path, root: Path) -> bool:
        try:
            resolved_path = path.resolve()
            resolved_root = root.resolve()
        except OSError:
            resolved_path = path.absolute()
            resolved_root = root.absolute()
        return resolved_path == resolved_root or resolved_root in resolved_path.parents

    def _metashape_input_output_path_issue(self, path: Path) -> str | None:
        if not self.scene_dir:
            return None
        try:
            output = self._output_dir()
        except ValueError:
            return None
        if self._path_is_same_or_descendant(path, output):
            return i18n.t("MS_INPUT_IN_OUTPUT_HINT").format(path=str(path), output=str(output))
        return None

    @staticmethod
    def _scene_xml_candidates(scene_dir: Path) -> tuple[Path, ...]:
        return tuple(sorted([p for p in scene_dir.glob("*.xml") if p.is_file()], key=lambda x: x.name.lower()))

    @staticmethod
    def _scene_ply_candidates(scene_dir: Path) -> tuple[Path, ...]:
        return tuple(
            sorted(
                [p for p in scene_dir.glob("*.ply") if p.is_file() and p.name.lower() != _GENERATED_POINTCLOUD_NAME],
                key=lambda x: x.name.lower(),
            )
        )

    def _guess_xml(self, scene_dir: Path) -> Path | None:
        scored = [
            score
            for candidate in self._scene_xml_candidates(scene_dir)
            if (score := self._metashape_xml_candidate_score(candidate, scene_dir)) is not None
        ]
        self._metashape_auto_xml_candidates = tuple(score[0] for score in scored)
        if not scored:
            return None
        if len(scored) == 1:
            return scored[0][0]
        scored.sort(key=lambda item: (item[1], item[2], item[3], item[0].name.lower()), reverse=True)
        best = scored[0]
        second = scored[1]
        if best[1] > second[1]:
            return best[0]
        return None

    def _guess_ply(self, scene_dir: Path) -> Path | None:
        candidates = self._scene_ply_candidates(scene_dir)
        self._metashape_auto_ply_candidates = candidates
        return candidates[0] if len(candidates) == 1 else None

    def _metashape_xml_candidate_score(self, path: Path, scene_dir: Path) -> tuple[Path, int, int, int] | None:
        try:
            root = parse_xml_file(path).getroot()
        except (ET.ParseError, OSError, ValueError):
            return None
        if self._xml_tag_name(root.tag) != "document":
            return None
        image_lookup = self._metashape_image_label_lookup(scene_dir)
        total_cameras = 0
        transformed_cameras = 0
        image_matches = 0
        chunks = [node for node in root.iter() if self._xml_tag_name(node.tag) == "chunk"]
        for chunk in chunks:
            sensors = self._metashape_sensor_ids(chunk)
            if not sensors:
                continue
            cameras_parent = self._xml_child(chunk, "cameras")
            if cameras_parent is None:
                continue
            for camera in self._xml_children(cameras_parent, "camera"):
                if str(camera.get("sensor_id") or "").strip() not in sensors:
                    continue
                label = str(camera.get("label") or "").strip()
                if not label:
                    continue
                total_cameras += 1
                transform = self._xml_child(camera, "transform")
                if self._xml_transform_has_16_numbers(transform):
                    transformed_cameras += 1
                if self._metashape_label_matches_image(label, image_lookup):
                    image_matches += 1
        if total_cameras <= 0 or transformed_cameras <= 0:
            return None
        return (path, image_matches, transformed_cameras, total_cameras)

    @staticmethod
    def _xml_tag_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    @classmethod
    def _xml_child(cls, element: ET.Element, name: str) -> ET.Element | None:
        for child in element:
            if cls._xml_tag_name(child.tag) == name:
                return child
        return None

    @classmethod
    def _xml_children(cls, element: ET.Element, name: str) -> list[ET.Element]:
        return [child for child in element if cls._xml_tag_name(child.tag) == name]

    @classmethod
    def _metashape_sensor_ids(cls, chunk: ET.Element) -> set[str]:
        sensors_parent = cls._xml_child(chunk, "sensors")
        if sensors_parent is None:
            return set()
        sensor_ids: set[str] = set()
        for sensor in cls._xml_children(sensors_parent, "sensor"):
            sensor_id = str(sensor.get("id") or "").strip()
            if not sensor_id:
                continue
            if str(sensor.get("type") or "").strip() or cls._xml_child(sensor, "calibration") is not None:
                sensor_ids.add(sensor_id)
        return sensor_ids

    @staticmethod
    def _xml_transform_has_16_numbers(transform: ET.Element | None) -> bool:
        if transform is None or not transform.text:
            return False
        parts = transform.text.split()
        if len(parts) != 16:
            return False
        try:
            values = [float(part) for part in parts]
        except ValueError:
            return False
        return all(math.isfinite(value) for value in values)

    @staticmethod
    def _metashape_image_label_lookup(scene_dir: Path) -> dict[str, Path]:
        images_dir = scene_images_dir(scene_dir)
        roots = [images_dir] if images_dir.is_dir() else [scene_dir]
        grouped: dict[str, list[Path]] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                    continue
                for key in Step4RuntimeMixin._metashape_label_keys(scene_dir, images_dir, path):
                    grouped.setdefault(key.casefold(), []).append(path)
        return {
            key: paths[0]
            for key, paths in grouped.items()
            if len({str(path).replace("\\", "/").casefold() for path in paths}) == 1
        }

    @staticmethod
    def _metashape_label_keys(scene_dir: Path, images_dir: Path, path: Path) -> set[str]:
        keys = {path.name, path.stem}
        try:
            rel_scene = path.relative_to(scene_dir).as_posix()
            keys.add(rel_scene)
            keys.add(Path(rel_scene).name)
            keys.add(Path(rel_scene).stem)
        except ValueError:
            pass
        try:
            rel_images = path.relative_to(images_dir).as_posix()
            keys.add(rel_images)
            keys.add(Path(rel_images).name)
            keys.add(Path(rel_images).stem)
            if images_dir.name:
                root_rel = (Path(images_dir.name) / rel_images).as_posix()
                keys.add(root_rel)
                keys.add(Path(root_rel).name)
                keys.add(Path(root_rel).stem)
        except ValueError:
            pass
        return {key for key in keys if key}

    @staticmethod
    def _metashape_label_matches_image(label: str, image_lookup: dict[str, Path]) -> bool:
        return resolve_scene_image_label(label, image_lookup) is not None
