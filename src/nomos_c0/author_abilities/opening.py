"""Compile author opening data into typed literals with checked symbols."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0BindingError

from .literal_values import CollectionLiteral, RecordLiteral, ScalarLiteral, SymbolLiteral
from .values import ValueLimits, _Budget, _wire_check, validate_scalar


@dataclass(frozen=True)
class OpeningSymbol:
    name: str
    sort: str
    kind: str


@dataclass(frozen=True)
class ParameterValue:
    name: str
    type_name: str
    node: object


def value_node(table, plan, wire, symbols, *, limits=ValueLimits()):
    _wire_check(plan, wire, (), _Budget(limits))
    budget = _Budget(limits)

    def decode(current, value, path):
        budget.check(current, path)
        kind = current.kind
        if kind in ("unit", "bool", "int", "text", "enum"):
            try:
                validate_scalar(
                    kind,
                    value,
                    minimum=current.minimum,
                    maximum=current.maximum,
                    choices=current.choices,
                )
            except ValueError as error:
                raise C0BindingError(f"{current.name}{path}: {error}") from None
            return ScalarLiteral(value)
        if kind == "optional":
            return ScalarLiteral(None) if value is None else decode(current.element, value, path)
        if kind == "ref":
            if type(value) is not dict or len(value) != 1:
                raise C0BindingError(f"{current.name}{path}: explicit actor/object symbol required")
            identity_kind, symbol = next(iter(value.items()))
            bound = dict(symbols).get(symbol) if type(symbol) is str else None
            if (
                bound is None
                or identity_kind != ("actor" if bound.kind == "person" else "object")
                or not table.accepts_sort(current.sort, bound.sort)
            ):
                raise C0BindingError(f"{current.name}{path}: absent or incompatible opening symbol")
            return SymbolLiteral(
                symbol, "actor" if bound.kind == "person" else "object", bound.sort
            )
        if kind == "record":
            if type(value) is not dict or set(value) != set(dict(current.fields)):
                raise C0BindingError(f"{current.name}{path}: exact named record fields required")
            return RecordLiteral(
                current.name,
                tuple(
                    (name, decode(child, value[name], (*path, name)))
                    for name, child in current.fields
                ),
            )
        if kind == "variant":
            if (
                type(value) is not dict
                or set(value) != {"tag", "fields"}
                or type(value["tag"]) is not str
                or value["tag"] not in dict(current.cases)
            ):
                raise C0BindingError(f"{current.name}{path}: declared Variant tag/fields required")
            return decode(dict(current.cases)[value["tag"]], value["fields"], (*path, value["tag"]))
        if type(value) is not list:
            raise C0BindingError(f"{current.name}{path}: plain collection data required")
        budget.collection(current, value, path)
        return CollectionLiteral(
            kind,
            tuple(
                decode(current.element, item, (*path, index)) for index, item in enumerate(value)
            ),
        )

    return decode(plan, wire, ())
