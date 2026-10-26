"""Local Case preparation and automatic, explicitly provisional sample collection."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"non-finite JSON value: {value}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_nonfinite)


def digest(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value):
    """Replace atomically; a failed write must not erase a submitted command ID."""
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
def exclusive(path: Path):
    """One local writer; crash leftovers require verifying no writer before removal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(f"writer lock exists; inspect running processes before removing {path}") from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


class RubricItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    criterion: str = Field(min_length=1)
    pass_when: str = Field(min_length=1)
    fail_when: str = Field(min_length=1)


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")
    version: int = Field(ge=1)
    input: str = Field(min_length=1, max_length=12000)
    rubric_version: int = Field(ge=1)
    reference_facts: list[str] = Field(min_length=1)
    rubric: list[RubricItem] = Field(min_length=1, max_length=10)

    @field_validator("reference_facts")
    @classmethod
    def nonempty_facts(cls, facts):
        if any(not fact.strip() for fact in facts):
            raise ValueError("reference facts must be nonempty")
        return facts

    @model_validator(mode="after")
    def unique_rubric(self):
        if len({item.id for item in self.rubric}) != len(self.rubric):
            raise ValueError("rubric IDs must be unique")
        return self


def validate_case(value: dict) -> dict:
    return EvalCase.model_validate(value).model_dump()


def load_case(path: Path) -> dict:
    return validate_case(read_json(path))


def case_hash(case: dict) -> str:
    return digest(validate_case(case))


def _case_record(case: dict) -> dict:
    return {"schema_version": 1, "case_hash": case_hash(case), "case": deepcopy(case),
            "usage": "development", "review_status": "unreviewed", "samples": []}


def prepare_case(case: dict, library: Path) -> Path:
    case = validate_case(case)
    path = library / f"{case_hash(case)}.json"
    with exclusive(library / ".writer.lock"):
        if not path.exists():
            write_json(path, _case_record(case))
        elif read_json(path)["case"] != case:
            raise ValueError("stored Case does not match its content hash")
    return path


RULE_IDS = {"delivery", "skill_trace", "no_artifacts", "no_questions", "trajectory"}


def grading_budget(grade: dict) -> dict:
    requested = grade.get("config", {}).get("max_output_tokens")
    reported = (grade.get("usage") or {}).get("completion_tokens")
    known = type(requested) is int and requested > 0 and type(reported) is int and reported >= 0
    return {"requested_output_tokens": requested, "reported_completion_tokens": reported,
            "status": "exceeded" if known and reported > requested else "within_reported_usage" if known else "unknown"}


def classify_result(result: dict) -> str:
    rules = result.get("rules", [])
    if len(rules) != len(RULE_IDS) or {r.get("id") for r in rules} != RULE_IDS:
        return "unresolved"
    if any(r.get("verdict") not in {"pass", "fail", "undetermined"} for r in rules):
        return "unresolved"
    # Export/association failure is a measurement problem, not poor teaching.
    if next(r for r in rules if r["id"] == "trajectory")["verdict"] != "pass":
        return "unresolved"
    if any(r["verdict"] == "fail" for r in rules):
        return "bad"
    grades = result.get("grades", [])
    grade = grades[-1] if grades else {}
    if grade.get("status") != "completed":
        return "unresolved"
    checks = grade.get("results", [])
    ids = {r["id"] for r in result["case"]["rubric"]}
    if len(checks) != len(ids) or {c.get("rubric_id") for c in checks} != ids:
        return "unresolved"
    verdicts = [r["verdict"] for r in rules] + [c.get("verdict") for c in checks]
    if any(v not in {"pass", "fail", "undetermined"} for v in verdicts):
        return "unresolved"
    if "fail" in verdicts:
        return "bad"
    if grading_budget(grade)["status"] == "exceeded":
        return "unresolved"
    return "good" if all(v == "pass" for v in verdicts) else "unresolved"


def collect_sample(result: dict, library: Path, result_path: Path) -> Path:
    case = validate_case(result["case"])
    identity = case_hash(case)
    if result.get("case_hash") != identity or result.get("schema_version") != 1:
        raise ValueError("result Case identity/schema mismatch")
    grade = result.get("grades", [])[-1] if result.get("grades") else {}
    grade = {**grade, "budget_check": grading_budget(grade)}
    sample = {"execution_id": result["execution_id"], "grading_attempt_id": grade.get("attempt_id"),
              "run_id": result.get("evidence", {}).get("run", {}).get("run_id"),
              "label": classify_result(result), "label_source": "rules_and_llm",
              "review_status": "unreviewed", "calibration_status": grade.get("calibration_status", "unreviewed"),
              "result_ref": str(result_path.resolve()), "evidence_sha256": digest(result.get("evidence", {})),
              "final_response": deepcopy(result.get("final_response")),
              "rules": deepcopy(result.get("rules", [])), "grade": deepcopy(grade)}
    path = library / f"{identity}.json"
    with exclusive(library / ".writer.lock"):
        record = read_json(path) if path.exists() else _case_record(case)
        if record.get("case_hash") != identity or record.get("case") != case:
            raise ValueError("stored Case identity mismatch")
        key = (sample["execution_id"], sample["grading_attempt_id"])
        record["samples"] = [s for s in record["samples"]
                             if (s["execution_id"], s["grading_attempt_id"]) != key
                             and not (sample["grading_attempt_id"] is not None
                                      and s["execution_id"] == sample["execution_id"]
                                      and s["grading_attempt_id"] is None)] + [sample]
        write_json(path, record)
    return path
