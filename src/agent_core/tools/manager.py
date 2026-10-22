"""Compatible registration and direct execution with V1 permission gates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .output import OutputTruncator
from .validation import validate

from ..types import ToolCall, ToolResult, ToolResultMessage


ToolHandler = Callable[[dict[str, Any]], ToolResult]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    is_read_only: bool = True
    requires_approval: bool = False
    summarizable: bool = False

    def as_llm_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolManager:
    def __init__(
        self, tools: Iterable[ToolDefinition] = (), *, max_output_chars: int = 8_000,
        output_dir=None, truncator: OutputTruncator | None = None,
    ) -> None:
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")
        self.max_output_chars = max_output_chars
        self.truncator = truncator or OutputTruncator(max_output_chars, output_dir=output_dir)
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.as_llm_definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResultMessage:
        return self._execute(call, approval_checked=False)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def validate_call(self, call: ToolCall) -> ToolDefinition:
        tool = self.get(call.name)
        if tool is None:
            raise ValueError(f"Unknown tool: {call.name}")
        if not isinstance(call.arguments, dict):
            raise ValueError("arguments must be an object")
        validate(call.arguments, tool.parameters)
        return tool

    def error(self, call: ToolCall, reason: str) -> ToolResultMessage:
        return ToolResultMessage(call.id, self._truncate(f"Tool error: {reason}"), is_error=True)

    def _execute(self, call: ToolCall, *, approval_checked: bool) -> ToolResultMessage:
        """Internal scheduler entry; not an authority boundary against Python code."""
        try:
            tool = self.validate_call(call)
            if (tool.requires_approval or not tool.is_read_only) and not approval_checked:
                return self.error(call, "permission denied: approval required; use ToolScheduler")
            result = tool.handler(call.arguments)
            if not isinstance(result, ToolResult):
                raise TypeError("tool handler must return ToolResult")
        except Exception as exc:  # Tool failures become context, not engine crashes.
            result = ToolResult(False, error=f"{type(exc).__name__}: {exc}")

        content = self._render_result(result)
        content = self.truncator.truncate(
            content, is_error=not result.success,
            summarizable=bool(result.success and tool.summarizable) if 'tool' in locals() else False,
            max_chars=self.max_output_chars,
        )
        return ToolResultMessage(call.id, content[:self.max_output_chars], is_error=not result.success)

    @staticmethod
    def _render_result(result: ToolResult) -> str:
        if not result.success:
            return f"Tool error: {result.error or 'unknown error'}"
        if isinstance(result.data, str):
            return result.data
        try:
            return json.dumps(result.data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result.data)

    def _truncate(self, content: str) -> str:
        return self.truncator.truncate(content, is_error=True, max_chars=self.max_output_chars)
