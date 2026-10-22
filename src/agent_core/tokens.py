"""Conservative context estimates and separately measured provider usage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from threading import RLock
from typing import Mapping

from .storage.messages import encode_message
from .types import AgentContext


@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    reserved_output_tokens: int
    is_estimate: bool = True

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.reserved_output_tokens


class TokenEstimator:
    """UTF-8-byte upper-biased heuristic plus framing allowances, not usage.

    No tokenizer is installed. Counting a token per byte is deliberately more
    conservative than character/4, including CJK, JSON arguments and tool schemas.
    This is not a tokenizer-exact guarantee for every possible provider.
    """

    def estimate(self, context: AgentContext, *, reserve_output_tokens: int = 0) -> TokenEstimate:
        if type(reserve_output_tokens) is not int or reserve_output_tokens < 0:
            raise ValueError("reserve_output_tokens must be a nonnegative integer")
        payload = {
            "system": context.system_prompt,
            "messages": [encode_message(message) for message in context.messages],
            "tools": context.tools,
        }
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        framing = 64 + 32 * (len(context.messages) + len(context.tools) + bool(context.system_prompt))
        return TokenEstimate(size + framing, reserve_output_tokens)


class TokenCounter:
    """Accumulate only actual usage supplied by a provider in this process.

    Missing fields stay ``None`` in complete totals. ``known_usage`` exposes
    measured partial sums without representing them as the complete session cost.
    Restored audit messages must NOT be fed back into this counter.
    """

    _fields = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self) -> None:
        self._records: list[tuple[str, dict[str, int] | None]] = []
        self._mutex = RLock()

    def record(self, usage: Mapping[str, int] | None, *, kind: str = "completion") -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("Usage kind must be nonempty")
        if usage is not None:
            if not isinstance(usage, Mapping) or any(
                not isinstance(key, str) or type(value) is not int or value < 0
                for key, value in usage.items()
            ):
                raise ValueError("Provider usage must contain nonnegative integer measurements")
            usage = dict(usage) or None
        with self._mutex:
            self._records.append((kind, deepcopy(usage)))

    def _totals(self, records: list[tuple[str, dict[str, int] | None]]) -> dict:
        fields = set(self._fields)
        for _, usage in records:
            fields.update(usage or {})
        known: dict[str, int | None] = {}
        totals: dict[str, int | None] = {}
        for field in sorted(fields):
            values = [usage[field] for _, usage in records if usage is not None and field in usage]
            known[field] = sum(values) if values else None
            totals[field] = known[field] if records and len(values) == len(records) else None
        return {"calls": len(records), "unknown_calls": sum(not usage for _, usage in records),
                "usage": totals, "known_usage": known}

    def snapshot(self) -> dict:
        with self._mutex:
            result = self._totals(self._records)
            result["by_kind"] = {
                kind: self._totals([record for record in self._records if record[0] == kind])
                for kind in sorted({kind for kind, _ in self._records})
            }
            return result

    @property
    def totals(self) -> dict[str, int | None]:
        return self.snapshot()["usage"]
