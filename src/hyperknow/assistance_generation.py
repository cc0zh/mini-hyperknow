"""Recorded teaching execution with optional trusted skills and bounded tools."""

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
from time import monotonic

from pydantic import ValidationError

from agent_core import Agent
from agent_core.context import ContextManager
from agent_core.llm.openai import OpenAIService
from agent_core.skills import SkillRegistry
from agent_core.tokens import TokenEstimator
from agent_core.tools import ToolDefinition, ToolManager
from agent_core.types import AgentContext, ToolResult

from .assistance_domain import ARTIFACT_SCHEMAS, ArtifactDraft, TeachingResponse, ContinuationState
from .config import Settings
from .domain import AppError
from .generation import bounded_repair_message, parse_json
from .prompts.assistance import teaching_prompt
from .storage import now

CONTEXT_BUDGET = 64000
OUTPUT_RESERVE = 8192
MAX_MODEL_CALLS = 9
TRUSTED_SKILLS: tuple[str, ...] = ()


def teaching_output_limit(inputs: dict, output_reserve: int) -> int | None:
    # Context headroom is not a provider output cap. Omit that cap for an
    # explicit animation turn; ordinary/model-selected teaching stays bounded.
    if ("animation" in (inputs.get("requested_artifacts") or [])
            and "animation" not in (inputs.get("forbidden_artifacts") or [])):
        return None
    return output_reserve


def teaching_schema() -> dict:
    schema = TeachingResponse.model_json_schema()
    # Models must always provide an explicit teaching-state envelope.
    schema["required"] = list(schema["properties"])
    return schema


def continuation_state(inputs: dict) -> dict | None:
    if inputs["action"] != "continue":
        return None
    if "continuation_state" not in inputs:
        raise AppError("invalid_continuation", "当前没有等待继续的教学步骤", 409)
    return ContinuationState.model_validate(inputs["continuation_state"]).model_dump()


def validate_teaching(content: str, expected_state: dict | None) -> TeachingResponse:
    data = parse_json(content)
    if not isinstance(data, dict) or not set(teaching_schema()["required"]) <= set(data):
        raise ValueError("All six teaching response fields are required; explicitly provide empty questions/plan.")
    response = TeachingResponse.model_validate(data)
    if expected_state and (response.plan != expected_state["plan"] or
                           response.current_step != expected_state["current_step"]):
        raise ValueError("A continuation must preserve the exact saved plan and advance current_step by one.")
    return response


def build_skill_snapshots() -> dict:
    return SkillRegistry.from_directory(Path(__file__).parent / "skills", TRUSTED_SKILLS).snapshot()


