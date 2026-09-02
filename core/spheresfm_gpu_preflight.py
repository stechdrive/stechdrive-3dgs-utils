"""Run a tiny isolated GPU SIFT preflight for COLMAP spherical SfM."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from core.cancellation import CancellationToken, raise_if_cancelled, terminate_process
from core.colmap_cli import build_colmap_command
from core.path_safety import safe_clear_path
from core.spheresfm_project import iter_images, validate_spheresfm_colmap  # noqa: F401

PREFLIGHT_MAX_IMAGE_SIZE = "1024"
PREFLIGHT_MAX_NUM_FEATURES = "2048"


def reset_preflight_workspace(work_dir: Path) -> Path:
    resolved = work_dir.resolve()
    if resolved.name.lower() != "preflight":
        raise ValueError(f"Preflight work folder must end with 'preflight': {work_dir}")

    images_dir = work_dir / "images"
    database = work_dir / "database.db"
    if images_dir.exists():
        safe_clear_path(images_dir, allowed_roots=[work_dir])
    if database.exists():
        safe_clear_path(database, allowed_roots=[work_dir])
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def run_colmap_command(cmd: list[str], label: str, *, cancel_event: CancellationToken | None = None) -> None:
    raise_if_cancelled(cancel_event)
    print("$ " + subprocess.list2cmdline(cmd), flush=True)
    if cancel_event is None:
        try:
            result = subprocess.run(cmd, check=False)
        except OSError as exc:
            raise RuntimeError(f"{label} could not start: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(f"{label} failed with exit code {result.returncode}")
        return

    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        raise RuntimeError(f"{label} could not start: {exc}") from exc

    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            terminate_process(proc)
            raise_if_cancelled(cancel_event)
        time.sleep(0.05)

    raise_if_cancelled(cancel_event)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {proc.returncode}")


def build_feature_command(colmap: str, database: Path, images_dir: Path, camera_params: str) -> list[str]:
    return build_colmap_command(
        colmap,
        "feature_extractor",
        "--database_path",
        str(database),
        "--image_path",
        str(images_dir),
        "--ImageReader.camera_model",
        "EQUIRECTANGULAR",
        "--ImageReader.camera_params",
        camera_params,
        "--ImageReader.single_camera",
        "1",
        "--FeatureExtraction.use_gpu",
        "1",
        "--FeatureExtraction.max_image_size",
        PREFLIGHT_MAX_IMAGE_SIZE,
        "--SiftExtraction.max_num_features",
        PREFLIGHT_MAX_NUM_FEATURES,
    )


def main(argv: list[str] | None = None) -> int:
    from core.spheresfm_gpu_preflight_cli import main as _main

    return _main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
