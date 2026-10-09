"""Expand explicit finite participant signatures into the existing Action ABI."""

from copy import deepcopy

from .author_contract_v1 import C0LawError
from .declarative_nominal_v0 import _name, _row


def _names(raw, label):
    if type(raw) is not list or not 1 <= len(raw) <= 64:
        raise C0LawError(f"{label} needs 1..64 explicit names")
    names = tuple(_name(value, label) for value in raw)
    if len(set(names)) != len(names):
        raise C0LawError(f"{label} contains duplicate names")
    return names


def expand_participant_groups(source):
    """No lookup, Actor discovery or runtime permissions originate here."""
    definitions = source.get("participant_groups", [])
    if type(definitions) is not list or len(definitions) > 64:
        raise C0LawError("participant_groups must be a finite declaration list")
    groups = {}
    for raw in definitions:
        row = _row(
            raw, {"name", "members", "selector", "state", "read", "effects"}, "participant group"
        )
        name = _name(row["name"], "participant group name")
        if name in groups:
            raise C0LawError(f"duplicate participant group: {name}")
        members = _names(row["members"], f"participant group {name} members")
        if members != tuple(sorted(members)):
            raise C0LawError(f"participant group {name} members must be canonical")
        if set(members) & {"scene", "actor", "payload", "target", "occurrence"}:
            raise C0LawError(f"participant group {name} uses a reserved root")
        if row["selector"] not in ("closed_domain", "individual", "actor"):
            raise C0LawError(f"participant group {name} selector is unknown")
        _name(row["state"], f"participant group {name} state")
        paths = row["read"]
        if (
            type(paths) is not list
            or len(paths) > 64
            or any(
                type(path) is not str
                or not path
                or any(not part.isidentifier() or part.startswith("_") for part in path.split("."))
                for path in paths
            )
            or len(set(paths)) != len(paths)
        ):
            raise C0LawError(f"participant group {name} read paths are malformed")
        effects = row["effects"]
        if type(effects) is not dict or len(effects) > 64:
            raise C0LawError(f"participant group {name} effects must be a field/output mapping")
        for field, output in effects.items():
            _name(field, f"participant group {name} effect field")
            _name(output, f"participant group {name} effect output")
        groups[name] = row

    result = deepcopy(source)
    result.pop("participant_groups", None)
    actions = result.get("actions")
    if type(actions) is not list:
        raise C0LawError("Actions must be a declaration list")
    for action in actions:
        if type(action) is not dict:
            raise C0LawError("Action must be a declaration mapping")
        uses = action.pop("participant_groups", [])
        if type(uses) is not list or len(uses) > 64 or any(type(name) is not str for name in uses):
            raise C0LawError("Action participant_groups must list declaration names")
        if len(set(uses)) != len(uses):
            raise C0LawError("Action repeats a participant group")
        if not uses:
            continue
        if "target" in action:
            raise C0LawError("Action cannot mix target and participant groups")
        participants = action.setdefault("participants", [])
        if type(participants) is not list or any(type(row) is not dict for row in participants):
            raise C0LawError("Action participants must be a declaration list")
        names = [row.get("name") for row in participants]
        if any(type(name) is not str for name in names) or names != sorted(set(names)):
            raise C0LawError("Action explicit participants need unique canonical names")
        effects = action.get("effects")
        value = action.get("value")
        if (
            type(effects) is not dict
            or type(value) is not dict
            or type(value.get("read")) is not list
            or type(value.get("write_paths")) is not list
        ):
            raise C0LawError("grouped Action needs explicit effects and value read ports")
        for name in uses:
            if name not in groups:
                raise C0LawError(f"unknown participant group: {name}")
            group = groups[name]
            for member in group["members"]:
                if member in names or member in effects:
                    raise C0LawError(f"participant group {name} collides at {member}")
                names.append(member)
                participants.append(
                    {
                        "name": member,
                        "selector": group["selector"],
                        "state": group["state"],
                        "payload_field": member,
                        "write": bool(group["effects"]),
                    }
                )
                effects[member] = deepcopy(group["effects"])
                value["read"].extend(f"{member}.{path}" for path in group["read"])
                value["write_paths"].extend(f"{member}.{field}" for field in group["effects"])
        participants.sort(key=lambda row: row["name"])
    return result
