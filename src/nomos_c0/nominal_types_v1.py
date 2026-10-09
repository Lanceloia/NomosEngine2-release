"""Compiler-owned nominal sort identities and finite Object specialization."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMANTIC_IDENTITY = re.compile(r"^[A-Z][A-Z0-9_.]*@[1-9][0-9]*$")


class IRValidationError(ValueError):
    """A compiler semantic identity or nominal sort declaration is malformed."""


@dataclass(frozen=True, order=True)
class SemanticIdentity:
    value: str

    def __post_init__(self) -> None:
        self.validate_for_ir()

    def validate_for_ir(self) -> None:
        value = getattr(self, "value", None)
        if type(value) is not str or ".." in value or not _SEMANTIC_IDENTITY.fullmatch(value):
            raise IRValidationError(
                "semantic identity must match ^[A-Z][A-Z0-9_.]*@[1-9][0-9]*$ with no repeated dots"
            )


def _validate_ref(value: object, expected: type, label: str) -> None:
    identity = getattr(value, "identity", None)
    if type(value) is not expected or type(identity) is not SemanticIdentity:
        raise IRValidationError(f"{label} needs an exact semantic identity")
    identity.validate_for_ir()


@dataclass(frozen=True, order=True)
class ObjectSortRef:
    identity: SemanticIdentity

    def __post_init__(self) -> None:
        self.validate_for_ir()

    def validate_for_ir(self) -> None:
        _validate_ref(self, ObjectSortRef, "object sort ref")


@dataclass(frozen=True, order=True)
class EventSortRef:
    identity: SemanticIdentity

    def __post_init__(self) -> None:
        self.validate_for_ir()

    def validate_for_ir(self) -> None:
        _validate_ref(self, EventSortRef, "event sort ref")


@dataclass(frozen=True, order=True)
class ObjectSortSpecialization:
    child: ObjectSortRef
    parent: ObjectSortRef

    def __post_init__(self) -> None:
        if type(self.child) is not ObjectSortRef or type(self.parent) is not ObjectSortRef:
            raise IRValidationError("Object specialization needs exact sort references")
        if self.child == self.parent:
            raise IRValidationError("Object sort cannot specialize itself")


@dataclass(frozen=True)
class ObjectSortHierarchy:
    sorts: tuple[ObjectSortRef, ...]
    edges: tuple[ObjectSortSpecialization, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.sorts) is not tuple
            or type(self.edges) is not tuple
            or not self.sorts
            or any(type(sort) is not ObjectSortRef for sort in self.sorts)
            or any(type(edge) is not ObjectSortSpecialization for edge in self.edges)
            or self.sorts != tuple(sorted(set(self.sorts)))
            or self.edges != tuple(sorted(set(self.edges)))
        ):
            raise IRValidationError("Object sort hierarchy is not finite and canonical")
        declared = set(self.sorts)
        parents = {
            sort: tuple(edge.parent for edge in self.edges if edge.child == sort)
            for sort in self.sorts
        }
        if any(edge.child not in declared or edge.parent not in declared for edge in self.edges):
            raise IRValidationError("Object specialization refers to an undeclared sort")
        active: set[ObjectSortRef] = set()
        complete: set[ObjectSortRef] = set()

        def visit(sort: ObjectSortRef) -> None:
            if sort in active:
                raise IRValidationError("Object sort specialization forms a cycle")
            if sort in complete:
                return
            active.add(sort)
            for parent in parents[sort]:
                visit(parent)
            active.remove(sort)
            complete.add(sort)

        for sort in self.sorts:
            visit(sort)

    def accepts(self, base: ObjectSortRef, candidate: ObjectSortRef) -> bool:
        if type(base) is not ObjectSortRef or type(candidate) is not ObjectSortRef:
            raise IRValidationError("Object sort match needs exact sort references")
        if base not in self.sorts or candidate not in self.sorts:
            raise IRValidationError("Object sort match refers to an undeclared sort")
        pending = [candidate]
        seen: set[ObjectSortRef] = set()
        while pending:
            current = pending.pop()
            if current == base:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edge.parent for edge in self.edges if edge.child == current)
        return False
