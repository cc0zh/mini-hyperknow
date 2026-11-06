"""Whiteboard schemas and bounded, scenario-specific model inputs."""

import json
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .domain import AppError, Schema, uid


class BoardNode(Schema):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=300)


class BoardEdge(Schema):
    from_id: str = Field(min_length=1, max_length=80)
    to_id: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=200)


class BoardOperation(Schema):
    # Whitespace/indentation is meaningful in code and other board source.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    kind: Literal["text", "list", "code", "formula", "box", "arrow", "highlight", "mermaid",
                  "table", "diagram", "circle"]
    content: str = Field(default="", max_length=4000)
    items: list[str] = Field(default_factory=list, max_length=12)
    language: str = Field(default="", max_length=40)
    object_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    target_ids: list[str] = Field(default_factory=list, max_length=24)
    columns: list[str] = Field(default_factory=list, max_length=8)
    rows: list[list[str]] = Field(default_factory=list, max_length=16)
    nodes: list[BoardNode] = Field(default_factory=list, max_length=16)
    edges: list[BoardEdge] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def valid_payload(self):
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("operation target IDs must be unique")
        if any(not target.strip() or len(target) > 80 for target in self.target_ids):
            raise ValueError("operation target IDs must be nonempty and bounded")
        if self.kind == "table":
            if (not self.columns or not self.rows
                    or any(not column.strip() or len(column) > 200 for column in self.columns)
                    or any(len(row) != len(self.columns) for row in self.rows)
                    or any(not cell.strip() or len(cell) > 1000 for row in self.rows for cell in row)):
                raise ValueError("table requires bounded columns and nonempty rectangular rows")
        elif self.columns or self.rows:
            raise ValueError("only table operations accept columns and rows")
        if self.kind == "diagram":
            ids = {node.id for node in self.nodes}
            if not ids or len(ids) != len(self.nodes):
                raise ValueError("diagram requires unique nodes")
            if any(edge.from_id not in ids or edge.to_id not in ids for edge in self.edges):
                raise ValueError("diagram edges must connect nodes in this diagram")
        elif self.nodes or self.edges:
            raise ValueError("only diagram operations accept nodes and edges")
        if self.kind == "list":
            if not self.items or any(not item.strip() or len(item) > 1000 for item in self.items):
                raise ValueError("list operations require nonempty, bounded items")
        elif self.items:
            raise ValueError("only list operations accept items")
        elif self.kind not in {"table", "diagram"} and not self.content.strip() and not (
                self.kind in {"highlight", "circle"} and self.target_ids):
            raise ValueError("non-list operations require content and empty items")
        if self.kind != "code" and self.language:
            raise ValueError("only code operations accept language")
        return self


class BoardCheck(Schema):
    question: str = Field(min_length=1, max_length=1000)
    expected_answer: str = Field(min_length=1, max_length=2000)


class BoardRoadmapItem(Schema):
    keypoint_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    source_keypoint_index: int = Field(ge=0, le=7, strict=True)
    title: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=600)


class BoardFrame(Schema):
    """One visual frame; independent assistance has no course teaching plan."""

    title: str = Field(min_length=1, max_length=200)
    narration: str = Field(min_length=1, max_length=3000)
    page: int = Field(ge=1, le=36)
    column: Literal[1, 2]
    operations: list[BoardOperation] = Field(min_length=1, max_length=6)


class BoardStepDraft(BoardFrame):
    stage: Literal["opening", "explain", "example", "check", "summary"]
    keypoint_id: str | None = Field(default=None, min_length=1, max_length=80)
    focus_ids: list[str] = Field(default_factory=list, max_length=24)
    check: BoardCheck | None = None


def validate_board_references(steps: list[BoardFrame]):
    """References resolve in presentation order, never against future frames."""
    seen = set()
    for step in steps:
        for operation in step.operations:
            if operation.object_id in seen:
                raise ValueError("operation object IDs must be unique")
            if operation.kind in {"highlight", "circle"} and not operation.target_ids:
                raise ValueError("emphasis operations must target existing objects")
            if any(target not in seen for target in operation.target_ids):
                raise ValueError("operation cannot reference a future or unknown object")
            seen.add(operation.object_id)
            for node in operation.nodes:
                if node.id in seen:
                    raise ValueError("all object and node IDs must be unique within a board")
                seen.add(node.id)
        focus = getattr(step, "focus_ids", [])
        if len(set(focus)) != len(focus) or any(key not in seen for key in focus):
            raise ValueError("focus IDs must reference already introduced objects or nodes")


