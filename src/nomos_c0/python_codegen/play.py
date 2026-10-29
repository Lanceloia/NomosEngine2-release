"""Emit selected control mechanisms without encoding game-specific turns."""


def play_definition(emitter):
    plan = emitter.program.play
    if plan is None:
        return "None"
    formed = tuple(
        sorted(
            {
                product.schema.name
                for rule in emitter.resolution_plans
                for node in rule.resolution.walk()
                for product in node.forms
                if product.schema.kind == "person"
            }
        )
    )
    if plan.mechanism == "player_turn":
        return f"PlayDefinition('player_turn', {plan.player!r}, (), (), {formed!r})"
    joint = ", ".join(
        f"JointDecision({p.name!r}, {p.projection!r}, {p.participant!r}, "
        f"{p.locked!r}, {p.context!r}, {p.epoch!r}, {p.actions!r})"
        for p in plan.joint_decisions
    )
    return (
        f"PlayDefinition('tabletop', None, {plan.seats!r}, "
        f"({joint}{',' if joint else ''}), {formed!r})"
    )
