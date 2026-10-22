"""Core data contracts shared by the context, LLM, tool, and engine layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True)
class UserMessage:
    role: Literal["user"]
    content: str

    def __init__(self, content: str):
        object.__setattr__(self, "role", "user")
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantMessage:
    role: Literal["assistant"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: Literal["stop", "tool_use", "error", "aborted"] = "stop"
    model: str | None = None
    provider: str | None = None
    usage: dict[str, int] | None = None
    error_message: str | None = None

    def __init__(
        self,
        content: str = "",
        *,
        tool_calls: list[ToolCall] | None = None,
        stop_reason: Literal["stop", "tool_use", "error", "aborted"] = "stop",
        model: str | None = None,
        provider: str | None = None,
        usage: dict[str, int] | None = None,
        error_message: str | None = None,
    ):
        object.__setattr__(self, "role", "assistant")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "tool_calls", tool_calls or [])
        object.__setattr__(self, "stop_reason", stop_reason)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "usage", usage)
        object.__setattr__(self, "error_message", error_message)


@dataclass(frozen=True)
class ToolResultMessage:
    role: Literal["tool_result"]
    tool_call_id: str
    content: str
    is_error: bool = False

    def __init__(self, tool_call_id: str, content: str, *, is_error: bool = False):
        object.__setattr__(self, "role", "tool_result")
        object.__setattr__(self, "tool_call_id", tool_call_id)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "is_error", is_error)


Message: TypeAlias = UserMessage | AssistantMessage | ToolResultMessage


@dataclass
class AgentContext:
    """The complete, provider-neutral input sent to an LLM."""

    system_prompt: str
    messages: list[Message]
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None

