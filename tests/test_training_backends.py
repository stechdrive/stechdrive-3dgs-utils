import json
from pathlib import Path

import pytest

from gui.steps.training_backend_specs import (
    DEFAULT_TRAINING_BACKEND,
    OTHER_TRAINING_BACKEND_IDS,
    PRIMARY_TRAINING_BACKEND_IDS,
    TRAINING_BACKEND_BRUSH,
    TRAINING_BACKEND_GSPLAT,
    TRAINING_BACKEND_LICHTFELD,
    TRAINING_BACKEND_POSTSHOT,
    get_training_backend_spec,
    normalize_training_backend,
    training_backend_default_executable,
    training_backend_specs,
)
from gui.steps.training_backends import (
    BrushTrainingOptions,
    GsplatTrainingOptions,
    LichtFeldTrainingOptions,
    PostshotTrainingOptions,
    TrainingDataset,
    brush_export_filename,
    build_brush_training_cmd,
    build_gsplat_training_cmd,
    build_lichtfeld_config,
    build_lichtfeld_training_cmd,
    build_postshot_training_cmd,
    lichtfeld_auto_steps_scaler,
    lichtfeld_defaults,
)


def test_training_backend_specs_define_ui_order_and_command_metadata() -> None:
    primary_ids = tuple(spec.backend_id for spec in training_backend_specs(category="primary"))
    other_ids = tuple(spec.backend_id for spec in training_backend_specs(category="other"))
    visible_primary_ids = tuple(spec.backend_id for spec in training_backend_specs(category="primary", visible_only=True))
    visible_other_ids = tuple(spec.backend_id for spec in training_backend_specs(category="other", visible_only=True))

    assert DEFAULT_TRAINING_BACKEND == TRAINING_BACKEND_LICHTFELD
    assert primary_ids == (
        TRAINING_BACKEND_LICHTFELD,
        TRAINING_BACKEND_POSTSHOT,
        TRAINING_BACKEND_BRUSH,
        TRAINING_BACKEND_GSPLAT,
    )
    assert other_ids == ()
    assert visible_primary_ids == primary_ids
    assert visible_other_ids == ()
    assert PRIMARY_TRAINING_BACKEND_IDS == primary_ids
    assert OTHER_TRAINING_BACKEND_IDS == other_ids

    ordered_specs = training_backend_specs()
    assert [spec.stack_order for spec in ordered_specs] == [0, 1, 2, 3]
    assert get_training_backend_spec(TRAINING_BACKEND_LICHTFELD).supports_headless is True
    assert get_training_backend_spec(TRAINING_BACKEND_POSTSHOT).supports_headless is False
    assert get_training_backend_spec(TRAINING_BACKEND_BRUSH).supports_headless is False
    assert get_training_backend_spec(TRAINING_BACKEND_GSPLAT).supports_headless is False
    assert get_training_backend_spec(TRAINING_BACKEND_LICHTFELD).official_url == "https://lichtfeld.io/"
    assert get_training_backend_spec(TRAINING_BACKEND_POSTSHOT).official_url == "https://www.jawset.com/"
    assert get_training_backend_spec(TRAINING_BACKEND_BRUSH).official_url == "https://github.com/ArthurBrussee/brush"
    assert (
        get_training_backend_spec(TRAINING_BACKEND_GSPLAT).official_url
        == "https://github.com/nerfstudio-project/gsplat"
    )
    assert get_training_backend_spec(TRAINING_BACKEND_BRUSH).official_link_key == "TRAINING_LINK_BRUSH"
    assert (
        training_backend_default_executable(
            TRAINING_BACKEND_LICHTFELD,
            windows=True,
        )
        == "LichtFeld-Studio.exe"
    )
    assert (
        training_backend_default_executable(
            TRAINING_BACKEND_POSTSHOT,
            windows=False,
        )
        == "postshot-cli"
    )
    assert training_backend_default_executable(TRAINING_BACKEND_BRUSH, windows=True) == "brush.exe"
    assert training_backend_default_executable(TRAINING_BACKEND_GSPLAT, windows=False) == "python"
    assert normalize_training_backend("POSTSHOT") == TRAINING_BACKEND_POSTSHOT
    assert normalize_training_backend("Brush") == TRAINING_BACKEND_BRUSH
    assert normalize_training_backend("GSPLAT") == TRAINING_BACKEND_GSPLAT
    assert normalize_training_backend("custom") == DEFAULT_TRAINING_BACKEND
    assert normalize_training_backend("missing") == DEFAULT_TRAINING_BACKEND


