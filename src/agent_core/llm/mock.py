from __future__ import annotations

from collections.abc import Iterable

from ..types import AgentContext, AssistantMessage, ToolCall


class MockLLMService:
    """Queue-based LLM used to exercise the full loop without network access."""

    def __init__(self, responses: Iterable[AssistantMessage] = ()) -> None:
        self._responses = list(responses)
        self.calls: list[AgentContext] = []

    def complete(self, context: AgentContext) -> AssistantMessage:
        self.calls.append(context)
        if not self._responses:
            return AssistantMessage(
                stop_reason="error",
                error_message="MockLLMService response queue is empty",
            )
        return self._responses.pop(0)

    def add_response(self, response: AssistantMessage) -> None:
        self._responses.append(response)


def mock_text(text: str) -> AssistantMessage:
    return AssistantMessage(text)


def mock_tool_call(name: str, arguments: dict, *, call_id: str = "call-1") -> AssistantMessage:
    return AssistantMessage(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        stop_reason="tool_use",
    )
