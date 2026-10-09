"""Source locations for a single, already type-checked immutable guard tree."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .author_contract_v1 import C0LawError
from .expression_ir_v1 import C0Expression


@dataclass(frozen=True)
class C0ClauseSource:
    path: str
    names: tuple[str, ...]
    branches: tuple[str, ...]


@dataclass(frozen=True)
class C0GuardIR:
    expression: C0Expression
    clauses: tuple[C0ClauseSource, ...]
    source_paths: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_paths", MappingProxyType(dict(self.source_paths)))


def lower_checked_guard(expression: C0Expression, source_paths: Mapping[str, str]) -> C0GuardIR:
    """Index checked source nodes, without copying or interpreting predicates."""
    clauses: list[C0ClauseSource] = []
    declared: set[tuple[tuple[str, ...], str]] = set()
    locations = dict(source_paths)

    def index(value, path):
        if type(value) is C0Expression:
            locations[path] = value.origin
        if isinstance(value, Mapping):
            for key, child in value.items():
                index(child, f"{path}.{key}")
        elif type(value) is tuple:
            for number, child in enumerate(value):
                index(child, f"{path}[{number}]")

    index(expression, "guard")

    def visit(value, path, scope=(), names=(), branches=()) -> None:
        if isinstance(value, Mapping):
            if (
                set(value) == {"clause"}
                and isinstance(value["clause"], Mapping)
                and set(value["clause"]) == {"name", "test"}
                and type(value["clause"]["name"]) is str
            ):
                clause = value["clause"]
                key = (scope, clause["name"])
                if key in declared:
                    raise C0LawError(f"clause name repeats in the same scope: {path}")
                declared.add(key)
                nested_names = (*names, clause["name"])
                clauses.append(
                    C0ClauseSource(
                        locations[path],
                        nested_names,
                        tuple(locations[branch] for branch in branches),
                    )
                )
                visit(clause["test"], f"{path}.clause.test", (*scope, path), nested_names, branches)
            elif set(value) == {"call"}:
                declaration = value["call"]
                for name, argument in declaration["args"].items():
                    location = f"{path}.call.args.{name}"
                    visit(argument, location, (*scope, location), names, branches)
                location = f"{path}.call.body"
                visit(declaration["body"], location, (*scope, location), names, branches)
            elif set(value) == {"match"}:
                visit(value["match"]["value"], f"{path}.match.value", scope, names, branches)
                for case, arm in value["match"]["cases"].items():
                    location = f"{path}.match.cases.{case}.then"
                    visit(arm["then"], location, (*scope, location), names, (*branches, location))
            elif (
                set(value) == {"let"}
                and isinstance(value["let"], Mapping)
                and set(value["let"]) == {"name", "value", "in"}
            ):
                for child_name in ("value", "in"):
                    location = f"{path}.let.{child_name}"
                    visit(value["let"][child_name], location, (*scope, location), names, branches)
            elif (
                set(value) == {"if"}
                and isinstance(value["if"], Mapping)
                and set(value["if"]) == {"when", "then", "else"}
            ):
                for branch, child in value["if"].items():
                    location = f"{path}.if.{branch}"
                    visit(child, location, (*scope, location), names, (*branches, location))
            else:
                for key, child in value.items():
                    visit(child, f"{path}.{key}", scope, names, branches)
        elif type(value) is tuple:
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", scope, names, branches)

    visit(expression, "guard")
    return C0GuardIR(expression, tuple(clauses), MappingProxyType(locations))
