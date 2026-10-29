"""Compile personal structured inputs and compact category-bound views."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError
from nomos_cognition.local import Limits

from .expression_syntax import ExpressionLimits, _identifier
from .expressions import compile_value_expression
from .finite_model import producers


@dataclass(frozen=True)
class LocalInput:
    name: str
    channel: object
    producer: object
    guarantee: object
    history: str
    required: bool


@dataclass(frozen=True)
class LocalCategory:
    name: str
    key: object
    matching: object


@dataclass(frozen=True)
class LocalPlan:
    inputs: tuple
    universe: str
    categories: tuple
    period: str
    assumptions: tuple
    limits: Limits
    view_type: str


def compile_local(program, declaration, evidence, base, view_type, *, path, steps):
    from .frontend import row

    row(
        declaration,
        {"inputs", "universe", "categories", "period", "assumptions"},
        {"limits"},
        path=path,
    )
    if any(
        type(declaration[k]) is not dict or not declaration[k]
        for k in ("inputs", "categories", "assumptions")
    ):
        raise C0LawError(
            path + ": local inputs, categories and assumptions need named declarations"
        )
    if not _identifier(declaration["period"]):
        raise C0LawError(path + ": local period needs an explicit identifier")
    assumptions = tuple(declaration["assumptions"].items())
    if any(
        not _identifier(n) or type(v) is not str or not v.strip() or len(v) > 2000
        for n, v in assumptions
    ):
        raise C0LawError(path + ": local assumptions need bounded explanations")
    supplied = declaration.get("limits", {})
    if type(supplied) is not dict or set(supplied) - set(vars(Limits())):
        raise C0LawError(path + ": invalid local limits")
    try:
        limits = Limits(**supplied)
    except (ValueError, TypeError) as error:
        raise C0LawError(path + ": invalid local limits") from error
    table, available, channels = program.table, producers(program), dict(evidence)
    inputs, relation, member_type, label_type = [], None, None, None
    for name, body in declaration["inputs"].items():
        row(body, {"on", "constraint", "history"}, {"required"}, path=path + ".inputs." + str(name))
        if not _identifier(name) or type(body["on"]) is not str or body["on"] not in channels:
            raise C0LawError(path + ": local input needs selected evidence")
        channel = channels[body["on"]]
        producer = available[channel.channel]
        if body["history"] not in ("opening", "all", "latest") or (
            body["history"] == "opening"
        ) != (channel.channel in {p.name for p in program.information}):
            raise C0LawError(path + ": local input has incompatible sampling")
        required = body.get("required", True)
        if type(required) is not bool:
            raise C0LawError(path + ": local input required must be boolean")
        guarantee = next(
            (p for p in producer.constraints if p.definition.name == body["constraint"]), None
        )
        if guarantee is None or guarantee.definition.local is None:
            raise C0LawError(path + ": input requires an issued structured guarantee")
        local = guarantee.definition.local
        types = (local.members.result.element.type_id, local.labels.result.element.type_id)
        if relation is not None and (
            relation != local.relation or types != (member_type, label_type)
        ):
            raise C0LawError(path + ": local inputs have incompatible classification relations")
        relation, (member_type, label_type) = local.relation, types
        inputs.append(LocalInput(name, channel, producer, guarantee, body["history"], required))
    universe = declaration["universe"]
    selected = next((i for i in inputs if i.name == universe), None)
    if selected is None or selected.history != "opening" or not selected.required:
        raise C0LawError(path + ": local universe must select a required opening input")

    def record(kind, fields):
        if kind.kind != "record" or set(dict(kind.fields)) != fields:
            raise C0LawError(path + ": incompatible local view contract")
        return dict(kind.fields)

    view = record(table[view_type], {"status", "complete", "bounds"})
    if (
        view["status"].kind != "enum"
        or set(view["status"].choices) != {"complete", "conflict", "pending"}
        or view["complete"].kind != "bool"
        or view["bounds"].kind != "sequence"
    ):
        raise C0LawError(path + ": invalid local status or bounds view")
    bound = record(view["bounds"].element, {"members", "category", "minimum", "maximum"})
    if (
        bound["members"].kind != "set"
        or bound["members"].element.type_id != member_type
        or bound["category"].kind != "enum"
        or any(
            bound[k].kind != "int"
            or bound[k].minimum not in (0, None)
            or bound[k].maximum is not None
            for k in ("minimum", "maximum")
        )
    ):
        raise C0LawError(path + ": incompatible local bound types")
    categories = []
    for name, body in declaration["categories"].items():
        if not _identifier(name):
            raise C0LawError(path + ": category needs a valid name")
        row(body, {"key", "matching"}, path=path + ".categories." + name)

        def expression(text, returns):
            expr = compile_value_expression(
                text,
                table,
                base,
                returns=returns,
                library=program.queries,
                entities=program.entities,
                context="world",
                path=path + ".categories." + name,
                limits=ExpressionLimits(steps=steps),
            )
            if expr.summary.owner_reads or expr.summary.reference_domains:
                raise C0LawError(path + ": local categories only use supplied values")
            return expr

        key = expression(body["key"], bound["category"].name)
        matching = expression(body["matching"], None)
        if (
            matching.result.kind not in ("set", "sequence")
            or matching.result.element.type_id != label_type
        ):
            raise C0LawError(path + ": category has a foreign label type")
        categories.append(LocalCategory(name, key, matching))
    return LocalPlan(
        tuple(inputs),
        universe,
        tuple(categories),
        declaration["period"],
        assumptions,
        limits,
        view_type,
    )


def semantic_keys(plan):
    if plan is None:
        return None
    return (
        tuple(
            (i.name, i.channel.source, i.channel.slot, i.guarantee.definition.signature)
            for i in plan.inputs
        ),
        tuple((c.key.read_key, c.matching.read_key) for c in plan.categories),
    )
