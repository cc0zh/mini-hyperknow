"""Same-directory, fsynced atomic replacement for explicit memory updates."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def atomic_write(path: Path, content: bytes) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
