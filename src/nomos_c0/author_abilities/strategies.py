"""Finite Actor-local ranking produces requests, never speculative world effects."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from nomos_c0.author_contract_v1 import C0LawError

from .effects import EffectCompiler
from .expression_syntax import _identifier
from .opening import OpeningSymbol, ParameterValue, value_node


def _candidate_types(plan):
    from .context_state import context_types

    bindings = dict(plan.inputs.base)
    if plan.context is not None:
        bindings.update(context_types(plan.context, local=True))
    bindings.pop(plan.actor, None)
    return bindings


@dataclass(frozen=True)
class ControllerPlan:
    program: object
    strategies: tuple
    cognition: object | None = None
    evaluations: tuple = field(init=False, repr=False)

    def __post_init__(self):
        from nomos_c0.evaluation_plan import plan_candidate_evaluation

        actions = {plan.name: plan for plan in self.program.abilities}
        plans = tuple(
            (index, ordinal, plan_candidate_evaluation(actions[rule.ability], strategy, rule))
            for index, strategy in enumerate(self.strategies)
            for ordinal, rule in enumerate(strategy.candidates)
            if rule.meaning is not None
        )
        object.__setattr__(self, "evaluations", plans)


def compile_controllers(program, declaration, *, context=None, cognition=None):
    """Compile independent local policies against one exact, unchanged world Program."""
    from .frontend import row
    from .program import AuthorProgram

    if type(program) is not AuthorProgram:
        raise C0LawError("controllers require an AuthorProgram")
    from .cognition import channel_signatures_from_program, require_cognition

    channels = channel_signatures_from_program(program)
    if cognition is not None:
        require_cognition(program, cognition)
        channels.update(
            (("cognition", binding.name), (binding.view_type, "", ""))
            for binding in cognition.bindings
        )
    row(
        declaration,
        {"schema", "strategies", "control"},
        {"queries", "predictors", "rankings", "semantics"},
        path="AI",
    )
    if declaration["schema"] != "nomos.author.ai":
        raise C0LawError("AI requires nomos.author.ai schema")
    symbols = tuple((name, OpeningSymbol(name, sort, "person")) for name, sort in program.actors)
    from .expressions import compile_pure_values

    library = compile_pure_values(
        program.table,
        declaration.get("queries", {}),
        entities=program.entities,
        context=context,
        base_library=program.queries,
    )
    plans = compile_strategies(
        declaration["strategies"],
        declaration["control"],
        program.table,
        program.entities,
        library,
        program.abilities,
        dict(program.actors),
        program.actor_kinds,
        symbols,
        context,
        channels,
        declaration.get("predictors", {}),
        declaration.get("rankings", {}),
        declaration.get("semantics", {}),
        program.terminal,
    )
    for strategy in plans:
        for _, view in strategy.views:
            if view.kind != "cognition":
                continue
            model = next(b for b in cognition.bindings if b.name == view.channel)
            if strategy.selector_kind == "actor":
                covered = (
                    model.selector == "actor"
                    and model.target == strategy.controller
                    or model.selector == "kind"
                    and dict(program.actors)[strategy.controller] in model.families
                )
            else:
                sorts = {
                    sort
                    for sort in program.actor_kinds
                    if program.table.accepts_sort(strategy.controller, sort)
                }
                covered = model.selector == "kind" and sorts <= set(model.families)
            if not covered:
                raise C0LawError("strategy cannot import another Actor's cognition")
    return ControllerPlan(program, plans, cognition)


def read_controllers(program, path, *, cognition=None):
    from .assembly import read_author_modules

    document = read_author_modules(path)
    return compile_controllers(
        program, document.to_data(), context=document.context(), cognition=cognition
    )


def require_controllers(program, controllers, *, player=None):
    """Automation checks coverage; manual world sessions do not require an AI."""
    if type(controllers) is not ControllerPlan or controllers.program is not program:
        raise C0LawError("automation requires controllers bound to the exact Program")

    def matches(plan, symbol, sort):
        return (
            plan.selector_kind == "actor"
            and plan.controller == symbol
            or plan.selector_kind == "kind"
            and program.table.accepts_sort(plan.controller, sort)
        )

    for symbol, sort in program.actors:
        if symbol != player and not any(matches(p, symbol, sort) for p in controllers.strategies):
            raise C0LawError("automation needs a policy for every computer Actor")
    from .formation import formation_sorts

    producers = (
        *program.abilities,
        *program.reactions,
        *(p.event for p in program.periodic),
        *(p.completion for p in program.activities),
        *(p.cancellation for p in program.activities if p.cancellation is not None),
    )
    for rule in producers:
        for sort in formation_sorts(rule, kind="person"):
            if not any(
                p.selector_kind == "kind" and program.table.accepts_sort(p.controller, sort)
                for p in controllers.strategies
            ):
                raise C0LawError("automation needs a kind policy for every formed Actor")


@dataclass(frozen=True)
class StrategyExplanation:
    category: str
    label: str
    type_name: str
    value: object
    when: object


@dataclass(frozen=True)
class CandidateRule:
    ability: str
    guard: object
    priority: object
    scores: tuple
    supplied: tuple
    choices: tuple
    explanations: tuple
    prediction: object | None
    views: tuple
    meaning: object | None = None
    screen: object | None = None
    diversify: object | None = None


def compile_explanations(branch, declaration, location):
    from .frontend import row

    if not isinstance(declaration, Mapping) or set(declaration) - {
        "information",
        "judgment",
        "motive",
    }:
        raise C0LawError(location + ": explanation categories are information/judgment/motive")
    result = []
    for category, items in declaration.items():
        if not isinstance(items, Mapping):
            raise C0LawError(location + ": named explanation items required")
        for label, item in items.items():
            if type(label) is not str or not label.strip() or len(label) > 128:
                raise C0LawError(location + ": bounded explanation label required")
            path = location + "." + category + "." + label
            row(item, {"type", "value"}, {"when"}, path=path)
            if type(item["type"]) is not str or item["type"] not in dict(branch.table.definitions):
                raise C0LawError(path + ": named explanation type required")
            result.append(
                StrategyExplanation(
                    category,
                    label,
                    item["type"],
                    branch.expression(
                        item["value"], item["type"], path + ".value", context="actor"
                    ),
                    branch.expression(
                        item.get("when", "True"), "Bool", path + ".when", context="actor"
                    ),
                )
            )
    return tuple(result)


@dataclass(frozen=True)
class StrategyPlan:
    controller: str
    definition: str
    actor: str
    actor_type: str
    parameters: tuple
    tunable: tuple
    candidates: tuple
    minimum: object
    tie: str
    selector_kind: str
    views: tuple = ()
    semantics: object | None = None
    participation: tuple | None = None
    consideration: int | None = None


def compile_strategies(
    definitions,
    selected,
    table,
    entities,
    pure,
    abilities,
    actors,
    actor_sorts,
    symbols,
    context,
    channels,
    predictors,
    ranking_definitions,
    semantic_profiles,
    terminal,
):
    from .frontend import row

    if any(
        not isinstance(v, Mapping)
        for v in (definitions, selected, predictors, ranking_definitions, semantic_profiles)
    ):
        raise C0LawError("strategies/control require named declarations")
    result = []
    scopes = []
    for binding_name, binding in selected.items():
        row(
            binding,
            {"definition"},
            {"with", "actor", "kind", "views", "rankings", "tunable"},
            path="control." + str(binding_name),
        )
        selectors = set(binding) & {"actor", "kind"}
        if not _identifier(binding_name) or len(selectors) != 1:
            raise C0LawError("control requires one explicit actor/kind selector")
        selector = next(iter(selectors))
        actor = binding[selector]
        name = binding["definition"]
        if type(actor) is not str or type(name) is not str or name not in definitions:
            raise C0LawError("control requires an actual selected Actor and strategy definition")
        if selector == "actor":
            if actor not in actors:
                raise C0LawError("control.actor names an unknown opening Actor")
            matching_sorts = {actors[actor]}
        else:
            schemas = dict(entities.entities)
            if actor not in schemas or schemas[actor].kind != "person":
                raise C0LawError("control.kind requires a declared Person sort")
            matching_sorts = {sort for sort in actor_sorts if table.accepts_sort(actor, sort)}
            if not matching_sorts:
                raise C0LawError("control.kind has no selected Actor sort")
        for previous_selector, previous_actor, previous_sorts in scopes:
            conflict = (
                selector == previous_selector == "actor"
                and actor == previous_actor
                or selector == previous_selector == "kind"
                and matching_sorts & previous_sorts
                or selector == "actor"
                and previous_selector == "kind"
                and actors[actor] in previous_sorts
                or selector == "kind"
                and previous_selector == "actor"
                and actors[previous_actor] in matching_sorts
            )
            if conflict:
                raise C0LawError("control strategies overlap on an actual or possible Actor")
        scopes.append((selector, actor, matching_sorts))
        path = "strategies." + name
        body = definitions[name]
        semantic = isinstance(body, Mapping) and "semantics" in body
        row(
            body,
            {"actor", "candidates", "tie", "wait", "semantics" if semantic else "minimum"},
            {"parameters", "views", "explain"}
            | ({"participation", "consideration"} if semantic else set()),
            path=path,
        )
        if not isinstance(body["actor"], Mapping) or len(body["actor"]) != 1:
            raise C0LawError(path + ": one named Actor reference required")
        local, kind = next(iter(body["actor"].items()))
        if (
            not _identifier(local)
            or type(kind) is not str
            or kind not in dict(table.definitions)
            or table[kind].kind != "ref"
            or not all(table.accepts_sort(table[kind].sort, sort) for sort in matching_sorts)
        ):
            raise C0LawError(path + ": strategy Actor type does not accept its controller")
        if body["tie"] not in ("wait", "canonical") or body["wait"] != "no_candidate":
            raise C0LawError(path + ": explicit tie wait/canonical and no_candidate wait required")
        parameters, supplied = body.get("parameters", {}), binding.get("with", {})
        if (
            not isinstance(parameters, Mapping)
            or not isinstance(supplied, Mapping)
            or set(parameters) != set(supplied)
            or local in parameters
        ):
            raise C0LawError(path + ": exact disjoint parameter bindings required")
        fixed = []
        for key, type_name in parameters.items():
            if (
                not _identifier(key)
                or type(type_name) is not str
                or type_name not in dict(table.definitions)
            ):
                raise C0LawError(path + ": malformed strategy parameter")
            fixed.append(
                ParameterValue(
                    key, type_name, value_node(table, table[type_name], supplied[key], symbols)
                )
            )
        tunable = binding.get("tunable", None)
        if tunable is not None and (
            type(tunable) is not list
            or any(type(name) is not str for name in tunable)
            or len(set(tunable)) != len(tunable)
            or not set(tunable) <= set(parameters)
        ):
            raise C0LawError(path + ": tunable needs distinct declared parameter names")
        tunable = () if tunable is None else tuple(tunable)
        base = {local: kind, **parameters}
        from .local_views import compile_local_views

        views = compile_local_views(
            body.get("views", {}), binding.get("views", {}), table, pure, entities, base, channels
        )
        compiler = EffectCompiler(
            table,
            base,
            library=pure,
            entities=entities,
            actor=local,
            context=context,
            local_views=views,
        )
        minimum = (
            None
            if semantic
            else compiler.expression(body["minimum"], None, path + ".minimum", context="actor")
        )
        if minimum is not None and minimum.result.kind != "int":
            raise C0LawError(path + ": integer minimum score required")
        rows = body["candidates"]
        if type(rows) is not list or not rows:
            raise C0LawError(path + ": finite candidate rules required")
        profile, meanings = None, {}
        if semantic:
            from .action_semantics import select_profile

            profile, meanings = select_profile(body["semantics"], semantic_profiles, rows)
            if binding.get("rankings"):
                raise C0LawError(path + ": semantic candidates cannot mix fixed model rankings")
        candidates = []
        consideration = None
        if "consideration" in body:
            policy = body["consideration"]
            row(policy, {"per_ability"}, path=path + ".consideration")
            consideration = policy["per_ability"]
            if type(consideration) is not int or not 1 <= consideration <= 128:
                raise C0LawError(path + ": consideration needs per_ability in 1..128")
        participation = None
        if "participation" in body:
            defaults = body["participation"]
            row(defaults, {"personality", "goals"}, path=path + ".participation")
            vectors = []
            trait_names = {name for name, _, _ in profile.appraisal}
            for label in ("personality", "goals"):
                weights = defaults[label]
                allowed = set(profile.outcomes) | (trait_names if label == "personality" else set())
                if (
                    type(weights) is not dict
                    or not set(weights) <= allowed
                    or any(type(w) is not int or not -1000 <= w <= 1000 for w in weights.values())
                ):
                    raise C0LawError(path + ": participation requires declared bounded weights")
                vectors.append(tuple(sorted(weights.items())))
            participation = tuple(vectors)
        rankings = binding.get("rankings", {})
        definitions_in_rows = {
            r["definition"] for r in rows if type(r) is dict and type(r.get("definition")) is str
        }
        if type(rankings) is not dict or set(rankings) - definitions_in_rows:
            raise C0LawError(path + ": rankings must select candidate definitions")
        for index, declaration in enumerate(rows):
            location = f"{path}.candidates[{index}]"
            row(
                declaration,
                {"definition"} | (set() if semantic else {"score"}),
                {"inputs", "choices", "point", "explain", "guard", "priority"}
                | ({"screen", "diversify"} if consideration is not None else set()),
                path=location,
            )
            if semantic and ({"guard", "priority"} & set(declaration)):
                raise C0LawError(
                    location + ": guard and priority belong to direct-score candidates"
                )
            point = declaration.get("point", "begin")
            if not _identifier(point):
                raise C0LawError(location + ": named process point required")
            matching = [
                plan
                for plan in abilities
                if plan.definition == declaration["definition"]
                and any(
                    table.accepts_sort(table[plan.actor_type].sort, sort) for sort in matching_sorts
                )
                and (
                    plan.process is None
                    and point == "begin"
                    or plan.process is not None
                    and plan.process.point == point
                )
            ]
            if not matching:
                raise C0LawError(location + ": definition has no selected Actor Action")
            for plan in matching:
                bindings = _candidate_types(plan)
                bindings.update((item.name, item.type_name) for item in plan.inputs.inputs)
                if (
                    set(bindings) & set(base)
                    or set(dict(plan.views)) & set(base)
                    or set(dict(views)) & (set(bindings) | set(dict(plan.views)))
                ):
                    raise C0LawError(location + ": strategy names conflict with candidate bindings")
                ranking = None
                if plan.definition in rankings:
                    ranking_name = rankings[plan.definition]
                    if type(ranking_name) is not str or ranking_name not in ranking_definitions:
                        raise C0LawError(location + ": unknown named ranking")
                    ranking = ranking_definitions[ranking_name]
                    if type(ranking) is not dict:
                        raise C0LawError(location + ": selected ranking needs a declaration")
                extra_views = ()
                if ranking is not None:
                    from .prediction import compile_prediction

                    if type(ranking) is not dict or type(ranking.get("views", {})) is not dict:
                        raise C0LawError(location + ": ranking needs named local views")
                    declarations, sources = {}, {}
                    for alias, view in ranking.get("views", {}).items():
                        row(view, {"channel"}, {"reports", "projection"}, path=location)
                        declarations[alias] = {k: v for k, v in view.items() if k != "channel"}
                        sources[alias] = view["channel"]
                    extra_views = compile_local_views(
                        declarations,
                        sources,
                        table,
                        pure,
                        entities,
                        {**base, **bindings, **dict(plan.views), **dict(views)},
                        channels,
                    )
                branch = EffectCompiler(
                    table,
                    {**base, **bindings},
                    library=pure,
                    entities=entities,
                    actor=local,
                    context=context,
                    local_views=(*plan.views, *views, *extra_views),
                )
                terms = {} if semantic else declaration["score"]
                if type(terms) is str:
                    terms = {"得分": terms}
                if (
                    type(terms) is not dict
                    or not terms
                    and not semantic
                    or len(terms) > 64
                    or any(type(k) is not str or not k.strip() or len(k) > 128 for k in terms)
                ):
                    raise C0LawError(location + ": score needs an expression or named terms")
                scores = []
                for label, text in terms.items():
                    score = branch.expression(
                        text, None, location + ".score." + label, context="actor"
                    )
                    if score.result.kind != "int":
                        raise C0LawError(location + ": integer candidate score required")
                    scores.append((label, score))
                guard = branch.expression(
                    declaration.get("guard", "True"),
                    "Bool",
                    location + ".guard",
                    context="actor",
                )
                priority = branch.expression(
                    declaration.get("priority", "0"),
                    None,
                    location + ".priority",
                    context="actor",
                )
                if priority.result.kind != "int":
                    raise C0LawError(location + ": integer candidate priority required")
                inputs = declaration.get("inputs", {})
                choices = declaration.get("choices", {})
                chosen = {item.name: item for item in plan.inputs.inputs if item.kind != "derive"}
                if (
                    not isinstance(inputs, Mapping)
                    or not isinstance(choices, Mapping)
                    or set(inputs) - set(chosen)
                    or set(choices) - set(chosen)
                    or set(inputs) & set(choices)
                    or any(
                        item.kind == "enter" and key not in inputs and key not in choices
                        for key, item in chosen.items()
                    )
                ):
                    raise C0LawError(
                        location + ": explicit expressions required for typed-entry candidates"
                    )
                proposed = []
                pools = []
                bound_names = set(_candidate_types(plan))
                for input_name in plan.inputs.order:
                    item = plan.inputs.definition(input_name)
                    if input_name in inputs or input_name in choices:
                        pool = input_name in choices
                        expr = branch.expression(
                            choices[input_name] if pool else inputs[input_name],
                            None if pool else item.type_name,
                            location + (".choices." if pool else ".inputs.") + input_name,
                            context="actor",
                        )
                        if pool and (
                            expr.result.kind != "set"
                            or expr.result.element.type_id != table[item.type_name].type_id
                        ):
                            raise C0LawError(
                                location + ": candidate choices need a set of the exact input type"
                            )
                        if {read.root for read in expr.summary.reads} - (set(base) | bound_names):
                            raise C0LawError(
                                location + ": supplied inputs must follow candidate dependencies"
                            )
                        expr = replace(
                            expr,
                            inputs=tuple(
                                item for item in expr.inputs if item[0] in set(base) | bound_names
                            ),
                        )
                        (pools if pool else proposed).append((input_name, expr))
                    bound_names.add(input_name)
                explanations = (
                    *compile_explanations(branch, body.get("explain", {}), path + ".explain"),
                    *compile_explanations(
                        branch, declaration.get("explain", {}), location + ".explain"
                    ),
                )
                if len(explanations) > 24 or len(
                    {(e.category, e.label) for e in explanations}
                ) != len(explanations):
                    raise C0LawError(location + ": at most 24 distinct explanation items required")
                prediction = (
                    None
                    if ranking is None
                    else compile_prediction(branch, ranking, predictors, location + ".ranking")
                )
                if prediction is not None:
                    choices = {item.name for item in plan.inputs.inputs}
                    if any(
                        choices & {read.root for read in expr.summary.reads}
                        for expr in (
                            *(expr for _, expr in prediction.inputs),
                            *((prediction.when,) if prediction.when is not None else ()),
                        )
                    ):
                        raise C0LawError(
                            location + ": model evidence cannot depend on candidate choices"
                        )
                meaning = None
                screen = None
                diversify = None
                if consideration is not None:
                    if "screen" not in declaration:
                        raise C0LawError(location + ": considered candidates require screen")
                    screen = branch.expression(
                        declaration["screen"], None, location + ".screen", context="actor"
                    )
                    if screen.result.kind != "int":
                        raise C0LawError(location + ": screen requires an integer expression")
                    if "diversify" in declaration:
                        diversify = branch.expression(
                            declaration["diversify"], None, location + ".diversify", context="actor"
                        )
                if semantic:
                    from .action_semantics import compile_meaning

                    key = declaration["definition"] + ("" if point == "begin" else "." + point)
                    meaning = compile_meaning(
                        branch,
                        profile,
                        meanings[key],
                        "semantics." + profile.name + "." + key,
                        plan,
                    )
                candidates.append(
                    CandidateRule(
                        plan.name,
                        guard,
                        priority,
                        tuple(scores),
                        tuple(proposed),
                        tuple(pools),
                        explanations,
                        prediction,
                        extra_views,
                        meaning,
                        screen,
                        diversify,
                    )
                )
        if profile is not None:
            from .action_semantics import bind_profile
            from .feedback import compile_feedback

            profile = replace(
                profile,
                feedback=compile_feedback(
                    profile,
                    semantic_profiles[profile.name].get("feedback", {}),
                    candidates,
                    abilities,
                    table,
                    pure,
                    channels,
                    terminal,
                ),
            )
            profile = bind_profile(
                profile, candidates, fixed, views, abilities, body["tie"], consideration
            )
        result.append(
            StrategyPlan(
                actor,
                name,
                local,
                kind,
                tuple(fixed),
                tunable,
                tuple(candidates),
                minimum,
                body["tie"],
                selector,
                views,
                profile,
                participation,
                consideration,
            )
        )
    return tuple(result)
