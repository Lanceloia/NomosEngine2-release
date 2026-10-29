"""Recognize a checked equality-correlated integer sum, not domain-specific rules."""

from dataclasses import dataclass, field, replace

from .query_fields import HASHABLE_SCALARS, FieldProjection, pool_binding, projection


@dataclass(frozen=True)
class CorrelatedSumPlan:
    rows: object = field(repr=False)
    keys: tuple[tuple[FieldProjection, FieldProjection], ...]
    value: FieldProjection
    equality_costs: tuple[int, ...]
    fixed_cost: int
    row_cost: int
    matched_cost: int
    arguments: tuple = field(default=(), repr=False)
    query: str | None = None


def _size(node):
    return 1 + sum(_size(child) for child in node.children)


def plan_correlated_sum(node):
    if node.operation != "sum_by":
        return None
    if node.children[1].operation == "pure_call":
        return _query_plan(node)
    return _scan_plan(node)


def _equalities(condition):
    equalities, current = [], condition
    while current.operation == "and":
        equalities.append(current.children[1])
        current = current.children[0]
    return [current, *reversed(equalities)]


def _scan_plan(node):
    if node.children[1].operation != "sum_by":
        return None
    inner = node.children[1]
    rows, body = inner.children
    if (
        rows.value_type.kind not in {"set", "sequence"}
        or node.operand == inner.operand
        or (binding := pool_binding(rows)) is None
        or binding[0] in {node.operand, inner.operand}
        or body.operation != "if"
    ):
        return None
    condition, yes, no = body.children
    if no.operation != "literal" or type(no.operand) is not int or no.operand != 0:
        return None
    value = projection(yes, inner.operand)
    if value is None or value.kind != "int":
        return None
    equalities = _equalities(condition)
    if not 1 <= len(equalities) <= 4:
        return None
    keys, costs = [], []
    for equality in equalities:
        if equality.operation != "==":
            return None
        left, right = equality.children
        row, key = projection(left, inner.operand), projection(right, node.operand)
        if row is None or key is None:
            row, key = projection(right, inner.operand), projection(left, node.operand)
        if (
            row is None
            or key is None
            or row.kind not in HASHABLE_SCALARS
            or row.type_id != key.type_id
        ):
            return None
        keys.append((row, key))
        costs.append(_size(equality))
    return CorrelatedSumPlan(
        rows,
        tuple(keys),
        value,
        tuple(costs),
        1 + _size(rows),
        len(equalities) + costs[0] + 1,
        _size(yes) - 1,
    )


def _query_plan(node):
    call = node.children[1]
    arguments, checked_arguments, seen = call.children, [], set()
    fixed_cost, query = 0, call.operand.name
    while True:
        definition = call.operand
        if (
            id(definition) in seen
            or definition.returns.kind != "int"
            or definition.returns.minimum is not None
            or definition.returns.maximum is not None
            or any(
                pool_binding(argument) is None or argument.value_type.type_id != plan.type_id
                for (_, plan), argument in zip(definition.parameters, arguments, strict=True)
            )
        ):
            return None
        seen.add(id(definition))
        checked_arguments.extend(arguments)
        # Each layer pays its own authored paths, not the longer normalized paths.
        fixed_cost += 1 + sum(_size(argument) for argument in call.children)
        substitutions = dict(
            zip((name for name, _ in definition.parameters), arguments, strict=True)
        )
        inner = definition.body
        if inner.operation != "pure_call":
            break
        call = inner
        arguments = tuple(_substitute(arg, substitutions) for arg in call.children)
    if inner.operation != "sum_by" or inner.children[1].operation != "if":
        return None
    # This opaque binder exists only in analysis. Rename before substituting so
    # an actual caller variable named like the callee's row cannot be captured.
    binder = object()

    normalized = replace(
        inner,
        operand=binder,
        children=(
            _substitute(inner.children[0], substitutions),
            _substitute(inner.children[1], substitutions, binding=(inner.operand, binder)),
        ),
    )
    plan = _scan_plan(replace(node, children=(node.children[0], normalized)))
    if plan is None:
        return None
    # Data paths use actual arguments; virtual costs always use the original
    # authored callee. An actual argument's longer path is evaluated once/call.
    condition, yes, _ = inner.children[1].children
    costs = tuple(_size(equality) for equality in _equalities(condition))
    return replace(
        plan,
        equality_costs=costs,
        fixed_cost=fixed_cost + 1 + _size(inner.children[0]),
        row_cost=len(costs) + costs[0] + 1,
        matched_cost=_size(yes) - 1,
        arguments=tuple(checked_arguments),
        query=query,
    )


def _substitute(value, substitutions, *, binding=None):
    if value.operation == "variable":
        if binding is not None and value.operand == binding[0]:
            return replace(value, operand=binding[1])
        return substitutions.get(value.operand, value)
    return replace(
        value,
        children=tuple(
            _substitute(child, substitutions, binding=binding) for child in value.children
        ),
    )
