"""Typed imports of current projections and the controller's acquired content."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier, parse_expression
from .expressions import _INTRINSICS


@dataclass(frozen=True)
class LocalViewPlan:
    kind: str
    type_name: str
    channel: str
    source: str = ""
    slot: str = ""
    process_point: str = ""


def channel_signatures(lib, source):
    channels = {}
    for name, use in source["use"].items():
        definition = use.get("definition")
        for category, kind in (("information", "reports"), ("projections", "projected")):
            if definition in lib.get(category, {}):
                channels[kind, name] = (
                    lib[category][definition]["returns"],
                    f"author.{source['name']}.opening-information",
                    name,
                )
        executable = []
        if definition in lib.get("periodic", {}):
            executable.append(
                (
                    name,
                    lib["periodic"][definition]["resolve"],
                    f"author.{source['name']}.{name}.event",
                )
            )
        if definition in lib["abilities"]:
            executable.append(
                (
                    name,
                    lib["abilities"][definition]["resolve"],
                    f"author.{source['name']}.{name}.action",
                )
            )
        if definition in lib.get("reactions", {}):
            executable.append(
                (
                    name,
                    lib["reactions"][definition]["resolve"],
                    f"author.{source['name']}.{name}.event",
                )
            )
        if definition in lib.get("activities", {}):
            activity = lib["activities"][definition]
            executable.append((name, activity["resolve"], f"author.{source['name']}.{name}.event"))
            if "cancel" in activity:
                executable.append(
                    (
                        name + ".cancel",
                        activity["cancel"]["resolve"],
                        f"author.{source['name']}.{name}.cancel.action",
                    )
                )
        if definition in lib.get("processes", {}):
            process = lib["processes"][definition]
            for point, node in {"begin": process["begin"], **process["decisions"]}.items():
                executable.append(
                    (
                        f"{name}.{point}",
                        node["resolve"],
                        f"author.{source['name']}.{name}.{point}.action",
                    )
                )
        for channel_root, resolution, source_key in executable:
            pending = [resolution]
            while pending:
                row = pending.pop()
                if "result" in row:
                    for label, text in row.get("deliver", {}).items():
                        if type(text) is dict:
                            from .frontend import row as check_row

                            check_row(text, {"for", "in", "value"}, path="deliver." + label)
                            text = text["value"]
                        call = parse_expression(text)
                        if call.operation != "call" or call.children[0].operation != "name":
                            raise C0LawError("delivery needs a named information function call")
                        body = lib.get("disclosures", {}).get(call.children[0].value)
                        if body is None:
                            raise C0LawError("unknown disclosure definition")
                        channel = f"{channel_root}.{label}"
                        value = (
                            body["returns"],
                            source_key,
                            label,
                        )
                        key = ("reports", channel)
                        if key in channels and channels[key] != value:
                            raise C0LawError("delivery label has incompatible branch types")
                        channels[key] = value
                else:
                    pending.extend(
                        row[key] for key in ("then", "else", "success", "failure") if key in row
                    )
    return channels


def compile_local_views(declarations, supplied, table, pure, entities, bindings, channels):
    if (
        not isinstance(declarations, dict)
        or not isinstance(supplied, dict)
        or set(declarations) != set(supplied)
    ):
        raise C0LawError("views require exact named bindings")
    reserved = (
        set(bindings)
        | set(dict(table.definitions))
        | set(dict(pure.definitions))
        | set(dict(entities.relations))
        | _INTRINSICS
    )
    result = []
    for alias, row in declarations.items():
        if (
            not _identifier(alias)
            or alias in reserved
            or not isinstance(row, dict)
            or len(row) != 1
        ):
            raise C0LawError("view alias conflicts with an expression symbol")
        label, name = next(iter(row.items()))
        kind = {"reports": "reports", "projection": "projected", "cognition": "cognition"}.get(
            label
        )
        channel = supplied[alias]
        if (
            kind is None
            or name not in dict(table.definitions)
            or type(channel) is not str
            or (kind, channel) not in channels
        ):
            raise C0LawError("unknown local view type/channel")
        actual_type, source, slot = channels[kind, channel]
        expected = table[name]
        if kind == "reports":
            if expected.kind != "sequence":
                raise C0LawError("report history needs a named Sequence type")
            expected = expected.element
        if expected.type_id != table[actual_type].type_id:
            raise C0LawError("local view kind/type differs from its selected channel")
        result.append((alias, LocalViewPlan(kind, name, channel, source, slot)))
    return tuple(result)
