"""Emit grouped strict maxima and exact virtual scan costs as direct Python."""

import ast

from .syntax import statements


def grouped_latest(
    emitter, node, plan, body, name, pool, depth, *, normal, source, nested, count=False
):
    prefix = name + "_latest"
    names = {
        key: prefix + "_" + key
        for key in (
            "n",
            "rows",
            "positions",
            "index",
            "item",
            "key",
            "version",
            "level",
            "group",
            "versions",
            "indices",
            "first",
            "witnesses",
            "stop",
            "cost",
        )
    }
    n, cost = names["n"], names["cost"]
    logical_depth = f"_depth + {depth}" if nested else str(depth)
    depth_bound = emitter.analysis.facts(node).depth_bound - 1
    k = len(plan.keys)
    slow = []
    normal(slow)
    body.extend(statements(f"_budget.lookup_work(1)\n{n} = len({pool.id})"))
    guard = statements(
        f"if {n} >= 16 and _budget.steps + {n} * {plan.fixed_cost} <= _budget.source_limits.steps "
        f"and ({logical_depth}) + {depth_bound} <= _budget.source_limits.depth:\n    pass"
    )[0]
    rows, positions = names["rows"], names["positions"]
    index, item, key, version = (names[x] for x in ("index", "item", "key", "version"))

    def projection(path):
        value = ast.Name(id=item, ctx=ast.Load())
        for record, field in path.fields:
            value = ast.Attribute(
                value=value, attr=emitter.types.field(record, field), ctx=ast.Load()
            )
        return value

    prepare = statements(
        f"{rows} = []\n{positions} = [{{}} for _ in range({k})]\n"
        f"for {index}, {item} in enumerate({pool.id}):\n"
        f"    {key} = ()\n    {version} = 0\n"
        f"    {rows}.append(({key}, {version}))\n"
        f"    for {names['level']} in range(1, {k + 1}):\n"
        f"        {positions}[{names['level']} - 1]"
        f".setdefault({key}[:{names['level']}], []).append({index})"
    )
    prepare[-1].body[0].value = ast.Tuple(
        elts=[projection(path) for path in plan.keys], ctx=ast.Load()
    )
    prepare[-1].body[1].value = projection(plan.version)
    witnesses, first, versions, indices, group = (
        names[x] for x in ("witnesses", "first", "versions", "indices", "group")
    )
    prepare.extend(
        statements(
            f"{witnesses} = [{n}] * {n}\n"
            f"for {group} in {positions}[-1].values():\n"
            f"    {versions} = {{}}\n"
            f"    for {index} in {group}:\n"
            f"        {versions}.setdefault({rows}[{index}][1], []).append({index})\n"
            f"    {first} = {n}\n"
            f"    for {version} in sorted({versions}, reverse=True):\n"
            f"        {indices} = {versions}[{version}]\n"
            f"        for {index} in {indices}:\n"
            f"            {witnesses}[{index}] = {first}\n"
            f"        {first} = min({first}, {indices}[0])\n"
            f"{cost} = 0\n"
            f"for {index}, ({key}, {version}) in enumerate({rows}):\n"
            f"    {names['stop']} = min({witnesses}[{index}] + 1, {n})\n"
            f"    {cost} += {plan.fixed_cost} + {names['stop']} * {k + plan.equality_costs[0]}"
        )
    )
    cost_loop = prepare[-1]
    for level, equality_cost in enumerate(plan.equality_costs[1:], 1):
        cost_loop.body.extend(
            statements(
                f"{cost} += _bisect_right({positions}[{level - 1}][{key}[:{level}]], "
                f"{names['stop']} - 1) * {equality_cost}"
            )
        )
    cost_loop.body.extend(
        statements(
            f"{cost} += _bisect_right({positions}[-1][{key}], {names['stop']} - 1) "
            f"* {plan.comparison_cost}"
        )
    )
    publish = statements(
        f"if _budget.steps + {cost} <= _budget.source_limits.steps:\n"
        f"    _budget.replay_source({cost})\n"
        f"    {name} = tuple({item} for {index}, {item} in enumerate({pool.id}) "
        f"if {witnesses}[{index}] == {n})\n"
        "else:\n    pass"
    )[0]
    if count:
        publish.body[-1].value = ast.parse(
            f"sum({index} == {n} for {index} in {witnesses})", mode="eval"
        ).body
    publish.orelse = slow
    # Sorting and each prefix bisection fit the n * bit_length(n) operation model.
    row_units = 10 + sum(len(path.fields) for path in plan.keys) + len(plan.version.fields)
    row_units += sum(level + 4 for level in range(1, k + 1))
    guard.body = [
        *statements(
            f"_budget.lookup_work({k + 3} + {n} * ({row_units} + {k + 2} * {n}.bit_length()))"
        ),
        *prepare,
        publish,
    ]
    # The original generated loop supplies the exact failure position at resource boundaries.
    guard.orelse = slow
    body.append(guard)
    emitter.grouped_latest_used = True
    return ast.Name(id=name, ctx=ast.Load())
