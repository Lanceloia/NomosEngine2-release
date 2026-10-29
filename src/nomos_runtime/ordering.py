"""Stable local value ordering, independent of policy execution and wire codecs."""

import json
from dataclasses import fields, is_dataclass

from .entities import Reference


def canonical(value):
    def wire(item):
        if type(item) is Reference:
            return ["ref", item.sort, wire(item.ordinal)]
        if type(item) is int:
            return ["int", format(item, "x")]
        if type(item) is frozenset:
            return [
                "set",
                sorted((wire(v) for v in item), key=lambda v: json.dumps(v, sort_keys=True)),
            ]
        if type(item) is tuple:
            return ["sequence", [wire(v) for v in item]]
        if is_dataclass(item):
            return [
                type(item).__name__,
                [(f.name, wire(getattr(item, f.name))) for f in fields(item)],
            ]
        return item

    return json.dumps(wire(value), sort_keys=True, separators=(",", ":"))


def ordered_members(budget, values):
    """Prepare pure Set traversal once per expression root, before any callbacks."""
    if type(values) is not frozenset:
        raise TypeError("ordered members need an exact Set")
    budget.lookup_work(1)
    if len(values) < 2:
        return tuple(values)
    orders = budget._orders
    key = id(values)
    if orders is not None and key in orders:
        return orders[key][1]
    budget.lookup_work(2 * len(values))
    result = tuple(sorted(values, key=canonical))
    if orders is None:
        orders = budget._orders = {}
    orders[key] = (values, result)
    return result
