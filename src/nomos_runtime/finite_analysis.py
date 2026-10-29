"""Finite search preparation over generated domain, predicate and result functions."""

from collections import Counter
from dataclasses import dataclass, replace

from .analysis import Preparation, PreparationBudget, budget_error, collect, expose, ordered, select
from .cognition import holder
from .expressions import ExpressionError, ValueBindingError


@dataclass(frozen=True)
class FiniteVariable:
    name: str
    type_name: str
    signature: str
    element: str
    choose: object
    each: object
    item: str | None
    choice: str | None
    build: object
    collection: object
    allocation: str


@dataclass(frozen=True)
class FiniteQuery:
    each: object
    item: str | None
    key: object
    key_type: str
    holds: object
    dependencies: tuple


@dataclass(frozen=True)
class FiniteDefinition:
    inputs: tuple
    variables: tuple
    queries: tuple
    model: object
    model_type: str
    assumptions: tuple
    limits: object


def analyze(definition, model, session, codec, actor, receipts):
    from nomos_cognition.analysis import Analysis, Conclusion
    from nomos_cognition.finite import Predicate, Variable, solve

    selection = select(definition.inputs, actor, receipts)
    grounds, cutoff = (), selection.cutoff
    meter = Preparation(definition.limits.work)

    def outcome(status, models=(), answers=(), work=None, reason=None):
        return Analysis(
            model,
            (actor.scope, holder(actor)),
            cutoff,
            grounds,
            definition.assumptions,
            status,
            models,
            answers,
            meter.work if work is None else work,
            reason,
        )

    try:
        selected = collect(selection, actor, codec, meter)
        grounds = tuple(v.ground for v in selected)
        if selection.missing:
            return outcome("pending", reason="missing_inputs")
        # Preserve verified grounds if an exposed aggregate exceeds its value budget.
        environment = expose(selection, selected, codec)
        variables, raw_names, groups, predicates = [], {}, {}, []

        def domain(variable, values):
            choices = ordered(variable.choose(session, codec, actor, values))
            meter.spend(len(choices) + 1)
            result = tuple(dict.fromkeys(codec.term(variable.element, value) for value in choices))
            if len(result) > definition.limits.domain:
                raise PreparationBudget
            return result

        for variable in definition.variables:
            if variable.each is None:
                raw_names[variable.name] = (variable.name,)
                variables.append(
                    Variable(
                        variable.name,
                        variable.type_name,
                        variable.signature,
                        domain(variable, environment),
                    )
                )
            else:
                members = ordered(variable.each(session, codec, actor, environment))
                if len(members) > definition.limits.variables - len(variables):
                    raise PreparationBudget
                meter.spend(len(members) + 1)
                raw_names[variable.name] = tuple(
                    variable.name + ":" + str(i) for i in range(len(members))
                )
                groups[variable.name] = tuple(zip(raw_names[variable.name], members, strict=True))
                if variable.allocation == "without_replacement":
                    supply = Counter(
                        codec.term(variable.element, value)
                        for value in variable.choose(session, codec, actor, environment)
                    )
                    for depth in range(1, len(members) + 1):
                        meter.spend(depth + 1)
                        names = raw_names[variable.name][:depth]
                        predicates.append(
                            Predicate(
                                "allocate:" + variable.name + ":" + str(depth),
                                names,
                                lambda raw, supply=supply: all(
                                    n <= supply[v] for v, n in Counter(raw.values()).items()
                                ),
                            )
                        )
                for name, member in groups[variable.name]:
                    choices = domain(variable, {**environment, variable.item: member})
                    signature = codec.codecs[variable.element][0]
                    variables.append(Variable(name, variable.element, signature, choices))
            if len(variables) > definition.limits.variables:
                raise PreparationBudget

        def materialize(raw):
            values = dict(environment)
            for variable in definition.variables:
                if not set(raw_names[variable.name]) <= raw.keys():
                    continue
                if variable.each is None:
                    value = codec.value(raw[variable.name])
                else:
                    value = variable.collection(
                        variable.build(
                            session,
                            codec,
                            actor,
                            {
                                **environment,
                                variable.item: member,
                                variable.choice: codec.value(raw[name]),
                            },
                        )
                        for name, member in groups[variable.name]
                    )
                values[variable.name] = codec.validate(variable.type_name, value)
            return values

        def dependencies(names):
            return tuple(
                raw
                for variable in definition.variables
                if variable.name in names
                for raw in raw_names[variable.name]
            )

        for index, entry in enumerate(selected):

            def check(raw, entry=entry):
                return entry.definition.evaluate(
                    session, codec, actor, {**materialize(raw), **entry.values}
                )

            predicates.append(
                Predicate("input:" + str(index), dependencies(entry.definition.dependencies), check)
            )
        keys, queries = [], []
        for query in definition.queries:
            members = (
                (None,)
                if query.each is None
                else ordered(query.each(session, codec, actor, environment))
            )
            meter.spend(len(members) + 1)
            for member in members:
                local = {} if query.item is None else {query.item: member}
                key = codec.term(
                    query.key_type, query.key(session, codec, actor, {**environment, **local})
                )
                if key in keys:
                    raise ValueError("finite queries need distinct nominal keys")
                keys.append(key)

                def check(raw, query=query, local=local):
                    return query.holds(session, codec, actor, {**materialize(raw), **local})

                queries.append(
                    Predicate(str(len(keys) - 1), dependencies(query.dependencies), check)
                )
        remaining = definition.limits.work - meter.work
        if remaining < 1:
            raise PreparationBudget
        result = solve(
            tuple(variables),
            tuple(predicates),
            tuple(queries),
            limits=replace(definition.limits, work=remaining),
        )
        meter.work += result.work
        if result.status != "consistent":
            return outcome(result.status, reason=result.reason)
        meter.spend(len(result.models) + len(result.answers) + 1)
        models = tuple(
            dict.fromkeys(
                codec.term(
                    definition.model_type,
                    definition.model(session, codec, actor, materialize(dict(raw))),
                )
                for raw in result.models
            )
        )
        answers = tuple(
            Conclusion(keys[int(answer.query)], answer.entailed, answer.possible, answer.refuted)
            for answer in result.answers
        )
        return outcome("consistent", models, answers)
    except PreparationBudget:
        return outcome("pending", reason="preparation_budget")
    except (ExpressionError, ValueBindingError) as error:
        if not budget_error(error):
            raise
        return outcome("pending", reason=error.diagnostic.code)
