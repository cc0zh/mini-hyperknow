from __future__ import annotations

from pathlib import Path
from typing import Any

from ...types import ToolResult

DEFAULT_MAX_CHARS = 100_000


def read_file(arguments: dict[str, Any]) -> ToolResult:
    path_value = arguments.get("path")
    if not isinstance(path_value, str) or not path_value:
        return ToolResult(False, error="path must be a non-empty string")
    max_chars = arguments.get("max_chars")
    if max_chars is not None and (not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1):
        return ToolResult(False, error="max_chars must be a positive integer")

    read_limit = max_chars or DEFAULT_MAX_CHARS
    try:
        with Path(path_value).open("r", encoding="utf-8") as handle:
            content = handle.read(read_limit)
    except (OSError, UnicodeError) as exc:
        return ToolResult(False, error=f"cannot read {path_value!r}: {exc}")
    return ToolResult(True, data=content)
