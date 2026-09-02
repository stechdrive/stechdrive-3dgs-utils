from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QProcess

from core.colmap_cli import (
    build_colmap_command,
    colmap_batch_qprocess_native_arguments,
    prefer_official_windows_launcher,
)


def test_colmap_executable_command_stays_direct() -> None:
    assert build_colmap_command("colmap.exe", "version") == ["colmap.exe", "version"]


@pytest.mark.skipif(os.name != "nt", reason="official COLMAP.bat handling is Windows-specific")
def test_official_package_bin_executable_prefers_top_level_launcher(tmp_path: Path) -> None:
    package = tmp_path / "COLMAP package"
    executable = package / "bin" / "colmap.exe"
    launcher = package / "COLMAP.bat"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    launcher.write_text("@echo off\n", encoding="utf-8")

    assert prefer_official_windows_launcher(str(executable)) == str(launcher)
    command = build_colmap_command(str(executable), "version")
    assert Path(command[0]).name.lower() == "cmd.exe"
    assert command[1:5] == ["/d", "/v:off", "/s", "/c"]
    assert command[5:] == [str(launcher), "version"]


@pytest.mark.skipif(os.name != "nt", reason="batch launcher execution is Windows-specific")
def test_colmap_batch_launcher_preserves_spaces_and_metacharacters(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "COLMAP&package" / "COLMAP.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\necho \"[%~1]\" \"[%~2]\" \"[%~3]\"\n", encoding="utf-8")

    command = build_colmap_command(str(launcher), "feature_extractor", "value with spaces", "value&meta")
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert '"[feature_extractor]" "[value with spaces]" "[value&meta]"' in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="batch launcher execution is Windows-specific")
def test_colmap_batch_launcher_runs_through_qprocess(
    tmp_path: Path,
) -> None:
    QCoreApplication.instance() or QCoreApplication([])
    launcher = tmp_path / "COLMAP & package" / "COLMAP.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\necho [%~1] [%~2]\n", encoding="utf-8")
    command = build_colmap_command(str(launcher), "gui", "model with spaces")

    process = QProcess()
    process.setProgram(command[0])
    native_arguments = colmap_batch_qprocess_native_arguments(command)
    assert native_arguments is not None
    process.setNativeArguments(native_arguments)
    process.start()

    assert process.waitForStarted(3000), process.errorString()
    assert process.waitForFinished(3000), process.errorString()
    output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
    error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
    assert process.exitCode() == 0, output + error
    assert "[gui] [model with spaces]" in output
