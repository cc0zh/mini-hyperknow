"""Repair interrupted tool groups at the provider boundary, without replaying tools."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from ..types import Message, ToolResultMessage


def sanitize_messages(messages: Iterable[Message]) -> list[Message]:
    result: list[Message] = []
    pending: set[str] = set()
    seen: set[str] = set()

    def finish_pending() -> None:
        # Preserve tool declaration order, not the iteration order of a set.
        if pending:
            assistant = next(m for m in reversed(result) if m.role == "assistant")
            for call in assistant.tool_calls:
                if call.id in pending:
                    result.append(ToolResultMessage(
                        call.id, "Tool execution was interrupted; outcome is unknown. Do not replay automatically.",
                        is_error=True,
                    ))
            pending.clear()

    for message in messages:
        if message.role == "tool_result":
            if message.tool_call_id in pending:
                result.append(deepcopy(message))
                pending.remove(message.tool_call_id)
            continue
        finish_pending()
        if message.role == "assistant":
            if message.stop_reason in {"error", "aborted"} and not message.tool_calls:
                continue
            for call in message.tool_calls:
                if not call.id or not call.name or call.id in seen:
                    raise ValueError("tool calls require non-empty, unique ids and names")
                seen.add(call.id)
                pending.add(call.id)
        result.append(deepcopy(message))
    finish_pending()
    return result
