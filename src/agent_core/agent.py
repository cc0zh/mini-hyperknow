"""Public V0 Agent facade."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Callable

from .context import ContextManager
from .engine import AgentEvent, LoopResult, run_agent_loop
from .llm.base import LLMService
from .tools import ToolManager
from .types import AssistantMessage, UserMessage


@dataclass(frozen=True)
class AgentRunResult:
    response: AssistantMessage
    turns: int
    aborted: bool = False


class Agent:
    """Compose context, LLM, tools, and the execution loop."""

    def __init__(
        self,
        llm: LLMService,
        *,
        tools: ToolManager | None = None,
        system_prompt: str = "You are a helpful assistant.",
        max_turns: int = 20,
        emit: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools or ToolManager()
        self.context = ContextManager(system_prompt)
        self.max_turns = max_turns
        self.emit = emit
        self._abort_event = Event()

    def run(self, user_text: str) -> AgentRunResult:
        if not user_text.strip():
            raise ValueError("user_text must not be empty")
        self._abort_event.clear()
        self.context.append_message(UserMessage(user_text))
        result: LoopResult = run_agent_loop(
            self.context,
            self.llm,
            self.tools,
            emit=self.emit,
            max_turns=self.max_turns,
            is_aborted=self._abort_event.is_set,
        )
        return AgentRunResult(result.response, result.turns, result.aborted)

    def abort(self) -> None:
        """Stop before the next LLM turn; providers may add native cancellation later."""
        self._abort_event.set()
