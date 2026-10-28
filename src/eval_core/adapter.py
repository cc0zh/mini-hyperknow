"""Explicit product boundary. All returned values are JSON-serializable dictionaries.

Observation: state=preparing|running|waiting|terminal|blocked, outcome optional,
actions=list[str], resources=dict, checkpoints=list[str]. Opaque bindings are
adapter-owned; the runner only persists them. collect returns immutable factual
material, not scores. build_action returns the exact public request before act.
recover returns bindings only when the original command has a verified receipt;
None means unresolved, never permission to resend an in-flight request.
"""

from typing import Protocol


class Adapter(Protocol):
    def preflight(self, case: dict, bindings: dict | None = None) -> dict:
        """Validate a fresh environment or the persisted trial's exact bindings."""
        ...

    def prepare(self, case: dict) -> dict:
        """Return initial bindings without writes or model calls."""
        ...

    def observe(self, bindings: dict) -> dict:
        ...

    def build_action(self, step: dict, observation: dict, bindings: dict,
                     command_id: str) -> dict:
        ...

    def act(self, action: dict) -> dict:
        """Submit one exact request; return replacement adapter bindings."""
        ...

    def recover(self, action: dict) -> dict | None:
        ...

    def collect(self, observation: dict, bindings: dict) -> dict:
        ...
