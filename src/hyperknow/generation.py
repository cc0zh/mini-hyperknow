"""Real provider calls, typed content and one bounded schema repair."""

import json
from threading import Event
from time import monotonic

from pydantic import ValidationError

from agent_core.llm.openai import OpenAIService
from agent_core.tokens import TokenEstimator
from agent_core.types import AgentContext, UserMessage

from .config import Settings
from .domain import AppError, Clarification
from .blueprint_domain import (BlueprintDraft, UnitExpansionDraft, planning_context,
                               validate_blueprint, validate_expansion)
from .lesson_domain import BoardScriptDraft, LessonAnswer, validate_lesson_coverage
from .model_output import validate_model_output
from .teacher import TeachingBasisDraft, TeacherGenerator, validate_basis
from .quiz_domain import QuizDraft, validate_sources
from .prompts.classroom import (BOARD_SCRIPT_INSTRUCTION, LESSON_ANSWER_INSTRUCTION,
                                 LESSON_BASIS_INSTRUCTION)
from .prompts.course import BLUEPRINT_INSTRUCTION, CLARIFICATION_INSTRUCTION, UNIT_INSTRUCTION
from .prompts.quiz import QUIZ_INSTRUCTION
from .storage import Database, now


PLANNING_CONTEXT_BUDGET = 64000
PLANNING_OUTPUT_RESERVE = 8192
PLANNING_REPAIR_RESERVE = 12000


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def bounded_repair_message(response: str, error: str, *, budget: int = PLANNING_REPAIR_RESERVE) -> UserMessage:
    """Bound the *added request bytes*, including nested JSON escaping/framing.

    The complete response remains in model_calls. These are explicitly labelled
    excerpts, never a patch that depends on having the full previous response.
    """
    payload = {
        "instruction": "上次结果未通过结构校验。以下错误及原结果可能被截断或省略，"
                       "请依据原始输入和Schema重新生成完整JSON对象，不要只输出补丁或续写摘录。",
        "validation_error_excerpt": "", "validation_error_truncated": bool(error),
        "response_excerpt": "", "response_truncated": bool(response), "response_omitted": bool(response),
    }
    estimator = TokenEstimator()
    anchor = UserMessage("")
    baseline = estimator.estimate(AgentContext("", [anchor])).input_tokens

    def message():
        return UserMessage(json.dumps(payload, ensure_ascii=False))

    def size():
        return estimator.estimate(AgentContext("", [anchor, message()])).input_tokens - baseline

    if size() > budget:
        raise ValueError("repair budget cannot fit excerpt labels and regeneration instruction")

    def fit(text: str, key: str, truncated_key: str, limit: int):
        raw = text.encode("utf-8")

        def set_excerpt(length: int):
            excerpt = raw[:length].decode("utf-8", errors="ignore")
            payload[key] = excerpt
            payload[truncated_key] = len(excerpt.encode("utf-8")) < len(raw)
            if key == "response_excerpt":
                payload["response_omitted"] = bool(text) and not excerpt

        low, high = 0, len(raw)
        while low < high:
            middle = (low + high + 1) // 2
            set_excerpt(middle)
            if size() <= limit:
                low = middle
            else:
                high = middle - 1
        set_excerpt(low)

    # The error gets at most 6000 *serialized* bytes, not 6000 characters.
    fit(error, "validation_error_excerpt", "validation_error_truncated", min(budget, size() + 6000))
    fit(response, "response_excerpt", "response_truncated", budget)
    return message()


