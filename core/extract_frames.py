#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import queue
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core.cancellation import AppJobCancelled, CancellationToken, is_cancelled, raise_if_cancelled, terminate_process
from core.extract_sessions import (
    build_session_record,
    load_manifest,
    new_session_id,
    sanitize_filename_prefix,
    save_manifest,
    session_matches_video,
    video_identity,
)
from core.frame_pair_analysis import (
    PAIR_LOW_TEXTURE_SHARPNESS,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_MOTION_BLUR_BASELINE_MIN,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_MOTION_BLUR_DROP_RATIO,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_MOTION_BLUR_RATIO,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_MOTION_BLUR_REVIEW_RATIO,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_SHARPNESS_HISTORY,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_THRESHOLD_PROFILE_CHOICES,  # noqa: F401 - re-exported for script-module compatibility
    PAIR_THRESHOLD_PROFILES,  # noqa: F401 - re-exported for script-module compatibility
    PairCandidateFrame,  # noqa: F401 - re-exported for script-module compatibility
    PairFrameRisk,  # noqa: F401 - re-exported for script-module compatibility
    PairThresholdProfile,  # noqa: F401 - re-exported for script-module compatibility
    PairTrackMetrics,  # noqa: F401 - re-exported for script-module compatibility
    analyze_pair_selection,
    assess_pair_frame_risk,  # noqa: F401 - re-exported for script-module compatibility
    compute_pair_blur_score,  # noqa: F401 - re-exported for script-module compatibility
    compute_pair_metrics,  # noqa: F401 - re-exported for script-module compatibility
    compute_pair_track_metrics,  # noqa: F401 - re-exported for script-module compatibility
    ensure_python_deps,
    pair_gate_dimensions,
    pair_gate_frame,  # noqa: F401 - re-exported for script-module compatibility
    resolve_pair_thresholds,
    scaled_dimensions,  # noqa: F401 - re-exported for script-module compatibility
)
from core.path_safety import safe_clear_path
from core.scene_layout import extract_report_path, frame_cache_dir, scene_images_dir, selected_frames_path
from core.video_info import VideoInfo, frame_rates_indicate_vfr


@dataclass(frozen=True, slots=True)
class ExtractFramesOptions:
    input_video: Path
    output_dir: Path = Path(".")
    mode: str = "fixed"
    interval_sec: float = 0.5
    min_gap_sec: float = 0.25
    max_gap_sec: float = 2.0
    fixed_smart: bool = False
    quick_extract: bool = False
    fixed_smart_max_inserts_per_interval: int = 2
    pair_track_min_count: int = 36
    pair_motion_profile: str = "walk"
    pair_drop_threshold: float = -1.0
    pair_add_threshold: float = -1.0
    pair_track_min_confidence: float = 0.25
    analysis_width: int = 1920
    image_ext: str = "jpg"
    jpg_quality: int = 2
    filename_prefix: str = ""
    output_mode: str = "overwrite"
    allow_duplicate_video: bool = False
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    estimate_only: bool = False
    print_summary_json: bool = False
    cancel_event: CancellationToken | None = None


def options_from_args(args: argparse.Namespace) -> ExtractFramesOptions:
    return ExtractFramesOptions(
        input_video=Path(str(args.input_video)),
        output_dir=Path(str(args.output_dir)),
        mode=str(args.mode),
        interval_sec=float(args.interval_sec),
        min_gap_sec=float(args.min_gap_sec),
        max_gap_sec=float(args.max_gap_sec),
        fixed_smart=bool(args.fixed_smart),
        quick_extract=bool(args.quick_extract),
        fixed_smart_max_inserts_per_interval=int(args.fixed_smart_max_inserts_per_interval),
        pair_track_min_count=int(args.pair_track_min_count),
        pair_motion_profile=str(args.pair_motion_profile),
        pair_drop_threshold=float(args.pair_drop_threshold),
        pair_add_threshold=float(args.pair_add_threshold),
        pair_track_min_confidence=float(args.pair_track_min_confidence),
        analysis_width=int(args.analysis_width),
        image_ext=str(args.image_ext),
        jpg_quality=int(args.jpg_quality),
        filename_prefix=str(args.filename_prefix),
        output_mode=str(args.output_mode),
        allow_duplicate_video=bool(args.allow_duplicate_video),
        ffmpeg=str(args.ffmpeg),
        ffprobe=str(args.ffprobe),
        estimate_only=bool(args.estimate_only),
        print_summary_json=bool(args.print_summary_json),
    )


def parse_fraction(value: str) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        den_f = float(den)
        if den_f == 0:
            return 0.0
        return float(num) / den_f
    return float(value)


def frame_index_digits(total_frames: int, frame_indices: Sequence[int] | None = None) -> int:
    """Return the zero-padding width needed for frame-index filenames."""
    max_index = total_frames - 1 if total_frames > 0 else -1
    if frame_indices:
        max_index = max(max_index, max(frame_indices))
    if max_index < 0:
        return 6
    return max(1, len(str(max_index)))


def frame_filename(filename_prefix: str, frame_index: int, image_ext: str, digits: int) -> str:
    return f"{filename_prefix}_{frame_index:0{max(1, digits)}d}.{image_ext}"


def run_cmd(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        check=False,
    )


