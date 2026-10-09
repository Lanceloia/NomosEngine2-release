"""Reuse closed authored participant selections without granting port permissions."""

from copy import deepcopy

from .author_contract_v1 import C0LawError
from .author_document_v1 import C0OriginFrame


def expand_participant_bindings(source, owner_types, source_context=None):
    declarations = source.get("participant_bindings", [])
    if type(declarations) is not list or len(declarations) > 64:
        raise C0LawError("participant bindings need at most 64 declarations")
    groups = {}
    paths = {}
    selected_kinds = {
        item["kind"] for item in source.get("object_kinds", []) if type(item) is dict
    }

    def check_members(members):
        if type(members) is not dict or not 1 <= len(members) <= 64:
            raise C0LawError("participant binding needs a nonempty finite mapping")
        for alias, selection in members.items():
            if type(alias) is not str or not alias.isidentifier() or type(selection) is not dict:
                raise C0LawError("participant binding alias or selection is malformed")
            if set(selection) == {"kind"}:
                kind = selection["kind"]
                if type(kind) is not str or kind not in selected_kinds:
                    raise C0LawError("participant binding selects an unselected Object kind")
            elif set(selection) == {"actors"}:
                actors = selection["actors"]
                if (
                    type(actors) is not list
                    or not 1 <= len(actors) <= 64
                    or any(
                        type(actor) is not str
                        or actor not in owner_types
                        or owner_types[actor][1] is None
                        for actor in actors
                    )
                    or len(set(actors)) != len(actors)
                ):
                    raise C0LawError("participant binding selects foreign or repeated Actors")
            else:
                raise C0LawError("participant binding requires actors or kind")

    for index, row in enumerate(declarations):
        if type(row) is not dict or set(row) != {"name", "participants"}:
            raise C0LawError("participant binding declaration is malformed")
        name = row["name"]
        if type(name) is not str or not name.isidentifier() or name in groups:
            raise C0LawError("participant binding name is malformed or repeated")
        check_members(row["participants"])
        groups[name] = row["participants"]
        paths[name] = ("participant_bindings", index)

    actions = source.get("actions")
    if type(actions) is not list:
        raise C0LawError("participant bindings need Action declarations")
    expanded = []
    frames = {}
    for index, raw in enumerate(actions):
        if type(raw) is not dict or "use_participants" not in raw:
            expanded.append(raw)
            continue
        uses = raw["use_participants"]
        if (
            type(uses) is not list
            or not 1 <= len(uses) <= 64
            or any(type(name) is not str or name not in groups for name in uses)
            or len(set(uses)) != len(uses)
        ):
            raise C0LawError("Action uses foreign or repeated participant bindings")
        if "target" in raw:
            raise C0LawError("Action cannot mix target and participant bindings")
        members = {}
        origin_frames = []
        for name in uses:
            overlap = set(members) & set(groups[name])
            if overlap:
                raise C0LawError("Action participant bindings repeat an alias")
            members.update(deepcopy(groups[name]))
            path = paths[name]
            origin_frames.append(
                C0OriginFrame(
                    "participant_binding",
                    name,
                    repr(path),
                    source_context.index.spans.get(path) if source_context else None,
                )
            )
        if "participants" in raw:
            extra = raw["participants"]
            check_members(extra)
            if set(members) & set(extra):
                raise C0LawError("Action inline participants repeat a binding alias")
            members.update(deepcopy(extra))
        if len(members) > 64:
            raise C0LawError("expanded participant binding exceeds 64 aliases")
        action = {key: value for key, value in raw.items() if key != "use_participants"}
        action["participants"] = members
        expanded.append(action)
        frames[index] = tuple(origin_frames)
    result = {key: value for key, value in source.items() if key != "participant_bindings"}
    result["actions"] = expanded
    return result, frames
