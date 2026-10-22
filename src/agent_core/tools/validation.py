"""Small, fail-closed JSON-schema subset, not a full JSON Schema validator."""

from __future__ import annotations

import math
from typing import Any


_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
    "description", "title", "default", "$schema",
}


def validate(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    """Reject unsupported constraints rather than silently claiming validation."""
    unsupported = set(schema) - _KEYWORDS
    if unsupported:
        raise ValueError(f"unsupported schema keywords: {sorted(unsupported)}")
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if kind is not None and (kind not in valid or not valid[kind]):
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        raise ValueError(f"{path} is not an allowed value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"unexpected argument: {path}.{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(item, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list):
        for key, compare in (("minItems", len(value) < schema.get("minItems", 0)),
                             ("maxItems", len(value) > schema.get("maxItems", len(value)))):
            if compare:
                raise ValueError(f"{path} violates {key}")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise ValueError(f"{path} has invalid length")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Integers are finite, including values too large to convert to a float.
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError(f"{path} is outside the allowed range")
