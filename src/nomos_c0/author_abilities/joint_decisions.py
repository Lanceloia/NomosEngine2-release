"""Checked tabletop coordination descriptions over actual local projections."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier


@dataclass(frozen=True)
class JointDecisionPlan:
    name: str
    projection: str
    participant: str
    locked: str
    context: str
    epoch: str
    actions: tuple[str, ...]


def compile_joint_decisions(declarations, seats, actors, table, projections, abilities):
    from .frontend import row

    if not isinstance(declarations, dict):
        raise C0LawError("tabletop joint_decisions requires named windows")
    views = {p.name: p for p in projections}
    actions = {p.name: p for p in abilities}
    selected, used = [], set()
    for name, spec in declarations.items():
        path = "play.joint_decisions." + str(name)
        if not _identifier(name):
            raise C0LawError(path + ": named window required")
        row(spec, {"projection", "participant", "locked", "epoch", "actions"}, path=path)
        view = views.get(spec["projection"]) if type(spec["projection"]) is str else None
        if view is None:
            raise C0LawError(path + ": selected current projection required")
        records = view.value.result
        fields = (
            dict(records.element.fields)
            if records.kind == "set" and records.element.kind == "record"
            else {}
        )
        participant = fields.get(spec["participant"]) if type(spec["participant"]) is str else None
        locked = fields.get(spec["locked"]) if type(spec["locked"]) is str else None
        if (
            participant is None
            or participant.kind != "ref"
            or locked is None
            or locked.kind != "bool"
            or any(not table.accepts_sort(participant.sort, actors[seat]) for seat in seats)
            or any(
                not table.accepts_sort(table[view.viewer_type].sort, actors[seat]) for seat in seats
            )
        ):
            raise C0LawError(path + ": seat-compatible Ref and Bool record fields required")
        row(spec["epoch"], {"context", "field"}, path=path + ".epoch")
        context = view.context
        state = context.state
        field = spec["epoch"]["field"]
        kind = dict(state.fields).get(field) if state is not None and type(field) is str else None
        if (
            spec["epoch"]["context"] != context.name
            or kind is None
            or kind.kind != "int"
            or field not in state.public
        ):
            raise C0LawError(path + ": same-context public integer epoch required")
        chosen = spec["actions"]
        if (
            type(chosen) is not list
            or not chosen
            or any(type(a) is not str or a not in actions for a in chosen)
            or len(chosen) != len(set(chosen))
            or used.intersection(chosen)
            or any(
                actions[a].process is not None
                or actions[a].context != context
                or any(
                    not table.accepts_sort(table[actions[a].actor_type].sort, actors[seat])
                    for seat in seats
                )
                for a in chosen
            )
        ):
            raise C0LawError(path + ": disjoint same-context Actor Actions required")
        used.update(chosen)
        selected.append(
            JointDecisionPlan(
                name,
                view.name,
                spec["participant"],
                spec["locked"],
                context.name,
                field,
                tuple(chosen),
            )
        )
    return tuple(selected)
