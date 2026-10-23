"""Approved course plans, bounded expansion inputs and stable structure IDs."""

import json
from typing import Literal

from pydantic import Field, model_validator

from .domain import (AppError, ExamDraft, LectureDraft, ProjectDraft, Schema, StageDraft, uid)


class UnitBlueprint(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    learning_objectives: list[str] = Field(min_length=1, max_length=8)
    estimated_sessions: int = Field(ge=1, le=24)
    project_keys: list[str] = Field(default_factory=list, max_length=3)
    exam_goal: str = Field(default="", max_length=1200)


class BlueprintDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2400)
    target_learner: str = Field(min_length=1, max_length=1200)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    tags: list[str] = Field(min_length=1, max_length=8)
    language: str = "zh-CN"
    projects: list[ProjectDraft] = Field(default_factory=list, max_length=3)
    units: list[UnitBlueprint] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_plan(self):
        keys = {project.project_key for project in self.projects}
        if len(keys) != len(self.projects):
            raise ValueError("project keys must be unique")
        referenced = set()
        for unit in self.units:
            if any(not value.strip() for value in unit.learning_objectives):
                raise ValueError("learning objectives cannot be empty")
            if len(set(unit.project_keys)) != len(unit.project_keys) or not set(unit.project_keys) <= keys:
                raise ValueError("unit project keys must be unique and refer to planned projects")
            referenced.update(unit.project_keys)
        if referenced != keys:
            raise ValueError("every project must be planned in at least one unit")
        if sum(unit.estimated_sessions for unit in self.units) > 60:
            raise ValueError("course planning budget is 60 sessions")
        if any(not value.strip() for value in self.tags):
            raise ValueError("tags cannot be empty")
        return self


class UnitExpansionDraft(Schema):
    # The approved title, objectives and project plan are deliberately not editable.
    lectures: list[LectureDraft] = Field(min_length=1, max_length=4)
    exams: list[ExamDraft] = Field(default_factory=list, max_length=1)
    project_stages: list[StageDraft] = Field(default_factory=list, max_length=3)


def validate_expansion(draft: UnitExpansionDraft, unit: dict, session_budget: int):
    sessions = [session for lecture in draft.lectures for session in lecture.sessions]
    if len(sessions) > session_budget:
        raise ValueError("unit exceeds remaining course session budget")
    if any(not session.depths or len(set(session.depths)) != len(session.depths) for session in sessions):
        raise ValueError("new sessions require unique, nonempty teaching depths")
    if any(any(not point.strip() for point in session.key_points) for session in sessions):
        raise ValueError("session key points cannot be empty")
    stage_keys = [stage.project_key for stage in draft.project_stages]
    if len(set(stage_keys)) != len(stage_keys) or set(stage_keys) != set(unit["project_keys"]):
        raise ValueError("each approved unit project key needs exactly one stage")
    if unit["exam_goal"]:
        if len(draft.exams) != 1 or draft.exams[0].goal != unit["exam_goal"]:
            raise ValueError("unit requires one exam with the exact approved exam goal")
    elif draft.exams:
        raise ValueError("unit has no approved exam goal")
    return draft


def expansion_budget(course: dict, unit_id: str) -> int:
    used = sum(len(lecture["sessions"]) for unit in course["units"]
               if unit["unit_id"] != unit_id for lecture in unit["lectures"])
    reserved = sum(unit["estimated_sessions"] for unit in course["units"]
                   if unit["unit_id"] != unit_id and unit["generation_status"] != "ready")
    return 60 - used - reserved


def materialize_blueprint(draft: BlueprintDraft, run: dict, timestamp: str,
                          previous: dict | None = None) -> dict:
    course = draft.model_dump()
    old_projects = {project["project_key"]: project["project_id"]
                    for project in previous["projects"]} if previous else {}
    for project in course["projects"]:
        project["project_id"] = old_projects.get(project["project_key"]) or uid("project")
    for index, unit in enumerate(course["units"]):
        old_unit = previous["units"][index] if previous and index < len(previous["units"]) else None
        unit.update(unit_id=old_unit["unit_id"] if old_unit else uid("unit"),
                    generation_status="pending", lectures=[], exams=[], project_stages=[])
    return {**course, "course_id": previous["course_id"] if previous else uid("course"),
            "goal": run["goal"], "clarification": {"questions": run["questions"],
                "answers": run["answers"], "skipped": run["skipped"]},
            "created_at": previous["created_at"] if previous else timestamp,
            "schema_version": 1, "version": previous["version"] + 1 if previous else 1,
            "structure_status": "blueprint", "blueprint_version": previous["blueprint_version"] + 1 if previous else 1,
            "creation_run_id": run["run_id"], "unit_count": len(course["units"]),
            "session_count": 0, "exam_count": 0, "progress": None, "next_item": None}


