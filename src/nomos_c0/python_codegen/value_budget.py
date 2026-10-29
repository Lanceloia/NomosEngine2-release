"""Inline canonical ValueBudget visits at generated nominal validation boundaries."""

import ast
from copy import deepcopy

from .syntax import statements


def inline_value_budget_checks(function):
    """Only rewrite top-level checks with already-bound, effect-free arguments."""
    arguments = {arg.arg for arg in function.args.args}
    if not {"budget", "path"} <= arguments or not function.name.startswith(
        ("_check_", "_shape_", "_decode_", "_encode_")
    ):
        return 0
    bound, output, count = set(arguments), [], 0
    for statement in function.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and (
                isinstance(statement.value, ast.Constant)
                or isinstance(statement.value, ast.Name)
                and statement.value.id in bound
            )
        ):
            bound.add(statement.targets[0].id)
        call = statement.value if isinstance(statement, ast.Expr) else None
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "budget"
            and call.func.attr == "check"
            and not call.keywords
            and len(call.args) == 2
            and all(
                isinstance(arg, ast.Constant) or isinstance(arg, ast.Name) and arg.id in bound
                for arg in call.args
            )
        ):
            output.append(statement)
            # Generation currently places checks before control flow. Do not
            # infer binding facts through arbitrary later statements.
            if not isinstance(statement, ast.Assign):
                bound = set(arguments)
            continue
        definition, path = call.args
        checks = statements(
            "budget.nodes += 1\n"
            "if budget.nodes > budget.limits.nodes or len(path) > budget.limits.depth:\n"
            "    fail_value('', (), 'ValueBudget', 'bounded structure', 'node/depth limit')"
        )
        checks[-1].test.values[1].left.args[0] = deepcopy(path)
        failure = checks[-1].body[0].value
        failure.args[0], failure.args[1] = deepcopy(definition), deepcopy(path)
        output.extend(checks)
        count += 1
    function.body[:] = output
    return count
