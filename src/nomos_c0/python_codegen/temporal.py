"""Emit direct callbacks for authored activities, cancellation, and periodic Events."""

from dataclasses import replace

from nomos_c0.author_abilities.activities import local_dependencies

from .costs import costs
from .fixed_values import fixed_value
from .scheduling import action_cost, definitions


def cancellation_inputs(plan):
    return (
        plan.where,
        *((plan.time_cost,) if plan.time_cost is not None else ()),
        *(expr for cost in plan.costs for expr in cost.expressions()),
        *(
            argument
            if delivery.variable is None
            else replace(
                argument,
                inputs=tuple(pair for pair in argument.inputs if pair[0] != delivery.variable),
            )
            for leaf in plan.resolution.leaves()
            for delivery in leaf.deliveries
            for argument in delivery.expressions()
        ),
    )


def start_checks(emitter, plan):
    lines = []
    for activity in emitter.program.activities:
        if plan.source not in activity.completion.triggers:
            continue
        expressions = (activity.duration,)
        if activity.cancellation is not None:
            expressions += cancellation_inputs(activity.cancellation)
        used = {name for expression in expressions for name, _ in expression.inputs}
        lines.extend(
            fixed_value(emitter.program.table, parameter, references="actor_reads.references")
            for parameter in activity.completion.parameters
            if parameter.name in used
        )
    return lines


def start_requests(emitter, plan):
    return [
        f"draft.scheduled.append(_activity_{index}_start("
        "session, before, controller, environment, draft.result, receipts))"
        for index, activity in enumerate(emitter.program.activities)
        if plan.source in activity.completion.triggers
    ]


def _return_values(names):
    if not names:
        return "()"
    return "(" + ", ".join(f"({name!r}, environment[{name!r}])" for name in names) + ",)"


def due_callback(emitter, name, plan):
    names = (*(name for name, _, _ in plan.captures), *(p.name for p in plan.parameters))
    lines = ["environment = dict(pending.values)", "world_reads = session.context(before)"]
    for key, kind in (
        *((name, kind) for name, _, kind in plan.captures),
        *((p.name, p.type_name) for p in plan.parameters),
    ):
        lines.append(
            f"_VALIDATORS[{kind!r}](environment[{key!r}], "
            "ValueBudget(session.limits.value, world_reads.references), ())"
        )
    if plan.context is not None:
        lines.append(
            f"environment = {{**session.context_values({plan.context.name!r}, before), "
            "**environment}"
        )
    lines.append(
        "draft = Draft(session, before, world_reads.references, "
        "session.limits.value, occurrence, allocation)"
    )
    lines.extend(emitter.resolutions.emit(emitter, plan))
    lines.append("return draft, dict(" + _return_values(names) + ")")
    emitter.function(name, "session, before, pending, receipts, occurrence, allocation", lines)


def activity_definition(emitter, index, activity):
    plan = activity.completion
    prefix = f"_activity_{index}"
    lines = [
        "original = dict(environment)",
        "original['result'] = result",
        *emitter.context(),
        "environment = {}",
    ]
    for local, remote, kind in plan.captures:
        lines.append(
            f"environment[{local!r}] = _VALIDATORS[{kind!r}](original[{remote!r}], "
            "ValueBudget(session.limits.value, world_reads.references), ())"
        )
    lines.extend(
        f"environment[{p.name!r}] = {fixed_value(emitter.program.table, p)}"
        for p in plan.parameters
    )
    names = (*(key for key, _, _ in plan.captures), *(p.name for p in plan.parameters))
    lines.append("values = " + _return_values(names))
    if plan.context is not None:
        lines.append(
            f"environment = {{**session.context_values({plan.context.name!r}, before, "
            "local=True), **environment}"
        )
    duration = emitter.expression(local_dependencies(activity.duration), reads="actor_reads")
    lines.append(
        f"return ActivityRequest({plan.name!r}, environment[{activity.actor!r}], "
        f"{duration}, values)"
    )
    emitter.function(
        prefix + "_start", "session, before, controller, environment, result, receipts", lines
    )
    due_callback(emitter, prefix + "_due", plan)
    cancel = "None"
    if activity.cancellation is not None:
        cancellation = activity.cancellation
        deferred = {slot.name for node in cancellation.resolution.walk() for slot in node.draws}
        lines = [
            "before = session._states",
            "controller = actor",
            "receipts = session._receipts",
            *emitter.context(),
            "environment = dict(choices.values)",
        ]
        if cancellation.context is not None:
            lines.append(
                f"environment = {{**session.context_values({cancellation.context.name!r}, "
                "before, local=True), **environment}"
            )
        inputs = dict(
            (key, spec.type_name)
            for expression in cancellation_inputs(cancellation)
            for key, spec in expression.inputs
            if key not in deferred
        )
        lines.extend(
            f"_VALIDATORS[{kind!r}](environment[{key!r}], "
            "ValueBudget(session.limits.value, actor_reads.references), ())"
            for key, kind in inputs.items()
        )
        lines.append(
            f"if not {emitter.expression(cancellation.where)}: "
            "raise AdmissionError('NotAdmitted', 'cancellation condition is false')"
        )
        lines.extend(costs(emitter, cancellation, execute=False))
        lines.append("return ActionAdmission(dict(choices.values), None)")
        emitter.function(prefix + "_cancel_admit", "session, actor, choices, record", lines)
        emitter.execution(prefix + "_cancel_execute", cancellation, process=False)
        cost = action_cost(emitter, prefix + "_cancel_time_cost", cancellation, None)
        cancel = (
            f"ActionDefinition({cancellation.name!r}, {cancellation.source!r}, "
            f"{emitter.program.table[cancellation.actor_type].sort!r}, "
            f"{prefix}_cancel_admit, {prefix}_cancel_execute, None, None, {cost}, None, None, "
            f"{cancellation.actor!r}, "
            f"{cancellation.resolution.leaves()[0].result.result.name!r}, ())"
        )
    return f"ActivityDefinition({plan.name!r}, {plan.source!r}, {prefix}_due, {cancel})"


def time_definition(emitter):
    if emitter.program.time is None:
        return "None"
    activities = [
        activity_definition(emitter, index, plan)
        for index, plan in enumerate(emitter.program.activities)
    ]
    periodic = []
    for index, plan in enumerate(emitter.program.periodic):
        name, event = f"_periodic_{index}", plan.event
        # Opening binds only fixed inputs; current context fields are read at each due.
        lines = ["environment = {}"]
        lines.extend(
            f"environment[{p.name!r}] = {fixed_value(emitter.program.table, p)}"
            for p in event.parameters
        )
        names = tuple(p.name for p in event.parameters)
        lines.append("return " + (_return_values(names) if names else "()"))
        emitter.function(name + "_opening", "session", lines)
        due_callback(emitter, name + "_due", event)
        periodic.append(
            f"PeriodicDefinition({event.name!r}, {event.source!r}, "
            f"{plan.interval!r}, {plan.first_after!r}, {name}_opening, {name}_due)"
        )
    return (
        f"TimeDefinition({emitter.program.time.order!r}, "
        f"({', '.join(activities)}{',' if activities else ''}), "
        f"({', '.join(periodic)}{',' if periodic else ''}), {definitions(emitter)})"
    )
