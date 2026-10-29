"""Collapse a proved uniform Set predicate while retaining logical Source traces."""

import ast

from .syntax import statements


def selected(emitter, node, environment):
    if node.operation not in {"exists", "forall", "exactly_one"}:
        return False
    pool, predicate = node.children
    if pool.value_type.kind != "set" or not emitter.proofs.validated_argument(
        pool, pool.value_type, environment
    ):
        return False
    facts = emitter.analysis.facts(predicate)
    if (
        not facts.body_total_with_checked_inputs
        or facts.external_reads
        or facts.queries
        or facts.iteration_dependent
        or facts.may_materialize_values
    ):
        return False
    pending, visited = [predicate], set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if current.operation == "variable" and current.operand == node.operand:
            return False
        pending.extend(current.children)
    return emitter.proofs.checked_operands(predicate, environment)


def emit(emitter, node, body, name, pool, depth, **scope):
    count, before, cost, repeats, steps = (
        name + suffix for suffix in ("_count", "_before", "_cost", "_repeats", "_steps")
    )
    body.extend(statements(f"_budget.lookup_work(1)\n{count} = len(())"))
    body[-1].value.args[0] = pool
    present = statements(f"if {count}:\n    pass\nelse:\n    {name} = False")[0]
    present.body = statements(f"{before} = _budget.steps")
    # One real evaluation fixes the branch and depth trace for all remaining members.
    value = emitter.bound_expression(
        node.children[1],
        node.operand,
        name + "_unused_member",
        present.body,
        depth,
        validated=True,
        **scope,
    )
    operation = node.operation
    expression = ast.unparse(value)
    if operation == "exists":
        repetitions = f"1 if {expression} else {count}"
    elif operation == "forall":
        repetitions = f"{count} if {expression} else 1"
    elif operation == "exactly_one":
        repetitions = f"min({count}, 2) if {expression} else {count}"
    else:
        raise AssertionError("unselected uniform quantifier")
    present.body.extend(
        statements(
            f"{cost} = _budget.steps - {before}\n"
            f"{repeats} = ({repetitions}) - 1\n"
            f"{steps} = {cost} * {repeats}\n"
            f"if _budget.steps + {steps} <= _budget.source_limits.steps:\n"
            f"    _budget.replay_source({steps})\n"
            f"else:\n    for _ in range({repeats}):\n        pass"
        )
    )
    fallback = present.body[-1].orelse[0]
    fallback.body = []
    # The error-only loop retains the original failing Source offset and step prefix.
    emitter.bound_expression(
        node.children[1],
        node.operand,
        name + "_unused_member",
        fallback.body,
        depth,
        validated=True,
        **scope,
    )
    result = f"{expression} and {count} == 1" if operation == "exactly_one" else expression
    present.body.extend(statements(f"{name} = {result}"))
    present.orelse[0].value = ast.Constant(value=operation == "forall")
    body.append(present)
    emitter.note(
        "Passed",
        "uniform-set-quantifier",
        scope["source"],
        (node.offset,),
        "checked-pool-and-total-member-independent-predicate",
        "Evaluate once; replay its proved Source cost; preserve original Source-limit failures.",
    )
    return ast.Name(id=name, ctx=ast.Load())
