"""Generate current projections, opening disclosures and typed local readers."""

from nomos_c0.author_abilities.entity_reads import projection_can_grant_references

from .assurances import certification
from .fixed_values import fixed_value


def context_definition(emitter, index, plan):
    name = f"_context_{index}"
    lines = ["environment = {}"]
    lines.extend(
        f"environment[{p.name!r}] = {fixed_value(emitter.program.table, p)}"
        for p in plan.parameters
    )
    emitter.function(name + "_bind", "session", [*lines, "return environment"])
    lines = [
        f"environment = session.context_values({plan.name!r}, session._states)",
        "world_reads = session.context(session._states)",
    ]
    if plan.assertion is not None:
        lines.append(
            f"if not {emitter.expression(plan.assertion)}: "
            f"raise AdmissionError('OpeningConstraint', {plan.name!r})"
        )
    lines.append("return None")
    emitter.function(name + "_check", "session", lines)
    fields = (
        () if plan.state is None else tuple((key, kind.name) for key, kind in plan.state.fields)
    )
    public = () if plan.state is None else plan.state.public
    return (
        f"ContextDefinition({plan.name!r}, {name}_bind, {name}_check, {fields!r}, "
        f"{public!r}, {plan.world_parameters!r})"
    )


def projection_function(emitter, index, plan):
    name = f"_projection_{index}"
    lines = [
        f"environment = {{**session.context_values({plan.context.name!r}, states), "
        f"{plan.viewer!r}: viewer}}",
        "world_reads = session.context(states, controller=viewer)",
        f"if not {emitter.expression(plan.audience)}: return False, None",
        f"return True, {emitter.expression(plan.value)}",
    ]
    emitter.function(name, "session, states, viewer", lines)
    return name


def projection_definition(emitter, index, plan):
    name = projection_function(emitter, index, plan)
    grants = projection_can_grant_references(
        plan.value.result, dict(emitter.program.entities.entities)
    )
    return (
        f"ProjectionDefinition({plan.name!r}, {emitter.program.table[plan.viewer_type].sort!r}, "
        f"{plan.value.result.name!r}, {name}, {grants!r})"
    )


def information_definition(emitter, index, plan):
    projection = plan.projection
    name = projection_function(emitter, index, projection)
    checker = certification(emitter, plan)
    return (
        f"InformationDefinition({projection.name!r}, "
        f"{emitter.program.table[projection.viewer_type].sort!r}, "
        f"{projection.value.result.name!r}, {name}, {checker})"
    )


def local_readers(emitter, prefix, plan, *, memoize=False):
    name = prefix + "_views"
    lines = [*(["from functools import cache"] if memoize else []), "return {"]
    for alias, view in plan.views:
        if view.kind == "reports" and not view.process_point:
            reader = (
                f"lambda: _report_inputs.checked_reports(session, _VALIDATORS[{view.type_name!r}], "
                f"controller, {view.channel!r}, {view.source!r}, before, receipts, record)"
            )
        else:
            if view.process_point:
                value = (
                    f"_report_inputs.process_information_values(controller, {view.channel!r}, "
                    f"{view.source!r}, receipts, record, {view.process_point!r})"
                )
            elif view.kind == "cognition":
                value = f"session.cognition_value(controller, {view.channel!r})"
            else:
                value = f"session.projected_value(controller, {view.channel!r}, before)"
            reader = (
                f"lambda: _VALIDATORS[{view.type_name!r}]({value}, "
                "ValueBudget(session.limits.value, session.references), ())"
            )
        if memoize:
            reader = f"cache({reader})"
        lines.append(f"    {alias!r}: {reader},")
    lines.append("}")
    emitter.function(name, "session, before, controller, receipts, record", lines)
    return name
