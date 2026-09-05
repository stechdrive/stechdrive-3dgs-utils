"""CLI adapter for COLMAP spherical SfM GPU SIFT preflight."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import core.spheresfm_gpu_preflight as preflight
from core.colmap_cli import build_colmap_command


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check COLMAP spherical SfM CLI support and GPU SIFT on one image.")
    parser.add_argument("--colmap", required=True, help="COLMAP 4.1+ executable or Windows COLMAP.bat launcher")
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--camera-params", required=True)
    parser.add_argument("--matcher", choices=("sequential",), default="sequential")
    parser.add_argument("--quality-preset", choices=("standard", "light", "lightest"), default="standard")
    parser.add_argument("--loop-detection", action="store_true")
    parser.add_argument("--use-masks", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.images_dir.is_dir():
        raise FileNotFoundError(f"Images folder not found: {args.images_dir}")
    images = preflight.iter_images(args.images_dir)
    if not images:
        raise FileNotFoundError(f"No supported images found: {args.images_dir}")

    preflight.validate_spheresfm_colmap(
        args.colmap,
        matcher=args.matcher,
        quality_preset=args.quality_preset,
        use_masks=args.use_masks,
        loop_detection=args.loop_detection,
    )

    preflight_images = preflight.reset_preflight_workspace(args.work_dir)
    source = images[0]
    target = preflight_images / f"preflight_000001{source.suffix.lower()}"
    shutil.copy2(source, target)
    print(f"COLMAP spherical GPU preflight image: {source}", flush=True)

    database = args.work_dir / "database.db"
    preflight.run_colmap_command(
        build_colmap_command(
            args.colmap,
            "database_creator",
            "--database_path",
            str(database),
        ),
        "COLMAP spherical preflight database_creator",
    )
    preflight.run_colmap_command(
        preflight.build_feature_command(args.colmap, database, preflight_images, args.camera_params),
        "COLMAP spherical preflight feature_extractor",
    )
    print("COLMAP spherical GPU preflight passed.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
