"""Immutable compiler literals, not live world identities or owner state."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScalarLiteral:
    value: None | bool | int | str


@dataclass(frozen=True)
class SymbolLiteral:
    symbol: str
    kind: str
    sort: str


@dataclass(frozen=True)
class RecordLiteral:
    type_name: str
    values: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class CollectionLiteral:
    kind: str
    values: tuple[object, ...]
