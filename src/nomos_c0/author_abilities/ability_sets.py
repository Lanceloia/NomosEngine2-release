"""Expand explicitly declared ability instances and their bounded source selectors."""

from collections.abc import Mapping
from dataclasses import replace

from .expression_syntax import ExpressionSource, _identifier
from .parameter_presets import preset_definition

_MAX_EXPANDED_ITEMS = 131072


def _fail(context, path, expected, actual):
    span = None if context is None else context.locate(path)
    ExpressionSource("", path, span).fail("AbilitySet", 0, expected, repr(actual))


def _alias(context, aliases, logical, original):
    if context is not None:
        physical = context.indexed_path(original)
        if physical is not None:
            aliases[logical] = physical


def _context(context, aliases):
    return None if context is None else replace(context, aliases=tuple(aliases.items()))


def expand_ability_sets(lib, source, context=None):
    """Generate ordinary use entries before scopes, preserving physical member origins."""
    if "ability_sets" not in source:
        return source, context
    groups = source["ability_sets"]
    uses = source.get("use")
    if not isinstance(groups, Mapping) or not isinstance(uses, Mapping):
        _fail(context, "ability_sets", "named sets and Source.use mappings", groups)
    if not isinstance(lib.get("abilities"), Mapping):
        _fail(context, "ability_sets", "named Lib.abilities", lib.get("abilities"))
    result = {**source, "use": dict(uses)}
    aliases = {} if context is None else dict(context.aliases)
    count = 0
    for name, group in groups.items():
        path = "ability_sets." + str(name)
        if (
            not _identifier(name)
            or not isinstance(group, Mapping)
            or set(group) - {"context", "members"}
            or "members" not in group
        ):
            _fail(context, path, "{members: nonempty mapping, optional context}", group)
        if "context" in group and (
            not isinstance(source.get("contexts", {}), Mapping)
            or type(group["context"]) is not str
            or group["context"] not in source.get("contexts", {})
        ):
            _fail(
                context, path + ".context", "explicit selected context instance", group["context"]
            )
        members = group["members"]
        if not isinstance(members, Mapping) or not members:
            _fail(context, path + ".members", "nonempty named ordinary ability instances", members)
        for alias, member in members.items():
            origin = path + ".members." + str(alias)
            if (
                not _identifier(alias)
                or not isinstance(member, Mapping)
                or set(member) - {"definition", "preset", "with", "views"}
                or (
                    "preset" not in member
                    and (
                        type(member.get("definition")) is not str
                        or member["definition"] not in lib["abilities"]
                    )
                )
            ):
                _fail(
                    context, origin, "ordinary ability definition with optional with/views", member
                )
            if "preset" in member:
                preset_definition(lib, source, member, context, origin)
            if alias in result["use"]:
                _fail(context, origin, "globally unique use alias", alias)
            count += 1
            if count > _MAX_EXPANDED_ITEMS:
                _fail(context, origin, "bounded ability-set expansion", count)
            selected = dict(member)
            if "context" in group:
                selected["context"] = group["context"]
            result["use"][alias] = selected
            _alias(context, aliases, "use." + alias, origin)
            if "context" in group:
                _alias(context, aliases, "use." + alias + ".context", path + ".context")
    return result, _context(context, aliases)


def expand_ability_set_selectors(lib, source, context=None):
    """Select only declared members; legacy selectors retain their original contracts."""
    groups = source.get("ability_sets", {})
    aliases = {} if context is None else dict(context.aliases)
    if not isinstance(source.get("use"), Mapping):
        return source, context
    if "ability_sets" not in source:
        selectors = []
        for binding in source["use"].values():
            after = binding.get("after") if isinstance(binding, Mapping) else None
            selectors.extend(after if type(after) is list else [after])
        collections = source.get("report_collections", {})
        if isinstance(collections, Mapping):
            for row in collections.values():
                channels = row.get("channels") if isinstance(row, Mapping) else None
                if type(channels) is list:
                    selectors.extend(channels)
        if not any(isinstance(item, Mapping) and "ability_set" in item for item in selectors):
            return source, context
    result = {key: value for key, value in source.items() if key != "ability_sets"}
    result["use"] = dict(source["use"])
    count = 0

    def select(selector, path, *, report=False, shared=None):
        nonlocal count
        keys = {"ability_set", "only", "label"} if report else {"ability_set", "only"}
        name = selector.get("ability_set")
        if (
            set(selector) - keys
            or type(name) is not str
            or name not in groups
            or report
            and not _identifier(selector.get("label"))
        ):
            _fail(context, path, "existing ability_set, optional only, report label", selector)
        group = groups[name]
        if not report and group.get("context") != shared:
            _fail(context, path, "ability set in the reaction context", group.get("context"))
        members = list(group["members"]) if "only" not in selector else selector["only"]
        if (
            type(members) is not list
            or not members
            or any(type(item) is not str or item not in group["members"] for item in members)
            or len(members) != len(set(members))
        ):
            _fail(context, path + ".only", "nonempty unique subset of this set", members)
        count += len(members)
        if count > _MAX_EXPANDED_ITEMS:
            _fail(context, path, "bounded ability-set selector expansion", count)
        return [name + "." + selector["label"] for name in members] if report else members

    for name, binding in source["use"].items():
        after = binding.get("after") if isinstance(binding, Mapping) else None
        entries = after if type(after) is list else [after]
        if not any(isinstance(item, Mapping) and "ability_set" in item for item in entries):
            continue
        path = "use." + name + ".after"
        reactions = lib.get("reactions", {})
        if not isinstance(reactions, Mapping) or binding.get("definition") not in reactions:
            _fail(
                context,
                path,
                "ability-set selector on ordinary reaction",
                binding.get("definition"),
            )
        expanded = []
        for index, item in enumerate(entries):
            origin = path + f"[{index}]" if type(after) is list else path
            chosen = (
                select(item, origin, shared=binding.get("context"))
                if isinstance(item, Mapping) and "ability_set" in item
                else [item]
            )
            for value in chosen:
                _alias(context, aliases, path + f"[{len(expanded)}]", origin)
                expanded.append(value)
        if any(type(item) is not str for item in expanded) or len(expanded) != len(set(expanded)):
            _fail(context, path, "non-overlapping explicit occurrence sources", expanded)
        result["use"][name] = {**binding, "after": expanded}

    collections = source.get("report_collections", {})
    if "report_collections" in source and isinstance(collections, Mapping):
        result["report_collections"] = dict(collections)
        for name, row in collections.items():
            entries = row.get("channels") if isinstance(row, Mapping) else None
            if type(entries) is not list:
                continue
            expanded = []
            for index, item in enumerate(entries):
                origin = f"report_collections.{name}.channels[{index}]"
                chosen = (
                    select(item, origin, report=True)
                    if isinstance(item, Mapping) and "ability_set" in item
                    else [item]
                )
                for value in chosen:
                    _alias(
                        context,
                        aliases,
                        f"report_collections.{name}.channels[{len(expanded)}]",
                        origin,
                    )
                    expanded.append(value)
            result["report_collections"][name] = {**row, "channels": expanded}
    return result, _context(context, aliases)
