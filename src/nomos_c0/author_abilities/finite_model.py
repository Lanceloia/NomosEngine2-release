"""Compile independent finite models over acquired guarantee parameters."""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError
from nomos_cognition.finite import Limits

from .expression_syntax import ExpressionLimits, _identifier
from .expressions import compile_value_expression


@dataclass(frozen=True)
class FiniteInput:
    name: str
    channel: object
    producer: object
    kind: str
    guarantee: object
    history: str
    required: bool
    expose: tuple
    bindings: tuple
    interpretation: object | None


@dataclass(frozen=True)
class FiniteVariable:
    name: str
    type_name: str
    choose: object
    each: object | None = None
    item: str | None = None
    choice: str | None = None
    value: object | None = None
    allocation: str = "independent"


@dataclass(frozen=True)
class FiniteQuery:
    name: str
    key: object
    holds: object
    each: object | None
    item: str | None


@dataclass(frozen=True)
class FinitePlan:
    inputs: tuple
    variables: tuple
    queries: tuple
    model_value: object
    assumptions: tuple
    limits: Limits
    view_type: str


def semantic_keys(plan):
    if plan is None:
        return None

    def key(expr):
        return None if expr is None else expr.read_key

    return (
        tuple(
            (v.name, v.type_name, key(v.choose), key(v.each), key(v.value), v.allocation)
            for v in plan.variables
        ),
        tuple(
            (
                i.name,
                i.channel.source,
                i.channel.slot,
                i.kind,
                i.guarantee.predicate.read_key
                if i.kind == "fact"
                else i.guarantee.definition.signature,
                i.history,
                i.required,
                i.expose,
                tuple((n, key(e)) for n, e in i.bindings),
                key(i.interpretation),
            )
            for i in plan.inputs
        ),
        tuple((q.name, key(q.key), key(q.holds), key(q.each)) for q in plan.queries),
        plan.model_value.read_key,
    )


def producers(program):
    result = {p.name: p for p in program.information}
    sources = (
        *program.abilities,
        *program.reactions,
        *(p.event for p in program.periodic),
        *(p.completion for p in program.activities),
        *(p.cancellation for p in program.activities if p.cancellation is not None),
    )
    for plan in sources:
        for leaf in plan.resolution.leaves():
            for call in leaf.deliveries:
                result[getattr(plan, "channel_name", plan.name) + "." + call.label] = (
                    call.definition
                )
    return result


