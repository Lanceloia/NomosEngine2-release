"""Emit process metadata and executable terminal predicates from checked declarations."""


def process_node(emitter, plan):
    node = plan.process
    if node is None:
        return "None"
    window = "None"
    if node.window is not None:
        window = (
            f"ResponseWindow({node.window.participants!r}, "
            f"{node.window.order!r}, {node.window.successor!r})"
        )
    process = next(p for p in emitter.program.processes if p.name == node.process)
    stage = () if process.stage is None else process.stage.actors
    return (
        f"ProcessNode({node.process!r}, {node.point!r}, {node.prompt!r}, {plan.actor!r}, "
        f"{tuple(c.name for c in node.prefix)!r}, "
        f"{tuple(c.name for c in node.inputs)!r}, {node.resets!r}, {window}, {stage!r})"
    )


def process_completion(emitter, plan):
    node = plan.process
    if node is None:
        return []
    lines = [
        f"draft.next_point, draft.advanced = destination(session, "
        f"session.program.actions[{plan.name!r}].process, record, environment, draft.next_point)"
    ]
    if node.completion is not None:
        lines.extend(
            [
                "if draft.next_point == 'finish':",
                "    completion_reads = ReadContext(session.program.schema_id, "
                "actor_reads.references, draft.after(), 'actor', "
                "session.program.reference_readers, controller)",
                f"    if not {emitter.expression(node.completion, reads='completion_reads')}:",
                "        raise ControlRejection('StageIncomplete', "
                "'post-effect stage completion condition is false')",
            ]
        )
    return lines


def terminal_definition(emitter):
    plan = emitter.program.terminal
    if plan is None:
        return "None"
    setup = [
        f"environment = session.context_values({plan.context.name!r}, states)",
        "world_reads = session.context(states)",
    ]
    emitter.function(
        "_terminal_triggered",
        "session, states",
        [*setup, f"return {emitter.expression(plan.when)}"],
    )
    emitter.function(
        "_terminal_outcome",
        "session, states",
        [*setup, f"return {emitter.expression(plan.value)}, {emitter.expression(plan.to)}"],
    )
    return (
        f"TerminalDefinition({plan.name!r}, {plan.boundary!r}, "
        f"_terminal_triggered, _terminal_outcome, {plan.value.result.name!r})"
    )
