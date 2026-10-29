"""Meter optimized expression prefixes without inserting per-node planning callbacks."""

import ast

from .syntax import statements


def meter_expression(function):
    for index, node in enumerate(function.body):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_budget"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "ExpressionBudget"
        ):
            break
    else:
        raise ValueError("generated expression has no owned budget")
    limits = statements("if logical_work is not None:\n    _budget.plan_work(logical_work)")
    guard = statements(
        "try:\n    pass\n"
        "except ExpressionError as _work_failure:\n"
        "    if (logical_work is not None and "
        "_work_failure.diagnostic.code == 'ExpressionBudget' and "
        "_budget.steps > _budget.limits.steps and _budget.limits.steps < limits.steps):\n"
        "        logical_work.interrupt()\n"
        "    raise\n"
        "finally:\n"
        "    if logical_work is not None:\n"
        "        _work_used = _budget.work_used()\n"
        "        if _work_used: logical_work.spend(_work_used)"
    )[0]
    guard.body = function.body[index + 1 :]
    function.body[index:] = [node, *limits, guard]
