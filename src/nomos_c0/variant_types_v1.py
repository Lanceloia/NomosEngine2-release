"""Nominal tagged sums, independent of domain invariants and owner permissions."""

from __future__ import annotations

from types import UnionType
from typing import Union, get_args, get_origin

from nomos_kernel import K0ProfileError


def variant_cases(carrier: object) -> dict[str, object]:
    return dict(getattr(carrier, "__nomos_cases__", ()))


def variant_common_fields(carrier: type) -> tuple[str, ...]:
    cases = variant_cases(carrier)
    return tuple(
        item.name for item in carrier.__nomos_fields__ if item.name not in {"case", *cases}
    )


def _payload_shape(annotation: object, value: object) -> bool:
    if get_origin(annotation) in (Union, UnionType):
        return any(_payload_shape(item, value) for item in get_args(annotation))
    if get_origin(annotation) is tuple:
        item, _ = get_args(annotation)
        return type(value) is tuple and all(_payload_shape(item, child) for child in value)
    return type(value) is annotation


def validate_variant(value: object) -> None:
    cases = variant_cases(type(value))
    if not cases:
        return
    if type(value.case) is not str or value.case not in cases:
        raise K0ProfileError("variant has an undeclared case")
    for name, annotation in cases.items():
        if annotation is type(None):
            continue
        payload = getattr(value, name)
        if (name == value.case) != (payload is not None):
            raise K0ProfileError("variant must have exactly its selected payload")
        if name == value.case and not _payload_shape(annotation, payload):
            raise K0ProfileError("variant payload has a foreign nominal shape")


def construct_variant(carrier: type, case: str, payload: object, common: dict) -> object:
    cases = variant_cases(carrier)
    if case not in cases or (cases[case] is type(None) and payload is not None):
        raise K0ProfileError("variant constructor has an invalid case or unit payload")
    result = carrier(
        **common,
        case=case,
        **{
            name: payload if name == case else None
            for name, t in cases.items()
            if t is not type(None)
        },
    )
    result.validate_for_k0()
    return result
