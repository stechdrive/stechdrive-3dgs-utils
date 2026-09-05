"""Exercise the actual FFmpeg batch routines with isolated, fake system tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows setup batch integration")


@pytest.mark.parametrize(
    ("ffmpeg_version", "ffprobe_version", "winget_available", "installed_version", "install_exit", "expected_exit", "should_install"),
    [
        ("7.0", "7.0", True, "9.0", 0, 0, False),
        ("9.0", "9.0", True, "9.0", 0, 0, False),
        ("6.1", "6.1", True, "9.0", 0, 1, False),
        ("9.0", "6.1", True, "9.0", 0, 1, False),
        (None, None, True, "9.0", 0, 0, True),
        ("8.0", None, True, "9.0", 0, 0, True),
        (None, None, False, "9.0", 0, 1, False),
        (None, None, True, "9.0", 1, 1, True),
        (None, None, True, "6.1", 0, 1, True),
    ],
)
def test_setup_validates_existing_and_newly_installed_tools(
    tmp_path: Path, ffmpeg_version, ffprobe_version, winget_available, installed_version,
    install_exit, expected_exit, should_install,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package = tmp_path / "core"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(repo_root / "core" / "ffmpeg_runtime.py", package / "ffmpeg_runtime.py")
    bin_dir = tmp_path / "fake tools"
    templates = bin_dir / "templates"
    templates.mkdir(parents=True)

    def write_tool(folder: Path, tool: str, version: str) -> None:
        (folder / f"{tool}.cmd").write_text(
            f"@echo off\necho {tool} version {version}\nexit /b 0\n", encoding="ascii",
        )

    for tool, version in (("ffmpeg", ffmpeg_version), ("ffprobe", ffprobe_version)):
        if version:
            write_tool(bin_dir, tool, version)
        write_tool(templates, tool, installed_version)
    if winget_available:
        (bin_dir / "winget.cmd").write_text(
            '@echo off\necho %* > "%~dp0winget_called.txt"\n'
            + (f"exit /b {install_exit}\n" if install_exit else
               'copy /y "%~dp0templates\\*.cmd" "%~dp0" >nul\nexit /b 0\n'),
            encoding="ascii",
        )

    source = (repo_root / "setup_windows.bat").read_text(encoding="utf-8")
    routines = source[source.index("\n:ensure_ffmpeg\n"):]
    # The real winget is an EXE; CALL lets its CMD test double return to the same routine.
    routines = routines.replace("\nwinget install ", "\ncall winget install ")
    # CreateProcess does not append .cmd to bare names as it does .exe.
    routines = routines.replace(
        "-m core.ffmpeg_runtime",
        "-m core.ffmpeg_runtime --ffmpeg ffmpeg.cmd --ffprobe ffprobe.cmd",
    )
    harness = tmp_path / "check_setup.cmd"
    harness.write_text(
        '@echo off\nsetlocal EnableExtensions EnableDelayedExpansion\n'
        f'set "PYTHON_CMD="{sys.executable}""\n'
        'call :ensure_ffmpeg\nexit /b %errorlevel%\n' + routines,
        encoding="utf-8",
    )
    env = os.environ.copy()
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    env["PATH"] = f"{bin_dir};{system32}"
    env["LOCALAPPDATA"] = str(tmp_path / "empty appdata")
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [str(system32 / "cmd.exe"), "/d", "/c", str(harness)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    marker = bin_dir / "winget_called.txt"
    assert marker.exists() is should_install, result.stdout + result.stderr
    if should_install:
        assert "install --id Gyan.FFmpeg --exact --source winget" in marker.read_text()
    if expected_exit == 0:
        assert "[ERROR]" not in result.stdout
    elif ffmpeg_version and ffprobe_version:
        assert "7 or newer is required" in result.stdout
