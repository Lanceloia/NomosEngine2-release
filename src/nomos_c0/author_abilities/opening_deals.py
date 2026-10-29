"""Typed opening deals from fixed context sequences into individual fields."""

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier


@dataclass(frozen=True)
class OpeningDealPlan:
    name: str
    context: str
    deal: str
    to: str
    sort: str
    field: str
    stream: str


def compile_opening(declarations, contexts, table, entities, random):
    from .frontend import row

    if not isinstance(declarations, Mapping):
        raise C0LawError("Source.opening requires named deals")
    if declarations and random is None:
        raise C0LawError("Source.opening requires a selected random mechanism")
    selected = {plan.name: plan for plan in contexts}
    result = []
    for name, declaration in declarations.items():
        path = "Source.opening." + str(name)
        if not _identifier(name):
            raise C0LawError("Source.opening needs valid deal names")
        row(declaration, {"context", "deal", "to", "field"}, {"stream"}, path=path)
        if any(not _identifier(declaration[key]) for key in ("context", "deal", "to", "field")):
            raise C0LawError(path + ": context, deal, to and field require names")
        context = selected.get(declaration["context"])
        if context is None:
            raise C0LawError(path + ": unknown context")
        parameters = {p.name: table[p.type_name] for p in context.parameters}
        cards, targets = (parameters.get(declaration[key]) for key in ("deal", "to"))
        if (
            cards is None
            or targets is None
            or cards.kind != "sequence"
            or targets.kind != "sequence"
            or targets.element.kind != "ref"
        ):
            raise C0LawError(path + ": deal/to require fixed Sequence parameters and entity refs")
        field = entities.field(targets.element.sort, declaration["field"])
        if field.name != cards.element.name:
            raise C0LawError(path + ": dealt values must match the nominal field type")
        for sort, schema in entities.entities:
            if table.accepts_sort(targets.element.sort, sort) and any(
                p.name == declaration["field"] for p in schema.initial
            ):
                raise C0LawError(path + ": opening deal conflicts with entity initial field")
        stream = declaration.get("stream", "main")
        if type(stream) is not str or stream not in random.streams:
            raise C0LawError(path + ": unknown random stream")
        result.append(
            OpeningDealPlan(
                name,
                context.name,
                declaration["deal"],
                declaration["to"],
                targets.element.sort,
                declaration["field"],
                stream,
            )
        )
    return tuple(result)
