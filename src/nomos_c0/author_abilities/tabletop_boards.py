"""Typed resource-board declarations over existing authorized reads."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class BoardGroup:
    name: str
    title: str
    key: str
    label: str
    quantity: str
    key_type: str
    labels: tuple


@dataclass(frozen=True)
class ResourceBoard:
    name: str
    title: str
    read: object
    owner: str
    reserve: str
    groups: tuple
    pools: tuple
    unit: str
    icon: str
    motion: str


def compile_boards(program, declaration, read_panel, text, icons):
    if type(declaration) is not dict:
        raise C0LawError("boards require named resource-board declarations")
    result = []

    def read(source, title):
        return read_panel(program, {"title": title, "zone": "board", "source": source})

    def quantity(value):
        return value.kind == "int" and value.minimum is not None and value.minimum >= 0

    for name, body in declaration.items():
        if (
            type(name) is not str
            or not name.isidentifier()
            or type(body) is not dict
            or set(body)
            - {"title", "source", "owner", "reserve", "groups", "pools", "unit", "icon", "motion"}
            or not {"title", "source", "owner", "reserve", "groups", "pools", "unit", "icon"}
            <= set(body)
            or any(type(body[k]) is not str for k in ("owner", "reserve"))
        ):
            raise C0LawError(
                "resource board requires title/source/owner/reserve/groups/pools/unit/icon"
            )
        source = read(body["source"], text(body["title"]))
        value = None if source.type_name is None else program.table[source.type_name]
        if value is None or value.kind not in ("sequence", "set") or value.element.kind != "record":
            raise C0LawError("resource board source requires visible records")
        fields = dict(value.element.fields)
        owner, reserve = fields.get(body["owner"]), fields.get(body["reserve"])
        schemas = dict(program.entities.entities)
        if (
            owner is None
            or owner.kind != "ref"
            or any(
                not program.table.accepts_sort(owner.sort, schemas[dict(program.actors)[s]].name)
                for s in program.play.seats
            )
            or reserve is None
            or not quantity(reserve)
        ):
            raise C0LawError("resource board needs a seat reference and nonnegative reserve")
        if (
            type(body["groups"]) is not dict
            or not body["groups"]
            or type(body["pools"]) is not dict
        ):
            raise C0LawError("resource board requires named groups and pools")
        groups = []
        for field, spec in body["groups"].items():
            collection = fields.get(field)
            if (
                type(spec) is not dict
                or set(spec) - {"title", "key", "label", "quantity", "labels"}
                or not {"title", "key", "label", "quantity"} <= set(spec)
                or any(type(spec[k]) is not str for k in ("key", "label", "quantity"))
                or collection is None
                or collection.kind not in ("sequence", "set")
                or collection.element.kind != "record"
            ):
                raise C0LawError("board group requires an actual collection of records")
            members = dict(collection.element.fields)
            key, label, amount = (members.get(spec[k]) for k in ("key", "label", "quantity"))
            if (
                key is None
                or key.kind not in ("int", "text", "enum")
                or label is None
                or label.kind not in ("text", "enum", "optional")
                or label.kind == "optional"
                and label.element.kind not in ("text", "enum")
                or amount is None
                or not quantity(amount)
            ):
                raise C0LawError(
                    "board sites require scalar keys, labels and nonnegative quantities"
                )
            captions = spec.get("labels", {})
            if type(captions) is not dict or any(type(k) is not str for k in captions):
                raise C0LawError("board site labels require string keys")
            groups.append(
                BoardGroup(
                    field,
                    text(spec["title"]),
                    spec["key"],
                    spec["label"],
                    spec["quantity"],
                    key.name,
                    tuple((k, text(v)) for k, v in captions.items()),
                )
            )
        pools = []
        for pool, spec in body["pools"].items():
            if (
                type(pool) is not str
                or not pool.isidentifier()
                or type(spec) is not dict
                or set(spec) != {"title", "source"}
            ):
                raise C0LawError("board pool requires a name, title and authorized source")
            pool_read = read(spec["source"], text(spec["title"]))
            if pool_read.type_name is None or not quantity(program.table[pool_read.type_name]):
                raise C0LawError("board pool requires a visible nonnegative quantity")
            pools.append((pool, pool_read))
        if type(body["icon"]) is not str or body["icon"] not in icons:
            raise C0LawError("board unit requires a supported icon")
        motion = body.get("motion", "changes")
        if type(motion) is not str or motion not in ("changes", "conserved"):
            raise C0LawError("board motion requires changes or conserved quantity redistribution")
        result.append(
            ResourceBoard(
                name,
                text(body["title"]),
                source,
                body["owner"],
                body["reserve"],
                tuple(groups),
                tuple(pools),
                text(body["unit"]),
                body["icon"],
                motion,
            )
        )
    return tuple(result)
