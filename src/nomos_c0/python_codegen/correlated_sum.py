"""Emit equality-correlated sums as grouped values and exact virtual scan costs."""

import ast
from copy import deepcopy

from nomos_c0.record_projection import VirtualRecord

from .syntax import statements


def _stable_pool(emitter, node, environment):
    if node.operation == "variable":
        value = environment[node.operand]
        return value if isinstance(value, VirtualRecord) else ast.Name(id=value, ctx=ast.Load())
    parent = _stable_pool(emitter, node.children[0], environment)
    record, field = node.operand
    if isinstance(parent, VirtualRecord):
        return deepcopy(dict(parent.fields)[field])
    return ast.Attribute(value=parent, attr=emitter.types.field(record, field), ctx=ast.Load())


def correlated_sum(
    emitter, node, plan, body, name, pool, depth, *, normal, environment, source, nested
):
    prefix = name + "_sum_index"
    names = {
        key: prefix + "_" + key
        for key in (
            "rows",
            "n",
            "m",
            "prefixes",
            "totals",
            "row",
            "item",
            "key",
            "level",
            "cost",
        )
    }
    rows, n, m, prefixes, totals = (names[key] for key in ("rows", "n", "m", "prefixes", "totals"))
    row, item, key, level, cost = (names[key] for key in ("row", "item", "key", "level", "cost"))

    def project(path, root):
        value = ast.Name(id=root, ctx=ast.Load())
        for record, field in path.fields:
            value = ast.Attribute(
                value=value, attr=emitter.types.field(record, field), ctx=ast.Load()
            )
        return value

    slow = []
    normal(slow)
    rows_value = _stable_pool(emitter, plan.rows, environment)
    pool_work = 2 + sum(
        isinstance(part, (ast.Name, ast.Attribute)) for part in ast.walk(rows_value)
    )
    body.extend(statements(f"_budget.lookup_work({pool_work})"))
    body.append(emitter.assign(rows, rows_value))
    body.extend(statements(f"{n} = len({rows})\n{m} = len({pool.id})"))
    logical_depth = f"_depth + {depth}" if nested else str(depth)
    depth_bound = emitter.analysis.facts(node).depth_bound - 1
    fixed, per_row, delta = plan.fixed_cost, plan.row_cost, plan.matched_cost
    k = len(plan.keys)
    limits_guard = "type(value_limits) is ValueLimits and " if plan.query is not None else ""
    guard = statements(
        f"if {limits_guard}{m} >= 2 and ({n} == 0 or {n} >= 16) and "
        f"_budget.steps + {m} * ({fixed} + {per_row} * {n}) <= _budget.source_limits.steps "
        f"and ({logical_depth}) + {depth_bound} <= _budget.source_limits.depth:\n    pass"
    )[0]
    # Prepay projections, prefix-table writes and keyed reads before allocating tables.
    row_units = 5 + sum(len(path.fields) for path, _ in plan.keys) + len(plan.value.fields)
    row_units += sum(level + 4 for level in range(1, k + 1))
    key_units = 3 + sum(len(path.fields) for _, path in plan.keys)
    key_units += sum(level + 3 for level in range(1, k + 1))
    prepare = statements(
        f"{prefixes} = [{{}} for _ in range({k})]\n{totals} = {{}}\n"
        f"for {row} in {rows}:\n"
        f"    {key} = ()\n"
        f"    for {level} in range(1, {k + 1}):\n"
        f"        {prefixes}[{level} - 1][{key}[:{level}]] = "
        f"{prefixes}[{level} - 1].get({key}[:{level}], 0) + 1\n"
        f"    {totals}[{key}] = {totals}.get({key}, 0) + 0\n"
        f"{name} = 0\n{cost} = {m} * ({fixed} + {per_row} * {n})\n"
        f"for {item} in {pool.id}:\n"
        f"    {key} = ()\n"
        f"    {name} += {totals}.get({key}, 0)"
    )
    build = prepare[2]
    build.body[0].value = ast.Tuple(
        elts=[project(row_path, row) for row_path, _ in plan.keys], ctx=ast.Load()
    )
    build.body[-1].value.right = project(plan.value, row)
    lookup = prepare[-1]
    lookup.body[0].value = ast.Tuple(
        elts=[project(key_path, item) for _, key_path in plan.keys], ctx=ast.Load()
    )
    for index, equality_cost in enumerate(plan.equality_costs[1:], 1):
        lookup.body.extend(
            statements(
                f"{cost} += {prefixes}[{index - 1}].get({key}[:{index}], 0) * {equality_cost}"
            )
        )
    if delta:
        lookup.body.extend(statements(f"{cost} += {prefixes}[-1].get({key}, 0) * {delta}"))
    publish = statements(
        f"if _budget.steps + {cost} <= _budget.source_limits.steps:\n"
        f"    _budget.replay_source({cost})\n"
        "else:\n    pass"
    )[0]
    publish.orelse = deepcopy(slow)
    # No rows means no body evaluation, but every original call/path still costs steps.
    empty = statements(
        f"if {n} == 0:\n    _budget.lookup_work(1)\n"
        f"    {name} = 0\n    _budget.replay_source({m} * {fixed})\nelse:\n    pass"
    )[0]
    empty.orelse = [
        *statements(f"_budget.lookup_work({k + 1} + {n} * {row_units} + {m} * {key_units})"),
        *prepare,
        publish,
    ]
    guard.body, guard.orelse = [empty], deepcopy(slow)
    body.append(guard)
    return ast.Name(id=name, ctx=ast.Load())
