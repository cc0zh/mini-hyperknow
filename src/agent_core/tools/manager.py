"""Tool definitions, registration, execution, and V0 output bounding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..types import ToolCall, ToolResult, ToolResultMessage


ToolHandler = Callable[[dict[str, Any]], ToolResult]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    is_read_only: bool = True

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
    def __init__(self, tools: Iterable[ToolDefinition] = (), *, max_output_chars: int = 8_000) -> None:
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")
        self.max_output_chars = max_output_chars
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
        tool = self._tools.get(call.name)
        if tool is None:
            content = self._truncate(f"Unknown tool: {call.name}")
            return ToolResultMessage(call.id, content, is_error=True)

        try:
            result = tool.handler(call.arguments)
        except Exception as exc:  # Tool failures become context, not engine crashes.
            result = ToolResult(False, error=f"{type(exc).__name__}: {exc}")

        content = self._render_result(result)
        return ToolResultMessage(call.id, self._truncate(content), is_error=not result.success)

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
        if len(content) <= self.max_output_chars:
            return content
        omitted = len(content) - self.max_output_chars
        marker = f"\n[output truncated; {omitted} characters omitted]"
        if len(marker) >= self.max_output_chars:
            return content[: self.max_output_chars]
        return f"{content[: self.max_output_chars - len(marker)]}{marker}"
