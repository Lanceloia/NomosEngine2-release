"""Nominal path validation and checked-path reads without graph phases."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import get_args, get_origin, get_type_hints

from nomos_kernel import (
    K0OccurrenceRef,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

_OPAQUE_REFERENCES = frozenset((K0OccurrenceRef, _K0ActorRef, _K0IndividualRef))


def _leaf_type(carrier: type, path: str) -> type | None:
    current = carrier
    parts = path.split(".")
    if not parts or any(not part.isidentifier() or part.startswith("_") for part in parts):
        return None
    for index, part in enumerate(parts):
        if (
            not isinstance(current, type)
            or current in _OPAQUE_REFERENCES
            or not is_dataclass(current)
        ):
            return None
        annotation = get_type_hints(current).get(part)
        if annotation is None:
            return None
        options = get_args(annotation)
        current = (
            next(item for item in options if item is not type(None))
            if len(options) == 2 and type(None) in options
            else annotation
        )
        if index < len(parts) - 1 and (not isinstance(current, type) or not is_dataclass(current)):
            return None
    return (
        current
        if current in (str, int, bool)
        or current in _OPAQUE_REFERENCES
        or (
            isinstance(current, type)
            and is_dataclass(current)
            and current.__dataclass_params__.frozen
        )
        or (
            get_origin(current) is tuple
            and len(get_args(current)) == 2
            and get_args(current)[1] is Ellipsis
            and isinstance(get_args(current)[0], type)
            and is_dataclass(get_args(current)[0])
            and get_args(current)[0].__dataclass_params__.frozen
        )
        else None
    )


def _read_leaf(view: object, path: str) -> object | None:
    current = view
    for part in path.split("."):
        if current is None:
            return None
        current = getattr(current, part)
    return current
