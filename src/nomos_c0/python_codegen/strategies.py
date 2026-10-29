"""Generate independent policy expressions against the exact selected world."""

from types import SimpleNamespace

from .evaluation import EvaluationEmitter
from .fixed_values import fixed_value
from .information import local_readers
from .input_bindings import InputBindings
from .syntax import statements


def controller_definition(emitter):
    if emitter.controllers is None:
        return "None"
    definitions = []
    plans = {plan.name: plan for plan in emitter.program.abilities}
    evaluations = {(i, j): plan for i, j, plan in emitter.controllers.evaluations}
    for index, strategy in enumerate(emitter.controllers.strategies):

        def parameter_value(parameter):
            default = fixed_value(
                emitter.program.table, parameter, references="actor_reads.references"
            )
            if parameter.name not in strategy.tunable:
                return default
            return f"session.controller_parameter(actor, {parameter.name!r}, {default})"

        rules = []
        for ordinal, rule in enumerate(strategy.candidates):
            plan = plans[rule.ability]
            name = f"_strategy_{index}_{ordinal}"
            views = local_readers(
                emitter,
                name,
                SimpleNamespace(views=(*plan.views, *strategy.views, *rule.views)),
                memoize=True,
            )
            lines = InputBindings(emitter).environment(plan, views)
            lines.extend(
                [
                    "environment.update(dict(values))",
                    f"environment.pop({plan.actor!r}, None)",
                    f"environment[{strategy.actor!r}] = actor",
                ]
            )
            lines.extend(
                f"environment[{p.name!r}] = {parameter_value(p)}" for p in strategy.parameters
            )
            evaluation = (
                EvaluationEmitter(emitter, evaluations[index, ordinal])
                if rule.meaning is not None
                else None
            )

            def expression(key, checked):
                return (
                    emitter.expression(checked)
                    if evaluation is None
                    else evaluation.expression(
                        key,
                        logical_work="logical_work"
                        if key[0] in {"feature", "prior", "known", "valuation", "target"}
                        else None,
                    )
                )

            prepare = "None"
            description_lines = []
            meaning_lines = []
            if rule.meaning is not None:
                prepare = name + "_prepare"
                meaning = rule.meaning
                features = ", ".join(
                    f"({key!r}, {expression(('feature', key), expr)})"
                    for key, expr in meaning.features
                )
                prior = ", ".join(
                    f"({key!r}, {expression(('prior', key), expr)})" for key, expr in meaning.prior
                )
                known = ", ".join(
                    f"({key!r}, {expression(('known', key), expr)})" for key, expr in meaning.known
                )
                valuation = ", ".join(
                    f"({key!r}, {expression(('valuation', key), expr)})"
                    for key, expr in meaning.valuation
                )
                target_lines = ["target = None"]
                if meaning.target is not None:
                    kind = meaning.target_type
                    target_lines = [
                        f"value = {expression(('target',), meaning.target)}",
                        f"_VALIDATORS[{kind!r}](value, "
                        "ValueBudget(evaluation_limits, actor_reads.references), ())",
                        f"target = Term({kind!r}, _TERM_CODECS[{kind!r}][0], "
                        f"_TERM_CODECS[{kind!r}][1](value))",
                    ]
                correlation_lines = ["correlation = []", "captured = []"]
                for collection, category, items in (
                    ("correlation", "correlation", meaning.correlation),
                    ("captured", "capture", meaning.capture),
                ):
                    for label, kind, checked in items:
                        correlation_lines.extend(
                            [
                                f"value = {expression((category, label), checked)}",
                                f"_VALIDATORS[{kind!r}](value, "
                                "ValueBudget(session.limits.value, actor_reads.references), ())",
                                f"{collection}.append(({label!r}, Term({kind!r}, "
                                f"_TERM_CODECS[{kind!r}][0], _TERM_CODECS[{kind!r}][1](value))))",
                            ]
                        )
                meaning_lines = [
                    *target_lines,
                    f"features = ({features},)",
                    f"known = ({known}{',' if known else ''})",
                    "candidate = SemanticCandidate(key, tuple((label, number) "
                    "for label, number in features if number != 0), "
                    f"({prior},), target, "
                    "frozenset(label for label, known in known if known), "
                    f"({valuation}{',' if valuation else ''}))",
                    "return candidate",
                ]
                projection_lines = []
                if meaning.projections:
                    projection = meaning.projections[0]
                    contribution_items = []
                    for label, expr in projection.features:
                        value = emitter.expression(
                            expr,
                            limits="evaluation_limits",
                            logical_work="logical_work",
                        )
                        contribution_items.append(f"({label!r}, {value})")
                    contribution_values = ", ".join(contribution_items)
                    projection_lines = [
                        "def project(values, member, *, logical_work=None):",
                        "    environment = {**base_environment, **dict(values)}",
                        f"    environment.pop({plan.actor!r}, None)",
                        f"    environment[{strategy.actor!r}] = actor",
                        "    environment.update(parameters)",
                        f"    environment[{projection.binder!r}] = member",
                        f"    return ({contribution_values},)",
                        "from nomos_runtime.decisions import PartialFeatureProjection",
                        f"projection = PartialFeatureProjection({strategy.semantics.digest!r}, "
                        f"{projection.input!r}, project, {projection.offsets!r}, "
                        f"{tuple(name for name, _ in projection.features)!r})",
                    ]
                else:
                    projection_lines = ["projection = None"]
                description_lines = [
                    "began = perf_counter()",
                    "candidate = meaning(values, key)",
                    "timing = DescriptionTiming((perf_counter() - began) * 1000, 0, 0)",
                    "def metadata():",
                    *("    " + line for line in correlation_lines),
                    "    return CandidateMetadata(tuple(correlation), tuple(captured))",
                    "def explain():",
                    f"    return {name}_explain_values("
                    "session, environment, actor_reads, world_reads, evaluations)",
                    "return CandidateDescription(candidate, metadata, explain, timing)",
                ]
            explanation_lines = ["items = []"]
            for explanation_index, item in enumerate(
                ()
                if rule.prediction is not None and rule.prediction.score_mode == "replace"
                else rule.explanations
            ):
                explanation_lines.extend(
                    [
                        f"if {expression(('explanation', explanation_index, 'when'), item.when)}:",
                        f"    items.append(({item.category!r}, {item.label!r}, {item.type_name!r}, "
                        f"{expression(('explanation', explanation_index, 'value'), item.value)}))",
                    ]
                )
            explanation_lines.append("return tuple(items)")
            emitter.function(
                name + "_explain_values",
                "session, environment, actor_reads, world_reads, evaluations",
                explanation_lines,
            )
            evaluation_lines = (
                ["evaluations = ()"] if evaluation is None else evaluation.preparation()
            )
            if rule.meaning is not None:
                prepare_lines = InputBindings(emitter).environment(plan, views)
                aliases = tuple(
                    dict.fromkeys(
                        name
                        for node in evaluation.plan.nodes
                        if any(
                            site[0] in {"feature", "prior", "known", "valuation", "target"}
                            for site in node.sites
                        )
                        for name, _ in node.dependencies.views
                    )
                )
                prepare_lines.extend(
                    [
                        "if detached:",
                        "    from nomos_runtime.entities import detached_reads",
                        f"    actor_reads = detached_reads(actor_reads, {aliases!r})",
                        f"    world_reads = detached_reads(world_reads, {aliases!r})",
                    ]
                )
                prepare_lines.append("base_environment = environment")
                parameters = ", ".join(
                    f"{p.name!r}: {parameter_value(p)}" for p in strategy.parameters
                )
                prepare_lines.append(f"parameters = {{{parameters}}}")
                prepare_lines.extend(
                    [
                        "evaluation_base = dict(base_environment)",
                        f"evaluation_base.pop({plan.actor!r}, None)",
                        f"evaluation_base[{strategy.actor!r}] = actor",
                        "evaluation_base.update(parameters)",
                    ]
                )
                candidate_lines = [
                    "environment = {**base_environment, **dict(values)}",
                    f"environment.pop({plan.actor!r}, None)",
                    f"environment[{strategy.actor!r}] = actor",
                    "environment.update(parameters)",
                ]
                emitter.function(
                    prepare,
                    "session, actor, record, *, detached=False",
                    [
                        *prepare_lines,
                        *evaluation_lines,
                        *projection_lines,
                        "def meaning(values, key, *, logical_work=None):",
                        *("    " + line for line in (*candidate_lines, *meaning_lines)),
                        *(
                            [
                                "def screen(values):",
                                *("    " + line for line in candidate_lines),
                                "    return ("
                                + expression(("screen",), rule.screen)
                                + ", "
                                + (
                                    expression(("diversify",), rule.diversify)
                                    if rule.diversify is not None
                                    else "None"
                                )
                                + ")",
                            ]
                            if rule.screen is not None
                            else []
                        ),
                        "def describe(values, key):",
                        *("    " + line for line in (*candidate_lines, *description_lines)),
                        "return PreparedCandidateRule("
                        f"{'screen' if rule.screen is not None else 'None'}, "
                        "describe, meaning, projection)",
                    ],
                )
            emitter.function(
                name + "_explain",
                "session, actor, values, record",
                [
                    *lines,
                    "evaluation_base = environment",
                    *evaluation_lines,
                    f"return {name}_explain_values("
                    "session, environment, actor_reads, world_reads, evaluations)",
                ],
            )
            prediction = "None"
            if rule.prediction is not None:
                prediction = name + "_predict"
                p = rule.prediction
                prediction_class = "Prediction" if p.kind == "categorical" else "EventPrediction"
                emitter.function(
                    name + "_model",
                    "",
                    [
                        "from nomos_cognition.prediction import provider",
                        "import json",
                        f"implementation = provider({p.provider!r})",
                        f"return implementation, implementation.build(json.loads({p.artifact!r}))",
                    ],
                )
                # Construct weights once per loaded artifact, never once per candidate.
                emitter.functions.extend(
                    statements(f"{name}_provider, {name}_weights = {name}_model()")
                )
                ports = ", ".join(f"{key!r}: {emitter.expression(expr)}" for key, expr in p.inputs)
                emitter.function(
                    prediction,
                    "session, actor, values, record",
                    [
                        *lines,
                        f"from nomos_cognition.prediction import {prediction_class}",
                        f"ports = {{{ports}}}",
                        "try:",
                        f"    probabilities = {name}_provider.predict({name}_weights, ports)",
                        "except (ValueError, KeyError, TypeError) as error:",
                        "    raise AdmissionError('PredictionInput', "
                        "'model input differs from its selected contract') from error",
                        f"return {prediction_class}({p.digest!r}, {p.label!r}, {p.subject_type!r}, "
                        "probabilities, len(session.history()))",
                    ],
                )
                emitter.function(
                    prediction + "_subject",
                    "session, actor, values, record",
                    [
                        *lines,
                        "return " + emitter.expression(p.subject),
                    ],
                )
                if p.when is not None:
                    emitter.function(
                        prediction + "_when",
                        "session, actor, values, record",
                        [*lines, "return " + emitter.expression(p.when)],
                    )
            for field, checked in (*rule.supplied, *rule.choices):
                lines.extend(
                    [f"if field == {field!r}:", "    return " + emitter.expression(checked)]
                )
            lines.append(
                "if field is not None: "
                "raise AdmissionError('MissingBinding', 'unknown supplied input')"
            )
            scored = (
                ()
                if rule.prediction is not None
                and rule.prediction.when is None
                and rule.prediction.score_mode == "replace"
                else rule.scores
            )
            parts = ", ".join(
                f"({label!r}, {emitter.expression(expression)})" for label, expression in scored
            )
            parts_expression = f"({parts}{',' if parts else ''})"
            conditional = rule.prediction is not None and rule.prediction.when is not None
            if conditional and rule.prediction.score_mode == "replace":
                parts_expression = (
                    f"(() if {emitter.expression(rule.prediction.when)} else {parts_expression})"
                )
            lines.append(
                "raise AdmissionError('AppraisalRequired', "
                "'semantic candidates have no fixed score')"
                if strategy.semantics is not None
                else f"return {emitter.expression(strategy.minimum)}, "
                f"{emitter.expression(rule.guard)}, {emitter.expression(rule.priority)}, "
                f"{parts_expression}"
            )
            emitter.function(name, "session, actor, values, record, field", lines)
            input_types = tuple(
                (i.name, i.type_name) for i in plan.inputs.inputs if i.kind != "derive"
            )
            planning = "None"
            if emitter.subject_planning and plan.name not in {
                action.name for action in emitter.planning.actions
            }:
                from .subject_binding import functions as binding_functions

                planning = binding_functions(
                    emitter, name + "_planning", plan, strategy, rule, views
                )
            meaning_features = tuple(k for k, _ in rule.meaning.features) if rule.meaning else ()
            rules.append(
                f"CandidateRule({rule.ability!r}, {tuple(k for k, _ in rule.supplied)!r}, "
                f"{tuple(k for k, _ in rule.choices)!r}, "
                f"{name}, {name}_explain, {prediction}, "
                f"{'None' if rule.prediction is None else prediction + '_subject'}, "
                f"{tuple(i.name for i in plan.inputs.inputs)!r}, "
                f"{meaning_features!r}, {prepare}, "
                f"{input_types!r}, {planning}, "
                f"{prediction + '_when' if conditional else 'None'}, "
                f"{'replace' if rule.prediction is None else rule.prediction.score_mode!r})"
            )
        semantics = "None"
        feedback = "()"
        if strategy.semantics is not None:
            from .feedback import definitions as feedback_definitions

            profile = strategy.semantics
            feedback = feedback_definitions(emitter, index, profile)
            semantics = (
                f"AppraisalModel({profile.name!r}, {profile.digest!r}, "
                f"{profile.features!r}, {profile.outcomes!r}, "
                f"applicability={profile.applicability!r}, appraisal={profile.appraisal!r})"
            )
        cognition = tuple(
            sorted({view.channel for _, view in strategy.views if view.kind == "cognition"})
        )
        tunable = tuple(
            (parameter.name, parameter.type_name)
            for parameter in strategy.parameters
            if parameter.name in strategy.tunable
        )
        definitions.append(
            f"StrategyDefinition({strategy.selector_kind!r}, {strategy.controller!r}, "
            f"{strategy.tie!r}, ({', '.join(rules)},), {cognition!r}, {semantics}, {feedback}, "
            f"{strategy.participation!r}, {strategy.consideration!r}, "
            f"{tunable!r})"
        )
    codecs = (
        "_TERM_CODECS"
        if any(s.semantics is not None for s in emitter.controllers.strategies)
        else "None"
    )
    return (
        f"ControllerLibrary(PROGRAM, ({', '.join(definitions)}"
        f"{',' if definitions else ''}), {codecs}, "
        f"{'PLANNING' if emitter.subject_planning else 'None'})"
    )
