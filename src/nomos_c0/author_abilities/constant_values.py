"""Nominal compiler values checked against an explicit declaration symbol table."""

from dataclasses import dataclass

from .literal_values import SymbolLiteral
from .value_types import TypeId, TypeTable
from .values import ValueLimits, _Budget, _fail, validate_scalar


@dataclass(frozen=True)
class ConstantValue:
    type_id: TypeId
    value: object


@dataclass(frozen=True)
class ConstantValues:
    table: TypeTable
    symbols: tuple = ()
    limits: ValueLimits = ValueLimits()

    def bind(self, name, value):
        plan = self.table[name]
        if type(value) is ConstantValue:
            actual = plan if value.type_id == plan.type_id else self.table.by_id(value.type_id)
            if actual is None or not self.table.assignable(plan, actual):
                _fail(plan, (), "TypeMismatch", plan.name, "foreign nominal constant")
            value = value.value
        budget = _Budget(self.limits)

        def check(kind, item, path):
            budget.check(kind, path)
            if kind.kind == "ref":
                symbol = (
                    dict(self.symbols).get(item.symbol) if type(item) is SymbolLiteral else None
                )
                if (
                    symbol is None
                    or item.kind != ("actor" if symbol.kind == "person" else "object")
                    or item.sort != symbol.sort
                    or not self.table.accepts_sort(kind.sort, symbol.sort)
                ):
                    _fail(
                        kind, path, "InvalidConstant", kind.name, "undeclared or wrong-sort symbol"
                    )
            elif kind.kind == "optional":
                if item is not None:
                    check(kind.element, item, path)
            elif kind.kind == "record":
                if type(item) is not kind.annotation:
                    _fail(kind, path, "TypeMismatch", kind.name, "foreign nominal record")
                for field, child in kind.fields:
                    try:
                        member = object.__getattribute__(item, kind.storage_field(field))
                    except AttributeError:
                        _fail(kind, (*path, field), "InvalidConstant", child.name, "missing field")
                    check(child, member, (*path, field))
            elif kind.kind == "variant":
                child = next(
                    (child for _, child in kind.cases if type(item) is child.annotation), None
                )
                if child is None:
                    _fail(kind, path, "TypeMismatch", kind.name, "foreign variant case")
                check(child, item, path)
            elif kind.kind in ("set", "sequence"):
                if type(item) is not (frozenset if kind.kind == "set" else tuple):
                    _fail(kind, path, "TypeMismatch", "immutable collection", type(item).__name__)
                budget.collection(kind, item, path)
                for index, member in enumerate(item):
                    check(kind.element, member, (*path, index))
            else:
                try:
                    validate_scalar(
                        kind.kind,
                        item,
                        minimum=kind.minimum,
                        maximum=kind.maximum,
                        choices=kind.choices,
                    )
                except ValueError as error:
                    _fail(kind, path, "InvalidValue", kind.name, str(error))

        check(plan, value, ())
        return ConstantValue(plan.type_id, value)

    def construct(self, name, fields, /, *, tag=None):
        plan = self.table[name]
        selected = dict(plan.cases).get(tag) if plan.kind == "variant" else plan
        if (
            selected is None
            or selected.kind != "record"
            or (plan.kind == "record" and tag is not None)
        ):
            _fail(plan, (), "InvalidConstructor", "declared record or variant case", str(tag))
        if type(fields) is not dict or set(fields) != set(dict(selected.fields)):
            _fail(plan, (), "InvalidConstructor", "exact declared fields", "missing or extra field")
        values = {
            selected.storage_field(field): self.bind(child.name, fields[field]).value
            for field, child in selected.fields
        }
        return self.bind(name, selected.annotation(**values))
