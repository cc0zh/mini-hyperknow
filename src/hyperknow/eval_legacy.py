"""Read-only schema-v1 Case validation and historical result summaries.

No business requests, model calls, sample writes or implicit schema migration.
"""

from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eval_core.store import digest


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


def case_hash(case: dict) -> str:
    return digest(validate_case(case))


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


def summarize_legacy_result(state: dict) -> dict:
    """Expose saved v1 judgments without executing, reparsing or modifying them."""
    if type(state.get("schema_version")) is not int or state["schema_version"] != 1:
        raise ValueError("expected a historical schema-v1 result")
    raw_case = state["case"]
    # The earliest saved v1 contract required this fixed hint. Keep it in its
    # original content identity; never strip it and pretend it was the later v1.
    if isinstance(raw_case, dict) and "skill_hint" in raw_case:
        if raw_case["skill_hint"] != "concept-explanation":
            raise ValueError("unsupported historical skill_hint")
        case = {**validate_case({key: value for key, value in raw_case.items() if key != "skill_hint"}),
                "skill_hint": raw_case["skill_hint"]}
    else:
        case = validate_case(raw_case)
    if state.get("case_hash") != digest(case):
        raise ValueError("historical Case identity mismatch")
    if not isinstance(state.get("execution_id"), str) or not state["execution_id"].strip():
        raise ValueError("historical execution identity is missing")
    return deepcopy({"schema_version": 1, "legacy_read_only": True,
        "execution_id": state["execution_id"], "run_id": state.get("run_id"), "stage": state["stage"],
        "label": classify_result(state), "rules": state.get("rules", []),
        "grades": [{**{key: grade.get(key) for key in
                    ("attempt_id", "status", "model", "results", "usage", "calibration_status")},
                    "budget_check": grading_budget(grade)} for grade in state.get("grades", [])],
        "final_response": state.get("final_response"), "subject_usage": state.get("subject_usage"),
        "error": state.get("error")})
