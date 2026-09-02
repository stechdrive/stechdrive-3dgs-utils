"""CLI adapter for COLMAP spherical SfM project preparation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from core.spheresfm_project import iter_images, prepare_masks, validate_spheresfm_colmap


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare masks and validate a COLMAP spherical SfM launcher.")
    parser.add_argument("--colmap", required=True, help="COLMAP 4.1+ executable or Windows COLMAP.bat launcher")
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--source-masks-dir", type=Path)
    parser.add_argument("--output-masks-dir", type=Path)
    parser.add_argument("--use-masks", action="store_true")
    parser.add_argument("--matcher", choices=("sequential", "exhaustive", "spatial"), default="sequential")
    parser.add_argument("--quality-preset", choices=("fast", "standard", "quality"), default="standard")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    images_dir = args.images_dir
    if not images_dir.is_dir():
        raise FileNotFoundError(f"Images folder not found: {images_dir}")
    images = iter_images(images_dir)
    if not images:
        raise FileNotFoundError(f"No supported images found: {images_dir}")

    validate_spheresfm_colmap(
        args.colmap,
        matcher=args.matcher,
        quality_preset=args.quality_preset,
        use_masks=args.use_masks,
    )

    if args.use_masks:
        if args.source_masks_dir is None or not args.source_masks_dir.is_dir():
            raise FileNotFoundError(f"Masks folder not found: {args.source_masks_dir}")
        if args.output_masks_dir is None:
            raise ValueError("--output-masks-dir is required with --use-masks")
        copied, missing = prepare_masks(images_dir, args.source_masks_dir, args.output_masks_dir)
        print(f"Prepared COLMAP spherical masks: copied={copied}, missing={missing}", flush=True)
    else:
        print("COLMAP spherical masks disabled.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
