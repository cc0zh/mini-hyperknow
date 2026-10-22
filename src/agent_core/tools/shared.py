"""Workspace boundaries, read baselines, and atomic writes shared by tools."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import Callable

from .scheduler import is_cancelled


MAX_FILE_BYTES = 8_000_000
MAX_PREVIEW_CHARS = 32_000


def check_cancelled() -> None:
    if is_cancelled():
        raise RuntimeError("cancelled")


def is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("only regular files are supported")
        while chunk := handle.read(65536):
            check_cancelled()
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {MAX_FILE_BYTES} byte safety limit")
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("only regular files are supported")
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} byte safety limit")
    return content


class Workspace:
    def __init__(self, root: str | Path, output_dir: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("workspace root must be a directory")
        self.output_dir = Path(output_dir).resolve()
        self.reads: dict[Path, str] = {}
        self.artifacts: set[Path] = set()
        self.lock = threading.RLock()

    def path(self, value: str, *, writing: bool = False) -> Path:
        if not value or "\x00" in value:
            raise ValueError("path must be non-empty and contain no NUL")
        raw = Path(value)
        raw = raw if raw.is_absolute() else self.root / raw
        resolved = raw.resolve()
        if not resolved.is_relative_to(self.root):
            if not writing and resolved in self.artifacts and raw.absolute() == resolved:
                return resolved
            raise PermissionError("path escapes workspace (including symlinks)")
        if writing:
            current = raw
            while current != self.root and current != current.parent:
                if is_link(current):
                    raise PermissionError("refusing symlink/junction replacement or write traversal")
                current = current.parent
        if resolved.exists() and not (resolved.is_dir() or resolved.is_file()):
            raise ValueError("only regular files and directories are supported")
        return resolved

    def record_read(self, path: Path, digest: str) -> None:
        with self.lock:
            self.reads[path] = digest

    def expected(self, path: Path) -> str | None:
        if path.exists():
            if path not in self.reads:
                raise ValueError("file must be read before overwrite/edit")
            current = digest_file(path)
            if current != self.reads[path]:
                raise ValueError("file changed since read; read it again before writing")
            return current
        if path in self.reads:
            raise ValueError("file changed since read (removed); read it again")
        return None

    def atomic_write(self, value: str, content: str, expected: str | None) -> Path:
        check_cancelled()
        path = self.path(value, writing=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        parent_identity = path.parent.stat()
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        fd, temporary = tempfile.mkstemp(prefix=".agent-write-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(temporary, mode)
            check_cancelled()
            current = self.path(value, writing=True)
            if current != path or not os.path.samestat(parent_identity, path.parent.stat()):
                raise ValueError("write path changed during operation")
            actual = digest_file(path) if path.exists() else None
            if actual != expected:
                raise ValueError("file changed during write; read it again")
            os.replace(temporary, path)
            self.reads[path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return path
        finally:
            Path(temporary).unlink(missing_ok=True)

    def archive(self, path: Path) -> None:
        with self.lock:
            self.artifacts.add(path.resolve())
