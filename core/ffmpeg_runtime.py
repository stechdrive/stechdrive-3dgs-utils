"""Shared, standard-library-only FFmpeg checks for extraction and Windows setup."""

from __future__ import annotations

import argparse
import re
import subprocess

MIN_FFMPEG_MAJOR = 7
_VERSION_TIMEOUT_SEC = 10
_INSTALL_HINT = (
    "Install FFmpeg 7 or newer with its bundled FFprobe, then retry. "
    "On Windows, run setup_windows.bat if they are missing; "
    "otherwise update FFmpeg and check the executable paths selected in Step 1."
)


def require_ffmpeg_version(executable: str, tool: str) -> str:
    """Check a release version before any scene files are changed."""
    if tool not in {"ffmpeg", "ffprobe"}:
        raise ValueError(f"Unsupported FFmpeg tool: {tool}")
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERSION_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Cannot run {tool}: {executable}. {_INSTALL_HINT}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "No version information").strip()
        raise RuntimeError(f"Cannot check {tool}: {executable}. {detail}\n{_INSTALL_HINT}")
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    match = re.search(rf"(?m)^\s*{tool} version\s+(\S+)", output)
    version = match.group(1) if match else "unknown"
    release = re.match(r"n?(\d+)\.(\d+)(?:\D|$)", version)
    if release is None:
        raise RuntimeError(
            f"Cannot determine the {tool} release version: {version} ({executable}). "
            f"Use an FFmpeg {MIN_FFMPEG_MAJOR}+ release build. {_INSTALL_HINT}"
        )
    if int(release.group(1)) < MIN_FFMPEG_MAJOR:
        raise RuntimeError(
            f"{tool} {MIN_FFMPEG_MAJOR} or newer is required; found {version} ({executable}). {_INSTALL_HINT}"
        )
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the FFmpeg 7+ runtime without installing anything.")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args(argv)
    try:
        for tool in ("ffmpeg", "ffprobe"):
            version = require_ffmpeg_version(getattr(args, tool), tool)
            print(f"[INFO] {tool}: {version}")
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
