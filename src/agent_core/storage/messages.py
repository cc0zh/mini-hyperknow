"""Strict JSON message encoding and provider tool-pair validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from typing import Any, Iterable

from ..types import AssistantMessage, Message, ToolCall, ToolResultMessage, UserMessage


def encode_message(message: Message) -> dict[str, Any]:
    if not isinstance(message, (UserMessage, AssistantMessage, ToolResultMessage)):
        raise ValueError("Unsupported session message")
    data = asdict(message)
    decode_message(data)
    json.dumps(data, ensure_ascii=False, allow_nan=False)
    return deepcopy(data)


def decode_message(data: Any) -> Message:
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        raise ValueError("Message must contain string content")
    role = data.get("role")
    if role == "user" and set(data) == {"role", "content"}:
        return UserMessage(data["content"])
    if role == "tool_result" and set(data) == {"role", "content", "tool_call_id", "is_error"}:
        if not isinstance(data["tool_call_id"], str) or not data["tool_call_id"]:
            raise ValueError("Tool result must identify its call")
        if type(data["is_error"]) is not bool:
            raise ValueError("Tool result is_error must be boolean")
        return ToolResultMessage(data["tool_call_id"], data["content"], is_error=data["is_error"])
    fields = {"role", "content", "tool_calls", "stop_reason", "model", "provider", "usage", "error_message"}
    if role != "assistant" or set(data) != fields:
        raise ValueError("Unknown message role or fields")
    if data["stop_reason"] not in {"stop", "tool_use", "error", "aborted"}:
        raise ValueError("Invalid assistant stop reason")
    for name in ("model", "provider", "error_message"):
        if data[name] is not None and not isinstance(data[name], str):
            raise ValueError(f"Invalid assistant {name}")
    usage = data["usage"]
    if usage is not None and (not isinstance(usage, dict) or any(
        not isinstance(k, str) or type(v) is not int or v < 0 for k, v in usage.items()
    )):
        raise ValueError("Invalid provider usage")
    if not isinstance(data["tool_calls"], list):
        raise ValueError("tool_calls must be a list")
    calls = []
    for call in data["tool_calls"]:
        if not isinstance(call, dict) or set(call) != {"id", "name", "arguments"}:
            raise ValueError("Invalid tool call")
        if any(not isinstance(call[k], str) or not call[k] for k in ("id", "name")):
            raise ValueError("Tool call must have an id and name")
        if not isinstance(call["arguments"], dict):
            raise ValueError("Tool arguments must be an object")
        _validate_json(call["arguments"])
        calls.append(ToolCall(call["id"], call["name"], deepcopy(call["arguments"])))
    return AssistantMessage(
        data["content"], tool_calls=calls, stop_reason=data["stop_reason"],
        model=data["model"], provider=data["provider"], usage=deepcopy(usage),
        error_message=data["error_message"],
    )


def _validate_json(value: Any) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _validate_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_json(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("Tool arguments must be JSON data")
    json.dumps(value, allow_nan=False)


def validate_history(messages: Iterable[Message], *, allow_pending: bool = False) -> list[str]:
    """Reject orphan/duplicate results and interleaved unresolved tool calls."""
    pending: dict[str, None] = {}
    seen: set[str] = set()
    for message in messages:
        if isinstance(message, ToolResultMessage):
            if message.tool_call_id not in pending:
                raise ValueError("Orphan or duplicate tool result")
            del pending[message.tool_call_id]
            continue
        if pending:
            raise ValueError("Tool calls must be resolved before another message")
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                if not call.id or call.id in seen:
                    raise ValueError("Tool call ids must be nonempty and unique within active history")
                seen.add(call.id)
                pending[call.id] = None
        elif not isinstance(message, UserMessage):
            raise ValueError("Unsupported message")
    if pending and not allow_pending:
        raise ValueError("Unresolved tool calls cannot be sent to a provider")
    return list(pending)
