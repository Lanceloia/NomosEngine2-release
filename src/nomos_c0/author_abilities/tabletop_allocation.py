"""Checked allocation presentation over ordinary nominal input values."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


def nonnegative(value_type):
    return value_type.kind == "int" and value_type.minimum is not None and value_type.minimum >= 0


def allocation_shape(value_type, names):
    if (
        type(names) is not dict
        or set(names) != {"rows", "target", "quantity", "reserve"}
        or any(type(name) is not str for name in names.values())
        or names["rows"] == names["reserve"]
        or names["target"] == names["quantity"]
        or value_type.kind != "record"
    ):
        raise C0LawError("allocation requires named rows, target, quantity and reserve fields")
    fields = dict(value_type.fields)
    if set(fields) != {names["rows"], names["reserve"]}:
        raise C0LawError("allocation requires exact rows and reserve record fields")
    rows, reserve = fields[names["rows"]], fields[names["reserve"]]
    if rows.kind != "sequence" or rows.element.kind != "record" or not nonnegative(reserve):
        raise C0LawError("allocation requires record rows and nonnegative reserve")
    columns = dict(rows.element.fields)
    if set(columns) != {names["target"], names["quantity"]}:
        raise C0LawError("allocation rows require exact target and quantity fields")
    key, quantity = columns[names["target"]], columns[names["quantity"]]
    if key.kind not in ("int", "text", "enum", "bool", "ref") or not nonnegative(quantity):
        raise C0LawError("allocation requires scalar target keys and nonnegative quantities")
    return key


@dataclass(frozen=True)
class AllocationInput:
    targets: object
    total: object
    minimum: object
    key: str
    label: str
    capacity: str


def compile_allocation(table, input_plan, components, declaration, expression, available, location):
    from .frontend import row

    row(declaration, {"targets", "key", "label", "capacity", "total", "minimum"}, path=location)
    component = next((c for c in components if c.type_name == input_plan.type_name), None)
    if input_plan.kind != "enter" or component is None or component.kind != "allocation":
        raise C0LawError("allocation metadata requires a typed allocation component input")
    key_type = allocation_shape(table[input_plan.type_name], component.specification["fields"])
    targets = expression(declaration["targets"], None, available, location + ".targets")
    kind = targets.result
    if kind.kind not in ("set", "sequence") or kind.element.kind != "record":
        raise C0LawError("allocation targets require a record collection")
    fields = dict(kind.element.fields)
    key, label, capacity = (declaration[k] for k in ("key", "label", "capacity"))
    if any(type(k) is not str or k not in fields for k in (key, label, capacity)):
        raise C0LawError("allocation targets require actual key, label and capacity fields")
    if (
        fields[key].name != key_type.name
        or fields[label].kind != "text"
        or not nonnegative(fields[capacity])
    ):
        raise C0LawError("allocation target key, label or capacity has the wrong nominal type")
    total = expression(declaration["total"], None, available, location + ".total")
    minimum = expression(declaration["minimum"], None, available, location + ".minimum")
    if not nonnegative(total.node.value_type) or not nonnegative(minimum.node.value_type):
        raise C0LawError("allocation total and minimum require nonnegative integers")
    return AllocationInput(targets, total, minimum, key, label, capacity)
