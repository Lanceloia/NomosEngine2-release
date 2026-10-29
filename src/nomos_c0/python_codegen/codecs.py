"""Generate specialized wire decoders and encoders for checked value types."""

import ast

from .syntax import constant, statements


def emit_decoder(values, plan):
    """Opening wire values become the same immutable carriers as generated rules."""
    function = statements(f"def {values.decoder(plan)}(value, budget, path):\n    pass")[0]
    function.body = [
        ast.Assign(targets=[ast.Name(id="definition", ctx=ast.Store())], value=constant(plan.name))
    ]
    kind = plan.kind
    if kind in {"unit", "bool", "int", "text", "enum"}:
        function.body.extend(statements(f"return {values.validator(plan)}(value, budget, path)"))
        return function
    function.body.extend(statements("budget.check(definition, path)"))
    if kind == "ref":
        function.body.extend(
            statements(
                "if budget.resolve_reference is not None:\n"
                f"    value = budget.resolve_reference(value, {plan.sort!r})\n"
                f"    return {values.validator(plan)}(value, budget, path)\n"
                "if type(value) is not dict or len(value) != 1:\n"
                "    fail_value(definition, path, 'InvalidValue', 'actor/object symbol', "
                "'wrong wire')\n"
                "kind, symbol = next(iter(value.items()))\n"
                "if kind not in ('actor', 'object') or budget.references is None:\n"
                "    fail_value(definition, path, 'UnknownIdentity', 'reference domain', "
                "'absent/wrong kind')\n"
                "value = budget.references.resolve(\n"
                "    'person' if kind == 'actor' else 'object', symbol)\n"
                f"return {values.validator(plan)}(value, budget, path)"
            )
        )
    elif kind == "optional":
        function.body.extend(
            statements(
                "return None if value is None else "
                f"{values.decoder(plan.element)}(value, budget, path)"
            )
        )
    elif kind == "record":
        check = statements(
            "if type(value) is not dict or set(value) != set(()):\n"
            "    fail_value(definition, path, 'InvalidValue', 'exact record fields', "
            "'wrong wire')"
        )[0]
        check.test.values[1].comparators[0].args[0] = constant(
            tuple(name for name, _ in plan.fields)
        )
        function.body.append(check)
        args = [
            ast.Call(
                func=ast.Name(id=values.decoder(child), ctx=ast.Load()),
                args=[
                    ast.Subscript(
                        value=ast.Name(id="value", ctx=ast.Load()),
                        slice=constant(name),
                        ctx=ast.Load(),
                    ),
                    ast.Name(id="budget", ctx=ast.Load()),
                    ast.Tuple(
                        elts=[
                            ast.Starred(value=ast.Name(id="path", ctx=ast.Load()), ctx=ast.Load()),
                            constant(name),
                        ],
                        ctx=ast.Load(),
                    ),
                ],
                keywords=[],
            )
            for name, child in plan.fields
        ]
        function.body.append(
            ast.Return(
                value=ast.Call(
                    func=ast.Name(id=values.carrier(plan), ctx=ast.Load()), args=args, keywords=[]
                )
            )
        )
    elif kind == "variant":
        function.body.extend(
            statements(
                "if (type(value) is not dict or set(value) != {'tag', 'fields'}\n"
                "    or type(value['tag']) is not str):\n"
                "    fail_value(definition, path, 'InvalidValue', 'variant tag/fields', "
                "'wrong wire')"
            )
        )
        for tag, child in plan.cases:
            branch = statements(
                "if value['tag'] == '':\n"
                f"    return {values.decoder(child)}(value['fields'], budget, (*path, ''))"
            )[0]
            branch.test.comparators[0] = constant(tag)
            branch.body[0].value.args[-1].elts[-1] = constant(tag)
            function.body.append(branch)
        function.body.extend(
            statements(
                "fail_value(definition, path, 'InvalidValue', 'declared variant tag', "
                "'unknown tag')"
            )
        )
    else:
        carrier = "frozenset" if kind == "set" else "tuple"
        function.body.extend(
            statements(
                "if type(value) is not list:\n"
                "    fail_value(definition, path, 'InvalidValue', 'collection list', "
                "'wrong wire')\n"
                "budget.collection(definition, path, len(value))\n"
                f"result = {carrier}(\n"
                f"    {values.decoder(plan.element)}(item, budget, (*path, index))\n"
                "    for index, item in enumerate(value))\n"
                "if len(result) != len(value):\n"
                "    fail_value(definition, path, 'InvalidValue', 'unique set elements', "
                "'duplicates')\n"
                "return result"
            )
        )
    return function


def emit_encoder(values, plan):
    """Emit detached wire projections, including nominal variant tags."""
    lines = ["budget.check(" + repr(plan.name) + ", path)"]

    def encode(child, value, path="path"):
        return f"{values.encoder(child)}({value}, budget, {path}, reference)"

    kind = plan.kind
    if kind in {"unit", "bool", "int", "text", "enum"}:
        lines.append("return value")
    elif kind == "ref":
        lines.append("return reference(value)")
    elif kind == "optional":
        lines.append(f"return None if value is None else {encode(plan.element, 'value')}")
    elif kind == "record":
        fields = ", ".join(
            f"{name!r}: {encode(child, 'value.' + name, f'(*path, {name!r})')}"
            for name, child in plan.fields
        )
        lines.append("return {" + fields + "}")
    elif kind == "variant":
        for tag, child in plan.cases:
            lines.append(
                f"if type(value) is {values.carrier(child)}: "
                f"return {{'tag': {tag!r}, 'fields': "
                + encode(child, "value", f"(*path, {tag!r})")
                + "}"
            )
        lines.append("raise TypeError('foreign nominal variant')")
    else:
        lines.extend(
            [
                f"budget.collection({plan.name!r}, path, len(value))",
                "result = ["
                + encode(plan.element, "item", "(*path, index)")
                + " for index, item in enumerate(value)]",
            ]
        )
        if kind == "set":
            lines.append("result.sort(key=wire_key)")
        lines.append("return result")
    return statements(
        f"def {values.encoder(plan)}(value, budget, path, reference):\n"
        + "\n".join("    " + line for line in lines)
    )[0]
