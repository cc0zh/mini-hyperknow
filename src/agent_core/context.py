"""V0 context assembly: system prompt plus an in-memory conversation."""

from __future__ import annotations

from typing import Iterable

from .types import AgentContext, Message


class ContextManager:
    """Owns the conversation history and renders the current agent context."""

    def __init__(self, system_prompt: str = "You are a helpful assistant.") -> None:
        self.system_prompt = system_prompt
        self._messages: list[Message] = []

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def append_message(self, message: Message) -> None:
        self._messages.append(message)

    def get_context(self, tool_definitions: Iterable[dict] = ()) -> AgentContext:
        return AgentContext(
            system_prompt=self.system_prompt,
            messages=list(self._messages),
            tools=list(tool_definitions),
        )
