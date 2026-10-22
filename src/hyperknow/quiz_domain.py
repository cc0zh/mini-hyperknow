"""Objective quizzes, source-bounded inputs and deterministic personal scoring."""

import json
from typing import Literal

from pydantic import Field, model_validator

from .domain import AppError, Schema, uid


TargetType = Literal["practice", "exam"]
MAX_ELAPSED_MS = 86_400_000


class QuizOption(Schema):
    id: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1200)


class QuizQuestion(Schema):
    question_id: str = Field(min_length=1, max_length=80)
    kind: Literal["single", "multiple", "boolean"]
    prompt: str = Field(min_length=1, max_length=3000)
    options: list[QuizOption] = Field(min_length=2, max_length=8)
    correct_option_ids: list[str] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1, max_length=4000)
    source_refs: list[str] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def valid_answers(self):
        ids = {o.id for o in self.options}
        answers = set(self.correct_option_ids)
        if len(ids) != len(self.options) or len(answers) != len(self.correct_option_ids):
            raise ValueError("option and answer IDs must be unique")
        if not answers <= ids:
            raise ValueError("answers must belong to the supplied options")
        if self.kind == "multiple" and len(answers) < 2:
            raise ValueError("multiple questions require at least two correct options")
        if self.kind != "multiple" and len(answers) != 1:
            raise ValueError("single/boolean questions require one correct option")
        if self.kind == "boolean" and len(ids) != 2:
            raise ValueError("boolean questions require exactly two options")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("source refs must be unique")
        return self


class QuizDraft(Schema):
    title: str = Field(min_length=1, max_length=200)
    source_refs: list[str] = Field(min_length=1, max_length=80)
    questions: list[QuizQuestion] = Field(min_length=3, max_length=8)

    @model_validator(mode="after")
    def valid_questions(self):
        if len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError("question IDs must be unique")
        if {q.kind for q in self.questions} != {"single", "multiple", "boolean"}:
            raise ValueError("quiz must include single, multiple and boolean questions")
        refs = set(self.source_refs)
        if len(refs) != len(self.source_refs) or any(not set(q.source_refs) <= refs for q in self.questions):
            raise ValueError("question source refs must belong to unique quiz source refs")
        return self


class Quiz(QuizDraft):
    quiz_id: str
    course_id: str
    unit_id: str
    target_type: TargetType
    target_id: str
    content_version: int = Field(ge=1)
    schema_version: Literal[1] = 1
    created_at: str


class QuizAnswer(Schema):
    question_id: str
    option_ids: list[str]
    skipped: bool
    elapsed_ms: int = Field(strict=True, ge=0, le=MAX_ELAPSED_MS)
    correct: bool
    fast: bool
    points: int = Field(ge=0)
    answered_at: str


class QuizResult(Schema):
    total_score: int
    max_score: int
    correct_count: int
    question_count: int
    skipped_count: int
    fast_count: int
    best_streak: int
    stars: int = Field(ge=0, le=3)
    total_elapsed_ms: int
    scoring_version: Literal[1] = 1


class QuizAttempt(Schema):
    attempt_id: str
    quiz_id: str
    course_id: str
    target_type: TargetType
    target_id: str
    status: Literal["in_progress", "submitted"]
    version: int = Field(ge=1)
    cursor: int = Field(ge=0)
    question_started_at: str
    answers: list[QuizAnswer]
    result: QuizResult | None
    created_at: str
    updated_at: str
    submitted_at: str | None


class QuizSnapshot(Schema):
    course_id: str
    unit_id: str
    target_type: TargetType
    target_id: str
    title: str
    description: str
    quiz: Quiz | None
    generation_run: dict | None
    latest_attempt: QuizAttempt | None
    completed: bool
    version: int = Field(ge=1)


class AttemptSnapshot(Schema):
    quiz: Quiz
    attempt: QuizAttempt
    course: dict


def validate_sources(draft: QuizDraft, context: dict) -> QuizDraft:
    allowed = set(context["allowed_source_refs"])
    if not set(draft.source_refs) <= allowed:
        raise ValueError("quiz source refs must belong to this generation input")
    return draft


