"""Curated tasks, not a task-generation or publication service."""

from pathlib import Path

from .schema import validate_case
from .storage import artifact_path, digest, read_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE = ROOT / "evals" / "suite.json"


def load_case(path: Path) -> dict:
    if Path(path).suffix.lower() != ".json":
        raise ValueError("tasks must be JSON files")
    return validate_case(read_json(path))


def load_suite(path: Path = DEFAULT_SUITE) -> tuple[dict, list[dict]]:
    path = artifact_path(path)
    manifest = read_json(path)
    if (set(manifest) != {"schema_version", "id", "revision", "purpose", "cases"}
            or manifest["schema_version"] != 3 or manifest["purpose"] != "development"
            or not isinstance(manifest["cases"], list) or not manifest["cases"]):
        raise ValueError("invalid development suite manifest")
    cases = []
    for member in manifest["cases"]:
        if not isinstance(member, str):
            raise ValueError("suite members must be relative JSON paths")
        target = artifact_path(path.parent / member)
        if not target.is_relative_to(path.parent) or target.suffix.lower() != ".json":
            raise ValueError("suite paths must stay within the suite directory")
        cases.append(load_case(target))
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("duplicate task identity in suite")
    return {**manifest, "sha256": digest(cases)}, cases


def inventory(cases: list[dict]) -> dict:
    def counts(field):
        values = [case[field] for case in cases]
        return {value: values.count(value) for value in sorted(set(values))}
    return {"cases": len(cases), "domains": counts("domain"), "workflows": counts("workflow"),
            "review_status": {status: sum(case["reference"]["review_status"] == status for case in cases)
                              for status in {case["reference"]["review_status"] for case in cases}},
            "calls": 0, "purpose": "development; not a held-out benchmark"}
