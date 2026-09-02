from __future__ import annotations

import struct
from pathlib import Path

import pytest

from core.colmap_sparse_model import CAMERA_MODEL_IDS, read_cameras_binary
from core.spheresfm_to_transforms import convert


def _write_camera_binary(path: Path, *, model_id: int, params: tuple[float, ...]) -> None:
    path.write_bytes(
        struct.pack("<QiiQQ", 1, 1, model_id, 64, 32)
        + struct.pack("<" + "d" * len(params), *params)
    )


def test_colmap_42_camera_model_registry_uses_official_ids() -> None:
    expected = {
        11: ("RAD_TAN_THIN_PRISM_FISHEYE", 16),
        12: ("SIMPLE_DIVISION", 4),
        13: ("DIVISION", 5),
        14: ("SIMPLE_FISHEYE", 3),
        15: ("FISHEYE", 4),
        16: ("EUCM", 6),
        17: ("EQUIRECTANGULAR", 2),
    }

    assert {model_id: (CAMERA_MODEL_IDS[model_id].name, CAMERA_MODEL_IDS[model_id].num_params) for model_id in expected} == expected


def test_camera_binary_id_11_is_official_rad_tan_model(tmp_path: Path) -> None:
    path = tmp_path / "cameras.bin"
    params = tuple(float(index) for index in range(16))
    _write_camera_binary(path, model_id=11, params=params)

    camera = read_cameras_binary(path)[1]

    assert camera.model == "RAD_TAN_THIN_PRISM_FISHEYE"
    assert camera.params == params


def test_legacy_sphere_binary_requires_explicit_compatibility_mode(tmp_path: Path) -> None:
    path = tmp_path / "cameras.bin"
    _write_camera_binary(path, model_id=11, params=(1.0, 32.0, 16.0))

    with pytest.raises(EOFError):
        read_cameras_binary(path)

    camera = read_cameras_binary(path, allow_legacy_sphere=True)[1]
    assert camera.model == "SPHERE"
    assert camera.params == (1.0, 32.0, 16.0)


def test_spherical_conversion_reads_legacy_sphere_binary(tmp_path: Path) -> None:
    sparse = tmp_path / "sparse" / "0"
    sparse.mkdir(parents=True)
    _write_camera_binary(sparse / "cameras.bin", model_id=11, params=(1.0, 32.0, 16.0))
    (sparse / "images.bin").write_bytes(
        struct.pack("<Q", 1)
        + struct.pack("<idddddddi", 1, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1)
        + b"frame_0001.jpg\x00"
        + struct.pack("<Q", 0)
    )
    (sparse / "points3D.bin").write_bytes(struct.pack("<Q", 0))
    images = tmp_path / "images"
    images.mkdir()
    (images / "frame_0001.jpg").write_bytes(b"image")

    result = convert(tmp_path / "sparse", tmp_path / "output", images)

    assert result["num_images"] == 1
    assert result["num_points"] == 0
