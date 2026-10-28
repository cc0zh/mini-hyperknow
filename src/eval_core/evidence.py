"""Shared frozen evidence validation for recovery, grading and reporting."""

from .contracts import validate_observation
from .store import digest


def validate_evidence(item: dict):
    """Verify both content and checkpoint/observation identity, not data alone."""
    required = {"evidence_id", "checkpoint_id", "data", "observation", "sha256", "captured_at"}
    if not isinstance(item, dict) or not required <= item.keys():
        raise ValueError("Invalid frozen evidence structure")
    for key in ("evidence_id", "checkpoint_id", "sha256", "captured_at"):
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError("Invalid frozen evidence identity/metadata")
    validate_observation(item["observation"])
    material = {key: item[key] for key in ("checkpoint_id", "data", "observation")}
    if item["sha256"] != digest(item["data"]) or item["evidence_id"] != digest(material):
        raise ValueError("Frozen evidence content or checkpoint/observation hash mismatch")
