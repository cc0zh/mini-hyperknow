from copy import deepcopy
from typing import TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def validate_model_output(schema: type[T], raw: object) -> T:
    try:
        return schema.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors()
        for error in errors:
            value = error["input"]
            if error["type"] != "extra_forbidden" or not (
                value is None or type(value) in (str, list, dict) and not value
            ):
                raise
        normalized = deepcopy(raw)
        for error in errors:
            parent = normalized
            for key in error["loc"][:-1]:
                parent = parent[key]
            del parent[error["loc"][-1]]
        return schema.model_validate(normalized)
