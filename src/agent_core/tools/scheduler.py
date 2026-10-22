"""Synchronous scheduling, thread-resolvable approvals, and paired events."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
import math
import logging
import re
import threading
import time
from typing import Any, Callable, Iterable
import uuid

from ..types import ToolCall, ToolResultMessage
from .manager import ToolManager


_cancelled: ContextVar[Callable[[], bool]] = ContextVar("tool_cancelled", default=lambda: False)
_logger = logging.getLogger(__name__)


def is_cancelled() -> bool:
    return _cancelled.get()()


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    tool_call: ToolCall
    expires_at: float
    status: str = "pending"


class ApprovalStore:
    """One-shot in-process approvals; timestamps use time.monotonic()."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._requests: dict[str, ApprovalRequest] = {}

    def request(self, call: ToolCall, timeout: float) -> ApprovalRequest:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("approval timeout must be finite and non-negative")
        request = ApprovalRequest(uuid.uuid4().hex, deepcopy(call), time.monotonic() + timeout)
        with self._condition:
            self._requests[request.id] = request
            self._condition.notify_all()
        return deepcopy(request)

    def pending(self) -> list[ApprovalRequest]:
        with self._condition:
            now = time.monotonic()
            for key, request in self._requests.items():
                if request.status == "pending" and now >= request.expires_at:
                    self._requests[key] = replace(request, status="expired")
            return [deepcopy(r) for r in self._requests.values() if r.status == "pending"]

    def resolve(self, approval_id: str, approved: bool) -> bool:
        if type(approved) is not bool:
            raise TypeError("approved must be a bool")
        return self._finish(approval_id, "approved" if approved else "denied")

    def cancel(self, approval_id: str) -> bool:
        return self._finish(approval_id, "cancelled")

    def _finish(self, approval_id: str, status: str) -> bool:
        with self._condition:
            request = self._requests.get(approval_id)
            if request is None or request.status != "pending":
                return False
            timely = time.monotonic() < request.expires_at
            self._requests[approval_id] = replace(request, status=status if timely else "expired")
            self._condition.notify_all()
            return timely

    def wait(self, approval_id: str, is_aborted: Callable[[], bool]) -> str:
        with self._condition:
            try:
                while True:
                    request = self._requests[approval_id]
                    if is_aborted():
                        return "cancelled"
                    if time.monotonic() >= request.expires_at:
                        return "expired"
                    if request.status != "pending":
                        return request.status
                    self._condition.wait(min(0.025, request.expires_at - time.monotonic()))
            finally:
                self._requests.pop(approval_id, None)


class ToolScheduler:
    def __init__(
        self, manager: ToolManager, approval_store: ApprovalStore | None = None,
        emit: Callable[..., Any] | None = None, mode: str = "parallel",
        approval_timeout: float = 60, is_aborted: Callable[[], bool] | None = None,
        *, max_workers: int = 8,
    ) -> None:
        if mode not in {"parallel", "sequential", "serial"}:
            raise ValueError("mode must be parallel or sequential (serial is an alias)")
        if not math.isfinite(approval_timeout) or approval_timeout < 0 or max_workers < 1:
            raise ValueError("invalid scheduler limits")
        self.manager, self.approval_store, self.emit = manager, approval_store, emit
        self.mode, self.approval_timeout, self.max_workers = mode, approval_timeout, max_workers
        self.is_aborted = is_aborted or (lambda: False)

    def _emit(self, event_type: str, **data: Any) -> bool:
        if self.emit is not None:
            try:
                # ToolCall is frozen, but its nested arguments are not. Observers
                # must never mutate the validated/approved execution snapshot.
                self.emit(event_type, **deepcopy(data))
            except Exception:
                _logger.warning("Tool event callback failed: %s", event_type)
                return False
        return True

    @staticmethod
    def _on_result(callback: Callable[[ToolResultMessage], Any] | None, result: ToolResultMessage) -> None:
        if callback is not None:
            # This is a durability barrier, not an observation callback. A failed
            # commit must propagate and stop the batch before any later writes.
            # Already-running read-only work may finish; never retry side effects.
            callback(deepcopy(result))

    def _execute(self, call: ToolCall) -> ToolResultMessage:
        result = self.manager.error(call, "cancelled before execution")
        token = _cancelled.set(self.is_aborted)
        started = time.monotonic()
        try:
            self._emit("tool_start", tool_call=call)
            tool = self.manager.validate_call(call)
            if self.is_aborted():
                return result
            if tool.requires_approval or not tool.is_read_only:
                if self.approval_store is None:
                    result = self.manager.error(call, "permission denied: no approval store")
                    return result
                request = self.approval_store.request(call, self.approval_timeout)
                if not self._emit("approval_required", tool_call=call, approval_id=request.id,
                                  expires_at=request.expires_at):
                    self.approval_store.cancel(request.id)
                status = self.approval_store.wait(request.id, self.is_aborted)
                if status != "approved":
                    result = self.manager.error(call, f"permission {status}: approval {status}")
                    return result
            if self.is_aborted():
                result = self.manager.error(call, "cancelled before execution")
                return result
            result = self.manager._execute(call, approval_checked=True)
            if self.is_aborted() and not result.is_error:
                result = self.manager.error(call, "cancelled during execution; effects may have occurred")
            return result
        except Exception as exc:
            result = self.manager.error(call, f"{type(exc).__name__}: {exc}")
            return result
        finally:
            _cancelled.reset(token)
            self._emit("tool_end", tool_call=call, result=result, duration=time.monotonic() - started)

    def execute_batch(
        self, calls: Iterable[ToolCall], *,
        on_result: Callable[[ToolResultMessage], Any] | None = None,
    ) -> list[ToolResultMessage]:
        """Preflight the entire batch, then execute read groups and write barriers.

        Results return in request order; on_result runs on the calling thread in
        read completion order, before the next write barrier. Unlike emit,
        on_result exceptions propagate and stop scheduling subsequent groups.
        """
        calls = [deepcopy(call) for call in calls]
        try:
            seen: set[str] = set()
            for call in calls:
                if not isinstance(call.id, str) or not call.id or call.id in seen:
                    raise ValueError("batch requires unique, non-empty tool call ids")
                seen.add(call.id)
                if not isinstance(call.name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", call.name) is None:
                    raise ValueError("invalid tool name")
                self.manager.validate_call(call)
        except (TypeError, ValueError) as exc:
            rejected = []
            for call in calls:
                self._emit("tool_start", tool_call=call)
                result = self.manager.error(call, f"batch rejected before execution: {exc}")
                self._emit("tool_end", tool_call=call, result=result, duration=0.0)
                rejected.append(result)
                self._on_result(on_result, result)
            return rejected
        results: list[ToolResultMessage] = []
        index = 0
        while index < len(calls):
            end = index
            while end < len(calls):
                tool = self.manager.get(calls[end].name)
                if self.mode != "parallel" or tool is None or not tool.is_read_only or tool.requires_approval:
                    break
                end += 1
            if end == index:
                result = self._execute(calls[index])
                results.append(result)
                self._on_result(on_result, result)
                index += 1
            else:
                with ThreadPoolExecutor(max_workers=min(self.max_workers, end - index)) as executor:
                    futures = {executor.submit(self._execute, calls[i]): i - index for i in range(index, end)}
                    group: list[ToolResultMessage | None] = [None] * (end - index)
                    for future in as_completed(futures):
                        result = future.result()
                        group[futures[future]] = result
                        self._on_result(on_result, result)
                    results.extend(result for result in group if result is not None)
                index = end
        return results
