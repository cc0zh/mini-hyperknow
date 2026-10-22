"""The V0 LLM -> tool -> context execution loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .context import ContextManager
from .llm.base import LLMService
from .tools import ToolManager
from .types import AssistantMessage, ToolResultMessage


@dataclass(frozen=True)
class AgentEvent:
    type: str
    data: dict[str, Any]


@dataclass(frozen=True)
class LoopResult:
    response: AssistantMessage
    turns: int
    aborted: bool = False


def run_agent_loop(
    context: ContextManager,
    llm: LLMService,
    tools: ToolManager,
    *,
    emit: Callable[[AgentEvent], None] | None = None,
    max_turns: int = 20,
    is_aborted: Callable[[], bool] | None = None,
) -> LoopResult:
    """Run until the model returns no tool calls, an error, or cancellation.

    ``max_turns`` is a safety valve for a misbehaving provider; V0 otherwise
    follows the model's stop signal rather than imposing a task policy.
    """
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    is_aborted = is_aborted or (lambda: False)

    for turn in range(1, max_turns + 1):
        if is_aborted():
            return LoopResult(AssistantMessage(stop_reason="aborted"), turn - 1, aborted=True)
        _emit(emit, "turn_start", turn=turn)
        assistant = llm.complete(context.get_context(tools.definitions()))
        context.append_message(assistant)
        _emit(emit, "assistant_message", message=assistant)

        if assistant.stop_reason in {"error", "aborted"}:
            for call in assistant.tool_calls:
                result = ToolResultMessage(
                    call.id,
                    f"Tool call was not completed because the assistant stopped with {assistant.stop_reason}.",
                    is_error=True,
                )
                context.append_message(result)
                _emit(emit, "tool_end", tool_call=call, result=result)
            _emit(emit, "turn_end", turn=turn, stop_reason=assistant.stop_reason)
            return LoopResult(assistant, turn, aborted=assistant.stop_reason == "aborted")

        if not assistant.tool_calls:
            _emit(emit, "turn_end", turn=turn, stop_reason=assistant.stop_reason)
            return LoopResult(assistant, turn)

        for call in assistant.tool_calls:
            _emit(emit, "tool_start", tool_call=call)
            result = tools.execute(call)
            context.append_message(result)
            _emit(emit, "tool_end", tool_call=call, result=result)
        _emit(emit, "turn_end", turn=turn, stop_reason="tool_use")

    exhausted = AssistantMessage(
        content="Agent stopped after reaching the maximum number of turns.",
        stop_reason="error",
        error_message="max_turns exceeded",
    )
    return LoopResult(exhausted, max_turns)


def _emit(emit: Callable[[AgentEvent], None] | None, event_type: str, **data: Any) -> None:
    if emit is not None:
        emit(AgentEvent(event_type, data))