def inline_schema(schema: dict) -> dict:
    """Expand local Pydantic refs into the core's fail-closed schema subset."""
    definitions = schema.get("$defs", {})

    def expand(node):
        if isinstance(node, list):
            return [expand(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            key = node["$ref"].removeprefix("#/$defs/")
            if node["$ref"] != f"#/$defs/{key}" or key not in definitions:
                raise ValueError("unsupported schema reference")
            return expand({**definitions[key], **{k: v for k, v in node.items() if k != "$ref"}})
        return {("enum" if key == "const" else key): ([value] if key == "const" else expand(value))
                for key, value in node.items() if key != "$defs"}

    return expand(schema)


class TeachingContext(ContextManager):
    """Project staged HTML out of follow-up requests, never out of the audit."""

    def get_context(self, tool_definitions=()) -> AgentContext:
        context = super().get_context(tool_definitions)
        succeeded = {m.tool_call_id for m in context.messages
                     if m.role == "tool_result" and not m.is_error}
        for message in context.messages:
            if message.role != "assistant" or message.stop_reason != "tool_use":
                continue
            for call in message.tool_calls:
                if call.name != "create_animation" or call.id not in succeeded:
                    continue
                html = call.arguments["data"]["html"]
                raw = html.encode("utf-8")
                marker = ("[HTML omitted from follow-up context after successful create_animation; "
                          "full source remains staged and in the original model-call audit. "
                          f"utf8_bytes={len(raw)}, sha256={sha256(raw).hexdigest()}]")
                if len(marker.encode("utf-8")) < len(raw):
                    # get_context returns a deep copy; live history, audit and
                    # the staged artifact remain exact, including whitespace.
                    call.arguments["data"]["html"] = marker
        return context


class RecordedTeachingModel:
    def __init__(self, provider, owner):
        self.provider, self.owner = provider, owner
        self.calls = 0

    def complete(self, context: AgentContext):
        owner = self.owner
        owner.require_active()
        if self.calls >= MAX_MODEL_CALLS:
            raise AppError("assistance_budget_exceeded", "教学已达到本轮调用上限，请明确重试或简化问题", 422, True)
        estimate = TokenEstimator().estimate(context, reserve_output_tokens=owner.output_reserve)
        if estimate.total_tokens > CONTEXT_BUDGET:
            raise AppError("context_too_large", "本轮上下文与技能超过预算，请缩短问题或新建会话", 422)
        self.calls += 1
        started = monotonic()
        response = self.provider.complete(context)
        owner.db.record_call(owner.run["run_id"], {
            "kind": "assistance", "phase": owner.run.get("stage", "generating"), "attempt": self.calls,
            "requested_model": owner.run["model"], "model": response.model, "provider": response.provider,
            "prompt_version": "assistance-v2", "schema_version": 2,
            "system_prompt": context.system_prompt, "messages": [asdict(m) for m in context.messages],
            "tools": context.tools, "input_basis": owner.run["input"], "skill_uses": deepcopy(owner.used),
            "response": asdict(response), "usage": response.usage, "stop_reason": response.stop_reason,
            "context_budget": {"utf8_upper_bound": CONTEXT_BUDGET, "estimated_input_tokens": estimate.input_tokens,
                               "output_reserve": owner.output_reserve,
                               "max_output_tokens": self.provider.max_output_tokens, "is_estimate": True},
            "elapsed_ms": int((monotonic() - started) * 1000), "created_at": now(),
        })
        owner.require_active()
        return response


class AssistantGenerator:
    """One run owns its skills, tool results and budget; no shared mutable chat."""

    def __init__(self, settings: Settings, db, stopping: Event, changed=None, *,
                 output_reserve: int = OUTPUT_RESERVE):
        if type(output_reserve) is not int or not 1 <= output_reserve < CONTEXT_BUDGET:
            raise ValueError("output_reserve must be a positive integer below the context budget")
        self.settings, self.db, self.stopping, self.changed = settings, db, stopping, changed
        self.output_reserve = output_reserve
        self.run = {}
        self.used: list[dict] = []
        self.artifacts: list[dict] = []
        self.persistence_failed = False
        self.deadline = 0.0

    def require_active(self):
        if self.persistence_failed:
            raise AppError("assistance_storage_failed", "教学过程未确认保存，已停止后续请求", 503, True)
        if self.stopping.is_set() or self.db.get_run(self.run["run_id"])["status"] != "generating":
            raise AppError("run_inactive", "本轮已取消或中断，未发起后续调用", 409)
        if monotonic() > self.deadline:
            raise AppError("assistance_budget_exceeded", "本轮教学已达到执行时限，请显式重试", 422, True)

    def _step(self, data: dict):
        self.require_active()
        try:
            self.db.assistance_step(self.run["run_id"], {**data, "created_at": now()})
        except Exception:
            self.persistence_failed = True
            raise
        if self.changed:
            self.changed(self.db.get_run(self.run["run_id"]))

    def _load_skill(self, args: dict):
        self.require_active()
        skill = self.registry.load(args["name"])
        metadata = {k: skill[k] for k in ("name", "version", "sha256")}
        if metadata not in self.used:
            self._step({"tool": "get_skills", "status": "ready", **metadata})
            self.used.append(metadata)
        return ToolResult(True, data=skill)

    def _create(self, kind: str, args: dict):
        self.require_active()
        requested = self.run["input"].get("requested_artifacts") or []
        if requested and kind != requested[0]:
            return ToolResult(False, error=f"This turn must create a {requested[0]} artifact, not a {kind}.")
        refused = self.run["input"].get("forbidden_artifacts") or []
        if kind in refused:
            return ToolResult(False, error=f"The learner explicitly refused a {kind} this turn; reply in text instead.")
        if self.artifacts:
            return ToolResult(False, error="One artifact per teaching turn. Teach in the response, not with a second tool call.")
        draft = ArtifactDraft(kind=kind, **args).model_dump()
        self._step({"tool": f"create_{kind}", "status": "ready", "title": draft["title"]})
        self.artifacts.append(draft)
        return ToolResult(True, data={"kind": kind, "title": draft["title"],
                                     "notice": "Validated and staged; finalize the teaching response to save."})

    def tools(self):
        definitions = []
        catalog = self.registry.catalog()
        if catalog:
            definitions.append(ToolDefinition("get_skills",
                "Optionally load a relevant trusted skill by exact catalog name. "
                "Not required for ordinary teaching or artifacts; never grants tools or runs scripts.",
                {"type": "object", "properties": {"name": {"type": "string", "enum": [s["name"] for s in catalog]}},
                 "required": ["name"], "additionalProperties": False}, self._load_skill))
        for kind, schema in ARTIFACT_SCHEMAS.items():
            data_schema = inline_schema(schema.model_json_schema())
            hint = {
                "flashcards": "Use accurate question/answer pairs for repeated recall, usually 3-6 cards.",
                "quiz": "Use self-check questions with consistent correct option IDs and explanations, usually 2-4.",
                "diagram": "Use valid Mermaid without configuration directives, plus a short caption for relationships or processes.",
                "whiteboard": "Use ordered pages/columns, usually 3-8 steps, with concrete narration and 1-6 operations per step. "
                    "Only text/list/code/formula/box/arrow/highlight/mermaid; list uses items, others content, only code has language.",
                "animation": "Use complete self-contained HTML/CSS/JavaScript with native DOM/Canvas/SVG and clear controls. "
                    "No external scripts, fonts, images, iframe, network, eval, form submission, download, navigation or parent access.",
            }[kind]
            definitions.append(ToolDefinition(f"create_{kind}",
                f"Create a {kind} learning artifact from this conversation only. {hint} "
                "No network, files, execution or course changes. At most one artifact exists per turn, "
                "so call this only if the artifact is genuinely the best teaching move, then finalize the teaching JSON.",
                {"type": "object", "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200}, "data": data_schema},
                 "required": ["title", "data"], "additionalProperties": False},
                lambda args, kind=kind: self._create(kind, args)))
        return ToolManager(definitions, max_output_chars=13000)

    def generate(self, run: dict) -> dict:
        self.run = run
        self.used = []
        self.artifacts = []
        self.persistence_failed = False
        self.deadline = monotonic() + 360
        self.registry = SkillRegistry(run["input"]["skill_snapshots"])
        self.require_active()
        system = teaching_prompt(self.registry.catalog(), teaching_schema())
        # Immutable snapshots live in SQLite, but only their metadata is exposed
        # initially. The selected body enters context through get_skills.
        inputs = {k: v for k, v in run["input"].items() if k != "skill_snapshots"}
        expected_state = continuation_state(inputs)
        if expected_state:
            inputs["required_continuation_state"] = expected_state
        with OpenAIService(model=run["model"], api_key=self.settings.api_key,
                           base_url=self.settings.base_url, timeout=self.settings.timeout,
                           max_retries=0,
                           max_output_tokens=teaching_output_limit(inputs, self.output_reserve)) as provider:
            model = RecordedTeachingModel(provider, self)
            context = TeachingContext(system, max_context_tokens=CONTEXT_BUDGET,
                                      reserve_output_tokens=self.output_reserve, compression_threshold=1)
            agent = Agent(model, tools=self.tools(), context=context, max_turns=8,
                          tool_mode="sequential")
            result = agent.run(json.dumps(inputs, ensure_ascii=False)
                + "\n本轮最终回复必须是完整的6字段JSON对象，不可用普通Markdown代替；"
                "若有required_continuation_state，必须保留原plan并使用指定current_step，不得新增第三步或从头讲。")
            if result.response.stop_reason != "stop":
                raise AppError("assistance_generation_failed", "真实教学请求未完成，请检查配置、预算或显式重试", 502, True)
            requested = inputs.get("requested_artifacts") or []
            if requested and not any(a["kind"] == requested[0] for a in self.artifacts):
                raise AppError("artifact_not_created", "你点名了教学产物，但模型没有创建，未保存完成结果", 502, True)
            response = result.response
            for attempt in range(2):
                self.require_active()
                try:
                    draft = validate_teaching(response.content, expected_state)
                    return {"response": draft.model_dump(), "artifacts": deepcopy(self.artifacts),
                            "skill_uses": deepcopy(self.used)}
                except (ValueError, ValidationError) as exc:
                    if attempt:
                        raise AppError("assistance_validation_failed", "教学内容一次修复后仍不符合结构要求", 502, True) from exc
                    # Only formatting may be repaired; never repeat artifact tools.
                    response = model.complete(AgentContext(
                        "只修复教学回复格式，保持原教学内容，不声称创建新产物。仅输出JSON：\n"
                        + json.dumps(teaching_schema(), ensure_ascii=False)
                        + "\n每个字段都必填。以下为原会话及本轮输入，只用于修复结构和教学状态，不添加新教学内容：\n"
                        + json.dumps(inputs, ensure_ascii=False)
                        + "\n若required_continuation_state.is_last_step为true，不得等待continue；"
                        "没有实际问题时questions=[]且waiting_for=none。",
                        [bounded_repair_message(response.content, str(exc), budget=16000)]))
                    if response.stop_reason != "stop":
                        raise AppError("assistance_generation_failed", "教学格式修复未完成", 502, True)
        raise RuntimeError("unreachable teaching state")
