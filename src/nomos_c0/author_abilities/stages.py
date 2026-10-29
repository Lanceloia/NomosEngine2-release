"""Explicit process stages: captured participants and post-effect completion gates."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class StagePlan:
    actors: tuple[str, ...]


def compile_stage(declaration, bindings, table, entities, initiator, path):
    if declaration is None:
        return None
    from .frontend import row

    row(declaration, {"actors", "complete_when"}, path=path)
    actors = declaration["actors"]
    if (
        type(actors) is not list
        or not actors
        or any(type(name) is not str or name not in bindings for name in actors)
        or len(set(actors)) != len(actors)
        or initiator not in actors
    ):
        raise C0LawError(f"{path}.actors: unique entry captures including initiator required")
    schemas = dict(entities.entities)
    for name in actors:
        kind = table[bindings[name]]
        if kind.kind in ("set", "sequence"):
            kind = kind.element
        if (
            kind.kind != "ref"
            or schemas[kind.sort].kind != "person"
            or schemas[kind.sort].reference != "public"
        ):
            raise C0LawError(f"{path}.actors: public Person captures required")
    return StagePlan(tuple(actors))
