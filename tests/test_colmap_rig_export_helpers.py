import json
import math

import numpy as np
import pytest

from core.colmap_rig_export import (
    build_rig_config,
    cam_from_rig_rotation_quaternion,
    camera_name_for_index,
    frame_filename,
    prepare_views_for_colmap,
    rig_config_has_current_geometry,
    rig_views_are_non_overlapping,
    write_rig_config_json,
)
from core.colmap_sparse_model import qvec_to_rotmat
from core.cubemap_remap import build_remap
from core.cubemap_view_spec import make_default_cube6_views


def test_prepare_views_for_colmap_sorts_and_names_cameras() -> None:
    views = [
        {"name": "top", "pitch": -90.0, "yaw": 0.0},
        {"name": "front", "pitch": 0.0, "yaw": 0.0},
        {"name": "left", "pitch": 0.0, "yaw": -90.0},
    ]

    prepared = prepare_views_for_colmap(views)

    assert [(v["name"], v["camera_name"]) for v in prepared] == [
        ("top", "cam01"),
        ("left", "cam02"),
        ("front", "cam03"),
    ]
    assert "camera_name" not in views[0]


def test_camera_name_and_frame_filename_padding() -> None:
    assert camera_name_for_index(1, 6) == "cam01"
    assert camera_name_for_index(1, 120) == "cam001"
    assert frame_filename(1, 9, ".jpg") == "frame_00001.jpg"
    assert frame_filename(100000, 100000, "png") == "frame_100000.png"


def test_rig_config_first_camera_is_reference() -> None:
    prepared = prepare_views_for_colmap(
        [
            {"name": "front", "pitch": 0.0, "yaw": 0.0, "fov": 90.0},
            {"name": "right", "pitch": 0.0, "yaw": 90.0, "fov": 90.0},
        ]
    )

    config = build_rig_config(prepared, (1024, 1024))

    cameras = config[0]["cameras"]
    assert cameras[0]["ref_sensor"] is True
    assert "cam_from_rig_rotation" not in cameras[0]
    assert cameras[1]["cam_from_rig_translation"] == [0.0, 0.0, 0.0]
    assert cameras[1]["camera_model_name"] == "PINHOLE"
    assert cameras[1]["image_prefix"] == "rig1/cam02/"


def test_cam_from_rig_quaternion_is_unit_length() -> None:
    q = cam_from_rig_rotation_quaternion(45.0, 30.0)
    assert math.sqrt(sum(v * v for v in q)) == pytest.approx(1.0)


def test_write_rig_config_json(tmp_path) -> None:
    prepared = prepare_views_for_colmap([{"name": "front", "pitch": 0.0, "yaw": 0.0, "fov": 90.0}])

    path = write_rig_config_json(tmp_path, prepared, (512, 512))

    assert path == tmp_path / "colmap_rig" / "rig_config.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["cameras"][0]["image_prefix"] == "rig1/cam01/"
    assert rig_config_has_current_geometry(path)


@pytest.mark.parametrize("yaw_offset", [0.0, 37.0, -123.0])
@pytest.mark.parametrize("custom", [False, True])
def test_rig_relative_rotations_project_actual_remap_rays(yaw_offset: float, custom: bool) -> None:
    views = [view.as_dict() for view in make_default_cube6_views(yaw_offset, 0)]
    if custom:
        views = [
            {"name": "a", "yaw": yaw_offset + 13, "pitch": -47},
            {"name": "b", "yaw": yaw_offset - 29, "pitch": 18},
            {"name": "c", "yaw": yaw_offset + 85, "pitch": 63},
        ]
    prepared = prepare_views_for_colmap(views)
    cameras = build_rig_config(prepared, (17, 17))[0]["cameras"]
    # Recover the reference camera's ERP ray basis from actual generated maps.
    # This exercises both yaw/pitch order and the image Y-down convention.
    reference = prepared[0]
    ref_x, ref_y = build_remap((7680, 3840), 90, reference["yaw"], reference["pitch"], 17)

    def erp_rays(map_x, map_y):
        lon = (map_x.astype(float) / 7680 * 2 - 1) * np.pi
        lat = (0.5 - map_y.astype(float) / 3840) * np.pi
        return np.stack([np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)], axis=-1)

    xs, ys = np.meshgrid(np.arange(17), np.arange(17))
    rays_camera = np.stack([xs - 8, ys - 8, np.full_like(xs, 8.5, dtype=float)], axis=-1)
    rays_camera /= np.linalg.norm(rays_camera, axis=-1, keepdims=True)
    cam_from_erp = np.linalg.lstsq(
        erp_rays(ref_x, ref_y).reshape(-1, 3), rays_camera.reshape(-1, 3), rcond=None,
    )[0].T
    for view, camera in zip(prepared, cameras, strict=True):
        map_x, map_y = build_remap((7680, 3840), 90, view["yaw"], view["pitch"], 17)
        rotation = qvec_to_rotmat(np.array(camera.get("cam_from_rig_rotation", [1, 0, 0, 0])))
        assert np.linalg.det(rotation) == pytest.approx(1)
        projected = erp_rays(map_x, map_y) @ cam_from_erp.T @ rotation.T
        np.testing.assert_allclose(projected, rays_camera, atol=2e-6)


def test_same_frame_skip_requires_disjoint_cube_layout() -> None:
    cube = [view.as_dict() for view in make_default_cube6_views(27, 0)]
    assert rig_views_are_non_overlapping(cube)
    assert rig_views_are_non_overlapping(cube[:4])
    assert not rig_views_are_non_overlapping(cube + [cube[0]])
    assert not rig_views_are_non_overlapping([{**v, "fov": 100} for v in cube])
    assert not rig_views_are_non_overlapping([cube[0], {**cube[0], "yaw": cube[0]["yaw"] + 45}])
    assert not rig_views_are_non_overlapping([])


def test_old_rig_geometry_requires_image_conversion(tmp_path) -> None:
    path = tmp_path / "rig_config.json"
    path.write_text(json.dumps([{"cameras": [{"ref_sensor": True}]}]), encoding="utf-8")
    assert not rig_config_has_current_geometry(path)
