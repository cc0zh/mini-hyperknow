"""Deterministic bounded previews with atomic, recoverable source archives."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable


class OutputTruncator:
    def __init__(
        self, max_chars: int = 8_000, *, output_dir: str | Path | None = None,
        summarize: Callable[[str], str] | None = None,
        on_archive: Callable[[Path], None] | None = None,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self.max_chars = max_chars
        self.output_dir = Path(output_dir).resolve() if output_dir is not None else None
        self.summarize = summarize
        self.on_archive = on_archive

    def archive(self, content: str) -> Path:
        if self.output_dir is None:
            self.output_dir = Path(tempfile.mkdtemp(prefix="agent-output-"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        for start in range(0, len(content), 65536):
            digest.update(content[start:start + 65536].encode("utf-8"))
        path = self.output_dir / f"{digest.hexdigest()}.txt"
        fd, temporary = tempfile.mkstemp(prefix=".output-", dir=self.output_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                for start in range(0, len(content), 65536):
                    handle.write(content[start:start + 65536])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if self.on_archive is not None:
                self.on_archive(path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return path

    def truncate(
        self, content: str, *, is_error: bool = False, summarizable: bool = False,
        archive_path: Path | None = None, max_chars: int | None = None,
    ) -> str:
        budget = self.max_chars if max_chars is None else min(self.max_chars, max_chars)
        if budget < 1:
            raise ValueError("max_chars must be positive")
        if len(content) <= budget:
            return content
        path = archive_path or self.archive(content)
        label = "truncated"
        preview = content
        # Never summarize errors, exact file/search data, or already archived logs.
        if summarizable and not is_error and archive_path is None and self.summarize is not None:
            try:
                summary = self.summarize(content)
                if isinstance(summary, str) and summary.strip() and len(summary) < len(content):
                    preview, label = summary, "summary; original truncated"
            except Exception:
                pass  # Deterministic source excerpt remains available.
        marker = f"\n[{label}; full text: {path}]"
        if len(marker) > budget:
            # Tiny budgets cannot contain a file pointer. The deterministic archive
            # still exists under output_dir; never exceed the caller's hard bound.
            return f"[truncated; archive: {path}]"[:budget]
        return preview[:budget - len(marker)] + marker