def test_lichtfeld_config_overrides_visible_training_parameters(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "output")
    options = LichtFeldTrainingOptions(
        executable="LichtFeld-Studio.exe",
        dataset=dataset,
        output_dir=tmp_path / "training",
        config_path=tmp_path / "config.json",
        strategy="mrnf",
        iterations=46800,
        max_gaussians=5_000_000,
        sh_degree=2,
        steps_scaler=1.56,
        bilateral_grid=True,
        mask_mode="segment_and_ignore",
        depth_loss=True,
        depth_loss_mode="pearson",
        depth_loss_weight=3.5,
        sparsity=True,
        gut=True,
        undistort=True,
        mip_filter=True,
        ppisp=True,
        background_mode="modulation",
        background_color=(0.25, 0.5, 0.75),
        config_overrides={
            "means_lr": 0.000123,
            "enable_eval": True,
            "save_steps": [5000, 30000],
        },
        headless=True,
    )

    config = build_lichtfeld_config(options)

    assert config["strategy"] == "mrnf"
    assert config["iterations"] == 30000
    assert config["max_cap"] == 5_000_000
    assert config["sh_degree"] == 2
    assert "tile_mode" not in config
    assert config["steps_scaler"] == pytest.approx(1.56)
    assert config["use_bilateral_grid"] is True
    assert config["mask_mode"] == "segment_and_ignore"
    assert config["use_depth_loss"] is True
    assert config["depth_loss_mode"] == "pearson"
    assert config["depth_loss_weight"] == pytest.approx(3.5)
    assert config["enable_sparsity"] is True
    assert config["gut"] is True
    assert config["undistort"] is True
    assert config["mip_filter"] is True
    assert config["use_ppisp"] is True
    assert config["bg_mode"] == "modulation"
    assert config["bg_color"] == [0.25, 0.5, 0.75]
    assert config["means_lr"] == pytest.approx(0.000123)
    assert config["enable_eval"] is True
    assert config["save_steps"] == [3205, 19231]
    assert config["headless"] is True
    assert config["auto_train"] is True
    assert config["eval_steps"] == [7000, 30000]

    cmd = build_lichtfeld_training_cmd(options)

    assert cmd == [
        "LichtFeld-Studio.exe",
        "--data-path",
        str(dataset.dataset_root),
        "--output-path",
        str(options.output_dir),
        "--config",
        str(options.config_path),
        "--train",
        "--export",
        "ply",
        "--no-splash",
        "--headless",
    ]
    assert json.loads(options.config_path.read_text(encoding="utf-8"))["iterations"] == 30000