def materialize_quiz(draft: QuizDraft, run: dict, timestamp: str) -> dict:
    validate_sources(draft, run["input"])
    return {**draft.model_dump(), "quiz_id": uid("quiz"), "course_id": run["course_id"],
            "unit_id": run["input"]["unit_id"], "target_type": run["target_type"],
            "target_id": run["target_id"], "content_version": 1, "schema_version": 1,
            "created_at": timestamp}


def quiz_context(course: dict, unit: dict, target: dict, target_type: str,
                 scripts: dict[str, dict], *, budget: int = 60000) -> dict:
    """Only real input references are offered; optional cached exam scripts are bounded."""
    result = {"course_id": course["course_id"], "course_title": course["title"],
              "language": course["language"], "unit_id": unit["unit_id"],
              "unit_title": unit["title"], "target_type": target_type,
              "target": target, "sources": [], "allowed_source_refs": []}
    if target_type == "practice":
        script = scripts.get(target["session_id"])
        if script is None:
            raise AppError("lesson_required", "请先准备本课真实讲义，再生成课后练习", 409)
        result["sources"] = [{"ref": f"script:{script['script_id']}", "script": script}]
        result["allowed_source_refs"] = [f"script:{script['script_id']}"] + [
            f"step:{step['step_id']}" for step in script["steps"]]
    else:
        result["sources"].append({"ref": f"unit:{unit['unit_id']}", "title": unit["title"],
                                  "description": unit["description"]})
        result["allowed_source_refs"].append(f"unit:{unit['unit_id']}")
        for lecture in unit["lectures"]:
            for session in lecture["sessions"]:
                ref = f"session:{session['session_id']}"
                result["sources"].append({"ref": ref, "session": {k: session[k] for k in
                    ("session_id", "title", "outline", "key_points")}})
                result["allowed_source_refs"].append(ref)
    size = lambda: len(json.dumps(result, ensure_ascii=False))
    if size() > budget:
        raise AppError("context_too_large", "出题必要来源超过上下文预算，未发送模型请求", 422)
    if target_type == "exam":
        for lecture in unit["lectures"]:
            for session in lecture["sessions"]:
                script = scripts.get(session["session_id"])
                if not script:
                    continue
                source = {"ref": f"script:{script['script_id']}", "script": script}
                refs = [source["ref"]] + [f"step:{s['step_id']}" for s in script["steps"]]
                result["sources"].append(source)
                result["allowed_source_refs"].extend(refs)
                if size() > budget:
                    result["sources"].pop()
                    del result["allowed_source_refs"][-len(refs):]
    return result


def score_answers(answers: list[dict], question_count: int) -> dict:
    """Clone personal rule only: pre-answer streak bonus and dual-path stars."""
    total = streak = best = correct = fast = 0
    for answer in answers:
        if answer["correct"]:
            total += 600 + min(streak * 100, 400) + (200 if answer["fast"] else 0)
            streak += 1
            best = max(best, streak)
            correct += 1
            fast += int(answer["fast"])
        else:
            streak = 0
    maximum = sum(800 + min(i * 100, 400) for i in range(question_count))
    accuracy = correct / question_count if question_count else 0
    accuracy_stars = 3 if accuracy >= .8 else 2 if accuracy >= .55 else 1 if accuracy >= .25 else 0
    ratio = total / maximum if maximum else 0
    deficit = maximum - total
    score_stars = (3 if deficit <= 0 else 2 if deficit == 1 or ratio >= .8
                   else 1 if ratio >= .5 else 0) if maximum else 0
    return {"total_score": total, "max_score": maximum, "correct_count": correct,
            "question_count": question_count, "skipped_count": sum(a["skipped"] for a in answers),
            "fast_count": fast, "best_streak": best, "stars": max(score_stars, accuracy_stars),
            "total_elapsed_ms": sum(a["elapsed_ms"] for a in answers), "scoring_version": 1}
