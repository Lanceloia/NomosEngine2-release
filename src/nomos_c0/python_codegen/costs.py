"""Generate current affordability checks and resource deductions into the existing Draft."""

from nomos_c0.author_contract_v1 import C0LawError


def costs(world, plan, *, execute):
    lines = []
    for index, cost in enumerate(plan.costs):
        if cost.operation != "consume":
            raise C0LawError("Python world generation does not yet support non-consume costs")
        lines.extend(
            [
                f"target_{index} = {world.expression(cost.target)}",
                f"amount_{index} = {world.expression(cost.value)}",
                f"balance_{index} = actor_reads.read(target_{index}, "
                f"{cost.target.result.sort!r}, {cost.field!r}, own=True)",
                f"if amount_{index} < 0 or amount_{index} > balance_{index}: "
                "raise AdmissionError('InsufficientResource', 'cost is not affordable')",
            ]
        )
        field_type = world.program.entities.field(cost.target.result.sort, cost.field).name
        lines.append(
            f"_VALIDATORS[{field_type!r}](balance_{index} - amount_{index}, "
            "ValueBudget(session.limits.value, session.references), ())"
        )
        if execute:
            lines.append(
                f"draft.set(target_{index}, {cost.field!r}, balance_{index} - amount_{index})"
            )
    return lines
