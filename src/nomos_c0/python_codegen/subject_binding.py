"""Compile finite policy domains into detached, incremental Subject bindings."""

from nomos_c0.author_contract_v1 import C0LawError

from .fixed_values import fixed_value
from .input_bindings import InputBindings
from .planning_construction import carrier, emit_prepared_expression


def functions(emitter, name, plan, strategy, rule, views):
    supplied, choices = dict(rule.supplied), dict(rule.choices)
    if plan.process is not None:
        raise C0LawError("automatic Subject binding requires atomic capabilities")
    if any(i.kind in {"derive", "sequence"} for i in plan.inputs.inputs):
        raise C0LawError("automatic Subject binding needs finite member/subset or policy pools")
    aliases = tuple(dict.fromkeys(a for a, _ in (*plan.views, *strategy.views, *rule.views)))
    preparation = []

    def expression(checked):
        index = len(preparation)
        descriptor = emit_prepared_expression(emitter, checked, name + "_domain_" + str(index))
        preparation.append(f"_domain_{index} = {descriptor}")
        return f"preparation.evaluate(_domain_{index}, environment, work)"

    lines = [
        "record = None",
        *InputBindings(emitter).environment(plan, views),
        "from nomos_runtime.entities import detached_reads",
        f"actor_reads = detached_reads(actor_reads, {aliases!r})",
        "base = dict(environment)",
        f"base[{strategy.actor!r}] = actor",
        *(
            f"base[{p.name!r}] = "
            + fixed_value(emitter.program.table, p, references="actor_reads.references")
            for p in strategy.parameters
        ),
        "value_limits = session.limits.value",
        f"work.spend({max(1, len(aliases))})",
    ]
    # Domain expressions retain the world's Actor binder; policy expressions use its own.
    bind = [
        f"if set(arguments) - set({tuple(i.name for i in plan.inputs.inputs)!r}): "
        "raise ValueError('unknown Subject argument')",
        "environment = {**base, **arguments}",
        f"environment[{plan.actor!r}] = actor",
    ]
    subsets = []
    for item in plan.inputs.inputs:
        override = item.name in supplied or item.name in choices
        subset = item.kind == "subset" and not override
        if subset:
            subsets.append(
                f"({item.name!r}, "
                f"{carrier(emitter, emitter.program.table[item.type_name].element)})"
            )
        if item.kind == "enter" and not override:
            raise C0LawError(
                "typed Subject entry requires a construction recipe or finite policy pool"
            )
        if item.name in supplied:
            pool = f"frozenset(({expression(supplied[item.name])},))"
        elif item.name in choices:
            pool = expression(choices[item.name])
        else:
            pool = expression(item.pool)
        bind.append("pool = " + pool)
        if subset:
            bind.extend(
                [
                    "minimum = " + expression(item.minimum),
                    "maximum = " + expression(item.maximum),
                    "if minimum < 0 or maximum < minimum or minimum > len(pool): return None",
                    f"if {item.name!r} not in arguments: "
                    f"return {item.name!r}, SubsetDomain(pool, minimum, maximum)",
                ]
            )
        else:
            bind.append(f"if {item.name!r} not in arguments: return {item.name!r}, pool")
        bind.append(
            f"value = _VALIDATORS[{item.type_name!r}](arguments[{item.name!r}], "
            "ValueBudget(value_limits, actor_reads.references), ())"
        )
        bind.append(
            "if not value <= pool or not minimum <= len(value) <= maximum: return None"
            if subset
            else "if value not in pool: return None"
        )
        bind.append(f"environment[{item.name!r}] = value")
        # A finite policy pool selects proposals; it never widens the world input domain.
        if override and item.kind in {"member", "subset"}:
            bind.append("allowed = " + expression(item.pool))
            if item.kind == "member":
                bind.append("if value not in allowed: return None")
            else:
                bind.extend(
                    [
                        "if not value <= allowed: return None",
                        f"if not {expression(item.minimum)} <= len(value) "
                        f"<= {expression(item.maximum)}: return None",
                    ]
                )
    for item in plan.inputs.inputs:
        if item.constraint is not None:
            bind.append(f"if not {expression(item.constraint)}: return None")
    bind.extend([f"if not {expression(plan.where)}: return None", "return None, environment"])
    parameters = ", ".join(
        f"({i.name!r}, {i.type_name!r}, {carrier(emitter, emitter.program.table[i.type_name])})"
        for i in plan.inputs.inputs
    )
    emitter.function(
        name,
        "session, actor, work",
        [
            *lines,
            "from nomos_runtime.planning_preparation import "
            "ConstructionFrame, ConstructionExpression",
            "preparation = ConstructionFrame(actor_reads, value_limits)",
            *preparation,
            "def bind(reads, limits, local, goal, arguments, work):",
            *("    " + line for line in bind),
            "def predict(reads, limits, local, state, goal, arguments, work):",
            "    if state: return None",
            "    bound = bind(reads, limits, local, goal, arguments, work)",
            "    return None if bound is None or bound[0] is not None else (True, None, 0)",
            f"return PlanningAction({plan.name!r}, ({parameters}{',' if parameters else ''}), "
            f"bind, predict, ({', '.join(subsets)}{',' if subsets else ''}))",
        ],
    )
    return name
