"""Canonical closed-wire primitives shared by kernel and capability codecs."""

from __future__ import annotations

from nomos_kernel._identity import K0ProfileError, _checked_label
from nomos_kernel._owner_abi import _K0CanonicalWirePayload


def _canonical_wire(value: _K0CanonicalWirePayload) -> _K0CanonicalWirePayload:
    """Validate and clone one primitive wire tree without retaining aliases."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is not tuple:
        raise K0ProfileError("wire values must be exact primitives or tuples")
    return tuple(_canonical_wire(item) for item in value)


def _wire_record(
    tag: str, values: tuple[_K0CanonicalWirePayload, ...]
) -> tuple[_K0CanonicalWirePayload, ...]:
    _checked_label(tag, "wire tag")
    if type(values) is not tuple:
        raise K0ProfileError("wire record values must use one exact tuple")
    return (tag, *(_canonical_wire(value) for value in values))


def _read_wire_record(
    wire: _K0CanonicalWirePayload, tag: str, arity: int
) -> tuple[_K0CanonicalWirePayload, ...]:
    _checked_label(tag, "wire tag")
    if type(arity) is not int or arity < 0:
        raise K0ProfileError("wire record arity must be a non-negative int")
    checked = _canonical_wire(wire)
    if type(checked) is not tuple or len(checked) != arity + 1 or checked[0] != tag:
        raise K0ProfileError(f"expected {tag!r} wire record with arity {arity}")
    return checked[1:]
