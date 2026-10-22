"""Public V1 facade; product workflows remain independent of the tool runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any, Callable

from .context import ContextManager
from .compression import ContextCompressor
from .engine import AgentEvent, LoopResult, _emit, run_agent_loop
from .llm.base import LLMService
from .llm.registry import LLMServiceRegistry, ModelTier
from .memory import LongTermMemory
from .storage import SessionStore
from .tokens import TokenCounter
from .tools import ApprovalStore, ToolManager, ToolScheduler
from .types import AssistantMessage, UserMessage


@dataclass(frozen=True)
class AgentRunResult:
    response: AssistantMessage
    turns: int
    aborted: bool = False
    usage: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Compose context, LLM, tools, and the execution loop."""

    def __init__(
        self,
        llm: LLMService | None = None,
        *,
        tools: ToolManager | None = None,
        system_prompt: str = "You are a helpful assistant.",
        max_turns: int | None = 20,
        emit: Callable[[AgentEvent], None] | None = None,
        registry: LLMServiceRegistry | None = None,
        tier: ModelTier = "high",
        context: ContextManager | None = None,
        session_store: SessionStore | None = None,
        memory: LongTermMemory | None = None,
        max_context_tokens: int | None = None,
        reserve_output_tokens: int = 0,
        compression_threshold: float = .8,
        compression_max_context_tokens: int = 32_000,
        compression_reserve_output_tokens: int = 1024,
        approval_store: ApprovalStore | None = None,
        approval_timeout: float = 60,
        tool_mode: str = "parallel",
        should_stop_after_turn: Callable[[int], bool] | None = None,
    ) -> None:
        if max_turns is not None and (isinstance(max_turns, bool)
                                      or not isinstance(max_turns, int) or max_turns < 1):
            raise ValueError("max_turns must be a positive integer or None")
        if llm is not None and registry is not None:
            raise ValueError("provide llm or registry, not both")
        if llm is None and registry is None:
            raise ValueError("provide an LLM service or model registry")
        if context is not None and (session_store is not None or memory is not None
                                    or max_context_tokens is not None
                                    or reserve_output_tokens != 0 or compression_threshold != .8
                                    or compression_max_context_tokens != 32_000
                                    or compression_reserve_output_tokens != 1024):
            raise ValueError("configure persistence and budgets on the supplied context")
        self.llm = llm if llm is not None else registry.get(tier)
        self.tools = tools or ToolManager()
        self.token_counter = TokenCounter()
        compressor = None
        if context is None and registry is not None and registry.has("low"):
            compressor = ContextCompressor(
                registry.get("low"),
                usage_callback=lambda usage: self.token_counter.record(usage, kind="summary"),
                max_context_tokens=compression_max_context_tokens,
                reserve_output_tokens=compression_reserve_output_tokens,
            )
        self.context = context if context is not None else ContextManager(
            system_prompt, session_store=session_store, memory=memory,
            max_context_tokens=max_context_tokens, reserve_output_tokens=reserve_output_tokens,
            compression_threshold=compression_threshold, compressor=compressor,
        )
        self.max_turns = max_turns
        self.emit = emit
        self.should_stop_after_turn = should_stop_after_turn
        self._abort_event = Event()
        self._run_lock = Lock()
        self.scheduler = ToolScheduler(
            self.tools, approval_store=approval_store, approval_timeout=approval_timeout,
            mode=tool_mode, is_aborted=self._abort_event.is_set,
            emit=lambda event_type, **data: _emit(self.emit, event_type, **data),
        )

    def run(self, user_text: str) -> AgentRunResult:
        if not user_text.strip():
            raise ValueError("user_text must not be empty")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("an Agent instance cannot run concurrently")
        try:
            self._abort_event.clear()
            self.context.begin_turn()
            self.context.append_message(UserMessage(user_text))
            result: LoopResult = run_agent_loop(
                self.context, self.llm, self.tools, emit=self.emit,
                max_turns=self.max_turns, is_aborted=self._abort_event.is_set,
                scheduler=self.scheduler, token_counter=self.token_counter,
                should_stop_after_turn=self.should_stop_after_turn,
            )
            return AgentRunResult(
                result.response, result.turns, result.aborted, self.token_counter.snapshot(),
            )
        finally:
            self._run_lock.release()

    def abort(self) -> None:
        """Stop before the next LLM turn; providers may add native cancellation later."""
        self._abort_event.set()
