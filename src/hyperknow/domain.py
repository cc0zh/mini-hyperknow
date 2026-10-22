"""Validated course definitions and deterministic application rules."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False,
                 *, latest_version: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        self.latest_version = latest_version

    def public(self) -> dict:
        result = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.latest_version is not None:
            result["latest_version"] = self.latest_version
        return result


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Option(Schema):
    id: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=600)


class Question(Schema):
    id: str = Field(min_length=1, max_length=60)
    question: str = Field(min_length=1, max_length=600)
    type: Literal["single", "multi"]
    allow_custom: bool = False
    options: list[Option] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def unique_options(self):
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError("option IDs must be unique")
        return self


class Clarification(Schema):
    questions: list[Question] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("question IDs must be unique")
        return self


class SessionDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    outline: str = Field(min_length=1, max_length=4000)
    key_points: list[str] = Field(min_length=1, max_length=8)
    estimated_minutes: int = Field(ge=1, le=180)


class LectureDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    sessions: list[SessionDraft] = Field(min_length=1, max_length=6)


class ExamDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=1200)


class ProjectDraft(Schema):
    project_key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    final_deliverable: str = Field(min_length=1, max_length=1200)


class StageDraft(Schema):
    project_key: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    deliverable: str = Field(min_length=1, max_length=1200)


class UnitDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    lectures: list[LectureDraft] = Field(min_length=1, max_length=4)
    exams: list[ExamDraft] = Field(default_factory=list, max_length=2)
    project_stages: list[StageDraft] = Field(default_factory=list, max_length=3)


class CourseDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2400)
    target_learner: str = Field(min_length=1, max_length=1200)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    tags: list[str] = Field(min_length=1, max_length=8)
    language: str = "zh-CN"
    projects: list[ProjectDraft] = Field(default_factory=list, max_length=3)
    units: list[UnitDraft] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_structure(self):
        keys = {p.project_key for p in self.projects}
        if len(keys) != len(self.projects):
            raise ValueError("project keys must be unique")
        stages = [s for u in self.units for s in u.project_stages]
        if any(s.project_key not in keys for s in stages):
            raise ValueError("project stage refers to an unknown project")
        if any(not any(s.project_key == key for s in stages) for key in keys):
            raise ValueError("every project needs at least one stage")
        sessions = [s for u in self.units for l in u.lectures for s in l.sessions]
        if len(sessions) > 60:
            raise ValueError("course exceeds the local generation budget of 60 sessions")
        for s in sessions:
            if any(not p.strip() for p in s.key_points):
                raise ValueError("key points cannot be empty")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("tags cannot be empty")
        return self


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def resolve_answers(questions: list[dict], answers: list[dict], skip: bool) -> list[dict]:
    if skip:
        if answers:
            raise AppError("invalid_answers", "跳过澄清时不能同时提交答案")
        return []
    by_id = {q["id"]: q for q in questions}
    resolved, seen = [], set()
    for answer in answers:
        qid = answer["question_id"]
        if qid not in by_id or qid in seen:
            raise AppError("invalid_answers", "存在未知或重复的澄清问题")
        seen.add(qid)
        q = by_id[qid]
        selected = answer.get("option_ids", [])
        custom = answer.get("custom_text", "").strip()
        options = {o["id"]: o for o in q["options"]}
        if len(set(selected)) != len(selected) or any(i not in options for i in selected):
            raise AppError("invalid_answers", "请选择本题提供的有效选项")
        if q["type"] == "single" and len(selected) > 1:
            raise AppError("invalid_answers", "单选题只能选择一项")
        if custom and not q.get("allow_custom"):
            raise AppError("invalid_answers", "该问题不支持自定义答案")
        if selected or custom:
            resolved.append({"question_id": qid, "question": q["question"], "option_ids": selected,
                             "selected_options": [options[i] for i in selected], "custom_text": custom})
    if not resolved:
        raise AppError("invalid_answers", "请至少回答一个问题，或明确选择跳过")
    return resolved


def materialize_course(draft: CourseDraft, run: dict, created_at: str) -> dict:
    course = draft.model_dump()
    project_ids = {p["project_key"]: uid("project") for p in course["projects"]}
    for p in course["projects"]:
        p["project_id"] = project_ids[p.pop("project_key")]
    count = 0
    exams = 0
    for unit in course["units"]:
        unit["unit_id"] = uid("unit")
        for lecture in unit["lectures"]:
            lecture["lecture_id"] = uid("lecture")
            for session in lecture["sessions"]:
                session["session_id"] = uid("session")
                count += 1
        for exam in unit["exams"]:
            exam["exam_id"] = uid("exam")
            exams += 1
        for stage in unit["project_stages"]:
            stage["stage_id"] = uid("stage")
            stage["project_id"] = project_ids[stage.pop("project_key")]
    first_unit = course["units"][0]
    first_session = first_unit["lectures"][0]["sessions"][0]
    return {**course, "course_id": uid("course"), "goal": run["goal"], "clarification": {
        "questions": run["questions"], "answers": run["answers"], "skipped": run["skipped"]},
        "created_at": created_at, "schema_version": 1, "version": 1, "unit_count": len(course["units"]),
        "session_count": count, "exam_count": exams, "progress": 0,
        "next_item": {"type": "lecture", "title": first_session["title"],
                      "session_id": first_session["session_id"], "unit_id": first_unit["unit_id"]}}
