"""Closed typed expression definitions; neither owner grants nor executable callbacks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0SourceContext, named_source_paths
from .condition_source_v0 import lower_author_expression
from .expression_ir_v1 import C0ValueType, closed_value_type, freeze_value_tree


def _name(value: object) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isidentifier()
        or value.startswith("_")
        or value == "occurrence"
    ):
        raise C0LawError("pure parameter must be a public ASCII name")
    return value


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _type(raw: object, records: Mapping[str, type], depth: int = 0) -> object:
    if depth > 12:
        raise C0LawError("pure signature type is too deep")
    scalar = {
        "bool": bool,
        "int": int,
        "str": str,
        "occurrence_ref": K0OccurrenceRef,
        "individual_ref": _K0IndividualRef,
    }
    if type(raw) is str:
        if raw in scalar:
            return scalar[raw]
        if raw in records:
            return records[raw]
    elif type(raw) is dict and len(raw) == 1:
        if "optional" in raw:
            return _type(raw["optional"], records, depth + 1) | None
        if "tuple" in raw:
            return tuple[_type(raw["tuple"], records, depth + 1), ...]
    raise C0LawError("pure signature names an unknown nominal type")


def _closed(node: object, names: frozenset[str], calls: set[str], depth: int = 0) -> None:
    if depth > 64:
        raise C0LawError("pure body is too deep")
    if not isinstance(node, Mapping):
        if type(node) is tuple:
            for item in node:
                _closed(item, names, calls, depth + 1)
        return
    if set(node) == {"ref"}:
        path = node["ref"]
        if type(path) is not str or path.split(".", 1)[0] not in names:
            raise C0LawError("pure body captures an undeclared value")
    elif set(node) == {"call"}:
        call = node["call"]
        if (
            set(call) != {"ref", "args"}
            or type(call["ref"]) is not str
            or not isinstance(call["args"], Mapping)
        ):
            raise C0LawError("pure call is malformed")
        calls.add(call["ref"])
        for argument in call["args"].values():
            _closed(argument, names, calls, depth + 1)
    elif set(node) == {"let"}:
        row = node["let"]
        alias = _name(row["name"])
        if alias in names:
            raise C0LawError("pure local shadows a parameter")
        _closed(row["value"], names, calls, depth + 1)
        _closed(row["in"], names | {alias}, calls, depth + 1)
    elif set(node) == {"match"}:
        row = node["match"]
        _closed(row["value"], names, calls, depth + 1)
        for arm in row["cases"].values():
            alias = _name(arm["as"])
            if alias in names:
                raise C0LawError("pure match shadows a parameter")
            _closed(arm["then"], names | {alias}, calls, depth + 1)
    elif set(node) == {"is_case"}:
        _closed(node["is_case"]["value"], names, calls, depth + 1)
    elif set(node) == {"collection_query"}:
        row = node["collection_query"]
        aliases = (_name(row["as"]), _name(row["right_as"]))
        if aliases[0] == aliases[1] or any(alias in names for alias in aliases):
            raise C0LawError("pure query aliases shadow a parameter or each other")
        _closed(row["collection"], names, calls, depth + 1)
        _closed(row["right_collection"], names, calls, depth + 1)
        _closed(row["where"], names | frozenset(aliases), calls, depth + 1)
    elif set(node) == {"unique_by"}:
        row = node["unique_by"]
        alias = _name(row["as"])
        if alias in names:
            raise C0LawError("pure unique_by alias shadows a parameter")
        _closed(row["collection"], names, calls, depth + 1)
        for key in row["keys"]:
            _closed(key, names | {alias}, calls, depth + 1)
    elif set(node) == {"update_matching"}:
        row = node["update_matching"]
        alias = _name(row["as"])
        if alias in names:
            raise C0LawError("pure update alias shadows a parameter")
        _closed(row["collection"], names, calls, depth + 1)
        _closed(row["matching"], names, calls, depth + 1)
        for value in row["set"].values():
            _closed(value, names | {alias}, calls, depth + 1)
    elif set(node) in (
        {"count_matching"},
        {"none_matching"},
        {"exists"},
        {"exactly_one"},
        {"collect_matching"},
    ):
        row = next(iter(node.values()))
        alias = _name(row["as"])
        if alias in names:
            raise C0LawError("pure quantifier shadows a parameter")
        _closed(row["collection"], names, calls, depth + 1)
        _closed(row["where"], names | {alias}, calls, depth + 1)
        if "collect_matching" in node:
            _closed(row["value"], names | {alias}, calls, depth + 1)
    elif set(node) in ({"record"}, {"variant"}):
        row = next(iter(node.values()))
        if "variant" in node:
            _closed(row["value"], names, calls, depth + 1)
        for value in row["fields"].values():
            _closed(value, names, calls, depth + 1)
    elif set(node) == {"copy"}:
        _closed(node["copy"]["from"], names, calls, depth + 1)
        for value in node["copy"]["changes"].values():
            _closed(value, names, calls, depth + 1)
    elif set(node) == {"clause"}:
        _closed(node["clause"]["test"], names, calls, depth + 1)
    elif set(node) == {"const"}:
        return
    else:
        for value in node.values():
            if (
                isinstance(value, Mapping)
                and len(node) == 1
                and next(iter(node)) in ("if", "die_roll", "replace_unique")
            ):
                for key, child in value.items():
                    if key != "key":
                        _closed(child, names, calls, depth + 1)
            else:
                _closed(value, names, calls, depth + 1)


@dataclass(frozen=True)
class C0PureDefinition:
    name: str
    parameter_types: tuple[tuple[str, C0ValueType], ...]
    result_type: C0ValueType
    stage: str
    body: Mapping[str, object]
    source_paths: Mapping[str, str]
    source_context: C0SourceContext | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", freeze_value_tree(self.body))
        object.__setattr__(self, "source_paths", MappingProxyType(dict(self.source_paths)))

    @property
    def parameters(self) -> tuple[tuple[str, object], ...]:
        return tuple((name, item.annotation) for name, item in self.parameter_types)

    @property
    def result(self) -> object:
        return self.result_type.annotation


def check_pure_definitions(
    raw: object, records: Mapping[str, type], *, source_context: C0SourceContext | None = None
) -> tuple[C0PureDefinition, ...]:
    """Resolve signatures and closed call graph; caller ports type-check actual uses."""
    if type(raw) is not list or len(raw) > 64:
        raise C0LawError("Lib pure definitions must be a finite list")
    definitions = {}
    dependencies = {}
    for index, declaration in enumerate(raw):
        if type(declaration) is not dict or set(declaration) != {
            "name",
            "parameters",
            "result",
            "stage",
            "body",
        }:
            raise C0LawError("pure definition has missing or unknown fields")
        name = declaration["name"]
        parameters = declaration["parameters"]
        if (
            type(name) is not str
            or not name
            or name in definitions
            or type(parameters) is not dict
            or len(parameters) > 16
            or declaration["stage"] not in ("admission", "effect")
        ):
            raise C0LawError("pure definition name, stage or parameters are malformed")
        signature = tuple(
            (_name(key), closed_value_type(_type(value, records)))
            for key, value in parameters.items()
        )
        body, locations = lower_author_expression(
            declaration["body"], path=f"pure_definitions.{name}.body"
        )
        body = _freeze(body)
        calls: set[str] = set()
        _closed(body, frozenset(key for key, _ in signature), calls)
        definitions[name] = C0PureDefinition(
            name,
            signature,
            closed_value_type(_type(declaration["result"], records)),
            declaration["stage"],
            body,
            MappingProxyType(locations),
            named_source_paths(
                source_context.at(
                    ("pure_definitions", index, "body"), root=f"pure_definitions.{name}.body"
                ),
                declaration["body"],
                root=f"pure_definitions.{name}.body",
            )
            if source_context is not None
            else None,
        )
        dependencies[name] = calls
    heights = {}

    def visit(name, active=()):
        if name not in definitions:
            raise C0LawError("pure call names an undeclared definition")
        if name in active:
            raise C0LawError("pure call graph contains recursion")
        if len(active) > 16:
            raise C0LawError("pure call graph is too deep")
        if name not in heights:
            height = 1 + max(
                (visit(called, (*active, name)) for called in dependencies[name]), default=0
            )
            if height > 16:
                raise C0LawError("pure call graph is too deep")
            heights[name] = height
        return heights[name]

    for name in definitions:
        visit(name)
    return tuple(definitions.values())
