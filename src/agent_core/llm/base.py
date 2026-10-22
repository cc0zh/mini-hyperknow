from __future__ import annotations

from typing import Protocol

from ..types import AgentContext, AssistantMessage


class LLMService(Protocol):
    """Synchronous provider interface; cancellation is checked at call boundaries."""

    def complete(self, context: AgentContext) -> AssistantMessage:
        ...
