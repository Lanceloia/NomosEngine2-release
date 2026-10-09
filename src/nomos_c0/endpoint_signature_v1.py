"""Derive endpoint types from explicit bindings, never from Law use or visibility."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import is_dataclass
from typing import get_args, get_origin, get_type_hints

from .author_contract_v1 import C0LawError


def endpoint_field(roots: Mapping[str, type], path: object) -> tuple[type, str, object]:
    if type(path) is not str or path.count(".") < 1:
        raise C0LawError("endpoint field path is malformed")
    root, *parts = path.split(".")
    carrier = roots.get(root)
    variants = get_args(carrier)
    if len(variants) == 2 and type(None) in variants:
        carrier = next(item for item in variants if item is not type(None))
    for index, part in enumerate(parts):
        element = part.endswith("[]")
        field = part[:-2] if element else part
        if not isinstance(carrier, type) or not is_dataclass(carrier):
            raise C0LawError(f"endpoint field {path} has no declared record")
        hints = get_type_hints(carrier)
        if field not in hints:
            raise C0LawError(f"endpoint field {path} is not declared")
        annotation = hints[field]
        if index == len(parts) - 1:
            if element:
                raise C0LawError(f"endpoint field {path} must end at a record field")
            return carrier, field, annotation
        variants = get_args(annotation)
        carrier = (
            next(item for item in variants if item is not type(None))
            if len(variants) == 2 and type(None) in variants
            else annotation
        )
        if element:
            arguments = get_args(carrier)
            if (
                get_origin(carrier) is not tuple
                or len(arguments) != 2
                or arguments[1] is not Ellipsis
            ):
                raise C0LawError(f"endpoint field {path} needs a homogeneous tuple")
            carrier = arguments[0]
    raise C0LawError("endpoint field path is empty")


def action_outputs(
    roots: Mapping[str, type],
    effects: Mapping[str, Mapping[str, str]],
    envelope: type,
    envelope_fields: Mapping[str, str],
    schedule_outputs: tuple[tuple[str, object], ...],
) -> dict[str, object]:
    outputs: dict[str, object] = {}

    def add(alias: str, annotation: object) -> None:
        if alias in outputs:
            raise C0LawError("Action output alias has multiple destinations")
        outputs[alias] = annotation

    for root, mapping in effects.items():
        for field, alias in mapping.items():
            add(alias, endpoint_field(roots, f"{root}.{field}")[2])
    for field, alias in envelope_fields.items():
        add(alias, endpoint_field({"envelope": envelope}, f"envelope.{field}")[2])
    for alias, annotation in schedule_outputs:
        add(alias, annotation)
    return outputs
