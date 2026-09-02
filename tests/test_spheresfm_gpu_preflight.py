from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core import spheresfm_gpu_preflight as preflight


def test_spheresfm_scripts_can_run_help_from_other_working_directory(tmp_path: Path) -> None:
    repo = Path.cwd()
    for script in ("spheresfm_gpu_preflight.py", "prepare_spheresfm_project.py", "spheresfm_to_transforms.py"):
        result = subprocess.run(
            [sys.executable, str(repo / "scripts" / script), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_preflight_copies_one_image_and_runs_gpu_sift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "frame_0001.jpg").write_bytes(b"image-one")
    (images_dir / "frame_0002.jpg").write_bytes(b"image-two")

    work_dir = tmp_path / "output" / "colmap_equirect" / "preflight"
    stale_dir = work_dir / "images"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old.jpg").write_bytes(b"old")
    (work_dir / "database.db").write_bytes(b"old-db")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{cmd[1]} ok\n", stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    monkeypatch.setattr(preflight, "validate_spheresfm_colmap", lambda _colmap, **_kwargs: None)

    assert preflight.main(
        [
            "--colmap",
            "spheresfm_colmap.exe",
            "--images-dir",
            str(images_dir),
            "--work-dir",
            str(work_dir),
            "--camera-params",
            "64,32",
        ]
    ) == 0

    copied = sorted((work_dir / "images").iterdir())
    assert [p.name for p in copied] == ["preflight_000001.jpg"]
    assert copied[0].read_bytes() == b"image-one"
    assert not (work_dir / "database.db").exists()

    assert calls[0][0:2] == ["spheresfm_colmap.exe", "database_creator"]
    assert calls[0][calls[0].index("--database_path") + 1] == str(work_dir / "database.db")
    assert calls[1][0:2] == ["spheresfm_colmap.exe", "feature_extractor"]
    assert calls[1][calls[1].index("--image_path") + 1] == str(work_dir / "images")
    assert calls[1][calls[1].index("--ImageReader.camera_model") + 1] == "EQUIRECTANGULAR"
    assert calls[1][calls[1].index("--ImageReader.camera_params") + 1] == "64,32"
    assert calls[1][calls[1].index("--FeatureExtraction.use_gpu") + 1] == "1"
    assert calls[1][calls[1].index("--FeatureExtraction.max_image_size") + 1] == "1024"

    captured = capsys.readouterr()
    assert "COLMAP spherical GPU preflight passed." in captured.out


def test_preflight_rejects_unscoped_work_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "frame_0001.jpg").write_bytes(b"image")

    monkeypatch.setattr(preflight, "validate_spheresfm_colmap", lambda _colmap, **_kwargs: None)
    with pytest.raises(ValueError, match="preflight"):
        preflight.main(
            [
                "--colmap",
                "spheresfm_colmap.exe",
                "--images-dir",
                str(images_dir),
                "--work-dir",
                str(tmp_path / "scratch"),
                "--camera-params",
                "64,32",
            ]
        )
