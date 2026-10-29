"""Recognize a checked same-sequence strict anti-dominance query."""

from dataclasses import dataclass

from .query_fields import (
    HASHABLE_SCALARS,
    FieldProjection,
    pool_binding,
    projection,
    same_projection,
)


@dataclass(frozen=True)
class GroupedLatestPlan:
    keys: tuple[FieldProjection, ...]
    version: FieldProjection
    equality_costs: tuple[int, ...]
    comparison_cost: int
    fixed_cost: int


def _size(node):
    return 1 + sum(_size(child) for child in node.children)


def plan_grouped_latest(node):
    if node.operation != "filter" or node.children[0].value_type.kind != "sequence":
        return None
    pool, predicate = node.children
    if predicate.operation != "not" or predicate.children[0].operation != "exists":
        return None
    exists = predicate.children[0]
    binding = pool_binding(pool)
    if (
        binding is None
        or binding != pool_binding(exists.children[0])
        or node.operand == exists.operand
        or binding[0] in {node.operand, exists.operand}
    ):
        return None

    # A left-associated conjunction visits every conjunction before its first test.
    comparisons, current = [], exists.children[1]
    while current.operation == "and":
        comparisons.append(current.children[1])
        current = current.children[0]
    comparisons = [current, *reversed(comparisons)]
    if not 2 <= len(comparisons) <= 5:
        return None
    keys, costs = [], []
    for equality in comparisons[:-1]:
        if equality.operation != "==":
            return None
        left, right = equality.children
        inner, outer = projection(left, exists.operand), projection(right, node.operand)
        if inner is None or outer is None:
            inner, outer = projection(right, exists.operand), projection(left, node.operand)
        if not same_projection(inner, outer) or inner.kind not in HASHABLE_SCALARS:
            return None
        keys.append(inner)
        costs.append(_size(equality))
    comparison = comparisons[-1]
    if comparison.operation not in {">", "<"}:
        return None
    left, right = comparison.children
    if comparison.operation == "<":
        left, right = right, left
    version, outer = projection(left, exists.operand), projection(right, node.operand)
    if not same_projection(version, outer) or version.kind != "int":
        return None
    return GroupedLatestPlan(
        tuple(keys), version, tuple(costs), _size(comparison), 2 + _size(exists.children[0])
    )
