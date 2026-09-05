"""Shared Step 4 route/profile contracts.

This module intentionally contains stable IDs rather than UI widgets. Keeping
these constants outside the Step 4 widget lets command builders, manifests,
output guards, and tests share the same contract without importing the giant
widget module.
"""

from __future__ import annotations

import math

from core.orientation_correction import LICHTFELD_FINAL_ORIENTATION_MATRIX
from core.scene_layout import STEP4_EXPORT_SETTINGS_JSON
from gui.steps import sfm_route_specs as _sfm_route_specs

_SPHERESFM_CUDA_ARCH_ERROR_MARKERS = (
    "no kernel image is available for execution on the device",
    "cudaerrornokernelimagefordevice",
)
_COLMAP_GUI_UNAVAILABLE_MARKERS = (
    "cannot start colmap gui",
    "built without gui support",
    "qt dependency is missing",
)
_METHOD_COLMAP = _sfm_route_specs.SFM_ROUTE_COLMAP
_METHOD_METASHAPE = _sfm_route_specs.SFM_ROUTE_METASHAPE
_METHOD_SPHERESFM = _sfm_route_specs.SFM_ROUTE_SPHERESFM
_PROFILE_POSTSHOT = "postshot"
_PROFILE_BRUSH = "brush"
_PROFILE_LICHTFELD = "lichtfeld"
_PROFILE_REALITYSCAN = "realityscan"
_PROFILE_CUSTOM = "custom"
_PIPELINE_STAGE_SFM = "sfm"
_PIPELINE_STAGE_CONVERSION = "conversion"
_PIPELINE_STATUS_READY = "ready"
_PIPELINE_STATUS_WARNING = "warning"
_PIPELINE_STATUS_OFF = "off"
_OUTPUT_SHAPE_PROJECTED = "projected"
_OUTPUT_SHAPE_EQUIRECT_3DGUT = "equirect_3dgut"
_COLMAP_MAPPER_INCREMENTAL = "incremental"
_COLMAP_MAPPER_GLOBAL = "global"
_COLMAP_MAPPER_GLOMAP = "glomap"
_COLMAP_MATCHER_SEQUENTIAL = "sequential"
_COLMAP_MATCHER_EXHAUSTIVE = "exhaustive"
_SPHERESFM_QUALITY_LIGHT = "light"
_SPHERESFM_QUALITY_LIGHTEST = "lightest"
_SPHERESFM_QUALITY_STANDARD = "standard"
_SPHERESFM_RUN_FULL = "full"
_SPHERESFM_RUN_SFM_ONLY = "sfm_only"
_SPHERESFM_RUN_CONVERT_ONLY = "convert_only"
_AXIS_POSTSHOT = "postshot"
_AXIS_BRUSH = "brush"
_AXIS_NONE = "none"
_NORMAL_OUTPUT_SCALE = 2.0 / math.pi
_SUPPORTED_TRAINING_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
_GENERATED_POINTCLOUD_NAME = "pointcloud.ply"
_LFS_ADVANCED_INT_KEYS = {
    "refine_every",
    "start_refine",
    "stop_refine",
    "grow_until_iter",
    "reset_every",
    "sh_degree_interval",
    "bilateral_grid_X",
    "bilateral_grid_Y",
    "bilateral_grid_W",
    "init_num_pts",
    "pause_refine_after_reset",
    "sparsify_steps",
    "ppisp_warmup_steps",
    "ppisp_controller_activation_step",
}
_LFS_ADVANCED_LIST_KEYS = {"eval_steps", "save_steps"}
_LFS_STRATEGIES = ("mrnf", "igs+", "mcmc")
_LFS_UI_STEP_TEXT_KEYS = {"iterations"}
_LFS_UI_STEP_ADVANCED_KEYS = {
    "sh_degree_interval",
    "refine_every",
    "start_refine",
    "stop_refine",
    "reset_every",
    "grow_until_iter",
}
_LFS_ADVANCED_FIELD_WIDTHS = {
    "means_lr": 112,
    "means_lr_end": 122,
    "shs_lr": 102,
    "opacity_lr": 102,
    "scaling_lr": 102,
    "scaling_lr_end": 112,
    "rotation_lr": 102,
    "grad_threshold": 116,
    "depth_loss_weight": 96,
    "mask_opacity_penalty_weight": 104,
    "mask_opacity_penalty_power": 104,
    "bilateral_grid_lr": 116,
    "lambda_dssim": 100,
    "init_num_pts": 108,
    "min_opacity": 108,
    "prune_opacity": 108,
    "grow_scale3d": 100,
    "grow_scale2d": 100,
    "prune_scale3d": 100,
    "prune_scale2d": 100,
    "growth_grad_threshold": 116,
    "means_noise_weight": 104,
    "bounds_percentile": 100,
    "sparsify_steps": 108,
    "ppisp_controller_activation_step": 108,
    "max_width": 92,
    "test_every": 86,
    "eval_steps": 136,
    "save_steps": 136,
}
_LFS_ADVANCED_FLOAT_FORMATS = {
    "means_lr": ".6f",
    "means_lr_end": ".8f",
    "shs_lr": ".4f",
    "opacity_lr": ".4f",
    "scaling_lr": ".4f",
    "scaling_lr_end": ".4f",
    "rotation_lr": ".4f",
    "grad_threshold": ".6f",
    "bilateral_grid_lr": ".6f",
    "lambda_dssim": ".3f",
    "opacity_reg": ".4f",
    "scale_reg": ".4f",
    "tv_loss_weight": ".1f",
    "init_opacity": ".3f",
    "init_scaling": ".3f",
    "init_extent": ".1f",
    "min_opacity": ".4f",
    "prune_opacity": ".4f",
    "grow_scale3d": ".4f",
    "grow_scale2d": ".3f",
    "prune_scale3d": ".3f",
    "prune_scale2d": ".3f",
    "growth_grad_threshold": ".5f",
    "grow_fraction": ".3f",
    "opacity_decay": ".4f",
    "scale_decay": ".4f",
    "means_noise_weight": ".1f",
    "bounds_percentile": ".2f",
    "init_rho": ".4f",
    "prune_ratio": ".3f",
    "mask_threshold": ".3f",
    "depth_loss_weight": ".3f",
    "mask_opacity_penalty_weight": ".3f",
    "mask_opacity_penalty_power": ".3f",
    "ppisp_controller_lr": ".5f",
}
_EXPORT_SETTINGS_NAME = STEP4_EXPORT_SETTINGS_JSON
_COLMAP_PROJECT_MANIFEST_NAME = "stechdrive_colmap_project.json"
_SPHERESFM_PROJECT_MANIFEST_NAME = "stechdrive_spheresfm_project.json"
_COLMAP_REPOSITORY_URL = "https://github.com/colmap/colmap"
_SPHERESFM_REPOSITORY_URL = "https://github.com/colmap/colmap"
_USER_SETTINGS_SECTION = "step4_colmap"
_LICHTFELD_FINAL_CORRECTION = LICHTFELD_FINAL_ORIENTATION_MATRIX


def is_spheresfm_rtx50_cuda_error_line(line: str) -> bool:
    """Detect CUDA binary/device-architecture failures seen with incompatible COLMAP builds."""
    lowered = line.lower()
    if any(marker in lowered for marker in _SPHERESFM_CUDA_ARCH_ERROR_MARKERS):
        return True
    if "invalid device function" not in lowered:
        return False
    return any(marker in lowered for marker in ("cuda", "sift", "pyramidcu", "cuteximage"))


def is_colmap_gui_unavailable_output(text: str) -> bool:
    """Detect COLMAP builds that can run CLI commands but cannot launch the Qt GUI."""
    lowered = text.lower()
    return any(marker in lowered for marker in _COLMAP_GUI_UNAVAILABLE_MARKERS)


def _normalize_spheresfm_quality_preset(value: str) -> str:
    from core.spheresfm_cli_contract import normalize_spheresfm_preset

    try:
        return normalize_spheresfm_preset(value)
    except ValueError:
        return _SPHERESFM_QUALITY_STANDARD
