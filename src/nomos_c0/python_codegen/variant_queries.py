"""Bypass query calls for checked constant variant arms, retaining all visits."""

import ast

from .syntax import constant, statements


def constant_variant_call(
    emitter, definition, plan, arguments, body, name, normal, depth, *, nested
):
    table = "_QUERY_CONSTANT_CASES_" + definition.name
    emitter.constant_variant_tables[table] = definition, plan
    arm = name + "_constant_arm"
    lookup = ast.Call(
        func=ast.Attribute(value=ast.Name(id=table, ctx=ast.Load()), attr="get", ctx=ast.Load()),
        args=[
            ast.Call(
                func=ast.Name(id="type", ctx=ast.Load()),
                args=[arguments[plan.parameter]],
                keywords=[],
            )
        ],
        keywords=[],
    )
    body.append(emitter.assign(arm, lookup))
    origin = emitter.source_name(definition.source)

    def logical(distance):
        return f"_depth + {depth + distance}" if nested else str(depth + distance)

    # These are the original match, subject and selected literal visits, in order.
    fast = statements(
        f"_budget.visit({origin}, {definition.body.offset}, {logical(1)})\n"
        f"_budget.visit({origin}, {definition.body.children[0].offset}, {logical(2)})\n"
        f"_budget.visit({origin}, {arm}[1], {logical(2)})\n"
        f"{name} = {arm}[0]"
    )
    body.append(
        ast.If(
            test=ast.Compare(
                left=ast.Name(id=arm, ctx=ast.Load()),
                ops=[ast.IsNot()],
                comparators=[constant(None)],
            ),
            body=fast,
            orelse=normal,
        )
    )


def emit_constant_variant_tables(emitter):
    output = []
    for name, (definition, plan) in emitter.constant_variant_tables.items():
        carriers = dict(definition.body.children[0].value_type.cases)
        output.append(
            emitter.assign(
                name,
                ast.Dict(
                    keys=[
                        ast.Name(id=emitter.types.carrier(carriers[tag]), ctx=ast.Load())
                        for tag, _, _ in plan.cases
                    ],
                    values=[constant((value, offset)) for _, value, offset in plan.cases],
                ),
            )
        )
    return output
