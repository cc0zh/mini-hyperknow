"""Private append-oriented trial records with content-addressed evidence."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .schema import validate_case


_PROTECTED_HISTORY = Path(__file__).resolve().parents[2] / "eval_result" / "2026-10-29"


def artifact_path(path: Path) -> Path:
    """Reject protected history before any content I/O, including lexical aliases."""
    lexical = Path(os.path.abspath(path))
    if lexical.is_relative_to(_PROTECTED_HISTORY):
        raise ValueError("the existing historical results directory is protected; choose a new path")
    resolved = lexical.resolve()
    if resolved.is_relative_to(_PROTECTED_HISTORY):
        raise ValueError("the existing historical results directory is protected; choose a new path")
    return resolved


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("nonfinite JSON number")


def read_json(path: Path):
    return json.loads(artifact_path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object, parse_constant=_nonfinite)


def write_json(path: Path, value) -> None:
    path = artifact_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encode(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive(directory: Path):
    """Never guess whether another writer's lock is stale."""
    path = artifact_path(directory) / ".writer.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def make_record(case: dict, *, config: dict | None = None) -> dict:
    fixed = validate_case(case)
    return {
        "schema_version": 3, "trial_id": uuid4().hex, "created_at": utcnow(),
        "finished_at": None, "case": fixed, "case_hash": digest(fixed),
        "config": deepcopy(config or {}), "subject": {"identity": "unknown"},
        "environment": {}, "status": "running", "actions": [], "business_runs": [],
        "evidence": [], "transcript": [], "checks": [], "model_requests": [],
        "judgments": [], "error": None,
    }


def new_trial(output: Path, case: dict, *, config: dict | None = None) -> dict:
    output = artifact_path(output)
    record = make_record(case, config=config)
    output.mkdir(parents=True, exist_ok=False)
    save_trial(output, record)
    return record


def save_trial(output: Path, record: dict) -> None:
    write_json(Path(output) / "trial.json", record)


def add_evidence(record: dict, kind: str, content, source: dict) -> str:
    """Content is never replaced; later observations receive new evidence IDs."""
    identity = f"e{len(record['evidence']) + 1:04d}"
    record["evidence"].append({
        "id": identity, "trial_id": record["trial_id"], "kind": kind,
        "content": deepcopy(content), "source": deepcopy(source),
        "sha256": digest(content), "captured_at": utcnow(),
    })
    return identity


def validate_record(record: dict) -> dict:
    if record.get("schema_version") != 3:
        raise ValueError("not a v3 trial; historical artifacts remain read-only outside this framework")
    fixed = validate_case(record["case"])
    if record.get("case_hash") != digest(fixed) or not record.get("trial_id"):
        raise ValueError("trial task identity mismatch")
    seen = set()
    for item in record["evidence"]:
        if (not isinstance(item.get("id"), str) or item["id"] in seen
                or item.get("trial_id") != record["trial_id"] or item.get("sha256") != digest(item["content"])):
            raise ValueError("evidence identity or content digest mismatch")
        seen.add(item["id"])
    for turn in record["transcript"]:
        if turn.get("role") not in {"student", "tutor"} or not isinstance(turn.get("text"), str):
            raise ValueError("invalid transcript turn")
        if turn.get("evidence_id") and turn["evidence_id"] not in seen:
            raise ValueError("transcript references unknown evidence")
    return record


def load_trial(output: Path) -> dict:
    path = artifact_path(output)
    return validate_record(read_json(path if path.is_file() else path / "trial.json"))


def evidence_hash(record: dict) -> str:
    validate_record(record)
    return digest({"trial_id": record["trial_id"], "case_hash": record["case_hash"],
                   "evidence": record["evidence"], "transcript": record["transcript"]})
