from __future__ import annotations

from typing import Protocol

from ..types import AgentContext, AssistantMessage


class LLMService(Protocol):
    """Minimal provider interface required by the V0 execution loop."""

    def complete(self, context: AgentContext) -> AssistantMessage:
        ...
