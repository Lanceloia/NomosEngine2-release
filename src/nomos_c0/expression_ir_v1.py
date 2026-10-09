"""Immutable checked expressions, independent of author container syntax."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import lru_cache, reduce
from operator import or_
from types import MappingProxyType, UnionType
from typing import Literal, Union, get_args, get_origin

from .author_document_v1 import C0OriginFrame


@dataclass(frozen=True, slots=True, eq=False)
class _OwnedValueMapping(Mapping):
    contents: Mapping

    def __post_init__(self):
        object.__setattr__(
            self,
            "contents",
            MappingProxyType({key: freeze_value_tree(item) for key, item in self.contents.items()}),
        )

    def __getitem__(self, key):
        return self.contents[key]

    def __iter__(self):
        return iter(self.contents)

    def __len__(self):
        return len(self.contents)


def freeze_value_tree(value: object) -> object:
    """Own container storage, including proxies backed by an editable dictionary."""
    if type(value) in (C0Expression, _ExpressionDraft, _OwnedValueMapping):
        return value
    if isinstance(value, Mapping):
        return _OwnedValueMapping({key: freeze_value_tree(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(freeze_value_tree(item) for item in value)
    return value


@dataclass(frozen=True)
class C0ValueType:
    """Closed type metadata; generic Python aliases never enter K0 configuration."""

    kind: str
    carrier: type | None = None
    arguments: tuple[C0ValueType, ...] = ()

    @property
    def annotation(self) -> object:
        if self.kind == "nominal":
            return self.carrier
        if self.kind == "variadic":
            return Ellipsis
        return _compound_annotation(self.kind, self.arguments)


@lru_cache(maxsize=1024)
def _compound_annotation(kind: str, arguments: tuple[C0ValueType, ...]) -> object:
    # Backend-only metadata: Python aliases must not enter K0's closed configuration.
    values = tuple(item.annotation for item in arguments)
    return reduce(or_, values) if kind == "union" else tuple[values] if values else tuple[()]


def closed_value_type(annotation: object) -> C0ValueType:
    if isinstance(annotation, type):
        return C0ValueType("nominal", annotation)
    if annotation is Ellipsis:
        return C0ValueType("variadic")
    origin = get_origin(annotation)
    if origin not in (tuple, Union, UnionType):
        raise TypeError("unsupported checked value type")
    return C0ValueType(
        "tuple" if origin is tuple else "union",
        arguments=tuple(closed_value_type(item) for item in get_args(annotation)),
    )


@dataclass(frozen=True)
class C0Expression(Mapping[str, object]):
    """One checked operation; the Mapping view is read-only traversal, not source."""

    operation: str
    operand: object
    value_type: C0ValueType
    stage: Literal["admission", "effect", "construction"]
    origin: str
    provenance: tuple[C0OriginFrame, ...] = field(default=(), compare=False)
    reference_path: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operand", freeze_value_tree(self.operand))
        object.__setattr__(
            self,
            "reference_path",
            tuple(self.operand.split(".")) if self.operation == "ref" else (),
        )

    @property
    def result_type(self) -> object:
        return self.value_type.annotation

    def __getitem__(self, key: str) -> object:
        if key != self.operation:
            raise KeyError(key)
        return self.operand

    def __contains__(self, key: object) -> bool:
        return key == self.operation

    def __iter__(self) -> Iterator[str]:
        yield self.operation

    def __len__(self) -> int:
        return 1


@dataclass(frozen=True)
class _ExpressionDraft(Mapping[str, object]):
    """Compile-only shape, never accepted by the evaluator."""

    operation: str
    operand: object
    origin: str
    provenance: tuple[C0OriginFrame, ...] = field(default=(), compare=False)

    def __getitem__(self, key: str) -> object:
        if key != self.operation:
            raise KeyError(key)
        return self.operand

    def __contains__(self, key: object) -> bool:
        return key == self.operation

    def __iter__(self) -> Iterator[str]:
        yield self.operation

    def __len__(self) -> int:
        return 1
