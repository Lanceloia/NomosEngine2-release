"""Share completed pure preparation within one captured candidate rule."""

from collections import Counter, deque

from ..expression_analysis import ExpressionAnalysis
from .proofs import ValueProofs
from .syntax import statements
from .values import ValueEmitter


def repeated_queries(controllers):
    if controllers is None:
        return frozenset()
    selected = set()
    analysis, calls = ExpressionAnalysis(), {}

    def direct(node):
        key = id(node)
        if key not in calls:
            counts, definitions, pending = Counter(), {}, [node]
            while pending:
                current = pending.pop()
                if current.operation == "pure_call":
                    definition = current.operand
                    counts[definition.name] = min(2, counts[definition.name] + 1)
                    definitions[definition.name] = definition
                pending.extend(current.children)
            calls[key] = node, tuple((definitions[name], count) for name, count in counts.items())
        return calls[key][1]

    for _, _, plan in controllers.evaluations:
        if not plan.sites:
            continue
        checked = plan.sites[0].expression
        proofs = ValueProofs(ValueEmitter(checked.source), analysis, checked.table)
        counts, definitions, pending = Counter(), {}, deque()

        def add(definition, amount):
            name = definition.name
            before = counts[name]
            counts[name] = min(2, before + amount)
            definitions[name] = definition
            if counts[name] > before:
                pending.append((definition, counts[name] - before))

        direct_records = Counter()
        for site in plan.sites:
            for definition, count in direct(site.expression.node):
                add(definition, count)
                if definition.returns.kind == "record":
                    direct_records[definition.name] += count
        while pending:
            definition, increment = pending.popleft()
            for child, count in direct(definition.body):
                add(child, increment * count)
        for name, count in counts.items():
            if count < 2:
                continue
            body = definitions[name].body
            result = definitions[name].returns
            facts = analysis.facts(body)
            environment = {parameter: parameter for parameter, _ in definitions[name].parameters}
            bindings = set(environment)
            returns_checked = proofs.validated_argument(
                body, result, environment, bindings=bindings
            ) or proofs.scalar_result_proven(body, result, environment, bindings=bindings)
            if not returns_checked or facts.external_reads:
                continue
            if direct_records[name] > 1 or (
                result.kind in {"set", "sequence", "int", "bool"} and facts.iteration_dependent
            ):
                selected.add(name)
    return frozenset(selected)


def share_query(emitter, definition, function, arguments):
    facts = emitter.analysis.facts(definition.body)
    if facts.external_reads:
        return
    # Identity keys retain their operands. The prepared rule fixes reads, but the key
    # also binds them and the value limits. Expression step/depth limits are
    # checked against the saved cost and depth on every use, not part of the value.
    operands = ", ".join(["reads", "value_limits", *arguments])
    prefix = statements(
        "_frame_cache = _budget.query_values\n"
        "if _frame_cache is not None:\n"
        f"    _budget.lookup_work({3 + len(arguments)} + len(_roles))\n"
        f"    _frame_operands = ({operands},)\n"
        f"    _frame_key = ({function.name!r}, _roles, "
        "tuple(id(value) for value in _frame_operands))\n"
        "    _frame_entry = _frame_cache.get(_frame_key)\n"
        "    if _frame_entry is not None and "
        "_budget.steps + _frame_entry[2] <= _budget.source_limits.steps and "
        f"_depth + {facts.depth_bound} <= _budget.source_limits.depth:\n"
        "        _budget.replay_source(_frame_entry[2])\n"
        "        return _frame_entry[1]\n"
        "_frame_start = _budget.steps"
    )
    result = function.body[-1].value
    function.body[-1:] = [
        emitter.assign("_frame_result", result),
        *statements(
            "if _frame_cache is not None:\n"
            "    _frame_cache[_frame_key] = ("
            "_frame_operands, _frame_result, _budget.steps - _frame_start)\n"
            "return _frame_result"
        ),
    ]
    function.body[:0] = prefix