def test_lichtfeld_strategy_defaults_match_upstream_presets() -> None:
    mrnf = lichtfeld_defaults("mrnf")
    mcmc = lichtfeld_defaults("mcmc")
    igs = lichtfeld_defaults("igs+")

    assert mrnf["strategy"] == "mrnf"
    assert mrnf["max_cap"] == 5_000_000
    assert mrnf["means_lr"] == pytest.approx(0.00002)
    assert mrnf["means_lr_end"] == pytest.approx(0.0000002)
    assert mrnf["shs_lr"] == pytest.approx(0.002)
    assert mrnf["opacity_lr"] == pytest.approx(0.012)
    assert mrnf["scaling_lr"] == pytest.approx(0.007)
    assert mrnf["rotation_lr"] == pytest.approx(0.002)
    assert mrnf["refine_every"] == 200
    assert mrnf["start_refine"] == 0
    assert mrnf["stop_refine"] == 28_500
    assert mrnf["min_opacity"] == pytest.approx(1.0 / 255.0)
    assert mrnf["grad_threshold"] == pytest.approx(0.003)
    assert mrnf["opacity_reg"] == pytest.approx(0.0)
    assert mrnf["scale_reg"] == pytest.approx(0.0)
    assert mrnf["revised_opacity"] is True

    assert mcmc["strategy"] == "mcmc"
    assert mcmc["max_cap"] == 1_000_000
    assert mcmc["means_lr"] == pytest.approx(0.000016)
    assert mcmc["means_lr_end"] == pytest.approx(0.00000016)
    assert mcmc["shs_lr"] == pytest.approx(0.0025)
    assert mcmc["opacity_lr"] == pytest.approx(0.025)
    assert mcmc["scaling_lr"] == pytest.approx(0.005)
    assert mcmc["rotation_lr"] == pytest.approx(0.001)
    assert mcmc["refine_every"] == 100
    assert mcmc["start_refine"] == 500
    assert mcmc["stop_refine"] == 25_000
    assert mcmc["min_opacity"] == pytest.approx(0.005)
    assert mcmc["grad_threshold"] == pytest.approx(0.0002)
    assert mcmc["opacity_reg"] == pytest.approx(0.01)
    assert mcmc["scale_reg"] == pytest.approx(0.01)
    assert mcmc["revised_opacity"] is False

    assert igs["strategy"] == "igs+"
    assert igs["max_cap"] == 4_000_000
    assert igs["means_lr"] == pytest.approx(0.000016)
    assert igs["means_lr_end"] == pytest.approx(0.00000016)
    assert igs["shs_lr"] == pytest.approx(0.005)
    assert igs["opacity_lr"] == pytest.approx(0.025)
    assert igs["scaling_lr"] == pytest.approx(0.02)
    assert igs["rotation_lr"] == pytest.approx(0.0015)
    assert igs["refine_every"] == 500
    assert igs["start_refine"] == 500
    assert igs["stop_refine"] == 15_000
    assert igs["min_opacity"] == pytest.approx(0.005)
    assert igs["grad_threshold"] == pytest.approx(0.0002)
    assert igs["opacity_reg"] == pytest.approx(0.0)
    assert igs["scale_reg"] == pytest.approx(0.0)
    assert igs["init_opacity"] == pytest.approx(0.1)
    assert igs["init_scaling"] == pytest.approx(0.1)
    assert igs["tv_loss_weight"] == pytest.approx(5.0)
    assert igs["revised_opacity"] is True


def test_lichtfeld_auto_steps_scaler_matches_image_count(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "output")
    options = LichtFeldTrainingOptions(
        executable="LichtFeld-Studio.exe",
        dataset=dataset,
        output_dir=tmp_path / "training",
        config_path=tmp_path / "config.json",
        strategy="mrnf",
        iterations=46800,
        max_gaussians=5_000_000,
        sh_degree=3,
        steps_scaler=9.99,
        image_count=468,
        auto_steps_scaler=True,
    )

    config = build_lichtfeld_config(options)

    assert lichtfeld_auto_steps_scaler(300) == pytest.approx(1.0)
    assert lichtfeld_auto_steps_scaler(468) == pytest.approx(1.56)
    assert config["steps_scaler"] == pytest.approx(1.56)
    assert config["iterations"] == 30000


def test_lichtfeld_command_includes_dataset_cli_overrides(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "output")
    options = LichtFeldTrainingOptions(
        executable="LichtFeld-Studio.exe",
        dataset=dataset,
        output_dir=tmp_path / "training",
        config_path=tmp_path / "config.json",
        strategy="mrnf",
        iterations=30000,
        max_gaussians=5_000_000,
        sh_degree=3,
        steps_scaler=1.0,
        output_name="scene_final.ply",
        dataset_resize_factor="2",
        dataset_max_width=0,
        dataset_use_cpu_cache=False,
        dataset_use_fs_cache=False,
        dataset_test_every=12,
    )

    cmd = build_lichtfeld_training_cmd(options)

    assert cmd[cmd.index("--export") + 1] == "ply"
    assert cmd[cmd.index("--output-name") + 1] == "scene_final"
    assert cmd[cmd.index("--resize_factor") + 1] == "2"
    assert cmd[cmd.index("--max-width") + 1] == "0"
    assert "--no-cpu-cache" in cmd
    assert "--no-fs-cache" in cmd
    assert cmd[cmd.index("--test-every") + 1] == "12"


