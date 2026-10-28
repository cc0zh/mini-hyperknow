"""Strict, JSON-only contracts shared by execution and offline evaluation."""

from copy import deepcopy
import re
from typing import Annotated, Literal

from pydantic import (BaseModel, ConfigDict, Field, JsonValue, StringConstraints,
                      model_validator)

from .store import digest


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
State = Literal["preparing", "running", "waiting", "terminal", "blocked"]
STATES = ("preparing", "running", "waiting", "terminal", "blocked")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class Task(StrictModel):
    profile: Text
    input: JsonValue
    answer_policy: dict[str, JsonValue] | None = None


class When(StrictModel):
    state: list[State] = Field(default_factory=lambda: list(STATES), min_length=1)
    action: Text | None = None
    checkpoint: Text | None = None


class Step(StrictModel):
    id: Text
    action: Text
    input: dict[str, JsonValue] = Field(default_factory=dict)
    when: When = Field(default_factory=When)
    optional: bool = False
    checkpoint: Text


class Check(StrictModel):
    check_id: Text
    version: Text
    kind: Literal["rule", "llm"]
    evaluator: Text
    criterion: Text
    pass_when: Text
    fail_when: Text
    evidence: list[Text]
    evidence_fields: list[Text] = Field(default_factory=list)
    required: bool = True
    applicable_when: When = Field(default_factory=When)

    @model_validator(mode="after")
    def top_level_evidence_fields(self):
        if len(self.evidence_fields) != len(set(self.evidence_fields)):
            raise ValueError("evidence_fields must be unique")
        if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) is None for key in self.evidence_fields):
            raise ValueError("evidence_fields must name literal top-level data keys, not paths or expressions")
        return self


class Limits(StrictModel):
    max_actions: int = Field(default=32, ge=0)
    wait_seconds: float = Field(default=420, ge=0, allow_inf_nan=False)
    poll_seconds: float = Field(default=0.25, gt=0, allow_inf_nan=False)
    max_model_calls: int = Field(default=32, ge=0)


class Completion(StrictModel):
    states: list[Literal["waiting", "terminal"]] = Field(
        default_factory=lambda: ["waiting", "terminal"], min_length=1)
    outcomes: list[Text] = Field(default_factory=lambda: ["success"], min_length=1)


class EvalCase(StrictModel):
    schema_version: Literal[2]
    id: Text
    version: Text
    title: Text
    tags: list[Text]
    task: Task
    prerequisites: dict[str, JsonValue]
    steps: list[Step]
    checks: list[Check]
    reference_facts: list[JsonValue]
    capture: list[Text]
    limits: Limits = Field(default_factory=Limits)
    completion: Completion = Field(default_factory=Completion)

    @model_validator(mode="after")
    def identities_and_evidence(self):
        for label, values in (("step IDs", [step.id for step in self.steps]),
                              ("check IDs", [check.check_id for check in self.checks]),
                              ("step checkpoints", [step.checkpoint for step in self.steps]),
                              ("capture checkpoints", self.capture)):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        checkpoints = set(self.capture) | {step.checkpoint for step in self.steps}
        for check in self.checks:
            if not set(check.evidence) <= checkpoints:
                raise ValueError(f"unknown evidence checkpoint in check {check.check_id}")
            if len(check.evidence) != len(set(check.evidence)):
                raise ValueError(f"duplicate evidence checkpoint in check {check.check_id}")
        return self


def validate_case(value: dict) -> dict:
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 2:
        raise ValueError("Case schema_version must be the integer 2")
    digest(value)  # Reject non-JSON data and non-finite numbers before coercion.
    result = EvalCase.model_validate(value).model_dump()
    # JSON null is valid task input and may occur inside arbitrary public data.
    # Strip only optional contract fields, never JSON material supplied by a Case.
    if result["task"]["answer_policy"] is None:
        del result["task"]["answer_policy"]
    conditions = [step["when"] for step in result["steps"]]
    conditions += [check["applicable_when"] for check in result["checks"]]
    for condition in conditions:
        for key in ("action", "checkpoint"):
            if condition[key] is None:
                del condition[key]
    return result


def public_case(case: dict) -> dict:
    """Project execution material without exposing private grading definitions."""
    result = deepcopy(validate_case(case))
    del result["checks"]
    del result["reference_facts"]
    return result


def validate_observation(value: dict) -> dict:
    """Keep adapter-owned facts opaque while validating the common boundary."""
    if type(value) is not dict:
        raise ValueError("observation must be a dictionary")
    digest(value)
    if value.get("state") not in STATES:
        raise ValueError("invalid observation state")
    for key in ("actions", "checkpoints"):
        items = value.get(key)
        if type(items) is not list or any(type(item) is not str or not item.strip() for item in items):
            raise ValueError(f"observation {key} must be a list of nonempty strings")
        if len(items) != len(set(items)):
            raise ValueError(f"observation {key} must be unique")
    if type(value.get("resources")) is not dict:
        raise ValueError("observation resources must be a dictionary")
    if value.get("outcome") is not None and (type(value["outcome"]) is not str or not value["outcome"].strip()):
        raise ValueError("observation outcome must be a nonempty string")
    calls = value.get("model_calls")
    if calls is not None and (type(calls) is not int or calls < 0):
        raise ValueError("model_calls must be a nonnegative integer or null")
    result = deepcopy(value)
    if result.get("outcome") is None:
        result.pop("outcome", None)
    return result
