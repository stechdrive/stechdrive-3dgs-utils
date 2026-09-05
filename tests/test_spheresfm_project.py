from __future__ import annotations

import subprocess

import pytest

from core import spheresfm_project
from core.spheresfm_cli_contract import required_spheresfm_options


def _completed(arguments: tuple[str, ...], output: str, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, returncode, stdout=output, stderr="")


def test_validate_spheresfm_colmap_checks_selected_command_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = required_spheresfm_options(matcher="spatial", quality_preset="quality", use_masks=True)
    calls: list[tuple[str, ...]] = []

    def fake_run(_colmap: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments == ("version",):
            return _completed(arguments, "COLMAP 4.2.0")
        return _completed(arguments, "\n".join(required[arguments[0]]))

    monkeypatch.setattr(spheresfm_project, "_run_colmap_capture", fake_run)

    version = spheresfm_project.validate_spheresfm_colmap(
        "COLMAP.bat",
        matcher="spatial",
        quality_preset="quality",
        use_masks=True,
    )

    assert version == (4, 2, 0)
    assert calls == [
        ("version",),
        ("feature_extractor", "-h"),
        ("sequential_matcher", "-h"),
        ("mapper", "-h"),
    ]


def test_validate_spheresfm_colmap_reports_missing_mapper_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = required_spheresfm_options(matcher="sequential", quality_preset="standard", use_masks=False)

    def fake_run(_colmap: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        if arguments == ("version",):
            return _completed(arguments, "COLMAP 4.2.0")
        options = list(required[arguments[0]])
        if arguments[0] == "mapper":
            options.remove("--Mapper.multiple_models")
        return _completed(arguments, "\n".join(options))

    monkeypatch.setattr(spheresfm_project, "_run_colmap_capture", fake_run)

    with pytest.raises(RuntimeError, match="--Mapper.multiple_models"):
        spheresfm_project.validate_spheresfm_colmap("colmap.exe")


def test_validate_spheresfm_colmap_recommends_42_for_quality(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    required = required_spheresfm_options(matcher="sequential", quality_preset="quality", use_masks=False)

    def fake_run(_colmap: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        if arguments == ("version",):
            return _completed(arguments, "COLMAP 4.1.1")
        return _completed(arguments, "\n".join(required[arguments[0]]))

    monkeypatch.setattr(spheresfm_project, "_run_colmap_capture", fake_run)

    spheresfm_project.validate_spheresfm_colmap("colmap.exe", quality_preset="quality")

    assert "COLMAP 4.2 or newer is recommended." in capsys.readouterr().out