def test_lichtfeld_output_name_rejects_paths(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "output")
    options = LichtFeldTrainingOptions(
        executable="LichtFeld-Studio.exe",
        dataset=dataset,
        output_dir=tmp_path / "training",
        config_path=tmp_path / "config.json",
        strategy="mrnf",
        iterations=30000,
        max_gaussians=5_000_000,
        sh_degree=3,
        steps_scaler=1.0,
        output_name="nested/final",
    )

    with pytest.raises(ValueError, match="file name"):
        build_lichtfeld_training_cmd(options)


def test_postshot_command_passes_images_sparse_and_project_file(tmp_path: Path) -> None:
    sparse = tmp_path / "dataset" / "sparse" / "0"
    sparse.mkdir(parents=True)
    for name in ("cameras.txt", "images.txt", "points3D.txt"):
        (sparse / name).write_text("", encoding="utf-8")
    (sparse / "points3D.ply").write_text("ply\n", encoding="ascii")
    dataset = TrainingDataset(
        dataset_root=tmp_path / "dataset",
        images_dir=tmp_path / "dataset" / "images",
        colmap_sparse_dir=sparse,
    )

    cmd = build_postshot_training_cmd(
        PostshotTrainingOptions(
            executable="postshot-cli.exe",
            dataset=dataset,
            output_dir=tmp_path / "training",
            project_name="scene.psht",
            ksteps=60,
            max_image_size=4096,
        )
    )

    assert cmd == [
        "postshot-cli.exe",
        "train",
        "--import",
        str(dataset.images_dir),
        str(sparse / "cameras.txt"),
        str(sparse / "images.txt"),
        str(sparse / "points3D.txt"),
        "--output",
        str(tmp_path / "training" / "scene.psht"),
        "--profile",
        "Splat3",
        "-s",
        "60",
        "--max-image-size",
        "4096",
        "--image-select",
        "all",
        "--max-sh-degree",
        "3",
    ]


def test_postshot_command_passes_masks_profile_and_advanced_options(tmp_path: Path) -> None:
    dataset = TrainingDataset(
        dataset_root=tmp_path / "dataset",
        images_dir=tmp_path / "dataset" / "images",
        masks_dir=tmp_path / "dataset" / "masks",
    )

    cmd = build_postshot_training_cmd(
        PostshotTrainingOptions(
            executable="postshot-cli.exe",
            dataset=dataset,
            output_dir=tmp_path / "training",
            project_name="scene.psht",
            ksteps=None,
            max_image_size=3840,
            profile="Splat MCMC",
            use_imported_poses=False,
            import_masks=True,
            mask_mode="background",
            image_select="best",
            num_train_images=180,
            pose_quality=4,
            gpu_index=1,
            max_num_splats=4500,
            anti_aliasing=False,
            max_sh_degree=2,
            create_sky_model=True,
            store_training_context=True,
            show_train_error=True,
            no_recenter_points=True,
            crop_box_min=(-1.0, -2.0, -3.0),
            crop_box_max=(1.0, 2.0, 3.0),
            roi_box_default=True,
            export_splat_path=tmp_path / "training" / "scene.spz",
        )
    )

    assert cmd == [
        "postshot-cli.exe",
        "train",
        "--import",
        str(dataset.images_dir),
        "--import-masks",
        str(dataset.masks_dir),
        "--mask-mode",
        "background",
        "--output",
        str(tmp_path / "training" / "scene.psht"),
        "--export-splat",
        str(tmp_path / "training" / "scene.spz"),
        "--profile",
        "Splat MCMC",
        "--max-image-size",
        "3840",
        "--image-select",
        "best",
        "--num-train-images",
        "180",
        "--pose-quality",
        "4",
        "--gpu",
        "1",
        "--no-recenter-points",
        "--max-num-splats",
        "4500",
        "--anti-aliasing",
        "false",
        "--max-sh-degree",
        "2",
        "--create-sky-model",
        "--store-training-context",
        "--show-train-error",
        "--crop-box-min",
        "-1",
        "-2",
        "-3",
        "--crop-box-max",
        "1",
        "2",
        "3",
        "--roi-box-default",
    ]


