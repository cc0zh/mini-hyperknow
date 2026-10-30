"""Small, strict task contract. Public interaction and private judgment stay separate."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WORKFLOWS = {"assistance", "course", "research", "lesson", "question", "practice", "exam", "artifact"}
DIMENSIONS = ("correctness", "pedagogy", "adaptation", "grounding")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value:
            raise ValueError("text fields must not be blank")
        return value


class Learner(Contract):
    background: str
    goal: str
    misconceptions: list[str] = Field(min_length=1)

    @field_validator("misconceptions")
    @classmethod
    def meaningful_gaps(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("learner gaps must not be blank")
        return value


class Task(Contract):
    opening: str
    course_goal: str | None = None
    mode: Literal["scripted", "simulated"] = "scripted"
    follow_ups: list[str] = Field(default_factory=list, max_length=7)
    max_turns: int = Field(default=3, ge=1, le=8, strict=True)
    clarification: Literal["skip", "facts"] = "skip"
    clarification_facts: str | None = None
    artifact_kind: Literal["whiteboard", "flashcards", "quiz", "diagram", "animation"] | None = None

    @model_validator(mode="after")
    def interaction_bounds(self):
        if len(self.follow_ups) + 1 > self.max_turns:
            raise ValueError("scripted messages exceed max_turns")
        if self.mode == "simulated" and self.follow_ups:
            raise ValueError("simulated mode does not also run scripted follow-ups")
        if self.clarification == "facts" and not self.clarification_facts:
            raise ValueError("facts clarification requires public facts")
        if any(not item.strip() for item in self.follow_ups):
            raise ValueError("follow-ups must not be blank")
        return self


class Budget(Contract):
    timeout_seconds: int = Field(default=900, ge=10, le=7200, strict=True)
    max_actions: int = Field(default=80, ge=1, le=500, strict=True)
    max_observed_calls: int = Field(default=64, ge=1, le=300, strict=True)


class Criterion(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    dimension: Literal["correctness", "pedagogy", "adaptation", "grounding"]
    description: str
    critical: bool = True


class Source(Contract):
    title: str
    url: str
    locator: str

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source must have a public HTTP(S) URL without credentials")
        return value


class Reference(Contract):
    facts: list[str] = Field(min_length=1)
    sources: list[Source] = Field(min_length=1)
    review_status: Literal["author_reviewed", "independently_reviewed"]
    reviewer: str

    @field_validator("facts")
    @classmethod
    def meaningful_facts(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("reference facts must not be blank")
        return value


class Case(Contract):
    schema_version: Literal[3] = 3
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")
    revision: int = Field(ge=1, strict=True)
    title: str
    domain: str
    workflow: Literal["assistance", "course", "research", "lesson", "question", "practice", "exam", "artifact"]
    learner: Learner
    task: Task
    budget: Budget = Field(default_factory=Budget)
    rubric: list[Criterion] = Field(min_length=2)
    reference: Reference
    provenance: str

    @model_validator(mode="after")
    def coverage(self):
        ids = [item.id for item in self.rubric]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion IDs must be unique")
        dimensions = {item.dimension for item in self.rubric}
        if not {"correctness", "pedagogy"} <= dimensions:
            raise ValueError("each task needs knowledge and teaching criteria")
        multi_turn = self.task.mode == "simulated" and self.task.max_turns > 1 or bool(self.task.follow_ups)
        if multi_turn and "adaptation" not in dimensions:
            raise ValueError("multi-turn tasks need an adaptation criterion")
        if self.workflow not in {"assistance", "artifact"} and self.task.mode == "simulated":
            raise ValueError("student simulation is scoped to assistance/artifact conversations")
        if self.workflow not in {"assistance", "artifact"} and self.task.follow_ups:
            raise ValueError("scripted follow-ups are scoped to assistance/artifact conversations")
        if self.workflow in {"lesson", "question", "practice", "exam"} and not self.task.course_goal:
            raise ValueError("downstream learning tasks require an explicit course_goal")
        if self.workflow == "artifact" and not self.task.artifact_kind:
            raise ValueError("artifact tasks declare their intended representation")
        return self


def validate_case(value: dict) -> dict:
    return Case.model_validate(value).model_dump(mode="json")


def public_case(case: dict) -> dict:
    """Execution sees no rubric, reference answers or hidden learner description."""
    fixed = validate_case(case)
    return {key: fixed[key] for key in ("id", "workflow", "task", "budget")}
