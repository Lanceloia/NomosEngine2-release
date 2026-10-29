"""Generate self-only scheduling projections and current admitted Action cost functions."""

from .fixed_values import fixed_value


def definitions(emitter):
    result = []
    if emitter.program.time is None:
        return "()"
    for index, plan in enumerate(emitter.program.time.schedules):
        name = f"_schedule_{index}"
        lines = [
            "actor_reads = ReadContext(session.program.schema_id, "
            "session.references.at(states), states, 'actor', "
            "session.program.reference_readers, actor)",
            f"environment = {{{plan.actor!r}: actor}}",
        ]
        lines.extend(
            f"environment[{p.name!r}] = {fixed_value(emitter.program.table, p)}"
            for p in plan.parameters
        )
        lines.append(
            f"return Projection({emitter.expression(plan.speed)}, "
            f"{emitter.expression(plan.eligible)})"
        )
        emitter.function(name, "session, states, actor", lines)
        result.append(
            f"ScheduleDefinition({plan.family!r}, {plan.initial!r}, {plan.priority!r}, {name})"
        )
    return "(" + ", ".join(result) + (",)" if result else ")")


def action_cost(emitter, name, plan, views):
    if plan.time_cost is None:
        return "None"
    lines = [*emitter.context(views), "environment = dict(environment)"]
    if plan.context is not None:
        lines.append(
            f"environment = {{**session.context_values({plan.context.name!r}, before, local=True), "
            "**environment}"
        )
    lines.append("return " + emitter.expression(plan.time_cost))
    emitter.function(name, "session, before, controller, environment, receipts, record", lines)
    return name
