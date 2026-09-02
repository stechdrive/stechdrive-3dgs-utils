from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.projection_contract import PROJECTION_EQUIRECTANGULAR
from core.scene_inventory import SceneInventory, build_scene_inventory


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SfmPreflightResult:
    route: str
    ok: bool
    issues: tuple[PreflightIssue, ...]

    def error_message(self) -> str:
        return "\n".join(issue.message for issue in self.issues)


def preflight_spheresfm(scene_or_inventory: str | Path | SceneInventory) -> SfmPreflightResult:
    inventory = (
        scene_or_inventory
        if isinstance(scene_or_inventory, SceneInventory)
        else build_scene_inventory(Path(scene_or_inventory))
    )
    issues: list[PreflightIssue] = []

    if inventory.image_count <= 0:
        issues.append(
            PreflightIssue(
                "no_images",
                "COLMAP spherical SfM requires equirectangular 360 images in images/.",
            )
        )
        return SfmPreflightResult(route="spheresfm", ok=False, issues=tuple(issues))

    non_erp = [image for image in inventory.images if image.projection != PROJECTION_EQUIRECTANGULAR]
    if non_erp:
        preview = ", ".join(image.rel_path for image in non_erp[:3])
        issues.append(
            PreflightIssue(
                "requires_equirectangular_only",
                "COLMAP spherical SfM supports only equirectangular 360 images. "
                f"Non-ERP images detected: {preview}",
            )
        )

    sizes = inventory.image_sizes
    if len(sizes) != 1:
        preview = ", ".join(f"{width}x{height}" for width, height in sorted(sizes)[:4])
        issues.append(
            PreflightIssue(
                "requires_single_resolution",
                "COLMAP spherical SfM requires all source images to have the same resolution. "
                f"Detected sizes: {preview or 'unknown'}",
            )
        )

    return SfmPreflightResult(route="spheresfm", ok=not issues, issues=tuple(issues))


def require_spheresfm_scene(scene_or_inventory: str | Path | SceneInventory) -> None:
    result = preflight_spheresfm(scene_or_inventory)
    if not result.ok:
        raise ValueError(result.error_message())
