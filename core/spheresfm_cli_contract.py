"""Command-line option contract for native COLMAP equirectangular SfM."""

from __future__ import annotations

SPHERESFM_MATCHERS = {"sequential", "exhaustive", "spatial"}
SPHERESFM_QUALITY_PRESETS = {"fast", "standard", "quality", "robust"}


def _validated_preset(preset: str) -> str:
    value = str(preset).strip().lower()
    if value not in SPHERESFM_QUALITY_PRESETS:
        raise ValueError(f"Unsupported spherical SfM quality preset: {preset}")
    return value


def spheresfm_matcher_subcommand(matcher: str) -> str:
    value = str(matcher).strip().lower()
    if value not in SPHERESFM_MATCHERS:
        raise ValueError(f"Unsupported spherical SfM matcher: {matcher}")
    if value == "spatial":
        return "spatial_matcher"
    if value == "exhaustive":
        return "exhaustive_matcher"
    return "sequential_matcher"


def spheresfm_feature_options(preset: str) -> list[str]:
    value = _validated_preset(preset)
    if value == "fast":
        max_image_size = "3200"
        max_num_features = "8192"
    elif value in {"quality", "robust"}:
        max_image_size = "5000"
        max_num_features = "32768"
    else:
        max_image_size = "4096"
        max_num_features = "16384"
    return [
        "--FeatureExtraction.use_gpu",
        "1",
        "--FeatureExtraction.max_image_size",
        max_image_size,
        "--SiftExtraction.max_num_features",
        max_num_features,
    ]


def spheresfm_matching_options(preset: str) -> list[str]:
    value = _validated_preset(preset)
    max_num_matches = "16384" if value == "fast" else "32768"
    options = [
        "--TwoViewGeometry.max_error",
        "4",
        "--TwoViewGeometry.min_num_inliers",
        "50",
        "--FeatureMatching.max_num_matches",
        max_num_matches,
    ]
    if value in {"quality", "robust"}:
        options.extend(["--FeatureMatching.guided_matching", "1"])
    return options


def spheresfm_sequential_overlap(preset: str) -> str:
    value = _validated_preset(preset)
    if value == "fast":
        return "5"
    if value in {"quality", "robust"}:
        return "15"
    return "10"


def spheresfm_mapper_options(preset: str) -> list[str]:
    value = _validated_preset(preset)
    options = [
        "--Mapper.ba_refine_focal_length",
        "0",
        "--Mapper.ba_refine_principal_point",
        "0",
        "--Mapper.ba_refine_extra_params",
        "0",
        "--Mapper.multiple_models",
        "0",
    ]
    if value == "fast":
        options.extend(
            [
                "--Mapper.ba_local_max_num_iterations",
                "12",
                "--Mapper.ba_global_max_num_iterations",
                "25",
                "--Mapper.ba_local_max_refinements",
                "1",
                "--Mapper.ba_global_max_refinements",
                "2",
                "--Mapper.ba_global_frames_ratio",
                "1.3",
                "--Mapper.ba_global_points_ratio",
                "1.3",
            ]
        )
    elif value in {"quality", "robust"}:
        options.extend(
            [
                "--Mapper.ba_local_max_num_iterations",
                "30",
                "--Mapper.ba_global_max_num_iterations",
                "75",
                "--Mapper.ba_local_max_refinements",
                "3",
                "--Mapper.ba_global_max_refinements",
                "5",
            ]
        )
    else:
        options.extend(
            [
                "--Mapper.ba_local_max_num_iterations",
                "16",
                "--Mapper.ba_global_max_num_iterations",
                "33",
                "--Mapper.ba_local_max_refinements",
                "2",
                "--Mapper.ba_global_max_refinements",
                "2",
                "--Mapper.ba_global_frames_ratio",
                "1.2",
                "--Mapper.ba_global_points_ratio",
                "1.2",
            ]
        )
    return options


def _option_names(arguments: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(argument for argument in arguments if argument.startswith("--")))


def required_spheresfm_options(
    *,
    matcher: str,
    quality_preset: str,
    use_masks: bool,
) -> dict[str, tuple[str, ...]]:
    """Return exact CLI options used by the selected spherical SfM route."""

    matcher_value = str(matcher).strip().lower()
    matcher_command = spheresfm_matcher_subcommand(matcher_value)
    feature_arguments = [
        "--database_path",
        "--image_path",
        "--ImageReader.camera_model",
        "--ImageReader.camera_params",
        "--ImageReader.single_camera",
    ]
    if use_masks:
        feature_arguments.append("--ImageReader.mask_path")
    feature_arguments.extend(spheresfm_feature_options(quality_preset))

    matcher_arguments = ["--database_path", *spheresfm_matching_options(quality_preset)]
    if matcher_value == "spatial":
        matcher_arguments.append("--SpatialMatching.max_distance")
    elif matcher_value == "sequential":
        matcher_arguments.extend(["--SequentialMatching.overlap", spheresfm_sequential_overlap(quality_preset)])

    mapper_arguments = [
        "--database_path",
        "--image_path",
        "--output_path",
        *spheresfm_mapper_options(quality_preset),
    ]
    return {
        "feature_extractor": _option_names(feature_arguments),
        matcher_command: _option_names(matcher_arguments),
        "mapper": _option_names(mapper_arguments),
    }
