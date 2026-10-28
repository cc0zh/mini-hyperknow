"""Small, product-independent JSON store with one explicit local writer."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


def _check_json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _check_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _check_json(item)
        return
    raise ValueError("value must contain only finite JSON values and string object keys")


def digest(value) -> str:
    _check_json(value)
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"non-finite JSON value: {value}")


def read_json(path):
    result = json.loads(Path(path).read_text(encoding="utf-8"),
                        object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    _check_json(result)
    return result


def write_json(path, value):
    """Replace atomically on the same filesystem, retaining old data on failure."""
    _check_json(value)
    path = Path(path)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def exclusive(path):
    """Fail closed on an existing lock; never guess that a crash lock is stale."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(f"writer lock exists; verify no writer before removing {path}") from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        path.unlink(missing_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
