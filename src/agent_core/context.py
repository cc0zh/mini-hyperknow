"""Compatible context assembly with optional durable sessions and token budgets."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from threading import RLock
from typing import Callable, Iterable

from .compression import (
    CompressionCandidate, ContextBudgetExceeded, ContextCompressor,
    history_fingerprint, plan_compression,
)
from .memory import LongTermMemory
from .storage import SessionStore
from .storage.messages import encode_message, validate_history
from .tokens import TokenEstimate, TokenEstimator
from .types import AgentContext, Message, ToolResultMessage, UserMessage


class ContextManager:
    """Own active history, preserving an independent immutable audit history.

    A supplied SessionStore is owned/closed by the caller. Restore only reads
    disk and records interrupted tool results; it never calls an LLM or replays a
    side effect. Call ``prepare`` before *every* model call, including tool rounds.
    """

    def __init__(self, system_prompt: str = "You are a helpful assistant.", *,
                 session_store: SessionStore | None = None, memory: LongTermMemory | None = None,
                 max_context_tokens: int | None = None, reserve_output_tokens: int = 0,
                 compression_threshold: float = .8, compressor: ContextCompressor | None = None) -> None:
        if max_context_tokens is not None and (type(max_context_tokens) is not int or max_context_tokens < 1):
            raise ValueError("max_context_tokens must be positive or None")
        if type(reserve_output_tokens) is not int or reserve_output_tokens < 0:
            raise ValueError("reserve_output_tokens must be nonnegative")
        if not 0 < compression_threshold <= 1:
            raise ValueError("compression_threshold must be in (0, 1]")
        self.system_prompt = system_prompt
        self.session_store = session_store
        self.memory = memory
        self.max_context_tokens = max_context_tokens
        self.reserve_output_tokens = reserve_output_tokens
        self.compression_threshold = compression_threshold
        self.compressor = compressor
        self.estimator = TokenEstimator()
        self._mutex = RLock()
        self._messages: list[Message] = []
        self._audit: list[Message] = []
        self._turn = 0
        self._revision = 0
        self._awaiting_user = False
        self._last_compression_attempt: str | None = None
        if session_store is not None:
            session_store.attach(self)
            snapshot = session_store.load()
            self._messages, self._audit = snapshot.messages, snapshot.audit_messages
            self._turn, self._revision = snapshot.turn, snapshot.revision
            self._awaiting_user = snapshot.awaiting_user
            for call_id in validate_history(self._messages, allow_pending=True):
                self.append_message(ToolResultMessage(
                    call_id,
                    "Interrupted tool call: execution outcome may be unknown. "
                    "It was not automatically re-executed during session recovery.",
                    is_error=True,
                ))

    @property
    def messages(self) -> list[Message]:
        with self._mutex:
            return deepcopy(self._messages)

    @property
    def audit_messages(self) -> list[Message]:
        with self._mutex:
            return deepcopy(self._audit)

    def begin_turn(self) -> int:
        with self._mutex:
            if not self._awaiting_user:
                validate_history(self._messages)
                if self.session_store is not None:
                    self._revision = self.session_store.begin_turn(expected_revision=self._revision)
                self._turn += 1
                self._awaiting_user = True
            return self._turn

    def append_message(self, message: Message) -> None:
        with self._mutex:
            encode_message(message)
            message = deepcopy(message)
            validate_history([*self._messages, message], allow_pending=True)
            if isinstance(message, UserMessage):
                self.begin_turn()
            if self.session_store is not None:
                self._revision = self.session_store.append_message(message, expected_revision=self._revision)
            self._messages.append(message)
            self._audit.append(deepcopy(message))
            if isinstance(message, UserMessage):
                self._awaiting_user = False

    def get_context(self, tool_definitions: Iterable[dict] = ()) -> AgentContext:
        with self._mutex:
            return self._render(self._messages, tool_definitions)

    def _render(self, messages: Iterable[Message], tool_definitions: Iterable[dict]) -> AgentContext:
        history = deepcopy(list(messages))
        validate_history(history)
        if self.memory is not None:
            memory_text = self.memory.render()
            if memory_text:
                history.insert(0, UserMessage(memory_text))
        return AgentContext(system_prompt=self.system_prompt, messages=history,
                            tools=deepcopy(list(tool_definitions)))

    def estimate_tokens(self, tool_definitions: Iterable[dict] = ()) -> TokenEstimate:
        return self.estimator.estimate(self.get_context(tool_definitions),
                                       reserve_output_tokens=self.reserve_output_tokens)

    def needs_compression(self, tool_definitions: Iterable[dict] = ()) -> bool:
        with self._mutex:
            return (self.max_context_tokens is not None
                    and self.estimate_tokens(tool_definitions).total_tokens
                    >= self.max_context_tokens * self.compression_threshold)

    def prepare(self, tool_definitions: Iterable[dict] = (), *,
                is_aborted: Callable[[], bool] | None = None) -> AgentContext:
        with self._mutex:
            definitions = deepcopy(list(tool_definitions))
            if is_aborted is not None and is_aborted():
                raise ContextBudgetExceeded("Context preparation was cancelled")
            try:
                context = self.get_context(definitions)
            except ValueError as exc:
                raise ContextBudgetExceeded(str(exc)) from exc
            if not self.needs_compression(definitions):
                return context
            if self.compressor is None:
                raise ContextBudgetExceeded("Context token threshold reached without a configured compressor")
            signature = hashlib.sha256((history_fingerprint(context.messages) + json.dumps(
                {"system": context.system_prompt, "tools": context.tools, "budget": self.max_context_tokens,
                 "reserve": self.reserve_output_tokens, "threshold": self.compression_threshold},
                ensure_ascii=False, sort_keys=True, allow_nan=False,
            )).encode("utf-8")).hexdigest()
            if signature == self._last_compression_attempt:
                raise ContextBudgetExceeded("Compression already attempted for this unchanged context")
            self._last_compression_attempt = signature
            plan = self.compressor.plan(self._messages)
            # Even an almost empty summary must leave all recent turns intact.
            minimum = self.estimator.estimate(self._render(plan.render("x"), definitions),
                                               reserve_output_tokens=self.reserve_output_tokens)
            if minimum.total_tokens >= self.max_context_tokens * self.compression_threshold:
                raise ContextBudgetExceeded("Retained complete recent turns cannot fit the context budget")
            candidate = self.compressor.complete_plan(plan, is_aborted=is_aborted)
            if is_aborted is not None and is_aborted():
                raise ContextBudgetExceeded("Compression was cancelled before checkpoint commit")
            self.commit_compression(candidate, tool_definitions=definitions)
            return self.get_context(definitions)

    def commit_compression(self, candidate: CompressionCandidate, *,
                           tool_definitions: Iterable[dict] = ()) -> None:
        """Validate a pure candidate, persist its checkpoint, then swap history."""
        with self._mutex:
            if candidate.source_fingerprint != history_fingerprint(self._messages):
                raise ContextBudgetExceeded("Compression candidate is stale")
            plan = plan_compression(self._messages, keep_recent_turns=candidate.keep_recent_turns)
            history = plan.render(candidate.summary)
            definitions = deepcopy(list(tool_definitions))
            before = self.estimate_tokens(definitions).total_tokens
            after = self.estimator.estimate(self._render(history, definitions),
                                           reserve_output_tokens=self.reserve_output_tokens).total_tokens
            if after >= before:
                raise ContextBudgetExceeded("Summary did not reduce the context estimate")
            if self.max_context_tokens is not None and after >= self.max_context_tokens * self.compression_threshold:
                raise ContextBudgetExceeded("Summary cannot meet the context token threshold")
            if self.session_store is not None:
                self._revision = self.session_store.checkpoint(history, expected_revision=self._revision)
            self._messages = history
