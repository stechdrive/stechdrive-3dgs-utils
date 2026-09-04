from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from threading import Event, Timer

import pytest

from core.cancellation import AppJobCancelled
from core.extract_frames import (
    VideoInfo,
    build_quick_extract_rows,
    build_selected_csv_rows,
    build_summary_from_counts,
    commit_staged_frame_outputs,
    extract_selected_frames,
    frame_rates_indicate_vfr,
    probe_video,
    run_cmd_with_ffmpeg_progress,
)


def _args(input_video: Path) -> argparse.Namespace:
    return argparse.Namespace(
        input_video=str(input_video),
        mode="fixed",
        interval_sec=0.8,
        min_gap_sec=0.25,
        max_gap_sec=2.0,
        fixed_smart=False,
        quick_extract=True,
        fixed_smart_max_inserts_per_interval=2,
        analysis_width=1920,
        pair_motion_profile="walk",
        pair_drop_threshold=-1.0,
        pair_add_threshold=-1.0,
        pair_track_min_count=36,
        pair_track_min_confidence=0.25,
    )


def test_quick_extract_rows_keep_review_status_ok() -> None:
    rows = build_quick_extract_rows([0, 24, 48])

    assert [row["final_index"] for row in rows] == [0, 24, 48]
    assert all(row["status"] == "ok" for row in rows)
    assert all(row["decision"] == "keep" for row in rows)


def test_quick_extract_csv_leaves_uncomputed_scores_blank() -> None:
    rows = build_selected_csv_rows(
        build_quick_extract_rows([0, 24]),
        fps=30.0,
        image_ext="jpg",
        filename_prefix="clip",
        frame_digits=3,
    )

    assert rows[0]["timestamp_sec"] == "0.000000"
    assert rows[1]["timestamp_sec"] == "0.800000"
    for key in (
        "change_score_original",
        "change_score_final",
        "blur_score_original",
        "blur_score_final",
        "sharpness_baseline",
        "sharpness_ratio",
    ):
        assert rows[0][key] == ""


def test_quick_extract_summary_marks_quality_mode_skipped(tmp_path: Path) -> None:
    video = tmp_path / "input.mp4"
    video.write_bytes(b"dummy")
    summary = build_summary_from_counts(
        args=_args(video),
        video_info=VideoInfo(width=3840, height=1920, fps=30.0, duration=10.0, total_frames=300),
        analysis_w=0,
        analysis_h=0,
        min_gap_frames=24,
        selected_count=14,
        estimate_mode="quick_extract",
        filename_prefix="input",
        frame_digits=3,
    )

    assert summary["estimate_mode"] == "quick_extract"
    assert summary["analysis"]["pipeline"] == "quick"
    assert summary["params"]["quick_extract"] is True


