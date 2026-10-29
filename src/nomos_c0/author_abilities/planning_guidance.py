"""Check report-backed preferences before any complete action candidate exists."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier
from .expressions import _INTRINSICS, compile_value_expression
from .frontend import row


@dataclass(frozen=True)
class GuidancePlan:
    views: tuple
    exploration: int
    actions: tuple
    members: tuple


def compile_guidance(program, document, views, actions, base):
    row(document, {"recall", "exploration", "actions"}, path="planning.guidance")
    selected = document["recall"]
    if (
        type(selected) is not list
        or not selected
        or any(type(n) is not str for n in selected)
        or len(set(selected)) != len(selected)
    ):
        raise C0LawError("planning recall needs distinct declared report aliases")
    available = dict(views)
    if any(n not in available or available[n].kind != "reports" for n in selected):
        raise C0LawError("planning recall only accepts actual report ports")
    ports = tuple((n, available[n]) for n in selected)
    if len({(v.channel, v.source) for _, v in ports}) != len(ports):
        raise C0LawError("planning recall cannot count the same physical report port twice")
    exploration = document["exploration"]
    if type(exploration) is not int or exploration < 2:
        raise C0LawError("planning exploration interval needs an integer of at least two")
    bodies = document["actions"]
    if type(bodies) is not dict or not bodies or set(bodies) - {a.name for a in actions}:
        raise C0LawError("planning guidance selects declared model actions")

    def expression(text, bindings, path):
        checked = compile_value_expression(
            text,
            program.table,
            bindings,
            returns="Integer<>",
            library=program.queries,
            entities=program.entities,
            context="actor",
            local_views=ports,
            path="planning.guidance." + path,
        )
        if checked.summary.owner_reads or checked.summary.reference_domains:
            raise C0LawError("planning guidance accepts local values and recalled reports only")
        return checked

    priorities, members = [], []
    reserved = (
        set(base)
        | set(available)
        | set(dict(program.table.definitions))
        | _INTRINSICS
        | set(dict(program.queries.definitions))
        | set(dict(program.entities.entities))
        | set(dict(program.entities.relations))
    )
    for action in actions:
        if action.name not in bodies:
            continue
        body = bodies[action.name]
        row(body, set(), {"priority", "inputs"}, path="planning.guidance." + action.name)
        if "priority" in body:
            priorities.append((action.name, expression(body["priority"], base, action.name)))
        inputs = body.get("inputs", {})
        if type(inputs) is not dict or set(inputs) - {i.name for i in action.inputs.inputs}:
            raise C0LawError("planning guidance selects actual input ports")
        bindings = dict(base)
        for item in action.inputs.inputs:
            if item.name in inputs:
                if item.name in dict(action.constructions):
                    raise C0LawError(
                        "construction preferences belong to atomic domains, not whole typed values"
                    )
                entry = inputs[item.name]
                row(entry, {"member", "priority"}, path="planning.guidance.inputs")
                name = entry["member"]
                if not _identifier(name) or name in reserved | set(bindings) | {"state", item.name}:
                    raise C0LawError("planning guidance member conflicts with a model binding")
                kind = program.table[item.type_name]
                element = kind.element.name if item.kind == "subset" else item.type_name
                members.append(
                    (
                        action.name,
                        item.name,
                        name,
                        expression(
                            entry["priority"],
                            {**bindings, name: element},
                            action.name + "." + item.name,
                        ),
                    )
                )
            bindings[item.name] = item.type_name
    if not priorities and not members:
        raise C0LawError("planning guidance needs a generation preference")
    return GuidancePlan(ports, exploration, tuple(priorities), tuple(members))
