"""COLMAP launcher handling shared by GUI and internal jobs."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

WINDOWS_BATCH_SUFFIXES = {".bat", ".cmd"}
CMD_META_CHARACTERS = "^&|<>()"
CMD_BATCH_ARGUMENT_PREFIX = ("/d", "/v:off", "/s", "/c")


def _escape_unquoted_cmd_argument(argument: str) -> str:
    if any(character.isspace() for character in argument):
        return argument
    escaped = argument
    for character in CMD_META_CHARACTERS:
        escaped = escaped.replace(character, f"^{character}")
    return escaped


def _unescape_cmd_argument(argument: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(argument):
        if (
            argument[index] == "^"
            and index + 1 < len(argument)
            and argument[index + 1] in CMD_META_CHARACTERS
        ):
            result.append(argument[index + 1])
            index += 2
        else:
            result.append(argument[index])
            index += 1
    return "".join(result)


def colmap_batch_qprocess_native_arguments(command: Sequence[str]) -> str | None:
    """Return cmd.exe native arguments when Qt's generic quoting is insufficient."""

    if len(command) < 6 or tuple(part.lower() for part in command[1:5]) != CMD_BATCH_ARGUMENT_PREFIX:
        return None
    if Path(command[0]).name.lower() not in {"cmd", "cmd.exe"}:
        return None
    values = [_unescape_cmd_argument(value) for value in command[5:]]
    command_line = " ".join(f'"{value}"' for value in values)
    return " ".join((*CMD_BATCH_ARGUMENT_PREFIX, f'"{command_line}"'))


def prefer_official_windows_launcher(executable: str) -> str:
    """Prefer the package-level COLMAP.bat next to an official Windows build."""

    path = Path(executable)
    if os.name != "nt" or path.suffix.lower() != ".exe" or path.name.lower() != "colmap.exe":
        return executable
    if not path.is_file():
        return executable

    candidates = (path.parent / "COLMAP.bat", path.parent.parent / "COLMAP.bat")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return executable


def build_colmap_command(launcher: str, *arguments: str | Path) -> list[str]:
    """Build a process command for a COLMAP executable or Windows batch launcher."""

    launcher_text = prefer_official_windows_launcher(str(launcher))
    args = [str(argument) for argument in arguments]
    if os.name == "nt" and Path(launcher_text).suffix.lower() in WINDOWS_BATCH_SUFFIXES:
        command_processor = os.environ.get("COMSPEC") or "cmd.exe"
        command_arguments = [_escape_unquoted_cmd_argument(value) for value in (launcher_text, *args)]
        return [command_processor, *CMD_BATCH_ARGUMENT_PREFIX, *command_arguments]
    return [launcher_text, *args]