def test_probe_video_marks_variable_frame_rate_from_ffprobe_rates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_cmd(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
        payload = {
            "streams": [
                {
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "24000/1001",
                    "r_frame_rate": "30/1",
                    "nb_frames": "240",
                    "duration": "10.0",
                }
            ],
            "format": {"duration": "10.0"},
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr("core.extract_frames.run_cmd", fake_run_cmd)

    info = probe_video(tmp_path / "vfr.mp4", "ffprobe")

    assert frame_rates_indicate_vfr(info.avg_frame_rate, info.r_frame_rate)
    assert info.variable_frame_rate is True
    assert "Variable-frame-rate" in info.frame_rate_warning


def test_quick_extract_allows_missing_trailing_frame_outputs(tmp_path: Path, monkeypatch) -> None:
    def fake_run_cmd_with_ffmpeg_progress(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess:
        out_pattern = Path(cmd[-1])
        out_dir = out_pattern.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "00000001.jpg").write_bytes(b"a")
        (out_dir / "00000002.jpg").write_bytes(b"b")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "core.extract_frames.run_cmd_with_ffmpeg_progress",
        fake_run_cmd_with_ffmpeg_progress,
    )

    extracted = extract_selected_frames(
        video_path=tmp_path / "input.mp4",
        ffmpeg_bin="ffmpeg",
        frame_indices=[0, 10, 20],
        output_dir=tmp_path / "images",
        image_ext="jpg",
        jpg_quality=2,
        filename_prefix="clip",
        frame_digits=2,
        allow_partial_tail=True,
    )

    assert extracted == [0, 10]
    assert (tmp_path / "images" / "clip_00.jpg").read_bytes() == b"a"
    assert (tmp_path / "images" / "clip_10.jpg").read_bytes() == b"b"
    assert not (tmp_path / "images" / "clip_20.jpg").exists()


def test_extract_uses_current_ffmpeg_filter_and_framerate_options(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_cmd_with_ffmpeg_progress(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess:
        commands.append(cmd)
        if len(commands) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "filter file option unavailable")
        out_pattern = Path(cmd[-1])
        out_pattern.parent.mkdir(parents=True, exist_ok=True)
        (out_pattern.parent / "00000001.jpg").write_bytes(b"frame")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "core.extract_frames.run_cmd_with_ffmpeg_progress",
        fake_run_cmd_with_ffmpeg_progress,
    )

    extracted = extract_selected_frames(
        video_path=tmp_path / "input.mp4",
        ffmpeg_bin="ffmpeg",
        frame_indices=[0],
        output_dir=tmp_path / "images",
        image_ext="jpg",
        jpg_quality=2,
        filename_prefix="clip",
        frame_digits=2,
    )

    assert extracted == [0]
    assert "-/filter:v" in commands[0]
    assert "-vf" in commands[1]
    assert all("-fps_mode" in command for command in commands)
    assert all("-vsync" not in command for command in commands)
    assert all("-filter_script:v" not in command for command in commands)


def test_ffmpeg_progress_command_terminates_on_cancel() -> None:
    cancel_event = Event()
    timer = Timer(0.15, cancel_event.set)
    timer.start()
    try:
        with pytest.raises(AppJobCancelled):
            run_cmd_with_ffmpeg_progress(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys,time\n"
                        "for i in range(100):\n"
                        "    sys.stderr.write(f'frame={i}\\n')\n"
                        "    sys.stderr.flush()\n"
                        "    time.sleep(0.05)\n"
                    ),
                ],
                phase="extract",
                total_items=100,
                cancel_event=cancel_event,
            )
    finally:
        timer.cancel()


def test_staged_replace_keeps_existing_frames_until_commit(tmp_path: Path, monkeypatch) -> None:
    def fake_run_cmd_with_ffmpeg_progress(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess:
        out_pattern = Path(cmd[-1])
        out_dir = out_pattern.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "00000001.jpg").write_bytes(b"new-a")
        (out_dir / "00000002.jpg").write_bytes(b"new-b")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "core.extract_frames.run_cmd_with_ffmpeg_progress",
        fake_run_cmd_with_ffmpeg_progress,
    )
    scene = tmp_path / "scene"
    images = scene / "images"
    staging = scene / "_stechdrive" / "frames" / "cache" / "extract_staging_test"
    images.mkdir(parents=True)
    (images / "clip_00.jpg").write_bytes(b"old-a")
    (images / "clip_10.jpg").write_bytes(b"old-b")
    (images / "clip_20.jpg").write_bytes(b"old-stale")

    extracted = extract_selected_frames(
        video_path=tmp_path / "input.mp4",
        ffmpeg_bin="ffmpeg",
        frame_indices=[0, 10],
        output_dir=staging,
        image_ext="jpg",
        jpg_quality=2,
        filename_prefix="clip",
        frame_digits=2,
    )

    assert extracted == [0, 10]
    assert (images / "clip_00.jpg").read_bytes() == b"old-a"
    assert (images / "clip_10.jpg").read_bytes() == b"old-b"
    assert (staging / "clip_00.jpg").read_bytes() == b"new-a"

    removed = commit_staged_frame_outputs(
        scene,
        staging,
        ["images/clip_00.jpg", "images/clip_10.jpg"],
        {"images/clip_00.jpg", "images/clip_10.jpg", "images/clip_20.jpg"},
    )

    assert removed == 3
    assert (images / "clip_00.jpg").read_bytes() == b"new-a"
    assert (images / "clip_10.jpg").read_bytes() == b"new-b"
    assert not (images / "clip_20.jpg").exists()
    assert not staging.exists()
