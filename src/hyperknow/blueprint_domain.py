"""Approved course plans, bounded expansion inputs and stable structure IDs."""

import json
from typing import Literal

from pydantic import Field, model_validator

from .domain import (AppError, ExamDraft, LectureDraft, ProjectDraft, Schema, StageDraft, uid)
from .research_domain import build_claim_context


class UnitBlueprint(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1200)
    learning_objectives: list[str] = Field(min_length=1, max_length=8)
    estimated_sessions: int = Field(ge=1, le=24)
    research_claim_ids: list[str] = Field(default_factory=list, max_length=12)
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
    allowed_claim_ids = set(unit.get("research_claim_ids", []))
    for session in sessions:
        if (len(set(session.research_claim_ids)) != len(session.research_claim_ids)
                or not set(session.research_claim_ids) <= allowed_claim_ids):
            raise ValueError("sessions may select only unique research claims assigned to their unit")
    for exam in draft.exams:
        if (len(set(exam.research_claim_ids)) != len(exam.research_claim_ids)
                or not set(exam.research_claim_ids) <= allowed_claim_ids):
            raise ValueError("exams may select only unique research claims assigned to their unit")
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
    research_report = run.get("research", {}).get("report") or {}
    selected_claim_ids = {claim_id for unit in course["units"]
                          for claim_id in unit.get("research_claim_ids", [])}
    research_claims = [{key: finding[key] for key in ("claim_id", "question_ids", "title", "summary")}
                       for finding in research_report.get("findings", [])
                       if finding.get("claim_id") in selected_claim_ids]
    research_evidence = [item for item in run.get("research", {}).get("evidence", [])
                         if item["claim_id"] in selected_claim_ids]
    return {**course, "research_claims": research_claims,
            "research_evidence": research_evidence,
            "course_id": previous["course_id"] if previous else uid("course"),
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


def validate_blueprint(draft: BlueprintDraft, context: dict) -> BlueprintDraft:
    allowed_claim_ids = {claim["claim_id"] for claim in context["research_claims"]}
    for unit in draft.units:
        if (len(set(unit.research_claim_ids)) != len(unit.research_claim_ids)
                or not set(unit.research_claim_ids) <= allowed_claim_ids):
            raise ValueError("units may select only unique claims in the research input")
        if allowed_claim_ids and not unit.research_claim_ids:
            raise ValueError("each unit must select at least one relevant research claim")
    return draft


def planning_context(run: dict, course: dict | None = None, *, budget: int = 60000) -> dict:
    """Pass exact passages attached to course-relevant claims, never arbitrary page prefixes."""
    research = run["research"]
    if not research.get("report") or not research["sources"]:
        raise AppError("research_required", "必须先完成真实调研才能规划课程", 409)
    report = research["report"]
    claim_metadata = [{key: finding[key] for key in ("claim_id", "question_ids", "title", "summary")}
                      for finding in report.get("findings", []) if finding.get("claim_id")]
    evidence_claim_ids = {item["claim_id"] for item in research.get("evidence", [])}
    if run["stage"] == "blueprint":
        selected_claim_ids = [claim["claim_id"] for claim in claim_metadata
                              if claim["claim_id"] in evidence_claim_ids]
    else:
        unit = next(unit for unit in course["units"] if unit["unit_id"] == run["current_unit_id"])
        selected_claim_ids = unit.get("research_claim_ids", [])
    try:
        research_claims = build_claim_context(claim_metadata, research.get("evidence", []), selected_claim_ids)
    except ValueError as exc:
        raise AppError("research_evidence_invalid", "所选课程主张缺少可验证的来源证据", 409) from exc
    result = {"goal": run["goal"], "questions": run["questions"], "answers": run["answers"],
              "clarification_skipped": run["skipped"],
              "research_claims": research_claims,
              "feedback": run.get("blueprint_feedback", ""),
              "budget_bytes": budget, "course_session_budget": 60}
    optional_sequences = {}
    if run["stage"] == "blueprint":
        result["research_report"] = {"summary": report.get("summary", ""), "questions": report.get("questions", []),
                                     "suggested_sequence": report.get("suggested_sequence", []),
                                     "limitations": report.get("limitations", [])}
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
    # Required claims and exact passages win over optional course history.
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
    return result
