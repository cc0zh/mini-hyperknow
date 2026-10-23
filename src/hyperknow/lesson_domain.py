"""Whiteboard schemas and bounded, scenario-specific model inputs."""

import json
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .domain import AppError, Schema, uid


class BoardOperation(Schema):
    # Whitespace/indentation is meaningful in code and other board source.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    kind: Literal["text", "list", "code", "formula", "box", "arrow", "highlight", "mermaid"]
    content: str = Field(default="", max_length=4000)
    items: list[str] = Field(default_factory=list, max_length=12)
    language: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def valid_payload(self):
        if self.kind == "list":
            if not self.items or any(not item.strip() or len(item) > 1000 for item in self.items):
                raise ValueError("list operations require nonempty, bounded items")
        elif self.items or not self.content.strip():
            raise ValueError("non-list operations require content and empty items")
        if self.kind != "code" and self.language:
            raise ValueError("only code operations accept language")
        return self


class BoardStepDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    narration: str = Field(min_length=1, max_length=3000)
    page: int = Field(ge=1, le=18)
    column: Literal[1, 2]
    operations: list[BoardOperation] = Field(min_length=1, max_length=6)


class BoardScriptDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    steps: list[BoardStepDraft] = Field(min_length=1, max_length=18)

    @model_validator(mode="after")
    def ordered_pages(self):
        positions = [(step.page, step.column) for step in self.steps]
        if positions != sorted(positions) or positions[0][0] != 1:
            raise ValueError("steps must start on page 1 and use ordered pages/columns")
        return self


class BoardStep(BoardStepDraft):
    step_id: str


class BoardScript(Schema):
    script_id: str
    session_id: str
    course_id: str
    content_version: int = Field(ge=1)
    schema_version: Literal[1] = 1
    title: str
    steps: list[BoardStep] = Field(min_length=1, max_length=18)
    created_at: str


class LessonAnswer(Schema):
    answer: str = Field(min_length=1, max_length=12000)


class LessonProgress(Schema):
    script_id: str | None
    cursor: int = Field(ge=-1)
    play_intent: Literal["paused", "playing"]
    version: int = Field(ge=1)
    updated_at: str


class Interaction(Schema):
    interaction_id: str
    run_id: str
    script_id: str
    step_id: str | None
    cursor: int = Field(ge=-1)
    question: str = Field(min_length=2, max_length=2000)
    answer: str | None
    was_playing: bool
    status: Literal["pending", "ready", "failed", "cancelled", "interrupted"]
    error: dict | None
    created_at: str


class LessonSnapshot(Schema):
    course_id: str
    course_title: str
    unit_title: str
    lecture_title: str
    session: dict
    script: BoardScript | None
    progress: LessonProgress
    interactions: list[Interaction]
    generation_run: dict | None
    completed: bool
    version: int = Field(ge=1)


def materialize_script(draft: BoardScriptDraft, run: dict, timestamp: str) -> dict:
    data = draft.model_dump()
    return {**data, "script_id": uid("script"), "session_id": run["session_id"],
            "course_id": run["course_id"], "content_version": 1, "schema_version": 1,
            "created_at": timestamp,
            "steps": [{**step, "step_id": uid("step")} for step in data["steps"]]}


def lesson_context(course: dict, unit: dict, lecture: dict, session: dict) -> dict:
    sessions = [s for u in course["units"] for l in u["lectures"] for s in l["sessions"]]
    index = next(i for i, s in enumerate(sessions) if s["session_id"] == session["session_id"])
    return {"course_id": course["course_id"], "course_title": course["title"],
            "goal": course["goal"], "clarification": course["clarification"],
            "language": course["language"], "unit_title": unit["title"],
            "unit_description": unit["description"], "lecture_title": lecture["title"],
            "session": {k: v for k, v in session.items() if k != "completed"},
            "previous_session": sessions[index - 1]["title"] if index else None,
            "next_session": sessions[index + 1]["title"] if index + 1 < len(sessions) else None}


def question_context(course: dict, session: dict, script: dict, cursor: int,
                     question: str, interactions: list[dict], *, budget: int = 60000) -> dict:
    """Never trim the current question or include unconfirmed future steps.

    Character counts are a conservative estimate, not a claimed token count.
    Mandatory prefix overflow is explicit; history is the first thing omitted.
    """
    result = {"course_id": course["course_id"], "course_title": course["title"],
              "goal": course["goal"], "language": course["language"],
              "session": {k: session[k] for k in ("session_id", "title", "outline", "key_points")},
              "script_id": script["script_id"], "content_version": script["content_version"],
              "cursor": cursor, "question": question,
              "displayed_steps": script["steps"][:cursor + 1], "recent_interactions": [],
              "budget_characters": budget}
    size = lambda value: len(json.dumps(value, ensure_ascii=False))
    if size(result) > budget:
        raise AppError("context_too_large", "已展示内容超过保守上下文预算，问题未发送，请缩小上下文后重试", 422)
    history_size = 0
    for interaction in reversed(interactions):
        if interaction["status"] != "ready" or not interaction.get("answer"):
            continue
        entry = {k: interaction[k] for k in ("interaction_id", "question", "answer", "cursor")}
        if len(result["recent_interactions"]) == 6 or history_size + size(entry) > 6000:
            break
        result["recent_interactions"].insert(0, entry)
        if size(result) > budget:
            result["recent_interactions"].pop(0)
            break
        history_size += size(entry)
    return result


def derive_course(course: dict, completed: set[str]) -> dict:
    """One read rule for course lists, detail and continue destinations."""
    total = done = 0
    next_item = None
    for unit in course["units"]:
        for lecture in unit["lectures"]:
            for session in lecture["sessions"]:
                session.setdefault("depths", [])
                session["completed"] = session["session_id"] in completed
                total += 1
                done += int(session["completed"])
                if next_item is None and not session["completed"]:
                    next_item = {"type": "lecture", "title": session["title"],
                                 "session_id": session["session_id"], "unit_id": unit["unit_id"]}
        for collection, kind, id_key in (("project_stages", "project", "stage_id"),
                                          ("exams", "exam", "exam_id")):
            for activity in unit[collection]:
                activity["completed"] = activity[id_key] in completed
                if next_item is None and not activity["completed"]:
                    next_item = {"type": kind, "title": activity["title"],
                                 id_key: activity[id_key], "unit_id": unit["unit_id"]}
    partial = course.get("structure_status", "ready") != "ready"
    if partial:
        pending = next((unit for unit in course["units"] if unit["generation_status"] != "ready"), None)
        if pending:
            next_item = {"type": "generation", "run_id": course["creation_run_id"],
                         "unit_id": pending["unit_id"], "title": pending["title"]}
    course.update(progress=None if partial else (done * 100 / total if total else 0), next_item=next_item)
    return course
