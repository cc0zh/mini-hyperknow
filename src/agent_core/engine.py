"""Budget-aware LLM -> scheduled tools -> durable context execution loop."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable
import warnings

from .context import ContextManager
from .compression import ContextBudgetExceeded
from .llm.base import LLMService
from .tokens import TokenCounter
from .tools import ToolManager, ToolScheduler
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
    max_turns: int | None = 20,
    is_aborted: Callable[[], bool] | None = None,
    scheduler: ToolScheduler | None = None,
    token_counter: TokenCounter | None = None,
    should_stop_after_turn: Callable[[int], bool] | None = None,
) -> LoopResult:
    """Run until the model returns no tool calls, an error, or cancellation.

    ``max_turns=None`` delegates the safety valve to ``should_stop_after_turn``.
    Synchronous network requests cannot be interrupted, but their late results
    must never start tools or another paid call after cancellation.
    """
    if max_turns is not None and (isinstance(max_turns, bool)
                                  or not isinstance(max_turns, int) or max_turns < 1):
        raise ValueError("max_turns must be a positive integer or None")
    is_aborted = is_aborted or (lambda: False)
    scheduler = scheduler or ToolScheduler(
        tools, emit=lambda event_type, **data: _emit(emit, event_type, **data),
        is_aborted=is_aborted,
    )
    _emit(emit, "agent_start")

    def finish(response: AssistantMessage, turns: int, *, aborted: bool = False) -> LoopResult:
        _emit(emit, "agent_end", response=response, turns=turns, aborted=aborted)
        return LoopResult(response, turns, aborted)

    turn = 0
    while max_turns is None or turn < max_turns:
        if is_aborted():
            return finish(AssistantMessage(stop_reason="aborted"), turn, aborted=True)
        try:
            prepared = context.prepare(tools.definitions(), is_aborted=is_aborted)
        except ContextBudgetExceeded as exc:
            aborted = is_aborted()
            return finish(AssistantMessage(
                stop_reason="aborted" if aborted else "error",
                error_message=str(exc),
            ), turn, aborted=aborted)
        if is_aborted():
            return finish(AssistantMessage(stop_reason="aborted"), turn, aborted=True)
        _emit(emit, "turn_start", turn=turn + 1)
        if is_aborted():
            _emit(emit, "turn_end", turn=turn + 1, stop_reason="aborted")
            return finish(AssistantMessage(stop_reason="aborted"), turn, aborted=True)
        turn += 1
        assistant = llm.complete(prepared)
        if token_counter is not None:
            token_counter.record(assistant.usage)
        previous_ids = {
            call.id for message in prepared.messages if message.role == "assistant"
            for call in message.tool_calls
        }
        current_ids = [call.id for call in assistant.tool_calls]
        if (len(set(current_ids)) != len(current_ids) or previous_ids.intersection(current_ids)
                or any(not call.id or not call.name or not isinstance(call.arguments, dict)
                       for call in assistant.tool_calls)):
            assistant = AssistantMessage(
                stop_reason="error", error_message="invalid or reused tool call identity",
                model=assistant.model, provider=assistant.provider, usage=assistant.usage,
            )
        context.append_message(assistant)
        _emit(emit, "assistant_message", message=assistant)

        aborted = is_aborted() or assistant.stop_reason == "aborted"
        if assistant.stop_reason == "error" or aborted:
            for call in assistant.tool_calls:
                result = ToolResultMessage(
                    call.id,
                    "Tool was not executed: agent cancelled." if aborted else
                    "Tool was not executed: assistant returned an incomplete or invalid response.",
                    is_error=True,
                )
                context.append_message(result)
                _emit(emit, "tool_end", tool_call=call, result=result)
            response = AssistantMessage(stop_reason="aborted") if aborted else assistant
            _emit(emit, "turn_end", turn=turn, stop_reason=response.stop_reason)
            return finish(response, turn, aborted=aborted)

        if not assistant.tool_calls:
            _emit(emit, "turn_end", turn=turn, stop_reason=assistant.stop_reason)
            return finish(assistant, turn)

        # Persist each result as soon as it completes, before the next mutation.
        # Parallel results may be committed in completion order; call ids retain
        # pairing, while execute_batch's public return remains request-ordered.
        try:
            scheduler.execute_batch(assistant.tool_calls, on_result=context.append_message)
        except Exception as exc:
            # Result persistence is a barrier, unlike best-effort event delivery.
            # Leave unresolved calls on disk for explicit unknown-outcome recovery.
            failed = AssistantMessage(
                stop_reason="error", error_message=(
                    f"Tool result commit failed ({type(exc).__name__}); execution stopped. "
                    "Effects may have occurred; reopen the session and inspect before retrying."
                ),
            )
            _emit(emit, "turn_end", turn=turn, stop_reason="error")
            return finish(failed, turn)
        _emit(emit, "turn_end", turn=turn, stop_reason="tool_use")
        if is_aborted():
            return finish(AssistantMessage(stop_reason="aborted"), turn, aborted=True)
        if should_stop_after_turn is not None and should_stop_after_turn(turn):
            return finish(AssistantMessage(
                stop_reason="error", error_message="agent stopped by caller turn policy",
            ), turn)

    exhausted = AssistantMessage(
        content="Agent stopped after reaching the maximum number of turns.",
        stop_reason="error",
        error_message="max_turns exceeded",
    )
    return finish(exhausted, turn)


def _emit(emit: Callable[[AgentEvent], None] | None, event_type: str, **data: Any) -> None:
    if emit is not None:
        try:
            emit(AgentEvent(event_type, deepcopy(data)))
        except Exception as exc:
            warnings.warn(f"Agent event observer failed: {type(exc).__name__}", RuntimeWarning, stacklevel=2)
