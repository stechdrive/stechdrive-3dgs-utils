from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from core.extract_frames import build_select_expr
from core.ffmpeg_runtime import require_ffmpeg_version


@pytest.mark.parametrize(
    "indices",
    [[], [0], [17], [0, 4, 8], [8, 0, 4, 4], list(range(0, 1197, 3)), list(range(0, 9000, 3))],
    ids=["empty", "first", "single", "odd", "duplicates", "399-frames", "3000-frames"],
)
def test_select_expr_preserves_choices_within_parser_depth(indices: list[int]) -> None:
    expr = build_select_expr(indices)
    assert expr.count("\\,") == len(indices)
    tree = ast.parse(expr.replace("\\,", ","), mode="eval")

    # FFmpeg 9 rejects expression trees deeper than 100, even from filter files.
    # Check the limit without requiring FFmpeg or a particular grouping layout.
    pending = [(tree.body, 0)]
    while pending:
        node, depth = pending.pop()
        assert depth <= 100
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))

    code = compile(tree, "<select-expression>", "eval")
    selected = set(indices)
    samples = set(range(40)) | selected | {max(selected, default=0) + 1}
    for frame in samples:
        result = eval(code, {"__builtins__": {}, "eq": lambda a, b: a == b, "n": frame})
        assert bool(result) == (frame in selected)


def _frame_checksums(output: str) -> list[tuple[int, str]]:
    rows = []
    for line in output.splitlines():
        if line and not line.startswith("#"):
            columns = [column.strip() for column in line.split(",")]
            rows.append((int(columns[2]), columns[-1]))
    return rows


@pytest.fixture(scope="module")
def ffmpeg_source() -> tuple[str, str, dict[int, str]]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("Optional integration check requires FFmpeg 7+ on PATH")
    require_ffmpeg_version(ffmpeg, "ffmpeg")
    source = "testsrc2=size=16x16:rate=30:duration=300"
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source, "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    reference = dict(_frame_checksums(proc.stdout))
    assert len(reference) == 9000
    return ffmpeg, source, reference


@pytest.mark.parametrize(
    "indices",
    [[], [0], [0, 4, 8], list(range(0, 1197, 3)), list(range(0, 9000, 3))],
    ids=["empty", "single", "odd", "399-frames", "3000-frames"],
)
def test_ffmpeg_select_expr_preserves_frame_pts_and_pixels(
    tmp_path: Path,
    ffmpeg_source: tuple[str, str, dict[int, str]],
    indices: list[int],
) -> None:
    ffmpeg, source, reference = ffmpeg_source
    script = tmp_path / "selection.ffscript"
    script.write_text(f"select='{build_select_expr(indices)}'\n", encoding="utf-8")
    proc = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source,
            "-/filter:v", str(script), "-fps_mode", "vfr", "-f", "framemd5", "-",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert _frame_checksums(proc.stdout) == [(i, reference[i]) for i in indices]
