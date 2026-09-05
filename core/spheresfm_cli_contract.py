"""Shared extraction budgets and CLI contract for native ERP video SfM."""

from __future__ import annotations

# Legacy values remain readable in saved jobs, but all ERP jobs use sequential
# matching and the common incremental mapper baseline.
SPHERESFM_MATCHERS = {"sequential", "exhaustive", "spatial"}
SPHERESFM_QUALITY_PRESETS = {"standard", "light", "lightest", "fast", "quality", "robust"}
_BUDGETS = {"standard": (1, 32768), "light": (2, 16384), "lightest": (4, 8192)}


def normalize_spheresfm_preset(preset: str) -> str:
    value = str(preset).strip().lower()
    value = {"fast": "lightest", "quality": "standard", "robust": "standard"}.get(value, value)
    if value not in _BUDGETS:
        raise ValueError(f"Unsupported spherical SfM quality preset: {preset}")
    return value


def spheresfm_matcher_subcommand(matcher: str) -> str:
    if str(matcher).strip().lower() not in SPHERESFM_MATCHERS:
        raise ValueError(f"Unsupported spherical SfM matcher: {matcher}")
    return "sequential_matcher"


def spheresfm_feature_options(preset: str, input_size: tuple[int, int]) -> list[str]:
    divisor, features = _BUDGETS[normalize_spheresfm_preset(preset)]
    if len(input_size) != 2 or any(not isinstance(size, int) or size <= 0 for size in input_size):
        raise ValueError("Spherical SfM input dimensions must be positive integers")
    return [
        "--FeatureExtraction.use_gpu", "1",
        "--FeatureExtraction.max_image_size", str(max(1, max(input_size) // divisor)),
        "--SiftExtraction.max_num_features", str(features),
    ]


def spheresfm_matching_options(preset: str) -> list[str]:
    _, features = _BUDGETS[normalize_spheresfm_preset(preset)]
    return [
        "--FeatureMatching.max_num_matches", str(features),
        "--FeatureMatching.guided_matching", "0",
    ]


def spheresfm_sequential_options(loop_detection: bool = False) -> list[str]:
    return [
        "--SequentialMatching.overlap", "10",
        "--SequentialMatching.loop_detection", "1" if loop_detection else "0",
    ]


def spheresfm_mapper_options(preset: str) -> list[str]:
    normalize_spheresfm_preset(preset)
    return [
        "--Mapper.ba_refine_focal_length", "0",
        "--Mapper.ba_refine_principal_point", "0",
        "--Mapper.ba_refine_extra_params", "0",
        "--Mapper.multiple_models", "0",
    ]


def _option_names(arguments: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(argument for argument in arguments if argument.startswith("--")))


def required_spheresfm_options(
    *, matcher: str, quality_preset: str, use_masks: bool, loop_detection: bool = False,
) -> dict[str, tuple[str, ...]]:
    """Return the exact option names used by execution, without reading images."""
    feature_arguments = [
        "--database_path", "--image_path", "--ImageReader.camera_model",
        "--ImageReader.camera_params", "--ImageReader.single_camera",
    ]
    if use_masks:
        feature_arguments.append("--ImageReader.mask_path")
    feature_arguments.extend(spheresfm_feature_options(quality_preset, (1, 1)))
    return {
        "feature_extractor": _option_names(feature_arguments),
        spheresfm_matcher_subcommand(matcher): _option_names([
            "--database_path", *spheresfm_matching_options(quality_preset),
            *spheresfm_sequential_options(loop_detection),
        ]),
        "mapper": _option_names([
            "--database_path", "--image_path", "--output_path",
            *spheresfm_mapper_options(quality_preset),
        ]),
    }
