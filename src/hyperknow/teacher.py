"""Teacher-led lesson contracts and the bounded real-model turn runner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic
from typing import Any, Callable, Literal

from agent_core.context import ContextManager
from agent_core.engine import AgentEvent, run_agent_loop
from agent_core.llm.openai import OpenAIService, to_openai_messages
from agent_core.tools import ToolDefinition, ToolManager
from agent_core.types import AgentContext, AssistantMessage, ToolCall, ToolResult, UserMessage
from pydantic import Field, model_validator

from .domain import AppError, Schema, uid
from .lesson_domain import BoardOperation, validate_board_operations
from .prompts.classroom import TEACHER_TURN_INSTRUCTION


class SourceRef(Schema):
    ref_id: str = Field(min_length=1, max_length=120)
    kind: Literal["keypoint", "claim"]
    title: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=3000)
    url: str = Field(default="", max_length=2000)
    claim_id: str | None = Field(default=None, max_length=120)


class EvidenceItem(Schema):
    item_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    content: str = Field(min_length=1, max_length=2500)
    source_refs: list[str] = Field(min_length=1, max_length=8)


class TeachingOption(Schema):
    option_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    approach: str = Field(min_length=1, max_length=800)
    useful_when: str = Field(min_length=1, max_length=800)
    source_refs: list[str] = Field(min_length=1, max_length=8)


class TeachingBasisDraft(Schema):
    schema_version: Literal[1]
    objectives: list[str] = Field(min_length=1, max_length=8)
    objective_refs: list[str] = Field(min_length=1, max_length=8)
    knowledge: list[EvidenceItem] = Field(min_length=1, max_length=12)
    examples: list[EvidenceItem] = Field(min_length=1, max_length=12)
    derivations: list[EvidenceItem] = Field(default_factory=list, max_length=8)
    misconceptions: list[EvidenceItem] = Field(min_length=1, max_length=12)
    teaching_options: list[TeachingOption] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_items(self):
        items = [item.item_id for group in (self.knowledge, self.examples, self.derivations, self.misconceptions)
                 for item in group]
        if len(items) != len(set(items)):
            raise ValueError("teaching basis item IDs must be unique")
        option_ids = [item.option_id for item in self.teaching_options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("teaching option IDs must be unique")
        return self


class TeacherTurnDraft(Schema):
    action: Literal["explain", "demonstrate", "ask", "check", "adapt", "summarize", "continue"]
    response: str = Field(min_length=1, max_length=8000)
    student_prompt: str = Field(default="", max_length=1600)
    awaits_student: bool = False
    basis_refs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def prompt_matches_wait(self):
        if self.awaits_student and len(self.student_prompt.strip()) < 2:
            raise ValueError("a turn awaiting the student needs a student prompt")
        return self


class TeacherBoard(Schema):
    version: int = Field(ge=1)
    operations: list[BoardOperation] = Field(default_factory=list, max_length=120)


class TeacherTurn(Schema):
    turn_id: str
    run_id: str
    index: int = Field(ge=0)
    student_answer: str | None = Field(default=None, max_length=4000)
    action: str
    response: str
    student_prompt: str
    awaits_student: bool
    board_object_ids: list[str] = Field(default_factory=list, max_length=24)
    basis_refs: list[str] = Field(default_factory=list, max_length=12)
    created_at: str


class BoardToolRequest(Schema):
    operations: list[BoardOperation] = Field(min_length=1, max_length=8)


WHITEBOARD_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operations"],
    "properties": {
        "operations": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "object_id"],
                "properties": {
                    "kind": {"type": "string", "enum": ["text", "list", "code", "formula", "box",
                                                               "arrow", "highlight", "circle", "mermaid", "table", "diagram"]},
                    "content": {"type": "string", "maxLength": 4000},
                    "items": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                    "language": {"type": "string", "maxLength": 40},
                    "object_id": {"type": "string", "minLength": 1, "maxLength": 80},
                    "target_ids": {"type": "array", "maxItems": 24, "items": {"type": "string"}},
                    "columns": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                    "rows": {"type": "array", "maxItems": 16, "items": {"type": "array", "items": {"type": "string"}}},
                    "nodes": {"type": "array", "maxItems": 16, "items": {
                        "type": "object", "additionalProperties": False, "required": ["id", "label"],
                        "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 80},
                                       "label": {"type": "string", "minLength": 1, "maxLength": 300}}
                    }},
                    "edges": {"type": "array", "maxItems": 24, "items": {
                        "type": "object", "additionalProperties": False, "required": ["from_id", "to_id"],
                        "properties": {"from_id": {"type": "string", "minLength": 1, "maxLength": 80},
                                       "to_id": {"type": "string", "minLength": 1, "maxLength": 80},
                                       "label": {"type": "string", "maxLength": 200}}
                    }}
                }
            }
        }
    }
}


class BoardLedger:
    """A per-turn board transaction; no operation is durable until the turn commits."""

    def __init__(self, operations: list[dict] | list[BoardOperation] = ()):  # noqa: D401
        self.operations = [BoardOperation.model_validate(operation).model_dump()
                           for operation in operations]
        self.initial_count = len(self.operations)
        validate_board_operations(self.operations)

    @property
    def additions(self) -> list[dict]:
        return self.operations[self.initial_count:]

    def present(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            request = BoardToolRequest.model_validate(arguments)
            additions = [operation.model_dump() for operation in request.operations]
            validate_board_operations([*self.operations, *additions])
            existing = {operation["object_id"] for operation in self.operations}
            if existing.intersection(operation["object_id"] for operation in additions):
                raise ValueError("whiteboard object IDs must not be reused")
            self.operations.extend(additions)
            return ToolResult(True, {"accepted_object_ids": [item["object_id"] for item in additions],
                                     "board_object_count": len(self.operations)})
        except Exception as exc:
            return ToolResult(False, error=f"whiteboard operation rejected: {exc}")


def whiteboard_tool(ledger: BoardLedger) -> ToolDefinition:
    return ToolDefinition(
        name="whiteboard_present",
        description=(
            "在当前课堂白板上呈现一批增量视觉内容。仅在视觉内容能帮助当前教学判断时调用；"
            "程序会校验安全操作、唯一对象身份和对已有对象的引用。不能执行代码、HTML、网络请求或修改课程外数据。"
            "每次调用只提交白板候选操作，最终教师回合成功后才保存。"
        ),
        parameters=WHITEBOARD_TOOL_SCHEMA,
        handler=ledger.present,
        is_read_only=True,
        requires_approval=False,
    )


def validate_basis(draft: TeachingBasisDraft, context: dict) -> None:
    allowed = set(context.get("basis_allowed_refs", []))
    if not set(draft.objective_refs) <= allowed:
        raise ValueError("teaching objectives contain an unknown source reference")
    for group in (draft.knowledge, draft.examples, draft.derivations, draft.misconceptions,
                  draft.teaching_options):
        for item in group:
            refs = item.source_refs
            if not refs or not set(refs) <= allowed:
                raise ValueError("teaching basis contains an unknown or missing source reference")


def materialize_basis(draft: TeachingBasisDraft, run: dict, context: dict, timestamp: str) -> dict:
    validate_basis(draft, context)
    references = [SourceRef.model_validate(item).model_dump() for item in context.get("basis_sources", [])]
    return {"basis_id": uid("basis"), "session_id": run["session_id"], "course_id": run["course_id"],
            "version": 1, "created_at": timestamp, **draft.model_dump(), "references": references}


def validate_turn(draft: TeacherTurnDraft, input_data: dict) -> None:
    allowed = set(input_data.get("basis_refs", []))
    if any(ref not in allowed for ref in draft.basis_refs):
        raise ValueError("teacher turn cites a source outside the prepared basis")


@dataclass(frozen=True)
class TeacherGenerationResult:
    draft: TeacherTurnDraft
    operations: list[dict]
    trace: list[dict]
    provider_stop_reason: str


def _message_record(message: Any) -> dict:
    result = {"role": message.role}
    if message.role == "user":
        result["content"] = message.content
    elif message.role == "assistant":
        result.update(content=message.content, stop_reason=message.stop_reason,
                      tool_calls=[{"id": call.id, "name": call.name, "arguments": call.arguments}
                                  for call in message.tool_calls])
    else:
        result.update(tool_call_id=message.tool_call_id, content=message.content, is_error=message.is_error)
    return result


class _RecordingLLM:
    def __init__(self, provider: OpenAIService, db, run_id: str, stopping: Callable[[], bool], trace: list[dict]):
        self.provider, self.db, self.run_id, self.stopping, self.trace = provider, db, run_id, stopping, trace
        self.index = 0

    def complete(self, context: AgentContext) -> AssistantMessage:
        if self.stopping():
            return AssistantMessage(stop_reason="aborted")
        started = monotonic()
        response = self.provider.complete(context)
        self.db.record_call(self.run_id, {
            "kind": "teacher_turn", "call_index": self.index, "system_prompt": context.system_prompt,
            "messages": [_message_record(message) for message in context.messages],
            "wire_messages": to_openai_messages(context), "tools": context.tools,
            "response": response.content, "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments} for call in response.tool_calls
            ], "model": response.model, "provider": response.provider, "usage": response.usage,
            "stop_reason": response.stop_reason, "error": response.error_message,
            "elapsed_ms": int((monotonic() - started) * 1000), "created_at": _now(),
        })
        self.index += 1
        return response


def _now() -> str:
    from .storage import now
    return now()


class TeacherGenerator:
    """Run one student-visible turn with bounded internal model/tool rounds."""

    def __init__(self, settings, db, stopping):
        self.settings, self.db, self.stopping = settings, db, stopping

    def generate(self, run: dict) -> TeacherGenerationResult:
        input_data = run["input"]
        ledger = BoardLedger(input_data.get("board", {}).get("operations", []))
        trace: list[dict] = []

        def is_aborted() -> bool:
            if self.stopping.is_set():
                return True
            try:
                return self.db.get_run(run["run_id"])["status"] != "generating"
            except AppError:
                return True

        def observe(event: AgentEvent):
            if event.type not in {"tool_start", "tool_end", "approval_required"}:
                return
            call = event.data.get("tool_call")
            trace.append({"event": event.type, "tool_call": {
                "id": call.id, "name": call.name, "arguments": call.arguments} if isinstance(call, ToolCall) else None,
                "result": getattr(event.data.get("result"), "content", None)})

        system = TEACHER_TURN_INSTRUCTION + "\n仅输出符合下述JSON Schema的JSON对象：\n" + json.dumps(
            TeacherTurnDraft.model_json_schema(), ensure_ascii=False)
        context = ContextManager(system)
        context.append_message(UserMessage(json.dumps(input_data, ensure_ascii=False)))
        provider = None
        try:
            provider = OpenAIService(model=run["model"], api_key=self.settings.api_key,
                                     base_url=self.settings.base_url, timeout=self.settings.timeout,
                                     max_retries=0, max_output_tokens=8192)
            llm = _RecordingLLM(provider, self.db, run["run_id"], is_aborted, trace)
            tools = ToolManager([whiteboard_tool(ledger)])
            result = run_agent_loop(context, llm, tools, max_turns=6,
                                    is_aborted=is_aborted, emit=observe, token_counter=None,
                                    scheduler=None)
            for repair_attempt in range(2):
                if result.aborted or result.response.stop_reason != "stop":
                    reason = result.response.error_message or result.response.stop_reason
                    raise AppError("teacher_runtime_stop", f"教师回合因运行限制停止：{reason}，未提交本回合板书", 502, True)
                if result.response.content.strip():
                    try:
                        draft = TeacherTurnDraft.model_validate(json.loads(result.response.content))
                        validate_turn(draft, input_data)
                    except (ValueError, TypeError):
                        draft = None
                    if draft is not None:
                        return TeacherGenerationResult(draft, ledger.additions, trace, result.response.stop_reason)
                if repair_attempt == 1:
                    raise AppError("teacher_output_invalid", "教师回合在一次结构修复后仍未通过输出契约校验，未提交本回合板书", 502, True)
                from .generation import bounded_repair_message
                context.append_message(bounded_repair_message(
                    result.response.content, "TeacherTurnDraft JSON schema or basis reference validation failed",
                ))
                result = run_agent_loop(context, llm, tools, max_turns=3,
                                        is_aborted=is_aborted, emit=observe, token_counter=None,
                                        scheduler=None)
        finally:
            if provider is not None:
                provider.close()
