from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core import ffmpeg_runtime
from core.extract_frames import ExtractFramesOptions, run_extract_frames


@pytest.mark.parametrize("tool", ["ffmpeg", "ffprobe"])
@pytest.mark.parametrize("version", ["7.0", "n7.1.1", "8.0.1-full_build-www.gyan.dev", "9.0", "10.0.2"])
def test_accepts_supported_release_versions(monkeypatch, tool: str, version: str) -> None:
    def run(cmd, **kwargs):
        assert cmd == ["custom tool.exe", "-version"]
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(cmd, 0, f"{tool} version {version} Copyright\n", "")

    monkeypatch.setattr(ffmpeg_runtime.subprocess, "run", run)
    assert ffmpeg_runtime.require_ffmpeg_version("custom tool.exe", tool) == version


@pytest.mark.parametrize("version", ["4.4.4", "5.0", "6.1.2", "n6.1"])
def test_rejects_older_versions_with_update_guidance(monkeypatch, version: str) -> None:
    monkeypatch.setattr(
        ffmpeg_runtime.subprocess, "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, f"ffmpeg version {version}\n", ""),
    )
    with pytest.raises(RuntimeError, match="7 or newer is required") as error:
        ffmpeg_runtime.require_ffmpeg_version("selected-ffmpeg", "ffmpeg")
    assert "selected-ffmpeg" in str(error.value)
    assert "Step 1" in str(error.value)


@pytest.mark.parametrize("banner", ["", "ffmpeg version N-12345-gabcdef", "ffprobe version 9.0"])
def test_does_not_guess_a_supported_version_from_unrecognized_output(monkeypatch, banner: str) -> None:
    monkeypatch.setattr(
        ffmpeg_runtime.subprocess, "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, banner, ""),
    )
    with pytest.raises(RuntimeError, match="Cannot determine"):
        ffmpeg_runtime.require_ffmpeg_version("ffmpeg", "ffmpeg")


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("ffmpeg", 10)])
def test_missing_or_unresponsive_tool_has_actionable_error(monkeypatch, error: Exception) -> None:
    def run(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(ffmpeg_runtime.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="setup_windows.bat"):
        ffmpeg_runtime.require_ffmpeg_version("ffmpeg", "ffmpeg")


def test_failed_version_command_reports_diagnostic(monkeypatch) -> None:
    monkeypatch.setattr(
        ffmpeg_runtime.subprocess, "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, "", "missing runtime DLL"),
    )
    with pytest.raises(RuntimeError, match="missing runtime DLL"):
        ffmpeg_runtime.require_ffmpeg_version("ffmpeg", "ffmpeg")


@pytest.mark.parametrize("unsupported_tool", ["ffmpeg", "ffprobe"])
def test_video_job_checks_both_tools_before_analysis_or_output_changes(tmp_path: Path, monkeypatch, capsys, unsupported_tool: str) -> None:
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    scene = tmp_path / "scene"
    images = scene / "images"
    images.mkdir(parents=True)
    existing = images / "existing.jpg"
    existing.write_bytes(b"keep this image")
    commands = []

    def run(cmd, **_kwargs):
        commands.append(cmd)
        tool = cmd[0]
        version = "6.1" if tool == unsupported_tool else "9.0"
        return subprocess.CompletedProcess(cmd, 0, f"{tool} version {version}\n", "")

    monkeypatch.setattr(ffmpeg_runtime.subprocess, "run", run)
    result = run_extract_frames(ExtractFramesOptions(
        input_video=video, output_dir=scene, quick_extract=True, output_mode="overwrite",
    ))
    assert result == 1
    assert all(cmd[1:] == ["-version"] for cmd in commands)
    assert commands[-1][0] == unsupported_tool
    assert existing.read_bytes() == b"keep this image"
    assert list(scene.iterdir()) == [images]
    assert "7 or newer is required" in capsys.readouterr().out


def test_setup_checker_reports_selected_tool_versions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        ffmpeg_runtime.subprocess, "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, f"{Path(cmd[0]).stem} version 9.0\n", ""),
    )
    assert ffmpeg_runtime.main(["--ffmpeg", "custom/ffmpeg.exe", "--ffprobe", "custom/ffprobe.exe"]) == 0
    output = capsys.readouterr().out
    assert "ffmpeg: 9.0" in output and "ffprobe: 9.0" in output