def materialize_expansion(draft: UnitExpansionDraft, course: dict) -> dict:
    data = draft.model_dump()
    projects = {project["project_key"]: project["project_id"] for project in course["projects"]}
    for lecture in data["lectures"]:
        lecture["lecture_id"] = uid("lecture")
        for session in lecture["sessions"]:
            session["session_id"] = uid("session")
    for exam in data["exams"]:
        exam["exam_id"] = uid("exam")
    for stage in data["project_stages"]:
        stage.update(stage_id=uid("stage"), project_id=projects[stage["project_key"]])
    return data


def _json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _sequence_excerpt(items: list[dict]) -> dict:
    return {"items": [], "total_items": len(items), "context_truncated": bool(items),
            "byte_limit": 6000}


def planning_context(run: dict, course: dict | None = None, *, budget: int = 60000) -> dict:
    """Use real evidence and bounded excerpts; record precisely what the model receives."""
    research = run["research"]
    if not research.get("report") or not research["sources"]:
        raise AppError("research_required", "必须先完成真实调研才能规划课程", 409)
    sources = []
    for source in research["sources"]:
        text = source.get("text", "")
        sources.append({**{key: value for key, value in source.items() if key != "text"},
                        "context_excerpt": "", "stored_excerpt_bytes": len(text.encode("utf-8")),
                        "context_truncated": bool(text)})
    result = {"goal": run["goal"], "questions": run["questions"], "answers": run["answers"],
              "clarification_skipped": run["skipped"], "research_report": research["report"],
              "feedback": run.get("blueprint_feedback", ""),
              "sources": sources, "source_excerpt_byte_limit": 6000, "budget_bytes": budget,
              "course_session_budget": 60}
    optional_sequences = {}
    if run["stage"] == "blueprint":
        if course:
            result["previous_blueprint"] = {key: course[key] for key in (
                "title", "description", "target_learner", "difficulty", "tags", "language", "projects", "units")}
    elif course:
        unit = next(unit for unit in course["units"] if unit["unit_id"] == run["current_unit_id"])
        result.update(approved_blueprint_version=course["blueprint_version"],
                      course_title=course["title"], language=course["language"], projects=course["projects"],
                      unit=unit, unit_session_budget=expansion_budget(course, unit["unit_id"]))
        optional_sequences = {
            "unit_sequence_excerpt": [{key: other[key] for key in (
                "unit_id", "title", "learning_objectives", "estimated_sessions", "project_keys", "exam_goal")}
                for other in course["units"]],
            "expanded_units_excerpt": [{"unit_id": other["unit_id"], "title": other["title"],
                "lectures": [{"title": lecture["title"], "sessions": [
                    {"title": session["title"]}
                    for session in lecture["sessions"]]} for lecture in other["lectures"]],
                "project_stages": [{"project_key": stage["project_key"], "title": stage["title"],
                                    "deliverable_excerpt": stage["deliverable"][:300],
                                    "context_truncated": len(stage["deliverable"]) > 300}
                                   for stage in other["project_stages"]]}
                for other in course["units"] if other["generation_status"] == "ready"]}
        result.update({key: _sequence_excerpt(items) for key, items in optional_sequences.items()})
    size = lambda: _json_bytes(result)
    if size() > budget:
        raise AppError("context_too_large", "课程规划输入超过保守上下文预算，未发起模型请求", 422)
    # Required evidence metadata, report and the exact approved current unit win over
    # optional history. Each sequence gets at most a quarter of the free space,
    # leaving at least half for source excerpts; the 6000-byte caps include JSON.
    allowance = (budget - size()) // 4
    for key, items in optional_sequences.items():
        excerpt = result[key]
        target = min(excerpt["byte_limit"], _json_bytes(excerpt) + allowance)
        for index, item in enumerate(items):
            excerpt["items"].append(item)
            excerpt["context_truncated"] = index + 1 < len(items)
            if _json_bytes(excerpt) > target:
                excerpt["items"].pop()
                excerpt["context_truncated"] = True
                break
    for index, source in enumerate(sources):
        raw = research["sources"][index].get("text", "").encode("utf-8")
        target = size() + (budget - size()) // (len(sources) - index)
        low, high = 0, min(6000, len(raw))
        while low < high:
            middle = (low + high + 1) // 2
            source["context_excerpt"] = raw[:middle].decode("utf-8", errors="ignore")
            source["context_truncated"] = middle < len(raw)
            if size() <= target:
                low = middle
            else:
                high = middle - 1
        source["context_excerpt"] = raw[:low].decode("utf-8", errors="ignore")
        source["context_truncated"] = len(source["context_excerpt"].encode("utf-8")) < len(raw)
    return result