class BoardScriptDraft(Schema):
    schema_version: Literal[2]
    title: str = Field(min_length=1, max_length=200)
    objectives: list[str] = Field(min_length=1, max_length=8)
    roadmap: list[BoardRoadmapItem] = Field(min_length=1, max_length=8)
    steps: list[BoardStepDraft] = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def ordered_pages(self):
        positions = [(step.page, step.column) for step in self.steps]
        if positions != sorted(positions) or positions[0][0] != 1:
            raise ValueError("steps must start on page 1 and use ordered pages/columns")
        if not self.objectives or any(not item.strip() or len(item) > 600 for item in self.objectives):
            raise ValueError("v2 requires nonempty bounded learning objectives")
        ids = [item.keypoint_id for item in self.roadmap]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("v2 requires a roadmap with unique keypoint IDs")
        if [item.source_keypoint_index for item in self.roadmap] != list(range(len(self.roadmap))):
            raise ValueError("roadmap must cover source keypoint indices once in order, starting at zero")
        if (self.steps[0].stage != "opening" or self.steps[-1].stage != "summary"
                or any(step.stage == "opening" for step in self.steps[1:])
                or any(step.stage == "summary" for step in self.steps[:-1])):
            raise ValueError("v2 requires exactly one opening first and one summary last")
        coverage = {key: set() for key in ids}
        last_keypoint, checks = -1, 0
        for step in self.steps:
            if step.keypoint_id is not None and step.keypoint_id not in coverage:
                raise ValueError("step refers to an unknown roadmap keypoint")
            if step.stage in {"opening", "summary"} and step.keypoint_id is not None:
                raise ValueError("opening and summary address the whole lesson")
            if step.stage in {"explain", "example"}:
                if step.keypoint_id is None:
                    raise ValueError("explain and example require a roadmap keypoint")
                index = ids.index(step.keypoint_id)
                if index < last_keypoint:
                    raise ValueError("teach keypoints in roadmap order")
                last_keypoint = index
                if step.stage == "example" and "explain" not in coverage[step.keypoint_id]:
                    raise ValueError("explain a keypoint before its example")
                coverage[step.keypoint_id].add(step.stage)
            if step.stage == "check":
                checks += 1
                if step.check is None:
                    raise ValueError("check steps require a question and expected answer")
                required = [coverage[step.keypoint_id]] if step.keypoint_id is not None else coverage.values()
                if any(stages != {"explain", "example"} for stages in required):
                    raise ValueError("check must follow explanation and example of the assessed keypoints")
            elif step.check is not None:
                raise ValueError("only check steps accept a check payload")
        if not checks or any(stages != {"explain", "example"} for stages in coverage.values()):
            raise ValueError("v2 requires explain and example for every keypoint and at least one check")
        validate_board_references(self.steps)
        return self


def validate_lesson_coverage(draft: BoardScriptDraft, context: dict):
    if [item.source_keypoint_index for item in draft.roadmap] != list(range(len(context["session"]["key_points"]))):
        raise ValueError("roadmap source indices must cover every session keypoint exactly once in order")


class BoardStep(BoardStepDraft):
    step_id: str = Field(min_length=1, max_length=80)


class BoardScript(BoardScriptDraft):
    script_id: str
    session_id: str
    course_id: str
    content_version: int = Field(ge=1)
    steps: list[BoardStep] = Field(min_length=1, max_length=36)
    created_at: str

    @model_validator(mode="after")
    def unique_steps(self):
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("persisted step IDs must be unique")
        return self


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
    anchor_step_id: str | None = None
    anchor_object_id: str | None = None
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
    format_error: dict | None = None
    progress: LessonProgress
    interactions: list[Interaction]
    generation_run: dict | None
    completed: bool
    version: int = Field(ge=1)


def materialize_script(draft: BoardScriptDraft, run: dict, timestamp: str) -> dict:
    data = draft.model_dump()
    return {**data, "script_id": uid("script"), "session_id": run["session_id"],
            "course_id": run["course_id"], "content_version": 1,
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
                     question: str, interactions: list[dict], *, budget: int = 60000,
                     anchor_step_id: str | None = None, anchor_object_id: str | None = None) -> dict:
    """Never trim the current question or include unconfirmed future steps.

    Character counts are a conservative estimate, not a claimed token count.
    Mandatory prefix overflow is explicit; history is the first thing omitted.
    """
    if not -1 <= cursor < len(script["steps"]):
        raise AppError("invalid_cursor", "课堂位置超出讲义步骤范围", 422)
    prefix = script["steps"][:cursor + 1]
    if anchor_step_id is not None:
        anchor_index = next((i for i, step in enumerate(prefix) if step["step_id"] == anchor_step_id), None)
        if anchor_index is None:
            raise AppError("invalid_anchor", "提问锚点只能指向已确认展示的步骤", 422)
        prefix = prefix[:anchor_index + 1]
    if anchor_object_id is not None:
        objects = {key for step in prefix for operation in step["operations"]
                   for key in [operation["object_id"], *[node["id"] for node in operation.get("nodes", [])]]}
        if anchor_object_id not in objects:
            raise AppError("invalid_anchor", "提问锚点只能指向该位置已展示的对象或图节点", 422)
    result = {"course_id": course["course_id"], "course_title": course["title"],
              "goal": course["goal"], "language": course["language"],
              "session": {k: session[k] for k in ("session_id", "title", "outline", "key_points")},
              "script_id": script["script_id"], "content_version": script["content_version"],
              "cursor": cursor, "question": question,
              "anchor_step_id": anchor_step_id, "anchor_object_id": anchor_object_id,
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
        entry.update({key: interaction.get(key) for key in ("anchor_step_id", "anchor_object_id")})
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