class Generator:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db
        self.stopping = Event()

    def require_active(self, run_id: str, phase: str):
        run = self.db.get_run(run_id)
        active = run["status"] == phase
        if run.get("kind", "course") == "course" and phase != "clarifying":
            active = run["status"] == "generating" and run.get("stage") == phase
        if self.stopping.is_set() or not active:
            raise AppError("run_inactive", "任务已取消或中断，未发起后续模型调用", 409)

    def generate(self, run: dict, phase: str):
        schema = Clarification
        kind = run.get("kind", "course")
        if kind == "quiz":
            schema = QuizDraft
            instruction = QUIZ_INSTRUCTION
            user = run["input"]
        elif kind == "lesson":
            schema = BoardScriptDraft
            instruction = BOARD_SCRIPT_INSTRUCTION
            user = run["input"]
        elif kind == "question":
            schema = LessonAnswer
            instruction = LESSON_ANSWER_INSTRUCTION
            user = run["input"]
        elif kind == "lesson_basis":
            schema = TeachingBasisDraft
            instruction = LESSON_BASIS_INSTRUCTION
            user = run["input"]
        elif kind == "teacher_turn":
            return TeacherGenerator(self.settings, self.db, self.stopping).generate(run)
        elif phase == "clarifying":
            instruction = CLARIFICATION_INSTRUCTION
            user = {"goal": run["goal"]}
        elif phase == "blueprint":
            schema = BlueprintDraft
            instruction = BLUEPRINT_INSTRUCTION
            planning_course = self.db.get_course(run["course_id"]) if run.get("course_id") else None
        elif phase == "units":
            schema = UnitExpansionDraft
            instruction = UNIT_INSTRUCTION
            planning_course = self.db.get_course(run["course_id"])
        else:
            raise AppError("state_conflict", "未知课程生成阶段", 409)
        system = instruction + "\n仅输出符合下述JSON Schema的JSON对象，不输出Markdown或解释：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        planning = kind == "course" and phase in {"blueprint", "units"}
        if planning:
            overhead = TokenEstimator().estimate(AgentContext(system, [UserMessage("")])).input_tokens
            budget = (PLANNING_CONTEXT_BUDGET - overhead - PLANNING_OUTPUT_RESERVE
                      - PLANNING_REPAIR_RESERVE - 512)
            user = planning_context(run, planning_course, budget=budget)
        messages = [UserMessage(json.dumps(user, ensure_ascii=False))]
        for attempt in range(2):
            self.require_active(run["run_id"], phase)
            context = AgentContext(system, messages.copy())
            if planning:
                reserve = PLANNING_OUTPUT_RESERVE + (PLANNING_REPAIR_RESERVE if attempt == 0 else 0)
                estimate = TokenEstimator().estimate(context, reserve_output_tokens=reserve)
                if attempt == 0 and estimate.total_tokens > PLANNING_CONTEXT_BUDGET:
                    # Account for JSON message escaping as well as the input object's bytes.
                    budget -= estimate.total_tokens - PLANNING_CONTEXT_BUDGET + 256
                    user = planning_context(run, planning_course, budget=budget)
                    messages = [UserMessage(json.dumps(user, ensure_ascii=False))]
                    context = AgentContext(system, messages.copy())
                    estimate = TokenEstimator().estimate(context, reserve_output_tokens=reserve)
                if estimate.total_tokens > PLANNING_CONTEXT_BUDGET:
                    raise AppError("context_too_large", "课程规划请求含结构与修复预留后超过保守UTF-8预算，未发起模型请求", 422)
            started = monotonic()
            record = {"phase": phase, "kind": kind, "attempt": attempt + 1,
                      "requested_model": run["model"], "model": run["model"], "provider": "openai",
                      "prompt_version": f"{kind}-{phase}-v{2 if kind == 'lesson' or phase in {'clarifying', 'blueprint', 'units'} else 1}",
                      "schema_version": 2 if kind == "lesson" or phase in {"clarifying", "blueprint", "units"} else 1,
                      "system_prompt": system, "messages": [m.content for m in messages],
                      "input_basis": user, "started_at": now()}
            if planning:
                record["context_budget"] = {"utf8_upper_bound": PLANNING_CONTEXT_BUDGET,
                    "estimated_input_tokens": estimate.input_tokens, "is_estimate": True,
                    "output_reserve": PLANNING_OUTPUT_RESERVE,
                    "repair_reserve": PLANNING_REPAIR_RESERVE if attempt == 0 else 0}
            provider = None
            try:
                self.require_active(run["run_id"], phase)
                provider = OpenAIService(model=run["model"], api_key=self.settings.api_key,
                                         base_url=self.settings.base_url, timeout=self.settings.timeout,
                                         max_retries=0, max_output_tokens=PLANNING_OUTPUT_RESERVE if planning else None)
                self.require_active(run["run_id"], phase)
                response = provider.complete(context)
            except AppError:
                raise
            except Exception as exc:
                record.update(error="model_request_failed", provider_error=type(exc).__name__,
                              response=None, usage=None, stop_reason="error",
                              elapsed_ms=int((monotonic() - started) * 1000), created_at=now())
                self.db.record_call(run["run_id"], record)
                raise AppError("model_request_failed", "真实模型请求未完成，请检查配置或网络后重试", 502, True) from exc
            finally:
                if provider is not None:
                    provider.client.close()
            record.update(model=response.model or run["model"], provider=response.provider,
                          provider_error=response.error_message, response=response.content, usage=response.usage,
                          elapsed_ms=int((monotonic() - started) * 1000), stop_reason=response.stop_reason,
                          created_at=now())
            if response.stop_reason != "stop" or not response.content.strip():
                record["error"] = "model_request_failed"
                self.db.record_call(run["run_id"], record)
                raise AppError("model_request_failed", "模型请求失败或未返回完整内容，请检查配置、额度或网络后重试", 502, True)
            try:
                raw = parse_json(response.content)
                result = validate_model_output(schema, raw) if kind == "course" else schema.model_validate(raw)
                if kind == "quiz":
                    validate_sources(result, user)
                elif kind == "lesson":
                    validate_lesson_coverage(result, user)
                elif kind == "lesson_basis":
                    validate_basis(result, user)
                elif kind == "course" and phase == "blueprint":
                    validate_blueprint(result, user)
                elif kind == "course" and phase == "units":
                    validate_expansion(result, user["unit"], user["unit_session_budget"])
            except (ValueError, ValidationError) as exc:
                record["error"] = "content_validation_failed"
                self.db.record_call(run["run_id"], record)
                if attempt:
                    raise AppError("content_validation_failed", "模型内容在一次修复后仍不符合内容结构，本次未保存生成结果", 502, True) from exc
                self.require_active(run["run_id"], phase)
                messages.append(bounded_repair_message(response.content, str(exc)))
            else:
                record["validated"] = True
                self.db.record_call(run["run_id"], record)
                return result
        raise RuntimeError("unreachable generation state")