def run_cmd_with_ffmpeg_progress(
    cmd: list[str],
    phase: str,
    total_items: int,
    *,
    cancel_event: CancellationToken | None = None,
) -> subprocess.CompletedProcess:
    raise_if_cancelled(cancel_event)
    if total_items <= 0:
        proc = run_cmd(cmd, capture=True)
        raise_if_cancelled(cancel_event)
        return proc

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stderr is not None
    stderr_queue: queue.Queue[str | None] = queue.Queue()

    def read_stderr() -> None:
        try:
            for raw_line in proc.stderr:
                stderr_queue.put(raw_line)
        finally:
            stderr_queue.put(None)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    progress_step = max(1, total_items // 100)
    last_reported = -1
    observed_frame = 0
    stderr_lines: list[str] = []

    def handle_progress_line(raw: str) -> None:
        nonlocal last_reported, observed_frame
        line = raw.strip()
        if not line:
            return
        if "=" not in line:
            stderr_lines.append(line)
            return
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in {
            "frame",
            "fps",
            "stream_0_0_q",
            "bitrate",
            "total_size",
            "out_time_us",
            "out_time_ms",
            "out_time",
            "dup_frames",
            "drop_frames",
            "speed",
            "progress",
        }:
            stderr_lines.append(line)
        if key != "frame":
            return
        try:
            frame_count = int(value)
        except ValueError:
            return

        if frame_count < observed_frame:
            return
        observed_frame = frame_count
        if observed_frame == 0:
            return

        if observed_frame - last_reported >= progress_step or observed_frame >= total_items:
            shown = min(total_items, observed_frame)
            pct = min(100.0, (shown / float(total_items)) * 100.0)
            print(f"[progress] {phase} {shown}/{total_items} frames ({pct:.1f}%)", flush=True)
            last_reported = observed_frame

    print(f"[progress] {phase} 0/{total_items} frames (0.0%)", flush=True)
    stderr_done = False
    try:
        while True:
            if is_cancelled(cancel_event):
                terminate_process(proc)
                raise AppJobCancelled()
            try:
                raw = stderr_queue.get(timeout=0.05)
            except queue.Empty:
                if proc.poll() is not None and stderr_done:
                    break
                if proc.poll() is not None and not stderr_thread.is_alive() and stderr_queue.empty():
                    break
                continue
            if raw is None:
                stderr_done = True
                if proc.poll() is not None:
                    break
                continue
            handle_progress_line(raw)
    finally:
        stderr_thread.join(timeout=1.0)

    proc.wait()
    if proc.returncode == 0 and last_reported < total_items:
        print(f"[progress] {phase} {total_items}/{total_items} frames (100.0%)", flush=True)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout="",
        stderr="\n".join(stderr_lines),
    )


def ensure_binary(path: str, name: str) -> None:
    proc = run_cmd([path, "-version"], capture=True)
    if proc.returncode != 0:
        msg = proc.stderr.strip() if proc.stderr else "not found"
        raise RuntimeError(f"Failed to execute {name}: {msg}")


def probe_video(video_path: Path, ffprobe_bin: str) -> VideoInfo:
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    proc = run_cmd(cmd, capture=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("No video stream found")

    stream = streams[0]
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    avg_frame_rate = parse_fraction(stream.get("avg_frame_rate", "0"))
    r_frame_rate = parse_fraction(stream.get("r_frame_rate", "0"))
    fps = avg_frame_rate
    if fps <= 0:
        fps = r_frame_rate

    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0.0)
    nb_frames_raw = stream.get("nb_frames")
    total_frames = int(nb_frames_raw) if nb_frames_raw and nb_frames_raw.isdigit() else 0

    if fps <= 0 and duration > 0 and total_frames > 0:
        fps = total_frames / duration
    if fps <= 0:
        raise RuntimeError("Could not determine FPS from video")
    if duration <= 0 and total_frames > 0:
        duration = total_frames / fps
    if total_frames <= 0 and duration > 0:
        total_frames = max(1, int(round(duration * fps)))

    variable_frame_rate = frame_rates_indicate_vfr(avg_frame_rate, r_frame_rate)
    frame_rate_warning = ""
    if variable_frame_rate:
        frame_rate_warning = (
            "Variable-frame-rate video suspected from ffprobe avg_frame_rate/r_frame_rate. "
            "Frame selection remains frame-index based; timestamp_sec values are approximate."
        )

    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        total_frames=total_frames,
        avg_frame_rate=avg_frame_rate,
        r_frame_rate=r_frame_rate,
        variable_frame_rate=variable_frame_rate,
        frame_rate_warning=frame_rate_warning,
    )


def select_fixed(total_frames: int, fps: float, interval_sec: float) -> tuple[list[int], int]:
    if interval_sec <= 0:
        raise ValueError("--interval-sec must be > 0")

    step = max(1, int(round(interval_sec * fps)))
    indices = list(range(0, total_frames, step))
    if indices[-1] != total_frames - 1:
        indices.append(total_frames - 1)
    return indices, step


def build_select_expr(frame_indices: list[int]) -> str:
    return "+".join(f"eq(n\\,{idx})" for idx in frame_indices)


