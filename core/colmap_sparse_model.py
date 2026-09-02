"""Small COLMAP sparse model reader used by dataset conversion jobs."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np


@dataclass(frozen=True)
class CameraModel:
    model_id: int
    name: str
    num_params: int


CAMERA_MODELS = [
    CameraModel(0, "SIMPLE_PINHOLE", 3),
    CameraModel(1, "PINHOLE", 4),
    CameraModel(2, "SIMPLE_RADIAL", 4),
    CameraModel(3, "RADIAL", 5),
    CameraModel(4, "OPENCV", 8),
    CameraModel(5, "OPENCV_FISHEYE", 8),
    CameraModel(6, "FULL_OPENCV", 12),
    CameraModel(7, "FOV", 5),
    CameraModel(8, "SIMPLE_RADIAL_FISHEYE", 4),
    CameraModel(9, "RADIAL_FISHEYE", 5),
    CameraModel(10, "THIN_PRISM_FISHEYE", 12),
    CameraModel(11, "RAD_TAN_THIN_PRISM_FISHEYE", 16),
    CameraModel(12, "SIMPLE_DIVISION", 4),
    CameraModel(13, "DIVISION", 5),
    CameraModel(14, "SIMPLE_FISHEYE", 3),
    CameraModel(15, "FISHEYE", 4),
    CameraModel(16, "EUCM", 6),
    CameraModel(17, "EQUIRECTANGULAR", 2),
]
LEGACY_SPHERE_CAMERA_MODEL = CameraModel(11, "SPHERE", 3)
CAMERA_MODEL_IDS = {model.model_id: model for model in CAMERA_MODELS}
CAMERA_MODEL_NAMES = {
    **{model.name: model for model in CAMERA_MODELS},
    LEGACY_SPHERE_CAMERA_MODEL.name: LEGACY_SPHERE_CAMERA_MODEL,
}


@dataclass(frozen=True)
class Camera:
    camera_id: int
    model: str
    width: int
    height: int
    params: tuple[float, ...]


@dataclass(frozen=True)
class ImagePose:
    image_id: int
    qvec: np.ndarray
    tvec: np.ndarray
    camera_id: int
    name: str


@dataclass(frozen=True)
class Point3D:
    point_id: int
    xyz: tuple[float, float, float]
    rgb: tuple[int, int, int]


def read_next_bytes(fid: BinaryIO, num_bytes: int, fmt: str) -> tuple:
    data = fid.read(num_bytes)
    if len(data) != num_bytes:
        raise EOFError("Unexpected end of COLMAP binary model")
    return struct.unpack("<" + fmt, data)


def model_extension(path: Path) -> str | None:
    if all((path / name).is_file() for name in ("cameras.bin", "images.bin", "points3D.bin")):
        return ".bin"
    if all((path / name).is_file() for name in ("cameras.txt", "images.txt", "points3D.txt")):
        return ".txt"
    return None


def read_registered_image_count(path: Path) -> int:
    ext = model_extension(path)
    if ext == ".bin":
        try:
            with (path / "images.bin").open("rb") as fid:
                return int(read_next_bytes(fid, 8, "Q")[0])
        except Exception:
            return 0
    if ext == ".txt":
        try:
            lines = [
                line
                for line in (path / "images.txt").read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except OSError:
            return 0
        return sum(1 for line in lines if len(line.split()) >= 10)
    return 0


def resolve_model_dir(path: Path) -> Path:
    if model_extension(path):
        return path
    if not path.is_dir():
        raise FileNotFoundError(f"Sparse model directory not found: {path}")
    candidates = [p for p in path.iterdir() if p.is_dir() and model_extension(p)]
    if not candidates:
        raise FileNotFoundError(f"No COLMAP sparse model found under: {path}")

    def sort_key(candidate: Path) -> tuple[int, int, str]:
        numeric = 0 if candidate.name.isdigit() else 1
        number = int(candidate.name) if candidate.name.isdigit() else 0
        return numeric, number, candidate.name.lower()

    return max(
        candidates,
        key=lambda p: (
            read_registered_image_count(p),
            tuple(-x if isinstance(x, int) else x for x in sort_key(p)),
        ),
    )


def read_cameras_text(path: Path) -> dict[int, Camera]:
    cameras: dict[int, Camera] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        camera_id = int(parts[0])
        model_name = parts[1]
        if model_name not in CAMERA_MODEL_NAMES:
            raise ValueError(f"Unsupported camera model '{model_name}' in {path}")
        model = CAMERA_MODEL_NAMES[model_name]
        params = tuple(float(v) for v in parts[4 : 4 + model.num_params])
        if len(params) != model.num_params:
            raise ValueError(f"Camera {camera_id} has invalid params in {path}")
        cameras[camera_id] = Camera(camera_id, model.name, int(parts[2]), int(parts[3]), params)
    return cameras


def _read_cameras_binary_with_models(path: Path, models: dict[int, CameraModel]) -> dict[int, Camera]:
    cameras: dict[int, Camera] = {}
    with path.open("rb") as fid:
        num_cameras = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_cameras):
            camera_id, model_id, width, height = read_next_bytes(fid, 24, "iiQQ")
            model = models.get(model_id)
            if model is None:
                raise ValueError(f"Unsupported camera model id {model_id} in {path}")
            params = read_next_bytes(fid, 8 * model.num_params, "d" * model.num_params)
            cameras[int(camera_id)] = Camera(
                int(camera_id),
                model.name,
                int(width),
                int(height),
                tuple(float(v) for v in params),
            )
        if fid.read(1):
            raise ValueError(f"Unexpected trailing data in {path}")
    return cameras


def read_cameras_binary(path: Path, *, allow_legacy_sphere: bool = False) -> dict[int, Camera]:
    """Read official COLMAP camera IDs, optionally retrying old SphereSfM id 11."""

    try:
        return _read_cameras_binary_with_models(path, CAMERA_MODEL_IDS)
    except (EOFError, ValueError) as official_error:
        if not allow_legacy_sphere:
            raise
        legacy_models = {**CAMERA_MODEL_IDS, LEGACY_SPHERE_CAMERA_MODEL.model_id: LEGACY_SPHERE_CAMERA_MODEL}
        try:
            return _read_cameras_binary_with_models(path, legacy_models)
        except (EOFError, ValueError) as legacy_error:
            raise ValueError(
                f"Could not parse official COLMAP or legacy SphereSfM cameras from {path}: "
                f"official={official_error}; legacy={legacy_error}"
            ) from official_error


def read_images_text(path: Path) -> dict[int, ImagePose]:
    images: dict[int, ImagePose] = {}
    lines = [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not line.startswith("#")
    ]
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        image_id = int(parts[0])
        qvec = np.array([float(v) for v in parts[1:5]], dtype=np.float64)
        tvec = np.array([float(v) for v in parts[5:8]], dtype=np.float64)
        camera_id = int(parts[8])
        name = " ".join(parts[9:])
        images[image_id] = ImagePose(image_id, qvec, tvec, camera_id, name)
        if idx < len(lines):
            idx += 1
    return images


def read_images_binary(path: Path) -> dict[int, ImagePose]:
    images: dict[int, ImagePose] = {}
    with path.open("rb") as fid:
        num_images = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_images):
            props = read_next_bytes(fid, 64, "idddddddi")
            image_id = int(props[0])
            qvec = np.array(props[1:5], dtype=np.float64)
            tvec = np.array(props[5:8], dtype=np.float64)
            camera_id = int(props[8])

            name_bytes = bytearray()
            while True:
                char = fid.read(1)
                if not char:
                    raise EOFError("Unexpected end of image name in images.bin")
                if char == b"\x00":
                    break
                name_bytes.extend(char)
            name = name_bytes.decode("utf-8", errors="replace")

            num_points2d = read_next_bytes(fid, 8, "Q")[0]
            fid.seek(24 * int(num_points2d), os.SEEK_CUR)
            images[image_id] = ImagePose(image_id, qvec, tvec, camera_id, name)
    return images


def read_points3d_text(path: Path) -> dict[int, Point3D]:
    points: dict[int, Point3D] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        point_id = int(parts[0])
        xyz = (float(parts[1]), float(parts[2]), float(parts[3]))
        rgb = (int(parts[4]), int(parts[5]), int(parts[6]))
        points[point_id] = Point3D(point_id, xyz, rgb)
    return points


def read_points3d_binary(path: Path) -> dict[int, Point3D]:
    points: dict[int, Point3D] = {}
    with path.open("rb") as fid:
        num_points = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_points):
            point_id, x, y, z, r, g, b, _error = read_next_bytes(fid, 43, "QdddBBBd")
            track_len = read_next_bytes(fid, 8, "Q")[0]
            fid.seek(8 * int(track_len), os.SEEK_CUR)
            points[int(point_id)] = Point3D(
                int(point_id),
                (float(x), float(y), float(z)),
                (int(r), int(g), int(b)),
            )
    return points


def read_model(
    path: Path,
    *,
    allow_legacy_sphere_binary: bool = False,
) -> tuple[dict[int, Camera], dict[int, ImagePose], dict[int, Point3D], Path]:
    model_dir = resolve_model_dir(path)
    ext = model_extension(model_dir)
    if ext == ".bin":
        return (
            read_cameras_binary(
                model_dir / "cameras.bin",
                allow_legacy_sphere=allow_legacy_sphere_binary,
            ),
            read_images_binary(model_dir / "images.bin"),
            read_points3d_binary(model_dir / "points3D.bin"),
            model_dir,
        )
    if ext == ".txt":
        return (
            read_cameras_text(model_dir / "cameras.txt"),
            read_images_text(model_dir / "images.txt"),
            read_points3d_text(model_dir / "points3D.txt"),
            model_dir,
        )
    raise FileNotFoundError(f"No COLMAP sparse model found: {path}")


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    q0, q1, q2, q3 = qvec
    return np.array(
        [
            [1 - 2 * q2 * q2 - 2 * q3 * q3, 2 * q1 * q2 - 2 * q0 * q3, 2 * q3 * q1 + 2 * q0 * q2],
            [2 * q1 * q2 + 2 * q0 * q3, 1 - 2 * q1 * q1 - 2 * q3 * q3, 2 * q2 * q3 - 2 * q0 * q1],
            [2 * q3 * q1 - 2 * q0 * q2, 2 * q2 * q3 + 2 * q0 * q1, 1 - 2 * q1 * q1 - 2 * q2 * q2],
        ],
        dtype=np.float64,
    )


def colmap_pose_to_c2w(image: ImagePose, *, opengl_camera: bool) -> np.ndarray:
    r_cw = qvec_to_rotmat(image.qvec)
    r_wc = r_cw.T
    t_wc = -r_wc @ image.tvec
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = r_wc
    transform[:3, 3] = t_wc
    if opengl_camera:
        transform[:3, 1:3] *= -1.0
    return transform


def resolve_image_path(images_dir: Path, image_name: str) -> Path:
    raw = Path(image_name)
    if raw.is_absolute():
        return raw
    candidate = images_dir / raw
    if candidate.exists():
        return candidate
    parts = raw.parts
    if parts and parts[0].lower() == "images" and len(parts) > 1 and images_dir.name.lower() == "images":
        return images_dir / Path(*parts[1:])
    return candidate