def compile_finite(program, declaration, evidence, base, query_type, view_type, *, path, steps):
    from .frontend import row

    row(
        declaration,
        {"inputs", "variables", "queries", "model", "assumptions"},
        {"limits"},
        path=path,
    )
    for field in ("inputs", "variables", "queries", "assumptions"):
        if not isinstance(declaration[field], Mapping):
            raise C0LawError(path + ": finite declarations require named mappings")
    if not declaration["inputs"] or not declaration["variables"]:
        raise C0LawError(path + ": finite model needs acquired inputs and variables")
    assumptions = tuple(declaration["assumptions"].items())
    if any(
        not _identifier(n) or type(t) is not str or not t.strip() or len(t) > 2000
        for n, t in assumptions
    ):
        raise C0LawError(path + ": assumptions require named bounded explanations")
    supplied = declaration.get("limits", {})
    if not isinstance(supplied, Mapping) or set(supplied) - set(vars(Limits())):
        raise C0LawError(path + ": invalid finite limits")
    try:
        limits = Limits(**supplied)
    except (ValueError, TypeError) as error:
        raise C0LawError(path + ": invalid finite limits") from error
    table, available = program.table, producers(program)
    evidence = dict(evidence)
    inputs, exposed = [], {}
    for name, body in declaration["inputs"].items():
        row(
            body,
            {"on", "history"},
            {"fact", "constraint", "expose", "bind", "interpret", "required"},
            path=path + ".inputs." + str(name),
        )
        if not _identifier(name) or type(body["on"]) is not str or body["on"] not in evidence:
            raise C0LawError(path + ": finite input needs selected evidence")
        kinds = set(body) & {"fact", "constraint"}
        if len(kinds) != 1 or body["history"] not in ("opening", "latest", "all"):
            raise C0LawError(path + ": input needs one guarantee and explicit sampling policy")
        if type(body.get("required", True)) is not bool:
            raise C0LawError(path + ": input required must be boolean")
        channel = evidence[body["on"]]
        producer = available[channel.channel]
        opening = channel.channel in {p.name for p in program.information}
        if (body["history"] == "opening") != opening:
            raise C0LawError(path + ": opening and occurrence sampling must not be mixed")
        kind = next(iter(kinds))
        plans = producer.assurances if kind == "fact" else producer.constraints
        guarantee = next(
            (p for p in plans if (p.fact if kind == "fact" else p.definition.name) == body[kind]),
            None,
        )
        if guarantee is None:
            raise C0LawError(path + ": selected producer does not issue this guarantee")
        if kind == "fact":
            parameters = {n: expr.result.name for n, expr in guarantee.arguments}
            if "interpret" not in body or "bind" in body or not assumptions:
                raise C0LawError(path + ": fact interpretation needs explicit analysis assumptions")
        else:
            parameters = dict(guarantee.definition.parameters)
            if "bind" not in body or "interpret" in body:
                raise C0LawError(path + ": constraint needs exact hypothetical variable binding")
        exports = body.get("expose", {})
        if not isinstance(exports, Mapping):
            raise C0LawError(path + ": expose selects guarantee parameters")
        export_plans = []
        for parameter, selection in exports.items():
            row(selection, {"as", "type"}, path=path + ".expose")
            alias, collection = selection["as"], selection["type"]
            if (
                parameter not in parameters
                or not _identifier(alias)
                or alias in exposed
                or alias in base
            ):
                raise C0LawError(path + ": duplicate/unknown guarantee parameter exposure")
            if (
                type(collection) is not str
                or collection not in dict(table.definitions)
                or table[collection].kind != "sequence"
                or (table[collection].element.type_id != table[parameters[parameter]].type_id)
            ):
                raise C0LawError(path + ": guarantee exposure needs an exact nominal Sequence")
            exposed[alias] = collection
            export_plans.append((parameter, alias, collection))
        inputs.append(
            (name, body, channel, producer, kind, guarantee, parameters, tuple(export_plans))
        )
    environment = {**base, **exposed}
    variable_types = {}
    for name, body in declaration["variables"].items():
        if not _identifier(name) or name in environment or not isinstance(body, Mapping):
            raise C0LawError(path + ": finite variables need distinct declared names")
        kind = body.get("type")
        if type(kind) is not str or kind not in dict(table.definitions):
            raise C0LawError(path + ": finite variable needs a nominal type")
        variable_types[name] = kind

    def expression(text, env, returns, location):
        value = compile_value_expression(
            text,
            table,
            env,
            returns=returns,
            library=program.queries,
            entities=program.entities,
            context="world",
            path=location,
            limits=ExpressionLimits(steps=steps),
        )
        if value.summary.owner_reads or value.summary.reference_domains:
            raise C0LawError(location + ": finite analysis cannot read world owners or catalogs")
        needed = {r.root for r in value.summary.reads}
        return replace(value, inputs=tuple(v for v in value.inputs if v[0] in needed))

    def collection(text, env, location):
        value = expression(text, env, None, location)
        if value.result.kind not in ("set", "sequence"):
            raise C0LawError(location + ": finite domain requires a typed collection")
        return value

    variables = []
    for name, body in declaration["variables"].items():
        location = path + ".variables." + name
        if "each" not in body:
            row(body, {"type", "choose"}, path=location)
            choose = collection(body["choose"], environment, location + ".choose")
            if choose.result.element.type_id != table[body["type"]].type_id:
                raise C0LawError(location + ": domain element differs from variable type")
            variables.append(FiniteVariable(name, body["type"], choose))
        else:
            row(body, {"type", "each", "choices", "value"}, {"allocation"}, path=location)
            each, choices = body["each"], body["choices"]
            if (
                not isinstance(each, Mapping)
                or len(each) != 1
                or not isinstance(choices, Mapping)
                or len(choices) != 1
            ):
                raise C0LawError(
                    location + ": grouped variable needs one each and one choice binder"
                )
            item, text = next(iter(each.items()))
            choice, choose_text = next(iter(choices.items()))
            if (
                any(
                    not _identifier(n) or n in environment or n in variable_types
                    for n in (item, choice)
                )
                or item == choice
            ):
                raise C0LawError(location + ": grouped binders alias model inputs")
            each_plan = collection(text, environment, location + ".each")
            local = {**environment, item: each_plan.result.element.name}
            choose = collection(choose_text, local, location + ".choices")
            allocation = body.get("allocation", "independent")
            if allocation not in ("independent", "without_replacement") or (
                allocation == "without_replacement" and item in {n for n, _ in choose.inputs}
            ):
                raise C0LawError(location + ": allocation requires a shared finite choice pool")
            output = table[body["type"]]
            if output.kind not in ("set", "sequence"):
                raise C0LawError(location + ": grouped variable requires a nominal collection")
            value = expression(
                body["value"],
                {**local, choice: choose.result.element.name},
                output.element.name,
                location + ".value",
            )
            variables.append(
                FiniteVariable(
                    name, output.name, choose, each_plan, item, choice, value, allocation
                )
            )
    formula_env = {**environment, **variable_types}
    compiled_inputs = []
    for name, body, channel, producer, kind, guarantee, parameters, exports in inputs:
        if set(parameters) & set(formula_env):
            raise C0LawError(path + ": guarantee parameter aliases finite variable or public input")
        local = {**formula_env, **parameters}
        bindings, interpretation = (), None
        if kind == "constraint":
            declared = {n: t for n, t, _ in guarantee.definition.variables}
            if not isinstance(body["bind"], Mapping) or set(body["bind"]) != set(declared):
                raise C0LawError(path + ": constraint needs exact hypothetical variable binding")
            bindings = tuple(
                (n, expression(body["bind"][n], local, t, path + ".bind." + n))
                for n, t in declared.items()
            )
        else:
            interpretation = expression(
                body["interpret"], local, "Bool", path + ".interpret." + name
            )
        compiled_inputs.append(
            FiniteInput(
                name,
                channel,
                producer,
                kind,
                guarantee,
                body["history"],
                body.get("required", True),
                exports,
                bindings,
                interpretation,
            )
        )
    queries = []
    for name, body in declaration["queries"].items():
        row(body, {"key", "holds"}, {"each"}, path=path + ".queries." + str(name))
        if not _identifier(name):
            raise C0LawError(path + ": queries need named declarations")
        local, each_plan, item = dict(environment), None, None
        if "each" in body:
            if not isinstance(body["each"], Mapping) or len(body["each"]) != 1:
                raise C0LawError(path + ": query each needs one binder")
            item, text = next(iter(body["each"].items()))
            if not _identifier(item) or item in formula_env:
                raise C0LawError(path + ": query binder aliases model environment")
            each_plan = collection(text, environment, path + ".queries." + name + ".each")
            local[item] = each_plan.result.element.name
        key = expression(body["key"], local, query_type, path + ".queries." + name + ".key")
        holds = expression(
            body["holds"], {**local, **variable_types}, "Bool", path + ".queries." + name + ".holds"
        )
        queries.append(FiniteQuery(name, key, holds, each_plan, item))
    view = table[view_type]
    if view.kind != "record" or set(dict(view.fields)) != {
        "status",
        "complete",
        "models",
        "answers",
    }:
        raise C0LawError(path + ": analysis view needs status/complete/models/answers")
    fields = dict(view.fields)
    if (
        fields["status"].kind != "enum"
        or set(fields["status"].choices) != {"consistent", "inconsistent", "pending"}
        or fields["complete"].kind != "bool"
        or fields["models"].kind != "sequence"
        or fields["answers"].kind != "sequence"
        or fields["answers"].element.kind != "record"
    ):
        raise C0LawError(path + ": invalid finite view field types")
    answers = dict(fields["answers"].element.fields)
    if set(answers) != {"key", "entailed", "possible", "refuted"} or (
        answers["key"].type_id != table[query_type].type_id
        or any(answers[n].kind != "bool" for n in ("entailed", "possible", "refuted"))
    ):
        raise C0LawError(path + ": finite answers require typed key and three boolean conclusions")
    model_value = expression(
        declaration["model"], formula_env, fields["models"].element.name, path + ".model"
    )
    return FinitePlan(
        tuple(compiled_inputs),
        tuple(variables),
        tuple(queries),
        model_value,
        assumptions,
        limits,
        view_type,
    )
