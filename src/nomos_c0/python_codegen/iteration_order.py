"""Select deterministic traversal only for pure expressions over nominal Sets."""

import ast


def ordered_pool(node, pool, body, name):
    if node.value_type.kind != "set":
        return pool
    target = name + "_ordered"
    body.append(
        ast.Assign(
            targets=[ast.Name(id=target, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="_ordered_members", ctx=ast.Load()),
                args=[ast.Name(id="_budget", ctx=ast.Load()), pool],
                keywords=[],
            ),
        )
    )
    return ast.Name(id=target, ctx=ast.Load())
