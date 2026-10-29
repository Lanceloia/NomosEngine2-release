"""Generate nominal validation, structure checks and record constructors."""

import ast

from .syntax import constant, statements


def emit_shape(values, plan):
    """Intermediate collections have structural budgets, not nominal scalar bounds."""
    function = statements(f"def {values.shape(plan)}(value, budget, path):\n    pass")[0]
    function.body = [
        ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="budget", ctx=ast.Load()), attr="check", ctx=ast.Load()
                ),
                args=[constant(plan.name), ast.Name(id="path", ctx=ast.Load())],
                keywords=[],
            )
        )
    ]
    if plan.kind == "optional":
        function.body.extend(
            statements(
                f"if value is not None:\n    {values.shape(plan.element)}(value, budget, path)"
            )
        )
    elif plan.kind in {"set", "sequence"}:
        check = statements("budget.collection('', path, len(value))")[0]
        check.value.args[0] = constant(plan.name)
        function.body.append(check)
        function.body.extend(
            statements(
                "for index, item in enumerate(value):\n"
                f"    {values.shape(plan.element)}(item, budget, (*path, index))"
            )
        )
    elif plan.kind == "record":
        for name, child in plan.fields:
            check = statements(
                f"{values.shape(child)}(value.{values.field(plan, name)}, budget, (*path, ''))"
            )[0]
            check.value.args[-1].elts[-1] = constant(name)
            function.body.append(check)
    elif plan.kind == "variant":
        for _, child in plan.cases:
            function.body.extend(
                statements(
                    f"if type(value) is {values.carrier(child)}:\n"
                    f"    return {values.shape(child)}(value, budget, path)"
                )
            )
    return function


def emit_validator(values, plan):
    function = statements(f"def {values.validator(plan)}(value, budget, path):\n    pass")[0]
    # Bind diagnostic constants once without interpolating authored names into code.
    function.body = [
        ast.Assign(targets=[ast.Name(id="definition", ctx=ast.Store())], value=constant(plan.name)),
        *statements("budget.check(definition, path)"),
    ]

    def fail_if(condition, code="InvalidValue", actual="wrong scalar carrier"):
        block = statements(
            f"if {condition}:\n    fail_value(definition, path, '', definition, '')"
        )[0]
        block.body[0].value.args[2] = constant(code)
        block.body[0].value.args[4] = constant(actual)
        return block

    if plan.kind in {"bool", "unit", "int", "text", "enum"}:
        carrier = {
            "bool": "bool",
            "unit": "type(None)",
            "int": "int",
            "text": "str",
            "enum": "str",
        }[plan.kind]
        function.body.append(fail_if(f"type(value) is not {carrier}"))
        if plan.kind == "int":
            for bound, operator in ((plan.minimum, "<"), (plan.maximum, ">")):
                if bound is not None:
                    block = fail_if(f"value {operator} 0", actual="integer outside declared bounds")
                    block.test.comparators[0] = constant(bound)
                    function.body.append(block)
        elif plan.kind == "text":
            block = fail_if(
                "len(value) > 0 or any(0xD800 <= ord(char) <= 0xDFFF for char in value)",
                actual="text exceeds its scalar bound or contains a surrogate",
            )
            block.test.values[0].comparators[0] = constant(plan.maximum)
            function.body.append(block)
        elif plan.kind == "enum":
            block = fail_if("value not in ()", actual="value outside declared enum")
            block.test.comparators[0] = constant(plan.choices)
            function.body.append(block)
    elif plan.kind == "ref":
        function.body.extend(
            statements(
                "if budget.references is None:\n"
                "    fail_value(definition, path, 'MissingBinding', 'reference domain', "
                "'absent')\n"
                "budget.references.require(value, '')"
            )
        )
        function.body[-1].value.args[-1] = constant(plan.sort)
    elif plan.kind == "record":
        function.body.append(
            fail_if(
                f"type(value) is not {values.carrier(plan)}",
                "TypeMismatch",
                "foreign nominal value",
            )
        )
        for name, child in plan.fields:
            block = statements(
                f"try:\n    item = value.{values.field(plan, name)}\n"
                "except AttributeError:\n"
                "    fail_value(definition, (*path, ''), 'InvalidValue', '', 'missing field')"
            )[0]
            block.handlers[0].body[0].value.args[1].elts[-1] = constant(name)
            block.handlers[0].body[0].value.args[3] = constant(child.name)
            function.body.append(block)
            call = statements(f"{values.validator(child)}(item, budget, (*path, ''))")[0]
            call.value.args[-1].elts[-1] = constant(name)
            function.body.append(call)
    elif plan.kind == "optional":
        function.body.extend(
            statements(
                f"if value is not None:\n    {values.validator(plan.element)}(value, budget, path)"
            )
        )
    elif plan.kind == "variant":
        branches = []
        for _, child in plan.cases:
            branches.extend(
                statements(
                    f"if type(value) is {values.carrier(child)}:\n"
                    f"    return {values.validator(child)}(value, budget, path)"
                )
            )
        function.body.extend(branches)
        function.body.extend(
            statements(
                "fail_value(definition, path, 'TypeMismatch', definition, 'foreign variant case')"
            )
        )
    else:
        carrier = "tuple" if plan.kind == "sequence" else "frozenset"
        function.body.append(
            fail_if(
                f"type(value) is not {carrier}",
                "TypeMismatch",
                "mutable or wrong collection carrier",
            )
        )
        function.body.extend(
            statements(
                "budget.collection(definition, path, len(value))\n"
                "for index, item in enumerate(value):\n"
                f"    {values.validator(plan.element)}(item, budget, (*path, index))"
            )
        )
    function.body.append(ast.Return(value=ast.Name(id="value", ctx=ast.Load())))
    return function


def emit_constructor(values, plan):
    function = statements(f"def _make_{values.index(plan)}(fields, budget):\n    pass")[0]
    check = statements(
        "if type(fields) is not dict or set(fields) != set(()):\n"
        "    fail_value('', (), 'InvalidConstructor', 'exact declared fields', "
        "'missing or extra field')"
    )[0]
    check.test.values[1].comparators[0].args[0] = constant(tuple(name for name, _ in plan.fields))
    check.body[0].value.args[0] = constant(plan.name)
    function.body = [
        check,
        ast.Return(
            value=ast.Call(
                func=ast.Name(id=values.validator(plan), ctx=ast.Load()),
                args=[
                    ast.Call(
                        func=ast.Name(id=values.carrier(plan), ctx=ast.Load()),
                        args=[
                            ast.Subscript(
                                value=ast.Name(id="fields", ctx=ast.Load()),
                                slice=constant(name),
                                ctx=ast.Load(),
                            )
                            for name, _ in plan.fields
                        ],
                        keywords=[],
                    ),
                    ast.Name(id="budget", ctx=ast.Load()),
                    constant(()),
                ],
                keywords=[],
            )
        ),
    ]
    return function
