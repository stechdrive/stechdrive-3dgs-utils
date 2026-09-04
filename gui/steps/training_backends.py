"""Training backend command builders for Step 4."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

_LICHTFELD_REQUIRED_STRATEGIES = {"mrnf", "mcmc", "igs+"}
_LICHTFELD_MASK_MODES = {"none", "segment", "ignore", "segment_and_ignore", "alpha_consistent"}
_LICHTFELD_DEPTH_LOSS_MODES = {"pearson", "adaptive-warped-l1"}
_LICHTFELD_BG_MODES = {"solid_color", "modulation", "image", "random"}
_POSTSHOT_PROFILES = {"Splat ADC", "Splat MCMC", "Splat3"}
_POSTSHOT_IMAGE_SELECT_MODES = {"all", "best"}
_POSTSHOT_MASK_MODES = {"background", "occluders"}
_BRUSH_RENDER_MODES = {"auto", "default", "mip"}
_BRUSH_ALPHA_MODES = {"auto", "masked", "transparent"}
_GSPLAT_STRATEGIES = {"default", "mcmc"}
_LICHTFELD_BASE_IMAGE_COUNT = 300
_LICHTFELD_STEP_KEYS = {
    "iterations",
    "sh_degree_interval",
    "refine_every",
    "start_refine",
    "stop_refine",
    "reset_every",
    "grow_until_iter",
}
_LICHTFELD_STEP_LIST_KEYS = {"eval_steps", "save_steps"}


def _base_defaults() -> dict:
    return {
        "iterations": 30000,
        "sh_degree_interval": 1000,
        "means_lr": 0.000016,
        "means_lr_end": 0.00000016,
        "shs_lr": 0.0025,
        "opacity_lr": 0.025,
        "scaling_lr": 0.005,
        "scaling_lr_end": 0.005,
        "rotation_lr": 0.001,
        "lambda_dssim": 0.2,
        "min_opacity": 0.005,
        "refine_every": 100,
        "start_refine": 500,
        "stop_refine": 25000,
        "grad_threshold": 0.0002,
        "sh_degree": 3,
        "opacity_reg": 0.01,
        "scale_reg": 0.01,
        "init_opacity": 0.5,
        "init_scaling": 0.1,
        "max_cap": 1000000,
        "eval_steps": [7000, 30000],
        "save_steps": [7000, 30000],
        "strategy": "mrnf",
        "enable_eval": False,
        "enable_save_eval_images": True,
        "headless": False,
        "mip_filter": False,
        "use_bilateral_grid": False,
        "bilateral_grid_X": 16,
        "bilateral_grid_Y": 16,
        "bilateral_grid_W": 8,
        "bilateral_grid_lr": 0.002,
        "tv_loss_weight": 10.0,
        "prune_opacity": 0.005,
        "grow_scale3d": 0.01,
        "grow_scale2d": 0.05,
        "prune_scale3d": 0.1,
        "prune_scale2d": 0.15,
        "reset_every": 3000,
        "pause_refine_after_reset": 0,
        "revised_opacity": False,
        "gut": False,
        "undistort": False,
        "steps_scaler": 1.0,
        "random": False,
        "init_num_pts": 100000,
        "init_extent": 3.0,
        "mask_mode": "none",
        "use_depth_loss": False,
        "depth_loss_mode": "adaptive-warped-l1",
        "depth_loss_weight": 2.0,
        "invert_masks": False,
        "mask_opacity_penalty_weight": 1.0,
        "mask_opacity_penalty_power": 2.0,
        "mask_threshold": 0.5,
        "use_alpha_as_mask": True,
        "enable_sparsity": False,
        "sparsify_steps": 15000,
        "init_rho": 0.0005,
        "prune_ratio": 0.6,
        "use_ppisp": False,
        "ppisp_lr": 0.002,
        "ppisp_reg_weight": 0.001,
        "ppisp_warmup_steps": 500,
        "ppisp_freeze_from_sidecar": False,
        "ppisp_sidecar_path": "",
        "ppisp_use_controller": False,
        "ppisp_freeze_gaussians_on_distill": True,
        "ppisp_controller_activation_step": -1,
        "ppisp_controller_lr": 0.002,
        "growth_grad_threshold": 0.003,
        "grow_fraction": 0.07,
        "grow_until_iter": 15000,
        "opacity_decay": 0.004,
        "scale_decay": 0.002,
        "means_noise_weight": 50.0,
        "bounds_percentile": 0.8,
        "use_error_map": True,
        "use_edge_map": True,
        "bg_modulation": False,
        "bg_mode": "solid_color",
        "bg_color": [0.0, 0.0, 0.0],
    }


def _mrnf_defaults() -> dict:
    params = _base_defaults()
    params.update(
        {
            "strategy": "mrnf",
            "refine_every": 200,
            "start_refine": 0,
            "stop_refine": 28500,
            "max_cap": 5000000,
            "min_opacity": 1.0 / 255.0,
            "grad_threshold": 0.003,
            "means_lr": 0.00002,
            "means_lr_end": 0.0000002,
            "opacity_lr": 0.012,
            "scaling_lr": 0.007,
            "scaling_lr_end": 0.005,
            "rotation_lr": 0.002,
            "shs_lr": 0.002,
            "lambda_dssim": 0.2,
            "revised_opacity": True,
            "opacity_reg": 0.0,
            "scale_reg": 0.0,
            "use_error_map": True,
            "use_edge_map": True,
        }
    )
    return params


def _mcmc_defaults() -> dict:
    params = _base_defaults()
    params["strategy"] = "mcmc"
    return params


def _igs_plus_defaults() -> dict:
    params = _base_defaults()
    params.update(
        {
            "strategy": "igs+",
            "means_lr": 0.000016,
            "shs_lr": 0.005,
            "scaling_lr": 0.02,
            "rotation_lr": 0.0015,
            "refine_every": 500,
            "stop_refine": 15000,
            "opacity_reg": 0.0,
            "scale_reg": 0.0,
            "init_opacity": 0.1,
            "init_scaling": 0.1,
            "max_cap": 4000000,
            "tv_loss_weight": 5.0,
            "revised_opacity": True,
            "gut": False,
        }
    )
    return params


def lichtfeld_defaults(strategy: str) -> dict:
    normalized = strategy.lower().strip()
    if normalized == "mcmc":
        return _mcmc_defaults()
    if normalized == "igs+":
        return _igs_plus_defaults()
    return _mrnf_defaults()


def lichtfeld_auto_steps_scaler(image_count: int) -> float:
    if image_count <= 0:
        return 1.0
    if image_count <= _LICHTFELD_BASE_IMAGE_COUNT:
        return 1.0
    return image_count / _LICHTFELD_BASE_IMAGE_COUNT


def _round_lfs_step(value: float) -> int:
    return max(1, int(math.floor(value + 0.5)))


def _unscale_lfs_step(value: int, scaler: float) -> int:
    if scaler <= 0.0 or math.isclose(scaler, 1.0):
        return int(value)
    return _round_lfs_step(value / scaler)


def _unscale_lfs_steps(values: list[int], scaler: float) -> list[int]:
    if scaler <= 0.0 or math.isclose(scaler, 1.0):
        return [int(value) for value in values]
    return sorted({_unscale_lfs_step(int(value), scaler) for value in values if int(value) > 0})


@dataclass(frozen=True)
class TrainingDataset:
    dataset_root: Path
    images_dir: Path | None = None
    masks_dir: Path | None = None
    colmap_sparse_dir: Path | None = None
    transforms_json: Path | None = None
    pointcloud_ply: Path | None = None
    output_shape: str = ""


@dataclass(frozen=True)
class LichtFeldTrainingOptions:
    executable: str
    dataset: TrainingDataset
    output_dir: Path
    config_path: Path
    strategy: str
    iterations: int
    max_gaussians: int
    sh_degree: int
    steps_scaler: float
    output_name: str = ""
    image_count: int | None = None
    auto_steps_scaler: bool = False
    bilateral_grid: bool = False
    mask_mode: str = "none"
    depth_loss: bool = False
    depth_loss_mode: str = "adaptive-warped-l1"
    depth_loss_weight: float = 2.0
    sparsity: bool = False
    gut: bool = False
    undistort: bool = False
    mip_filter: bool = False
    ppisp: bool = False
    background_mode: str = "solid_color"
    background_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    background_image_path: str = ""
    dataset_resize_factor: str | None = None
    dataset_max_width: int | None = None
    dataset_use_cpu_cache: bool = True
    dataset_use_fs_cache: bool = True
    dataset_test_every: int | None = None
    config_overrides: dict[str, object] | None = None
    headless: bool = False
    no_splash: bool = True


@dataclass(frozen=True)
class PostshotTrainingOptions:
    executable: str
    dataset: TrainingDataset
    output_dir: Path
    project_name: str
    ksteps: int | None
    max_image_size: int
    use_imported_poses: bool = True
    profile: str = "Splat3"
    import_masks: bool = False
    mask_mode: str = "background"
    image_select: str = "all"
    num_train_images: int = 0
    pose_quality: int = 3
    gpu_index: int | None = None
    splat_density: float = 1.0
    max_num_splats: int = 3000
    anti_aliasing: bool | None = None
    max_sh_degree: int = 3
    create_sky_model: bool = False
    store_training_context: bool = False
    show_train_error: bool = False
    no_recenter_points: bool = False
    crop_box_default: bool = False
    crop_box_min: tuple[float, float, float] | None = None
    crop_box_max: tuple[float, float, float] | None = None
    roi_box_default: bool = False
    roi_box_min: tuple[float, float, float] | None = None
    roi_box_max: tuple[float, float, float] | None = None
    export_splat_path: Path | None = None


@dataclass(frozen=True)
class BrushTrainingOptions:
    executable: str
    dataset: TrainingDataset
    output_dir: Path
    export_name: str
    total_train_iters: int
    export_every: int
    max_resolution: int
    with_viewer: bool = False
    sh_degree: int = 3
    render_mode: str = "auto"
    refine_every: int = 200
    max_splats: int = 10_000_000
    eval_split_every: int | None = None
    alpha_mode: str = "auto"
    subsample_frames: int | None = None
    subsample_points: int | None = None


@dataclass(frozen=True)
class GsplatTrainingOptions:
    executable: str
    script_path: Path
    dataset: TrainingDataset
    result_dir: Path
    strategy: str
    max_steps: int
    data_factor: int = 1
    test_every: int = 8
    save_ply: bool = True
    disable_viewer: bool = True
    with_3dgut: bool = False


def build_lichtfeld_config(options: LichtFeldTrainingOptions) -> dict:
    strategy = options.strategy.lower().strip()
    if strategy not in _LICHTFELD_REQUIRED_STRATEGIES:
        raise ValueError(f"Unsupported LichtFeld strategy: {options.strategy}")
    if options.mask_mode not in _LICHTFELD_MASK_MODES:
        raise ValueError(f"Unsupported LichtFeld mask mode: {options.mask_mode}")
    if options.depth_loss_mode not in _LICHTFELD_DEPTH_LOSS_MODES:
        raise ValueError(f"Unsupported LichtFeld depth loss mode: {options.depth_loss_mode}")
    if not math.isfinite(options.depth_loss_weight) or options.depth_loss_weight < 0.0:
        raise ValueError("LichtFeld depth loss weight must be a finite value greater than or equal to 0")
    if strategy == "igs+" and options.gut:
        raise ValueError("LichtFeld igs+ strategy cannot be used with GUT")
    if options.iterations <= 0:
        raise ValueError("LichtFeld iterations must be greater than 0")
    if options.max_gaussians <= 0:
        raise ValueError("LichtFeld max Gaussians must be greater than 0")
    if options.sh_degree < 0 or options.sh_degree > 3:
        raise ValueError("LichtFeld SH degree must be 0, 1, 2, or 3")
    if options.steps_scaler <= 0:
        raise ValueError("LichtFeld steps scaler must be greater than 0")
    if options.background_mode not in _LICHTFELD_BG_MODES:
        raise ValueError(f"Unsupported LichtFeld background mode: {options.background_mode}")
    if len(options.background_color) != 3 or any(
        not math.isfinite(c) or c < 0.0 or c > 1.0 for c in options.background_color
    ):
        raise ValueError("LichtFeld background color must contain three values between 0 and 1")

    steps_scaler = (
        lichtfeld_auto_steps_scaler(options.image_count)
        if options.auto_steps_scaler and options.image_count is not None
        else float(options.steps_scaler)
    )
    config_iterations = _unscale_lfs_step(int(options.iterations), steps_scaler)
    config = lichtfeld_defaults(strategy)
    config_overrides = dict(options.config_overrides or {})
    for key in _LICHTFELD_STEP_KEYS:
        if key in config_overrides:
            config_overrides[key] = _unscale_lfs_step(int(config_overrides[key]), steps_scaler)
    for key in _LICHTFELD_STEP_LIST_KEYS:
        if key in config_overrides:
            config_overrides[key] = _unscale_lfs_steps(list(config_overrides[key]), steps_scaler)
    if config_overrides:
        config.update(config_overrides)
    config.update(
        {
            "strategy": strategy,
            "iterations": config_iterations,
            "max_cap": int(options.max_gaussians),
            "sh_degree": int(options.sh_degree),
            "steps_scaler": float(steps_scaler),
            "use_bilateral_grid": bool(options.bilateral_grid),
            "mask_mode": options.mask_mode,
            "use_depth_loss": bool(options.depth_loss),
            "depth_loss_mode": options.depth_loss_mode,
            "depth_loss_weight": float(options.depth_loss_weight),
            "enable_sparsity": bool(options.sparsity),
            "gut": bool(options.gut),
            "undistort": bool(options.undistort),
            "mip_filter": bool(options.mip_filter),
            "use_ppisp": bool(options.ppisp),
            "bg_mode": options.background_mode,
            "bg_color": [float(c) for c in options.background_color],
            "headless": bool(options.headless),
            "auto_train": True,
            "no_splash": bool(options.no_splash),
        }
    )
    if options.background_image_path:
        config["bg_image_path"] = options.background_image_path
    return config


def write_lichtfeld_config(options: LichtFeldTrainingOptions) -> Path:
    options.config_path.parent.mkdir(parents=True, exist_ok=True)
    options.config_path.write_text(
        json.dumps(build_lichtfeld_config(options), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return options.config_path


def lichtfeld_output_name_stem(value: str) -> str:
    name = value.strip()
    if not name:
        return ""
    if any(sep in name for sep in ("/", "\\")):
        raise ValueError("LichtFeld output PLY name must be a file name, not a path")
    if name.lower().endswith(".ply"):
        name = name[:-4].strip()
    if not name:
        raise ValueError("LichtFeld output PLY name must not be empty")
    return name


def build_lichtfeld_training_cmd(options: LichtFeldTrainingOptions) -> list[str]:
    output_name = lichtfeld_output_name_stem(options.output_name)
    write_lichtfeld_config(options)
    data_path = options.dataset.dataset_root
    if (
        options.dataset.transforms_json is not None
        and options.dataset.transforms_json.is_file()
        and options.dataset.transforms_json.name not in {"transforms.json", "transforms_train.json"}
    ):
        data_path = options.dataset.transforms_json
    cmd = [
        options.executable,
        "--data-path",
        str(data_path),
        "--output-path",
        str(options.output_dir),
        "--config",
        str(options.config_path),
        "--train",
        "--export",
        "ply",
    ]
    if output_name:
        cmd.extend(["--output-name", output_name])
    if options.dataset_resize_factor:
        cmd.extend(["--resize_factor", options.dataset_resize_factor])
    if options.dataset_max_width is not None:
        if options.dataset_max_width < 0 or options.dataset_max_width > 4096:
            raise ValueError("LichtFeld max width must be between 0 and 4096")
        cmd.extend(["--max-width", str(options.dataset_max_width)])
    if not options.dataset_use_cpu_cache:
        cmd.append("--no-cpu-cache")
    if not options.dataset_use_fs_cache:
        cmd.append("--no-fs-cache")
    if options.dataset_test_every is not None:
        if options.dataset_test_every <= 0:
            raise ValueError("LichtFeld test every must be greater than 0")
        cmd.extend(["--test-every", str(options.dataset_test_every)])
    if options.no_splash:
        cmd.append("--no-splash")
    if options.headless:
        cmd.append("--headless")
    return cmd


def build_postshot_training_cmd(options: PostshotTrainingOptions) -> list[str]:
    if options.profile not in _POSTSHOT_PROFILES:
        raise ValueError(f"Unsupported Postshot profile: {options.profile}")
    if options.ksteps is not None and options.ksteps <= 0:
        raise ValueError("Postshot kSteps must be greater than 0")
    if options.max_image_size < 0:
        raise ValueError("Postshot max image size must be 0 or greater")
    if options.mask_mode not in _POSTSHOT_MASK_MODES:
        raise ValueError(f"Unsupported Postshot mask mode: {options.mask_mode}")
    if options.image_select not in _POSTSHOT_IMAGE_SELECT_MODES:
        raise ValueError(f"Unsupported Postshot image selection: {options.image_select}")
    if options.num_train_images < 0:
        raise ValueError("Postshot selected image count must be 0 or greater")
    if not 1 <= options.pose_quality <= 4:
        raise ValueError("Postshot pose quality must be between 1 and 4")
    if options.gpu_index is not None and not 0 <= options.gpu_index <= 255:
        raise ValueError("Postshot GPU index must be between 0 and 255")
    if not 0.125 <= options.splat_density <= 8.0:
        raise ValueError("Postshot splat density must be between 0.125 and 8")
    if options.max_num_splats <= 0:
        raise ValueError("Postshot max splats must be greater than 0")
    if not 0 <= options.max_sh_degree <= 3:
        raise ValueError("Postshot max SH degree must be between 0 and 3")

    def validate_box(name: str, default: bool, minimum: tuple[float, float, float] | None, maximum: tuple[float, float, float] | None) -> None:
        if default and (minimum is not None or maximum is not None):
            raise ValueError(f"Postshot {name} cannot use default and custom bounds together")
        if (minimum is None) != (maximum is None):
            raise ValueError(f"Postshot {name} requires both min and max coordinates")

    output_file = options.output_dir / options.project_name
    validate_box("crop box", options.crop_box_default, options.crop_box_min, options.crop_box_max)
    validate_box("ROI box", options.roi_box_default, options.roi_box_min, options.roi_box_max)
    import_sources = [str(options.dataset.images_dir or options.dataset.dataset_root)]
    if options.use_imported_poses:
        if options.dataset.colmap_sparse_dir is not None:
            import_sources.extend(str(path) for path in _postshot_colmap_pose_sources(options.dataset.colmap_sparse_dir))
        else:
            if options.dataset.transforms_json is not None:
                import_sources.append(str(options.dataset.transforms_json))
            if options.dataset.pointcloud_ply is not None:
                import_sources.append(str(options.dataset.pointcloud_ply))
    cmd = [
        options.executable,
        "train",
        "--import",
        *import_sources,
    ]
    if options.import_masks:
        if options.dataset.masks_dir is None:
            raise ValueError("Postshot mask import requires a mask directory")
        cmd.extend(["--import-masks", str(options.dataset.masks_dir), "--mask-mode", options.mask_mode])
    cmd.extend(["--output", str(output_file)])
    if options.export_splat_path is not None:
        cmd.extend(["--export-splat", str(options.export_splat_path)])
    cmd.extend(["--profile", options.profile])
    if options.ksteps is not None:
        cmd.extend(["-s", str(options.ksteps)])
    cmd.extend(["--max-image-size", str(options.max_image_size)])
    cmd.extend(["--image-select", options.image_select])
    if options.image_select == "best" and options.num_train_images > 0:
        cmd.extend(["--num-train-images", str(options.num_train_images)])
    if not options.use_imported_poses:
        cmd.extend(["--pose-quality", str(options.pose_quality)])
    if options.gpu_index is not None:
        cmd.extend(["--gpu", str(options.gpu_index)])
    if options.no_recenter_points:
        cmd.append("--no-recenter-points")
    if options.profile == "Splat ADC":
        cmd.extend(["--splat-density", f"{options.splat_density:g}"])
    if options.profile == "Splat MCMC":
        cmd.extend(["--max-num-splats", str(options.max_num_splats)])
    if options.anti_aliasing is not None:
        cmd.extend(["--anti-aliasing", "true" if options.anti_aliasing else "false"])
    cmd.extend(["--max-sh-degree", str(options.max_sh_degree)])
    if options.create_sky_model:
        cmd.append("--create-sky-model")
    if options.store_training_context:
        cmd.append("--store-training-context")
    if options.show_train_error:
        cmd.append("--show-train-error")

    def add_box(prefix: str, default: bool, minimum: tuple[float, float, float] | None, maximum: tuple[float, float, float] | None) -> None:
        if default:
            cmd.append(f"--{prefix}-default")
        elif minimum is not None and maximum is not None:
            cmd.append(f"--{prefix}-min")
            cmd.extend(f"{value:g}" for value in minimum)
            cmd.append(f"--{prefix}-max")
            cmd.extend(f"{value:g}" for value in maximum)

    add_box("crop-box", options.crop_box_default, options.crop_box_min, options.crop_box_max)
    add_box("roi-box", options.roi_box_default, options.roi_box_min, options.roi_box_max)
    return cmd


def brush_export_filename(export_name: str, total_train_iters: int) -> str:
    name = export_name.strip()
    if any(sep in name for sep in ("/", "\\")):
        raise ValueError("Brush export name must be a file name, not a path")
    if not name:
        raise ValueError("Brush export name must not be empty")
    if not name.lower().endswith(".ply"):
        name = f"{name}.ply"
    if "{iter}" in name:
        if total_train_iters <= 0:
            raise ValueError("Brush training iterations must be greater than 0")
        digits = int(math.floor(math.log10(total_train_iters))) + 1 if total_train_iters > 0 else 1
        name = name.replace("{iter}", f"{total_train_iters:0{digits}d}")
    return name


def build_brush_training_cmd(options: BrushTrainingOptions) -> list[str]:
    if options.total_train_iters <= 0:
        raise ValueError("Brush training iterations must be greater than 0")
    if options.export_every <= 0:
        raise ValueError("Brush export interval must be greater than 0")
    if options.max_resolution <= 0:
        raise ValueError("Brush max resolution must be greater than 0")
    if options.sh_degree < 0 or options.sh_degree > 3:
        raise ValueError("Brush SH degree must be between 0 and 3")
    if options.refine_every <= 0:
        raise ValueError("Brush refine interval must be greater than 0")
    if options.max_splats <= 0:
        raise ValueError("Brush max splats must be greater than 0")
    if options.render_mode not in _BRUSH_RENDER_MODES:
        raise ValueError(f"Unsupported Brush render mode: {options.render_mode}")
    if options.alpha_mode not in _BRUSH_ALPHA_MODES:
        raise ValueError(f"Unsupported Brush alpha mode: {options.alpha_mode}")
    if options.eval_split_every is not None and options.eval_split_every <= 0:
        raise ValueError("Brush eval split interval must be greater than 0")
    if options.subsample_frames is not None and options.subsample_frames <= 0:
        raise ValueError("Brush frame subsampling interval must be greater than 0")
    if options.subsample_points is not None and options.subsample_points <= 0:
        raise ValueError("Brush point subsampling interval must be greater than 0")

    export_name = options.export_name.strip()
    brush_export_filename(export_name, options.total_train_iters)
    if not export_name.lower().endswith(".ply"):
        export_name = f"{export_name}.ply"
    cmd = [
        options.executable,
        str(options.dataset.dataset_root),
        "--total-train-iters",
        str(options.total_train_iters),
        "--export-every",
        str(options.export_every),
        "--export-path",
        str(options.output_dir),
        "--export-name",
        export_name,
        "--max-resolution",
        str(options.max_resolution),
        "--sh-degree",
        str(options.sh_degree),
        "--refine-every",
        str(options.refine_every),
        "--max-splats",
        str(options.max_splats),
    ]
    if options.with_viewer:
        cmd.append("--with-viewer")
    if options.render_mode != "auto":
        cmd.extend(["--render-mode", options.render_mode])
    if options.eval_split_every is not None:
        cmd.extend(["--eval-split-every", str(options.eval_split_every)])
    if options.alpha_mode != "auto":
        cmd.extend(["--alpha-mode", options.alpha_mode])
    if options.subsample_frames is not None:
        cmd.extend(["--subsample-frames", str(options.subsample_frames)])
    if options.subsample_points is not None:
        cmd.extend(["--subsample-points", str(options.subsample_points)])
    return cmd


def build_gsplat_training_cmd(options: GsplatTrainingOptions) -> list[str]:
    if options.strategy not in _GSPLAT_STRATEGIES:
        raise ValueError(f"Unsupported gsplat strategy: {options.strategy}")
    if options.with_3dgut and options.strategy != "mcmc":
        raise ValueError("gsplat 3DGUT mode requires the mcmc strategy")
    if options.max_steps <= 0:
        raise ValueError("gsplat max steps must be greater than 0")
    if options.data_factor <= 0:
        raise ValueError("gsplat data factor must be greater than 0")
    if options.test_every <= 0:
        raise ValueError("gsplat test interval must be greater than 0")
    cmd = [
        options.executable,
        str(options.script_path),
        options.strategy,
        "--data_dir",
        str(options.dataset.dataset_root),
        "--result_dir",
        str(options.result_dir),
        "--max_steps",
        str(options.max_steps),
        "--data_factor",
        str(options.data_factor),
        "--test_every",
        str(options.test_every),
    ]
    if options.disable_viewer:
        cmd.append("--disable_viewer")
    if options.save_ply:
        cmd.append("--save_ply")
    if options.with_3dgut:
        cmd.extend(["--with_ut", "--with_eval3d"])
    return cmd


def _postshot_colmap_pose_sources(sparse_dir: Path) -> tuple[Path, ...]:
    text_files = (
        sparse_dir / "cameras.txt",
        sparse_dir / "images.txt",
        sparse_dir / "points3D.txt",
    )
    if all(path.is_file() for path in text_files):
        return text_files
    binary_files = (
        sparse_dir / "cameras.bin",
        sparse_dir / "images.bin",
        sparse_dir / "points3D.bin",
    )
    if all(path.is_file() for path in binary_files):
        return binary_files
    return (sparse_dir,)
