"""Domain-neutral author validation and opening errors shared by current C0 phases."""

from __future__ import annotations

import json
from typing import Any


class C0LawError(ValueError):
    """A declaration or author binding is not closed under its library ports."""


class C0BindingError(ValueError):
    """Opening assets cannot instantiate the compiled Program."""


def _object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise C0LawError(f"{label} must be an object with string keys")
    return value


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise C0LawError(f"{label} has missing or unknown fields")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise C0LawError("author declaration repeats a field")
        result[key] = value
    return result


def _source_object(source: str, label: str) -> dict[str, object]:
    if type(source) is not str or not source or len(source) > 131072:
        raise C0LawError(f"{label} is empty or too large")
    try:
        return _object(json.loads(source, object_pairs_hook=_unique_object), label)
    except C0LawError:
        raise
    except (ValueError, RecursionError) as error:
        raise C0LawError(f"{label} is not valid JSON") from error