def test_postshot_command_imports_transforms_and_pointcloud_for_imported_poses(tmp_path: Path) -> None:
    dataset = TrainingDataset(
        dataset_root=tmp_path / "dataset",
        images_dir=tmp_path / "dataset" / "images",
        transforms_json=tmp_path / "dataset" / "transforms.json",
        pointcloud_ply=tmp_path / "source" / "metashape.ply",
    )

    cmd = build_postshot_training_cmd(
        PostshotTrainingOptions(
            executable="postshot-cli.exe",
            dataset=dataset,
            output_dir=tmp_path / "training",
            project_name="scene.psht",
            ksteps=None,
            max_image_size=3840,
        )
    )

    assert cmd[:7] == [
        "postshot-cli.exe",
        "train",
        "--import",
        str(dataset.images_dir),
        str(dataset.transforms_json),
        str(dataset.pointcloud_ply),
        "--output",
    ]
    assert "--pose-quality" not in cmd


def test_brush_command_passes_cli_training_profile(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "dataset")

    cmd = build_brush_training_cmd(
        BrushTrainingOptions(
            executable="brush.exe",
            dataset=dataset,
            output_dir=tmp_path / "training",
            export_name="scene_{iter}.ply",
            total_train_iters=30000,
            export_every=2500,
            max_resolution=2048,
            with_viewer=True,
            sh_degree=2,
            render_mode="mip",
            refine_every=150,
            max_splats=4_000_000,
            eval_split_every=8,
            alpha_mode="masked",
            subsample_frames=2,
            subsample_points=3,
        )
    )

    assert brush_export_filename("scene_{iter}.ply", 30000) == "scene_30000.ply"
    assert cmd == [
        "brush.exe",
        str(dataset.dataset_root),
        "--total-train-iters",
        "30000",
        "--export-every",
        "2500",
        "--export-path",
        str(tmp_path / "training"),
        "--export-name",
        "scene_{iter}.ply",
        "--max-resolution",
        "2048",
        "--sh-degree",
        "2",
        "--refine-every",
        "150",
        "--max-splats",
        "4000000",
        "--with-viewer",
        "--render-mode",
        "mip",
        "--eval-split-every",
        "8",
        "--alpha-mode",
        "masked",
        "--subsample-frames",
        "2",
        "--subsample-points",
        "3",
    ]


def test_gsplat_command_passes_simple_trainer_options(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "dataset")
    script = tmp_path / "gsplat" / "examples" / "simple_trainer.py"

    cmd = build_gsplat_training_cmd(
        GsplatTrainingOptions(
            executable="python.exe",
            script_path=script,
            dataset=dataset,
            result_dir=tmp_path / "training" / "scene_gsplat",
            strategy="mcmc",
            max_steps=1200,
            data_factor=2,
            test_every=4,
            save_ply=True,
            disable_viewer=True,
            with_3dgut=True,
        )
    )

    assert cmd == [
        "python.exe",
        str(script),
        "mcmc",
        "--data_dir",
        str(dataset.dataset_root),
        "--result_dir",
        str(tmp_path / "training" / "scene_gsplat"),
        "--max_steps",
        "1200",
        "--data_factor",
        "2",
        "--test_every",
        "4",
        "--disable_viewer",
        "--save_ply",
        "--with_ut",
        "--with_eval3d",
    ]


def test_gsplat_3dgut_requires_mcmc(tmp_path: Path) -> None:
    dataset = TrainingDataset(dataset_root=tmp_path / "dataset")

    with pytest.raises(ValueError, match="mcmc"):
        build_gsplat_training_cmd(
            GsplatTrainingOptions(
                executable="python.exe",
                script_path=tmp_path / "simple_trainer.py",
                dataset=dataset,
                result_dir=tmp_path / "training",
                strategy="default",
                max_steps=100,
                with_3dgut=True,
            )
        )
