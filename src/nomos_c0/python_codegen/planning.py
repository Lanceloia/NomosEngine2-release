"""Emit pure prediction functions from the same checked Action bodies as execution."""

from dataclasses import replace

from .fixed_values import fixed_value

IMPORTS = (
    "from nomos_runtime.entities import Reference\n"
    "from nomos_runtime.planning import CompiledPlanning, PlanningAction"
)


def definition(plan, signature, functions):
    achieved, actions = functions
    return (
        f"CompiledPlanning(PROGRAM, {plan.name!r}, {signature!r}, "
        f"{plan.program.table[plan.actor_type].sort!r}, {plan.goal_type!r}, "
        f"_VALIDATORS[{plan.goal_type!r}], {plan.fields!r}, "
        f"({', '.join(actions)},), {achieved}, {plan.reward!r}, {plan.step!r})"
    )


def expression(emitter, checked, environment="environment"):
    # Permission was proved for every read by compile_planning, including dead branches.
    local = replace(checked, summary=replace(checked.summary, context="actor"))
    return emitter.expression(
        local, environment, reads="reads", limits="value_limits", logical_work="work"
    )


def functions(emitter, plan):
    achieved = "_planning_achieved"
    emitter.function(
        achieved,
        "reads, value_limits, goal, work",
        [
            f"environment = {{{plan.actor!r}: reads.controller, 'goal': goal}}",
            "return " + expression(emitter, plan.achieved),
        ],
    )
    actions = []
    carriers = {
        "bool": "bool",
        "unit": "type(None)",
        "int": "int",
        "text": "str",
        "enum": "str",
        "ref": "Reference",
    }
    for index, action in enumerate(plan.actions):
        prefix = f"_planning_action_{index}"
        names = tuple(item.name for item in action.inputs.inputs)
        lines = [
            f"if set(arguments) - set({names!r}): raise ValueError('unknown planning argument')",
            f"environment = {{{action.actor!r}: reads.controller}}",
        ]
        lines.extend(
            f"environment[{p.name!r}] = "
            + fixed_value(
                emitter.program.table, p, references="reads.references", limits="value_limits"
            )
            for p in action.parameters
        )
        for item in action.inputs.inputs:
            lines.extend(
                [
                    f"pool = {expression(emitter, item.pool)}",
                    f"if {item.name!r} not in arguments: return environment, {item.name!r}, pool",
                    f"value = _VALIDATORS[{item.type_name!r}](arguments[{item.name!r}], "
                    "ValueBudget(value_limits, reads.references), ())",
                    "if value not in pool: return None",
                    f"environment[{item.name!r}] = value",
                ]
            )
        for item in action.inputs.inputs:
            if item.constraint is not None:
                lines.append(f"if not {expression(emitter, item.constraint)}: return None")
        lines.extend(
            [
                f"if not {expression(emitter, action.where)}: return None",
                "return environment, None, None",
            ]
        )
        emitter.function(prefix + "_bind", "reads, value_limits, arguments, work", lines)
        lines = [
            f"prepared = {prefix}_bind(reads, value_limits, arguments, work)",
            "if prepared is None or prepared[1] is not None: return None",
            "environment = prepared[0]",
            f"if {len(action.resolution.effects)} > value_limits.nodes:",
            "    raise ValueError('prediction effects exceed execution node budget')",
            "changes = []",
        ]
        for effect in action.resolution.effects:
            kind = emitter.program.entities.field(effect.target.result.sort, effect.field).name
            lines.extend(
                [
                    f"target = {expression(emitter, effect.target)}",
                    f"value = {expression(emitter, effect.value)}",
                    f"_VALIDATORS[{kind!r}](value, "
                    "ValueBudget(value_limits, reads.references), ())",
                    f"changes.append((target, {effect.field!r}, value))",
                ]
            )
        lines.append(expression(emitter, action.resolution.result))
        lines.append("return tuple(changes)")
        emitter.function(prefix + "_predict", "reads, value_limits, arguments, work", lines)
        parameters = ", ".join(
            f"({item.name!r}, {item.type_name!r}, "
            f"{carriers[emitter.program.table[item.type_name].kind]})"
            for item in action.inputs.inputs
        )
        actions.append(
            f"PlanningAction({action.name!r}, ({parameters}{',' if parameters else ''}), "
            f"{prefix}_bind, {prefix}_predict)"
        )
    return achieved, actions