def extract_selected_frames(
    video_path: Path,
    ffmpeg_bin: str,
    frame_indices: list[int],
    output_dir: Path,
    image_ext: str,
    jpg_quality: int,
    filename_prefix: str,
    frame_digits: int,
    allow_partial_tail: bool = False,
    cancel_event: CancellationToken | None = None,
) -> list[int]:
    raise_if_cancelled(cancel_event)
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / "_tmp_extract"
    if tmp_dir.exists():
        for p in tmp_dir.glob("*"):
            p.unlink(missing_ok=True)
    tmp_dir.mkdir(exist_ok=True)

    select_expr = build_select_expr(frame_indices)

    quality_args: list[str] = []
    if image_ext == "jpg":
        quality_args = ["-q:v", str(jpg_quality)]

    out_pattern = str(tmp_dir / f"%08d.{image_ext}")

    # Try filter script first to avoid command-length issues.
    with tempfile.NamedTemporaryFile("w", suffix=".ffscript", delete=False, encoding="utf-8") as tf:
        tf.write(f"select='{select_expr}'\n")
        filter_script_path = tf.name

    try:
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-progress",
            "pipe:2",
            "-y",
            "-i",
            str(video_path),
            "-/filter:v",
            filter_script_path,
            "-fps_mode",
            "vfr",
            *quality_args,
            out_pattern,
        ]
        proc = run_cmd_with_ffmpeg_progress(
            cmd,
            phase="extract",
            total_items=len(frame_indices),
            cancel_event=cancel_event,
        )

        if proc.returncode != 0:
            raise_if_cancelled(cancel_event)
            # Fallback when loading the filter graph from a file is unsupported.
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostats",
                "-progress",
                "pipe:2",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"select='{select_expr}'",
                "-fps_mode",
                "vfr",
                *quality_args,
                out_pattern,
            ]
            proc = run_cmd_with_ffmpeg_progress(
                cmd,
                phase="extract",
                total_items=len(frame_indices),
                cancel_event=cancel_event,
            )
            stderr_text = (proc.stderr or "").lower()
            if proc.returncode != 0 and "unrecognized option" in stderr_text and "progress" in stderr_text:
                raise_if_cancelled(cancel_event)
                cmd = [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vf",
                    f"select='{select_expr}'",
                    "-fps_mode",
                    "vfr",
                    *quality_args,
                    out_pattern,
                ]
                proc = run_cmd(cmd, capture=True)
                raise_if_cancelled(cancel_event)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg extraction failed: {proc.stderr.strip()}")
    finally:
        Path(filter_script_path).unlink(missing_ok=True)

    extracted_files = sorted(tmp_dir.glob(f"*.{image_ext}"))
    if len(extracted_files) != len(frame_indices):
        if allow_partial_tail and 0 < len(extracted_files) < len(frame_indices):
            missing = len(frame_indices) - len(extracted_files)
            print(
                "[warn] ffmpeg produced fewer frames than requested; "
                f"keeping {len(extracted_files)} extracted frame(s) and dropping {missing} trailing request(s)",
                flush=True,
            )
            frame_indices = frame_indices[: len(extracted_files)]
        else:
            for p in extracted_files:
                p.unlink(missing_ok=True)
            tmp_dir.rmdir()
            raise RuntimeError(f"Expected {len(frame_indices)} extracted files, got {len(extracted_files)}")
    rename_total = len(frame_indices)
    rename_step = max(1, rename_total // 100)
    last_rename_report = 0
    print(f"[progress] finalize 0/{rename_total} files (0.0%)", flush=True)
    for seq, (src, frame_idx) in enumerate(zip(extracted_files, frame_indices, strict=True), start=1):
        raise_if_cancelled(cancel_event)
        dst_name = frame_filename(filename_prefix, frame_idx, image_ext, frame_digits)
        dst_path = output_dir / dst_name
        if dst_path.exists():
            dst_path.unlink()
        src.rename(dst_path)
        if seq - last_rename_report >= rename_step or seq == rename_total:
            pct = min(100.0, (seq / float(rename_total)) * 100.0)
            print(f"[progress] finalize {seq}/{rename_total} files ({pct:.1f}%)", flush=True)
            last_rename_report = seq

    tmp_dir.rmdir()
    return list(frame_indices)


SELECTED_CSV_FIELDNAMES = [
    "seq",
    "source_session",
    "source_video",
    "original_index",
    "final_index",
    "timestamp_sec",
    "change_score_original",
    "change_score_final",
    "blur_score_original",
    "blur_score_final",
    "sharpness_baseline",
    "sharpness_ratio",
    "local_sharpness_baseline",
    "local_sharpness_ratio",
    "local_sharpness_count",
    "status",
    "decision",
    "analysis_pipeline",
    "selection_reason",
    "review_required",
    "prev_kept_index",
    "gap_sec",
    "yaw_shift_px",
    "yaw_shift_deg",
    "residual_score",
    "raw_change_score",
    "track_count",
    "track_coverage",
    "match_confidence",
    "risk_flags",
    "analysis_width",
    "pair_gate_width",
    "pair_motion_profile",
    "pair_threshold_mode",
    "pair_drop_threshold",
    "pair_add_threshold",
    "output_file",
]


def _csv_score(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


def build_quick_extract_rows(frame_indices: Sequence[int]) -> list[dict]:
    return [
        {
            "original_index": idx,
            "final_index": idx,
            "change_score_original": None,
            "change_score_final": None,
            "blur_score_original": None,
            "blur_score_final": None,
            "status": "ok",
            "decision": "keep",
            "analysis_pipeline": "quick",
            "selection_reason": "quick_extract",
            "review_required": "0",
        }
        for idx in frame_indices
    ]


def build_selected_csv_rows(
    rows: list[dict],
    fps: float,
    image_ext: str,
    filename_prefix: str,
    frame_digits: int,
    session_id: str = "",
    source_video: str = "",
) -> list[dict]:
    out_rows: list[dict] = []
    for i, row in enumerate(rows, start=1):
        final_idx = row["final_index"]
        timestamp_sec = f"{final_idx / fps:.6f}" if fps > 0 else ""
        out_rows.append(
            {
                "seq": i,
                "source_session": session_id,
                "source_video": source_video,
                "original_index": row["original_index"],
                "final_index": final_idx,
                "timestamp_sec": timestamp_sec,
                "change_score_original": _csv_score(row.get("change_score_original")),
                "change_score_final": _csv_score(row.get("change_score_final")),
                "blur_score_original": _csv_score(row.get("blur_score_original")),
                "blur_score_final": _csv_score(row.get("blur_score_final")),
                "sharpness_baseline": _csv_score(row.get("sharpness_baseline")),
                "sharpness_ratio": _csv_score(row.get("sharpness_ratio")),
                "local_sharpness_baseline": _csv_score(row.get("local_sharpness_baseline")),
                "local_sharpness_ratio": _csv_score(row.get("local_sharpness_ratio")),
                "local_sharpness_count": row.get("local_sharpness_count", ""),
                "status": row["status"],
                "decision": row.get("decision", "keep"),
                "analysis_pipeline": row.get("analysis_pipeline", "pair"),
                "selection_reason": row.get("selection_reason", ""),
                "review_required": row.get("review_required", "1" if row.get("status", "ok") != "ok" else "0"),
                "prev_kept_index": row.get("prev_kept_index", ""),
                "gap_sec": _csv_score(row.get("gap_sec")),
                "yaw_shift_px": row.get("yaw_shift_px", ""),
                "yaw_shift_deg": _csv_score(row.get("yaw_shift_deg")),
                "residual_score": _csv_score(row.get("residual_score")),
                "raw_change_score": _csv_score(row.get("raw_change_score")),
                "track_count": row.get("track_count", ""),
                "track_coverage": _csv_score(row.get("track_coverage")),
                "match_confidence": _csv_score(row.get("match_confidence")),
                "risk_flags": row.get("risk_flags", ""),
                "analysis_width": row.get("analysis_width", ""),
                "pair_gate_width": row.get("pair_gate_width", ""),
                "pair_motion_profile": row.get("pair_motion_profile", ""),
                "pair_threshold_mode": row.get("pair_threshold_mode", ""),
                "pair_drop_threshold": _csv_score(row.get("pair_drop_threshold")),
                "pair_add_threshold": _csv_score(row.get("pair_add_threshold")),
                "output_file": f"images/{frame_filename(filename_prefix, final_idx, image_ext, frame_digits)}",
            }
        )
    return out_rows


def read_selected_csv(csv_path: Path) -> tuple[list[str], list[dict]]:
    if not csv_path.exists():
        return list(SELECTED_CSV_FIELDNAMES), []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or SELECTED_CSV_FIELDNAMES), list(reader)


def write_selected_csv_rows(csv_path: Path, fieldnames: Sequence[str], rows: Sequence[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ordered_fields = list(SELECTED_CSV_FIELDNAMES)
    for name in fieldnames:
        if name not in ordered_fields:
            ordered_fields.append(name)
    for row in rows:
        for name in row.keys():
            if name not in ordered_fields:
                ordered_fields.append(name)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fields)
        writer.writeheader()
        for seq, row in enumerate(rows, start=1):
            updated = dict(row)
            updated["seq"] = seq
            writer.writerow(updated)


def write_selected_csv(
    rows: list[dict],
    csv_path: Path,
    fps: float,
    image_ext: str,
    filename_prefix: str,
    frame_digits: int,
    existing_rows: Sequence[dict] | None = None,
    existing_fieldnames: Sequence[str] | None = None,
    session_id: str = "",
    source_video: str = "",
) -> None:
    if existing_rows is None:
        existing_rows = []
    if existing_fieldnames is None:
        existing_fieldnames = SELECTED_CSV_FIELDNAMES

    new_rows = build_selected_csv_rows(
        rows,
        fps=fps,
        image_ext=image_ext,
        filename_prefix=filename_prefix,
        frame_digits=frame_digits,
        session_id=session_id,
        source_video=source_video,
    )
    write_selected_csv_rows(csv_path, existing_fieldnames, [*existing_rows, *new_rows])


def write_report(
    report_path: Path,
    args: argparse.Namespace,
    video_info: VideoInfo,
    analysis_w: int,
    analysis_h: int,
    selected_rows: list[dict],
    min_gap_frames: int,
    filename_prefix: str,
    frame_digits: int,
) -> None:
    pair_thresholds = resolve_pair_thresholds(
        args.interval_sec,
        getattr(args, "pair_motion_profile", "walk"),
        getattr(args, "pair_drop_threshold", -1.0),
        getattr(args, "pair_add_threshold", -1.0),
    )
    kept_count = sum(1 for r in selected_rows if r.get("decision", "keep") != "drop")
    dropped_count = sum(1 for r in selected_rows if r.get("decision", "keep") == "drop")
    pipeline = "quick" if getattr(args, "quick_extract", False) else "pair"
    report = {
        "input_video": str(Path(args.input_video).resolve()),
        "mode": args.mode,
        "video": {
            "width": video_info.width,
            "height": video_info.height,
            "fps": video_info.fps,
            "avg_frame_rate": video_info.avg_frame_rate,
            "r_frame_rate": video_info.r_frame_rate,
            "variable_frame_rate": video_info.variable_frame_rate,
            "frame_rate_warning": video_info.frame_rate_warning,
            "duration_sec": video_info.duration,
            "total_frames": video_info.total_frames,
        },
        "analysis": {
            "width": analysis_w,
            "height": analysis_h,
            "pipeline": pipeline,
            "min_gap_frames": min_gap_frames,
        },
        "params": {
            "interval_sec": args.interval_sec,
            "min_gap_sec": args.min_gap_sec,
            "max_gap_sec": args.max_gap_sec,
            "fixed_smart": args.fixed_smart,
            "quick_extract": getattr(args, "quick_extract", False),
            "fixed_smart_max_inserts_per_interval": args.fixed_smart_max_inserts_per_interval,
            "pair_motion_profile": pair_thresholds.profile,
            "pair_threshold_mode": pair_thresholds.mode,
            "pair_drop_threshold": getattr(args, "pair_drop_threshold", -1.0),
            "pair_add_threshold": getattr(args, "pair_add_threshold", -1.0),
            "pair_drop_threshold_resolved": pair_thresholds.drop,
            "pair_add_threshold_resolved": pair_thresholds.add,
            "pair_track_min_count": getattr(args, "pair_track_min_count", 0),
            "pair_track_min_confidence": getattr(args, "pair_track_min_confidence", 0.0),
            "filename_prefix": filename_prefix,
            "frame_number_digits": frame_digits,
            "output_mode": getattr(args, "output_mode", "overwrite"),
        },
        "result": {
            "selected_count": kept_count,
            "dropped_count": dropped_count,
            "review_row_count": len(selected_rows),
            "novelty_added_count": sum(1 for r in selected_rows if "novelty_added" in r.get("status", "")),
            "blur_replacement_count": sum(1 for r in selected_rows if "blur_replacement" in r.get("status", "")),
            "redundant_drop_count": sum(1 for r in selected_rows if "redundant_drop" in r.get("status", "")),
            "gap_forced_count": sum(1 for r in selected_rows if "gap_forced" in r.get("status", "")),
            "motion_blur_count": sum(1 for r in selected_rows if "motion_blur" in r.get("status", "")),
            "borderline_blur_count": sum(1 for r in selected_rows if "borderline_blur" in r.get("status", "")),
            "low_texture_count": sum(1 for r in selected_rows if "low_texture" in r.get("status", "")),
            "weak_match_count": sum(1 for r in selected_rows if "weak_match" in r.get("status", "")),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def build_summary_from_counts(
    args: argparse.Namespace,
    video_info: VideoInfo,
    analysis_w: int,
    analysis_h: int,
    min_gap_frames: int,
    selected_count: int,
    estimate_mode: str,
    filename_prefix: str,
    frame_digits: int,
    estimate_meta: dict | None = None,
) -> dict:
    pair_thresholds = resolve_pair_thresholds(
        args.interval_sec,
        getattr(args, "pair_motion_profile", "walk"),
        getattr(args, "pair_drop_threshold", -1.0),
        getattr(args, "pair_add_threshold", -1.0),
    )
    pipeline = "quick" if getattr(args, "quick_extract", False) else "pair"
    summary = {
        "input_video": str(Path(args.input_video).resolve()),
        "mode": args.mode,
        "estimate_mode": estimate_mode,
        "video": {
            "width": video_info.width,
            "height": video_info.height,
            "fps": video_info.fps,
            "avg_frame_rate": video_info.avg_frame_rate,
            "r_frame_rate": video_info.r_frame_rate,
            "variable_frame_rate": video_info.variable_frame_rate,
            "frame_rate_warning": video_info.frame_rate_warning,
            "duration_sec": video_info.duration,
            "total_frames": video_info.total_frames,
        },
        "analysis": {
            "width": analysis_w,
            "height": analysis_h,
            "pipeline": pipeline,
            "min_gap_frames": min_gap_frames,
        },
        "params": {
            "interval_sec": args.interval_sec,
            "min_gap_sec": args.min_gap_sec,
            "max_gap_sec": args.max_gap_sec,
            "fixed_smart": args.fixed_smart,
            "quick_extract": getattr(args, "quick_extract", False),
            "fixed_smart_max_inserts_per_interval": args.fixed_smart_max_inserts_per_interval,
            "pair_motion_profile": pair_thresholds.profile,
            "pair_threshold_mode": pair_thresholds.mode,
            "pair_drop_threshold": getattr(args, "pair_drop_threshold", -1.0),
            "pair_add_threshold": getattr(args, "pair_add_threshold", -1.0),
            "pair_drop_threshold_resolved": pair_thresholds.drop,
            "pair_add_threshold_resolved": pair_thresholds.add,
            "pair_track_min_count": getattr(args, "pair_track_min_count", 0),
            "pair_track_min_confidence": getattr(args, "pair_track_min_confidence", 0.0),
            "analysis_width": args.analysis_width,
            "pair_gate_width": pair_gate_dimensions(analysis_w, analysis_h)[0] if analysis_w > 0 else 0,
            "filename_prefix": filename_prefix,
            "frame_number_digits": frame_digits,
        },
        "result": {
            "selected_count": selected_count,
        },
    }
    if estimate_meta:
        summary["estimate"] = estimate_meta
    return summary


def build_summary(
    args: argparse.Namespace,
    video_info: VideoInfo,
    analysis_w: int,
    analysis_h: int,
    selected_rows: list[dict],
    min_gap_frames: int,
    filename_prefix: str,
    frame_digits: int,
    estimate_mode: str = "full",
) -> dict:
    novelty_added_count = sum(1 for r in selected_rows if "novelty_added" in r.get("status", ""))
    blur_replacement_count = sum(1 for r in selected_rows if "blur_replacement" in r.get("status", ""))
    redundant_drop_count = sum(1 for r in selected_rows if "redundant_drop" in r.get("status", ""))
    gap_forced_count = sum(1 for r in selected_rows if "gap_forced" in r.get("status", ""))
    motion_blur_count = sum(1 for r in selected_rows if "motion_blur" in r.get("status", ""))
    borderline_blur_count = sum(1 for r in selected_rows if "borderline_blur" in r.get("status", ""))
    low_texture_count = sum(1 for r in selected_rows if "low_texture" in r.get("status", ""))
    weak_match_count = sum(1 for r in selected_rows if "weak_match" in r.get("status", ""))
    kept_count = sum(1 for r in selected_rows if r.get("decision", "keep") != "drop")
    dropped_count = sum(1 for r in selected_rows if r.get("decision", "keep") == "drop")

    summary = build_summary_from_counts(
        args=args,
        video_info=video_info,
        analysis_w=analysis_w,
        analysis_h=analysis_h,
        min_gap_frames=min_gap_frames,
        selected_count=kept_count,
        estimate_mode=estimate_mode,
        filename_prefix=filename_prefix,
        frame_digits=frame_digits,
    )
    summary["result"]["dropped_count"] = dropped_count
    summary["result"]["review_row_count"] = len(selected_rows)
    summary["result"]["novelty_added_count"] = novelty_added_count
    summary["result"]["blur_replacement_count"] = blur_replacement_count
    summary["result"]["redundant_drop_count"] = redundant_drop_count
    summary["result"]["gap_forced_count"] = gap_forced_count
    summary["result"]["motion_blur_count"] = motion_blur_count
    summary["result"]["borderline_blur_count"] = borderline_blur_count
    summary["result"]["low_texture_count"] = low_texture_count
    summary["result"]["weak_match_count"] = weak_match_count
    return summary


def video_info_to_dict(video_info: VideoInfo) -> dict:
    return {
        "width": video_info.width,
        "height": video_info.height,
        "fps": video_info.fps,
        "avg_frame_rate": video_info.avg_frame_rate,
        "r_frame_rate": video_info.r_frame_rate,
        "variable_frame_rate": video_info.variable_frame_rate,
        "frame_rate_warning": video_info.frame_rate_warning,
        "duration_sec": video_info.duration,
        "total_frames": video_info.total_frames,
    }


def output_files_for_indices(
    final_indices: Sequence[int],
    filename_prefix: str,
    image_ext: str,
    frame_digits: int,
) -> list[str]:
    return [
        f"images/{frame_filename(filename_prefix, frame_idx, image_ext, frame_digits)}" for frame_idx in final_indices
    ]


def remove_session_outputs(scene_dir: Path, output_files: Sequence[str]) -> int:
    removed = 0
    images_dir = scene_images_dir(scene_dir).resolve()
    for rel in output_files:
        path = (scene_dir / rel).resolve()
        try:
            path.relative_to(images_dir)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def commit_staged_frame_outputs(
    scene_dir: Path,
    staging_dir: Path,
    output_files: Sequence[str],
    replaced_output_files: set[str],
) -> int:
    images_dir = scene_images_dir(scene_dir).resolve()
    images_dir.mkdir(parents=True, exist_ok=True)
    expected_files = list(output_files)
    missing = [Path(rel).name for rel in expected_files if not (staging_dir / Path(rel).name).is_file()]
    if missing:
        preview = ", ".join(missing[:3])
        raise RuntimeError(f"staged extraction is incomplete ({len(missing)} missing). Example: {preview}")

    removed = 0
    for rel in expected_files:
        dst = (scene_dir / rel).resolve()
        try:
            dst.relative_to(images_dir)
        except ValueError as exc:
            raise RuntimeError(f"unsafe output path: {rel}") from exc
        if dst.exists() and rel not in replaced_output_files:
            raise RuntimeError(f"output file already exists: {rel}")

    for rel in expected_files:
        src = staging_dir / Path(rel).name
        dst = (scene_dir / rel).resolve()
        if dst.is_file() and rel in replaced_output_files:
            removed += 1
        src.replace(dst)

    stale_replaced = sorted(set(replaced_output_files) - set(expected_files))
    removed += remove_session_outputs(scene_dir, stale_replaced)
    safe_clear_path(staging_dir, allowed_roots=[frame_cache_dir(scene_dir)])
    return removed


def filter_rows_for_replaced_sessions(
    rows: Sequence[dict],
    replaced_session_ids: set[str],
    replaced_output_files: set[str],
) -> list[dict]:
    kept: list[dict] = []
    for row in rows:
        session_id = row.get("source_session", "")
        output_file = row.get("output_file", "")
        if session_id and session_id in replaced_session_ids:
            continue
        if output_file in replaced_output_files:
            continue
        kept.append(dict(row))
    return kept


def total_frames_for_fixed_selection(video_info: VideoInfo) -> int:
    total_frames = video_info.total_frames
    if total_frames <= 0 and video_info.duration > 0:
        total_frames = max(1, int(round(video_info.duration * video_info.fps)))
    return max(total_frames, 1)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract equirectangular frames via FFmpeg with SfM-oriented pair analysis."
    )
    parser.add_argument("input_video", help="Input video file path")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Output root directory (default='.')",
    )

    parser.set_defaults(mode="fixed")
    parser.add_argument("--interval-sec", type=float, default=0.5, help="Fixed interval in seconds")
    parser.add_argument("--min-gap-sec", type=float, default=0.25, help="Minimum gap in seconds")
    parser.add_argument("--max-gap-sec", type=float, default=2.0, help="Maximum safety gap in seconds")
    parser.add_argument(
        "--fixed-smart",
        action="store_true",
        help=(
            "Enable pair-analysis motion adjustment: drop redundant fixed candidates, "
            "add novelty candidates, and keep max-gap safety frames."
        ),
    )
    parser.add_argument(
        "--quick-extract",
        action="store_true",
        help=("Extract the requested fixed cadence directly without pair analysis or motion adjustment."),
    )
    parser.add_argument(
        "--fixed-smart-max-inserts-per-interval",
        type=int,
        default=2,
        help="Maximum novelty anchors inserted inside each fixed interval by --fixed-smart.",
    )
    parser.add_argument(
        "--pair-track-min-count",
        type=int,
        default=36,
        help="Minimum tracked feature count before a kept pair is flagged as weak_match.",
    )
    parser.add_argument(
        "--pair-motion-profile",
        choices=PAIR_THRESHOLD_PROFILE_CHOICES,
        default="walk",
        help=(
            "Auto threshold profile for pair analysis. GUI profiles: "
            "walk_standard, walk_close, walk_wide, drone_distant. "
            "Legacy walk and drone profiles remain accepted."
        ),
    )
    parser.add_argument(
        "--pair-drop-threshold",
        type=float,
        default=-1.0,
        help="Pair residual below this value drops fixed candidates. Negative uses profile-based auto.",
    )
    parser.add_argument(
        "--pair-add-threshold",
        type=float,
        default=-1.0,
        help="Pair residual at or above this value adds novelty candidates. Negative uses profile-based auto.",
    )
    parser.add_argument(
        "--pair-track-min-confidence",
        type=float,
        default=0.25,
        help="Minimum pair tracking confidence before a kept pair is flagged as weak_match.",
    )

    parser.add_argument(
        "--analysis-width",
        type=int,
        default=1920,
        help=(
            "Pair-analysis decode width for candidate tracking and sharpness checks. "
            "Yaw/residual monitoring is internally capped to a 1280px gate. "
            "Set to 0 or a value >= source width to use full resolution."
        ),
    )

    parser.add_argument("--image-ext", choices=["jpg", "png"], default="jpg")
    parser.add_argument("--jpg-quality", type=int, default=2, help="JPEG quality for ffmpeg -q:v (2 is high quality)")
    parser.add_argument(
        "--filename-prefix",
        default="",
        help="Output filename prefix. Default is input video stem.",
    )
    parser.add_argument(
        "--output-mode",
        choices=["overwrite", "append", "replace-video"],
        default="overwrite",
        help=(
            "How _stechdrive/frames/selected_frames.csv and _stechdrive/frames/extract_sessions.json are updated. "
            "overwrite=current single-extraction behavior, append=add a new video session, "
            "replace-video=replace prior sessions for the same video after successful extraction."
        ),
    )
    parser.add_argument(
        "--allow-duplicate-video",
        action="store_true",
        help="Allow appending a video that already exists in _stechdrive/frames/extract_sessions.json.",
    )

    parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg executable")
    parser.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe executable")
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Run probe/selection and print estimated selected count without image extraction",
    )
    parser.add_argument(
        "--print-summary-json",
        action="store_true",
        help="Print one-line JSON summary prefixed with SUMMARY_JSON:",
    )

    return parser.parse_args(argv)


def run_extract_frames(args: ExtractFramesOptions) -> int:
    raise_if_cancelled(args.cancel_event)
    if args.interval_sec <= 0:
        print("Error: --interval-sec must be > 0")
        return 1
    if args.min_gap_sec <= 0 or args.max_gap_sec <= 0:
        print("Error: --min-gap-sec and --max-gap-sec must be > 0")
        return 1
    if args.max_gap_sec < args.min_gap_sec:
        print("Error: --max-gap-sec must be >= --min-gap-sec")
        return 1
    if args.fixed_smart_max_inserts_per_interval < 0:
        print("Error: --fixed-smart-max-inserts-per-interval must be >= 0")
        return 1
    if args.pair_track_min_count < 0:
        print("Error: --pair-track-min-count must be >= 0")
        return 1
    try:
        resolve_pair_thresholds(
            args.interval_sec,
            args.pair_motion_profile,
            args.pair_drop_threshold,
            args.pair_add_threshold,
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    if args.pair_track_min_confidence < 0.0 or args.pair_track_min_confidence > 1.0:
        print("Error: --pair-track-min-confidence must be between 0 and 1")
        return 1
    if args.quick_extract and args.fixed_smart:
        print("Error: --quick-extract cannot be combined with --fixed-smart")
        return 1

    input_video = Path(args.input_video)
    if not input_video.exists():
        print(f"Error: input video not found: {input_video}")
        return 1

    raise_if_cancelled(args.cancel_event)
    output_root = Path(args.output_dir)
    scene_dir = output_root.resolve()
    images_dir = scene_images_dir(scene_dir)
    csv_path = selected_frames_path(scene_dir)
    report_path = extract_report_path(scene_dir)

    try:
        ensure_binary(args.ffmpeg, "ffmpeg")
        raise_if_cancelled(args.cancel_event)
        ensure_binary(args.ffprobe, "ffprobe")
        raise_if_cancelled(args.cancel_event)
        video_info = probe_video(input_video, args.ffprobe)
        raise_if_cancelled(args.cancel_event)
    except AppJobCancelled:
        raise
    except Exception as e:
        print(f"Error: {e}")
        return 1

    print(f"Input video: {input_video}")
    print(f"Video: {video_info.width}x{video_info.height} @ {video_info.fps:.3f} fps")
    if video_info.variable_frame_rate:
        print(f"Warning: {video_info.frame_rate_warning}")
    resolved_prefix = sanitize_filename_prefix(args.filename_prefix)
    if not resolved_prefix:
        resolved_prefix = sanitize_filename_prefix(input_video.stem)
    if not resolved_prefix:
        resolved_prefix = "frame"
    print(f"Filename prefix: {resolved_prefix}")

    current_video_identity = video_identity(input_video)
    manifest = load_manifest(scene_dir)
    manifest_sessions = [session for session in manifest.get("sessions", []) if isinstance(session, dict)]
    matching_sessions = [
        session for session in manifest_sessions if session_matches_video(session, current_video_identity)
    ]
    if args.output_mode == "append" and matching_sessions and not args.allow_duplicate_video:
        print(
            "Error: this video already exists in _stechdrive/frames/extract_sessions.json. "
            "Use --output-mode replace-video to re-extract it, or --allow-duplicate-video "
            "with a unique --filename-prefix to add it as a separate session."
        )
        return 1

    if args.quick_extract:
        raise_if_cancelled(args.cancel_event)
        total_frames = total_frames_for_fixed_selection(video_info)
        try:
            selected, min_gap_frames = select_fixed(total_frames, video_info.fps, args.interval_sec)
        except Exception as e:
            print(f"Error while selecting frames: {e}")
            return 1
        enriched_rows = build_quick_extract_rows(selected)
        analysis_w, analysis_h = 0, 0
        print("Quick extract: skipping analysis and motion adjustment")
    else:
        try:
            raise_if_cancelled(args.cancel_event)
            ensure_python_deps()
            pair_thresholds = resolve_pair_thresholds(
                args.interval_sec,
                args.pair_motion_profile,
                args.pair_drop_threshold,
                args.pair_add_threshold,
            )
            print(
                "Pair thresholds: "
                f"profile={pair_thresholds.profile} mode={pair_thresholds.mode} "
                f"drop={pair_thresholds.drop:.5f} add={pair_thresholds.add:.5f}"
            )
            (
                enriched_rows,
                analysis_w,
                analysis_h,
                min_gap_frames,
                _pair_max_gap_frames,
                total_frames,
            ) = analyze_pair_selection(
                video_path=input_video,
                ffmpeg_bin=args.ffmpeg,
                video_info=video_info,
                analysis_width=args.analysis_width,
                interval_sec=args.interval_sec,
                fixed_smart=args.fixed_smart,
                min_gap_sec=args.min_gap_sec,
                max_gap_sec=args.max_gap_sec,
                drop_threshold=pair_thresholds.drop,
                add_threshold=pair_thresholds.add,
                threshold_profile=pair_thresholds.profile,
                threshold_mode=pair_thresholds.mode,
                max_inserts_per_interval=args.fixed_smart_max_inserts_per_interval,
                track_min_confidence=args.pair_track_min_confidence,
                track_min_count=args.pair_track_min_count,
                progress_phase="analyze",
                cancel_event=args.cancel_event,
            )
        except AppJobCancelled:
            raise
        except Exception as e:
            print(f"Error during pair analysis: {e}")
            return 1
        print(f"Pair-analyzed frames: {total_frames} ({analysis_w}x{analysis_h})")

    kept_rows = [r for r in enriched_rows if r.get("decision", "keep") != "drop"]
    if not kept_rows:
        print("Error: no frames selected")
        return 1

    final_indices = [int(r["final_index"]) for r in enriched_rows]
    frame_digits = frame_index_digits(video_info.total_frames, final_indices)
    summary = build_summary(
        args=args,
        video_info=video_info,
        analysis_w=analysis_w,
        analysis_h=analysis_h,
        selected_rows=enriched_rows,
        min_gap_frames=min_gap_frames,
        filename_prefix=resolved_prefix,
        frame_digits=frame_digits,
        estimate_mode="quick_extract" if args.quick_extract else "full",
    )

    if args.estimate_only:
        raise_if_cancelled(args.cancel_event)
        print(f"Estimated selected frames: {summary['result']['selected_count']}")
        if not args.quick_extract:
            print(f"Estimated pair novelty additions: {summary['result'].get('novelty_added_count', 0)}")
            print(f"Estimated pair blur replacements: {summary['result'].get('blur_replacement_count', 0)}")
            print(f"Estimated pair redundant drops: {summary['result'].get('redundant_drop_count', 0)}")
            print(f"Estimated pair motion-blur review frames: {summary['result'].get('motion_blur_count', 0)}")
            print(
                "Estimated pair borderline-blur review frames: "
                f"{summary['result'].get('borderline_blur_count', 0)}"
            )
            print(f"Estimated pair low-texture review frames: {summary['result'].get('low_texture_count', 0)}")
            print(f"Estimated pair weak-match review frames: {summary['result'].get('weak_match_count', 0)}")
        if args.print_summary_json:
            print("SUMMARY_JSON:" + json.dumps(summary, ensure_ascii=False))
        return 0

    if not final_indices:
        print("Error: no frames selected; skipping extraction")
        return 1

    session_id = new_session_id()
    output_files = output_files_for_indices(
        final_indices,
        resolved_prefix,
        args.image_ext,
        summary["params"]["frame_number_digits"],
    )

    existing_fieldnames: list[str] = list(SELECTED_CSV_FIELDNAMES)
    existing_rows: list[dict] = []
    active_manifest_sessions = manifest_sessions
    if args.output_mode in {"append", "replace-video"}:
        existing_fieldnames, existing_rows = read_selected_csv(csv_path)

    replaced_session_ids: set[str] = set()
    replaced_output_files: set[str] = set()
    if args.output_mode == "replace-video" and matching_sessions:
        for session in matching_sessions:
            session_id_value = str(session.get("id") or "")
            if session_id_value:
                replaced_session_ids.add(session_id_value)
            for rel in session.get("output_files", []) or []:
                if isinstance(rel, str):
                    replaced_output_files.add(rel)
        existing_rows = filter_rows_for_replaced_sessions(
            existing_rows,
            replaced_session_ids,
            replaced_output_files,
        )
        active_manifest_sessions = [
            session for session in active_manifest_sessions if str(session.get("id") or "") not in replaced_session_ids
        ]
        print(
            f"Prior sessions for this video will be replaced after extraction succeeds: {len(matching_sessions)} session(s)"
        )

    if args.output_mode in {"append", "replace-video"}:
        collisions = [rel for rel in output_files if (scene_dir / rel).exists() and rel not in replaced_output_files]
        if collisions:
            preview = ", ".join(collisions[:3])
            print(
                f"Error: output files already exist ({len(collisions)}). "
                f"Use a unique --filename-prefix. Example: {preview}"
            )
            return 1

    staging_dir: Path | None = None
    extraction_output_dir = images_dir
    if replaced_output_files:
        staging_dir = frame_cache_dir(scene_dir) / f"extract_staging_{session_id}"
        if staging_dir.exists():
            safe_clear_path(staging_dir, allowed_roots=[frame_cache_dir(scene_dir)])
        extraction_output_dir = staging_dir

    try:
        extracted_indices = extract_selected_frames(
            input_video,
            args.ffmpeg,
            final_indices,
            extraction_output_dir,
            args.image_ext,
            args.jpg_quality,
            resolved_prefix,
            summary["params"]["frame_number_digits"],
            allow_partial_tail=args.quick_extract,
            cancel_event=args.cancel_event,
        )
    except AppJobCancelled:
        tmp_extract_dir = extraction_output_dir / "_tmp_extract"
        if tmp_extract_dir.exists():
            safe_clear_path(tmp_extract_dir, allowed_roots=[extraction_output_dir])
        if staging_dir is not None and staging_dir.exists():
            safe_clear_path(staging_dir, allowed_roots=[frame_cache_dir(scene_dir)])
        raise
    except Exception as e:
        if staging_dir is not None:
            if staging_dir.exists():
                safe_clear_path(staging_dir, allowed_roots=[frame_cache_dir(scene_dir)])
        print(f"Error during extraction: {e}")
        return 1

    raise_if_cancelled(args.cancel_event)
    if extracted_indices != final_indices:
        extracted_set = set(extracted_indices)
        enriched_rows = [r for r in enriched_rows if int(r["final_index"]) in extracted_set]
        final_indices = extracted_indices
        output_files = output_files_for_indices(
            final_indices,
            resolved_prefix,
            args.image_ext,
            summary["params"]["frame_number_digits"],
        )
        summary = build_summary(
            args=args,
            video_info=video_info,
            analysis_w=analysis_w,
            analysis_h=analysis_h,
            selected_rows=enriched_rows,
            min_gap_frames=min_gap_frames,
            filename_prefix=resolved_prefix,
            frame_digits=summary["params"]["frame_number_digits"],
            estimate_mode="quick_extract" if args.quick_extract else "full",
        )

    if staging_dir is not None:
        try:
            raise_if_cancelled(args.cancel_event)
            removed = commit_staged_frame_outputs(scene_dir, staging_dir, output_files, replaced_output_files)
        except AppJobCancelled:
            raise
        except Exception as e:
            print(f"Error while committing replacement frames: {e}")
            return 1
        print(
            f"Replaced prior sessions for this video: {len(matching_sessions)} session(s), {removed} file(s) replaced/removed"
        )

    raise_if_cancelled(args.cancel_event)
    write_selected_csv(
        enriched_rows,
        csv_path,
        video_info.fps,
        args.image_ext,
        resolved_prefix,
        summary["params"]["frame_number_digits"],
        existing_rows=existing_rows if args.output_mode in {"append", "replace-video"} else [],
        existing_fieldnames=existing_fieldnames,
        session_id=session_id,
        source_video=str(input_video.resolve()),
    )
    session_record = build_session_record(
        session_id=session_id,
        input_video=input_video,
        video_info=video_info_to_dict(video_info),
        mode=args.mode,
        filename_prefix=resolved_prefix,
        image_ext=args.image_ext,
        output_files=output_files,
        selected_count=sum(1 for r in enriched_rows if r.get("decision", "keep") != "drop"),
        dropped_count=sum(1 for r in enriched_rows if r.get("decision", "keep") == "drop"),
    )
    if args.output_mode == "overwrite":
        manifest["sessions"] = [session_record]
    else:
        manifest["sessions"] = [*active_manifest_sessions, session_record]
    save_manifest(scene_dir, manifest)
    raise_if_cancelled(args.cancel_event)
    write_report(
        report_path,
        args,
        video_info,
        analysis_w,
        analysis_h,
        enriched_rows,
        min_gap_frames,
        resolved_prefix,
        summary["params"]["frame_number_digits"],
    )
    try:
        from core.scene_asset_metadata import rebuild_scene_asset_metadata

        rebuild_scene_asset_metadata(scene_dir, cancel_event=args.cancel_event)
    except AppJobCancelled:
        raise
    except Exception as e:
        print(f"Warning: scene asset metadata refresh failed: {e}")

    novelty_added_count = sum(1 for r in enriched_rows if "novelty_added" in r.get("status", ""))
    blur_replacement_count = sum(1 for r in enriched_rows if "blur_replacement" in r.get("status", ""))
    redundant_drop_count = sum(1 for r in enriched_rows if "redundant_drop" in r.get("status", ""))
    gap_forced_count = sum(1 for r in enriched_rows if "gap_forced" in r.get("status", ""))
    motion_blur_count = sum(1 for r in enriched_rows if "motion_blur" in r.get("status", ""))
    borderline_blur_count = sum(1 for r in enriched_rows if "borderline_blur" in r.get("status", ""))
    low_texture_count = sum(1 for r in enriched_rows if "low_texture" in r.get("status", ""))
    weak_match_count = sum(1 for r in enriched_rows if "weak_match" in r.get("status", ""))
    dropped_count = sum(1 for r in enriched_rows if r.get("decision", "keep") == "drop")

    print(f"Selected frames: {len(final_indices)} (extracted)")
    if dropped_count > 0:
        print(f"Dropped review rows: {dropped_count}")
    if novelty_added_count > 0:
        print(f"Pair novelty additions: {novelty_added_count}")
    if blur_replacement_count > 0:
        print(f"Pair blur replacements: {blur_replacement_count}")
    if redundant_drop_count > 0:
        print(f"Pair redundant drops: {redundant_drop_count}")
    if gap_forced_count > 0:
        print(f"Pair gap-forced keeps: {gap_forced_count}")
    if motion_blur_count > 0:
        print(f"Pair motion-blur review frames: {motion_blur_count}")
    if borderline_blur_count > 0:
        print(f"Pair borderline-blur review frames: {borderline_blur_count}")
    if low_texture_count > 0:
        print(f"Pair low-texture review frames: {low_texture_count}")
    if weak_match_count > 0:
        print(f"Pair weak-match review frames: {weak_match_count}")
    print(f"Images: {images_dir}")
    print(f"Selection CSV: {csv_path}")
    print(f"Report: {report_path}")
    if args.print_summary_json:
        print("SUMMARY_JSON:" + json.dumps(summary, ensure_ascii=False))
    raise_if_cancelled(args.cancel_event)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_extract_frames(options_from_args(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
