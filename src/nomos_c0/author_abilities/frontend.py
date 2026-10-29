"""Compile the single author Lib/Source contract into a named-input Program."""

from collections.abc import Mapping

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0SourceContext

from .context_state import context_types, selected_context
from .defaults import normalize_action_defaults
from .disclosures import compile_disclosures
from .effects import EffectCompiler
from .entity_reads import compile_entity_reads
from .expression_syntax import _identifier
from .information import compile_information
from .inputs import compile_inputs
from .local_views import channel_signatures, compile_local_views
from .opening import OpeningSymbol, ParameterValue, value_node
from .processes import compile_process
from .program import AbilityPlan, AuthorProgram
from .projections import compile_contexts, compile_projection
from .terminals import compile_terminal
from .value_types import EntitySort, compile_value_types


def row(value, required, optional=(), *, path):
    if (
        not isinstance(value, Mapping)
        or set(value) - set(required) - set(optional)
        or set(required) - set(value)
    ):
        raise C0LawError(f"{path}: missing or unsupported fields")


def _compile_types(lib, context):
    if not isinstance(lib["entities"], Mapping):
        raise C0LawError("entity definitions require named declarations")
    if any(
        not isinstance(value, Mapping) or "kind" not in value for value in lib["entities"].values()
    ):
        raise C0LawError("entity definitions require a declared kind")
    sorts = tuple(
        EntitySort(name, value["kind"], () if "extends" not in value else (value["extends"],))
        for name, value in lib["entities"].items()
    )
    return compile_value_types(lib["values"], sorts=sorts, context=context)


def compile_author_world(lib, source, *, context=None, source_context=None):
    if context is not None and type(context) is not C0SourceContext:
        raise C0LawError("author source context is malformed")
    if source_context is not None and type(source_context) is not C0SourceContext:
        raise C0LawError("author selection source context is malformed")
    row(
        lib,
        {"schema", "values", "entities", "abilities"},
        {
            "relations",
            "queries",
            "contexts",
            "projections",
            "information",
            "disclosures",
            "processes",
            "terminals",
            "reactions",
            "activities",
            "periodic",
            "schedules",
            "facts",
            "constraints",
            "decision_groups",
            "scopes",
        },
        path="Lib",
    )
    row(
        source,
        {"schema", "name", "actors", "objects", "use"},
        {
            "contexts",
            "settlement",
            "time",
            "random",
            "actor_kinds",
            "play",
            "opening",
            "report_collections",
            "scopes",
            "ability_sets",
            "presets",
        },
        path="Source",
    )
    if lib["schema"] != "nomos.author.lib" or source["schema"] != "nomos.author.source":
        raise C0LawError("UnsupportedFeature: author Lib/Source schema required")
    from .ability_sets import expand_ability_set_selectors, expand_ability_sets
    from .author_scopes import expand_author_scopes
    from .decision_groups import check_group_conditions, check_group_epochs, expand_decision_groups

    source, source_context = expand_ability_sets(lib, source, source_context)
    preset_table = None
    if "presets" in source or (
        isinstance(source.get("use"), Mapping)
        and any(
            isinstance(value, Mapping) and "preset" in value for value in source["use"].values()
        )
    ):
        from .parameter_presets import expand_parameter_presets

        preset_table = _compile_types(lib, context)
        if not isinstance(source["actors"], Mapping) or any(
            not _identifier(name)
            or type(sort) is not str
            or sort not in lib["entities"]
            or lib["entities"][sort]["kind"] != "person"
            for name, sort in source["actors"].items()
        ):
            raise C0LawError("Source needs explicit declared Person actor symbols")
        preset_symbols = tuple(
            (name, OpeningSymbol(name, sort, "person")) for name, sort in source["actors"].items()
        )
        source, source_context = expand_parameter_presets(
            lib, source, preset_table, preset_symbols, source_context
        )
    lib, source, context, source_context = expand_author_scopes(
        lib, source, context, source_context
    )
    source, source_context = expand_ability_set_selectors(lib, source, source_context)
    lib = normalize_action_defaults(lib)
    lib, context, decision_groups = expand_decision_groups(lib, source, context)
    from .reaction_subscriptions import expand_reaction_subscriptions

    lib, source, _ = expand_reaction_subscriptions(lib, source, context, source_context)
    if not _identifier(source["name"]) or not isinstance(lib["entities"], Mapping):
        raise C0LawError("Source name and entity definitions are malformed")
    table = preset_table if preset_table is not None else _compile_types(lib, context)
    entities = compile_entity_reads(table, lib["entities"], lib.get("relations", {}))
    from .assurances import compile_fact_library
    from .constraints import compile_constraints

    facts = lib.get("facts", {})
    constraint_declarations = lib.get("constraints", {})
    pure = compile_fact_library(
        table,
        lib.get("queries", {}),
        facts,
        entities,
        context,
        constraints=constraint_declarations,
    )
    constraints = compile_constraints(table, constraint_declarations, pure, entities)
    if (
        not isinstance(source["actors"], Mapping)
        or not source["actors"]
        or type(source["objects"]) is not list
        or any(type(sort) is not str for sort in source["objects"])
        or len(source["objects"]) != len(set(source["objects"]))
    ):
        raise C0LawError("Source needs explicit actor symbols and unique selected Object sorts")
    schemas = dict(entities.entities)
    for symbol, sort in source["actors"].items():
        if (
            not _identifier(symbol)
            or type(sort) is not str
            or sort not in schemas
            or schemas[sort].kind != "person"
        ):
            raise C0LawError("Source actor names an absent Person sort")
    for sort in source["objects"]:
        if sort not in schemas or schemas[sort].kind != "object":
            raise C0LawError("Source selects an absent Object sort")
    future_kinds = source.get("actor_kinds", [])
    if (
        type(future_kinds) is not list
        or any(
            type(kind) is not str or kind not in schemas or schemas[kind].kind != "person"
            for kind in future_kinds
        )
        or len(future_kinds) != len(set(future_kinds))
    ):
        raise C0LawError("Source.actor_kinds requires unique declared Person sorts")
    actor_sorts = tuple(sorted({*source["actors"].values(), *future_kinds}))
    if (
        not isinstance(lib["abilities"], Mapping)
        or not isinstance(source["use"], Mapping)
        or not source["use"]
    ):
        raise C0LawError("Source must select at least one declared executable definition")
    definitions = {}
    for category in (
        "abilities",
        "projections",
        "information",
        "processes",
        "terminals",
        "reactions",
        "activities",
        "periodic",
    ):
        declarations = lib.get(category, {})
        if not isinstance(declarations, Mapping):
            raise C0LawError(category + " requires named declarations")
        for name, declaration in declarations.items():
            if not _identifier(name) or name in definitions:
                raise C0LawError("executable definition names must be valid and globally unique")
            definitions[name] = (category, declaration)
    symbols = tuple(
        (symbol, OpeningSymbol(symbol, sort, "person")) for symbol, sort in source["actors"].items()
    )
    contexts = compile_contexts(
        table,
        entities,
        pure,
        lib.get("contexts", {}),
        source.get("contexts", {}),
        symbols,
        tuple({*actor_sorts, *source["objects"]}),
        context=context,
    )
    abilities = []
    projections = []
    information = []
    processes = []
    terminal = None
    reaction_declarations = {}
    activity_declarations = {}
    periodic_declarations = {}
    disclosures = compile_disclosures(
        table,
        lib.get("disclosures", {}),
        entities,
        pure,
        context,
        facts=facts,
        constraints=constraints,
    )
    for name, selected in source["use"].items():
        row(
            selected, {"definition"}, {"with", "context", "views", "after"}, path="use." + str(name)
        )
        if type(selected["definition"]) is not str:
            raise C0LawError("use." + str(name) + ".definition requires a definition name")
    channels = channel_signatures(lib, source)
    for name, selected in source["use"].items():
        if not _identifier(name):
            raise C0LawError("executable use name is malformed")
        row(selected, {"definition"}, {"with", "context", "views", "after"}, path="use." + name)
        definition = selected["definition"]
        if type(definition) is not str or definition not in definitions:
            raise C0LawError("Source selects an unknown executable definition")
        category, declaration = definitions[definition]
        if category == "reactions":
            reaction_declarations[name] = (definition, declaration, selected)
            continue
        if category == "activities":
            activity_declarations[name] = (definition, declaration, selected)
            continue
        if category == "periodic":
            periodic_declarations[name] = (definition, declaration, selected)
            continue
        if category == "terminals":
            if terminal is not None:
                raise C0LawError(
                    "Source may select only one terminal policy, not competing defaults"
                )
            terminal = compile_terminal(
                name,
                declaration,
                selected,
                contexts,
                table,
                entities,
                pure,
                context,
                source["name"],
            )
            continue
        if category == "processes":
            plan = compile_process(
                name,
                definition,
                declaration,
                selected,
                table,
                entities,
                pure,
                symbols,
                actor_sorts,
                channels,
                disclosures,
                source["name"],
                context,
            )
            processes.append(plan)
            abilities.extend(plan.nodes)
            continue
        if category == "information":
            information.append(
                compile_information(
                    name,
                    definition,
                    declaration,
                    selected,
                    contexts,
                    table,
                    entities,
                    pure,
                    actor_sorts,
                    context=context,
                    facts=facts,
                    constraints=constraints,
                )
            )
            continue
        if category == "projections":
            projections.append(
                compile_projection(
                    name,
                    definition,
                    declaration,
                    selected,
                    contexts,
                    table,
                    entities,
                    pure,
                    actor_sorts,
                    context=context,
                )
            )
            continue
        row(selected, {"definition"}, {"with", "views", "context"}, path="use." + name)
        path = "abilities." + definition
        row(
            declaration,
            {"actor", "where", "results", "resolve"},
            {"parameters", "inputs", "cost", "views", "context", "epoch", "time_cost"},
            path=path,
        )
        actor = declaration["actor"]
        if not isinstance(actor, Mapping) or len(actor) != 1:
            raise C0LawError(f"{path}: exactly one named actor parameter required")
        actor_name, actor_type = next(iter(actor.items()))
        if not _identifier(actor_name) or actor_type not in dict(table.definitions):
            raise C0LawError(f"{path}: actor requires a named Ref type")
        actor_plan = table[actor_type]
        if (
            actor_plan.kind != "ref"
            or schemas[actor_plan.sort].kind != "person"
            or not any(table.accepts_sort(actor_plan.sort, sort) for sort in actor_sorts)
        ):
            raise C0LawError(f"{path}: actor must be a selected Person Ref")
        parameters = declaration.get("parameters", {})
        supplied = selected.get("with", {})
        if (
            not isinstance(parameters, Mapping)
            or not isinstance(supplied, Mapping)
            or set(supplied) != set(parameters)
        ):
            raise C0LawError(f"use.{name}: exact parameter bindings required")
        bound = []
        for symbol, type_name in parameters.items():
            if (
                not _identifier(symbol)
                or symbol == actor_name
                or type_name not in dict(table.definitions)
            ):
                raise C0LawError(f"{path}: parameter name/type is invalid")
            try:
                node = value_node(table, table[type_name], supplied[symbol], symbols)
            except ValueError as error:
                raise C0LawError(f"use.{name}.with.{symbol}: {error}") from None
            bound.append(ParameterValue(symbol, type_name, node))
        shared = selected_context(declaration, selected, contexts)
        shared_types = {} if shared is None else context_types(shared)
        if set(shared_types) & {actor_name, *parameters, *declaration.get("inputs", {})}:
            raise C0LawError(f"{path}: context names conflict with executable bindings")
        local_types = {} if shared is None else context_types(shared, local=True)
        base = {actor_name: actor_type, **parameters, **local_types}
        views = compile_local_views(
            declaration.get("views", {}),
            selected.get("views", {}),
            table,
            pure,
            entities,
            {*base, *shared_types, *declaration.get("inputs", {})},
            channels,
        )
        inputs = compile_inputs(
            table,
            declaration.get("inputs", {}),
            base,
            library=pure,
            entities=entities,
            actor=actor_name,
            path=path + ".inputs",
            context=context,
            local_views=views,
        )
        local_bindings = {**base, **{item.name: item.type_name for item in inputs.inputs}}
        bindings = {**local_bindings, **shared_types}
        compiler = EffectCompiler(
            table,
            bindings,
            library=pure,
            entities=entities,
            actor=actor_name,
            path=path,
            context=context,
            local_views=views,
            disclosures=disclosures,
            actor_bindings=local_bindings,
            shared_context=shared,
        )
        outcome = declaration["results"]
        if type(outcome) is not str or outcome not in dict(table.definitions):
            raise C0LawError(f"{path}: results require a named value type")
        check_group_conditions(decision_groups, definition, compiler)
        where = compiler.expression(declaration["where"], "Bool", path + ".where", context="actor")
        epoch = None
        if "epoch" in declaration:
            epoch = compiler.expression(
                declaration["epoch"], None, path + ".epoch", context="actor"
            )
            if {read.root for read in epoch.summary.reads} - set(base):
                raise C0LawError(f"{path}.epoch: request epoch cannot depend on new choices")
        costs = compiler.fields(declaration.get("cost", []), costs=True)
        from .scheduling import positive_time_cost

        time_cost = positive_time_cost(compiler, declaration.get("time_cost"), path + ".time_cost")
        resolution = compiler.resolution(declaration["resolve"], outcome)
        labels = {}
        for leaf in resolution.leaves():
            for call in leaf.deliveries:
                if call.label in labels and labels[call.label] != call.definition:
                    raise C0LawError("delivery label has inconsistent branch definitions")
                labels[call.label] = call.definition
        summary = compiler.summary(costs, resolution)
        abilities.append(
            AbilityPlan(
                name,
                definition,
                actor_name,
                actor_type,
                tuple(bound),
                inputs,
                where,
                costs,
                resolution,
                summary,
                f"author.{source['name']}.{name}.action",
                views,
                context=shared,
                epoch=epoch,
                time_cost=time_cost,
            )
        )
    check_group_epochs(decision_groups, abilities)
    from .activities import compile_activities, compile_time
    from .periodic import compile_periodic
    from .reactions import compile_reactions

    activities = compile_activities(
        activity_declarations,
        abilities,
        table,
        entities,
        pure,
        symbols,
        disclosures,
        source["name"],
        context,
        contexts,
    )
    periodic = compile_periodic(
        periodic_declarations,
        table,
        entities,
        pure,
        symbols,
        disclosures,
        source["name"],
        context,
        contexts,
    )
    temporal_roots = (
        tuple(p.event for p in periodic)
        + tuple(p.completion for p in activities)
        + tuple(p.cancellation for p in activities if p.cancellation is not None)
    )
    if "time" in source and source["time"] is None:
        raise C0LawError("Source.time requires a mechanism declaration, not null")
    if "time" in source and not isinstance(source["time"], Mapping):
        raise C0LawError("Source.time requires a mechanism mapping")
    if "time" in source and "scheduling" in source["time"] and source["time"]["scheduling"] is None:
        raise C0LawError("Source.time.scheduling requires an explicit policy, not null")
    from .scheduling import compile_schedules

    scheduling = compile_schedules(
        None if source.get("time") is None else source["time"].get("scheduling"),
        lib.get("schedules", {}),
        abilities,
        activities,
        table,
        entities,
        pure,
        symbols,
        actor_sorts,
        context,
    )
    time = compile_time(source.get("time"), activities, periodic, scheduling)

    reactions = compile_reactions(
        reaction_declarations,
        [*abilities, *temporal_roots],
        table,
        entities,
        pure,
        symbols,
        disclosures,
        source["name"],
        context,
        contexts,
    )
    from .settlements import compile_settlements

    settlements = compile_settlements(
        source.get("settlement", {"default": "wave"}),
        [*abilities, *temporal_roots],
        reactions,
        source["name"],
    )
    from .randomness import compile_random

    if "random" in source and source["random"] is None:
        raise C0LawError("Source.random requires an explicit mechanism, not null")
    random = compile_random(source.get("random"), [*abilities, *temporal_roots, *reactions])
    from .opening_deals import compile_opening

    opening = compile_opening(source.get("opening", {}), contexts, table, entities, random)
    from .formation import formation_sorts

    if any(
        sort not in source["objects"]
        for plan in [*abilities, *temporal_roots, *reactions]
        for sort in formation_sorts(plan)
    ):
        raise C0LawError("form requires each created Object type to be selected in Source.objects")
    if any(
        sort not in actor_sorts
        for plan in [*abilities, *temporal_roots, *reactions]
        for sort in formation_sorts(plan, kind="person")
    ):
        raise C0LawError("form requires each created Actor type to be selected in Source")
    from .play import compile_play

    if "play" in source and source["play"] is None:
        raise C0LawError("Source.play requires an explicit mechanism, not null")
    play = compile_play(
        source.get("play"),
        source["actors"],
        table,
        time,
        contexts,
        projections=projections,
        abilities=abilities,
        formed_sorts=tuple(
            {
                sort
                for plan in [*abilities, *temporal_roots, *reactions]
                for sort in formation_sorts(plan, kind="person")
            }
        ),
    )
    from .report_collections import compile_report_collections

    report_collections = compile_report_collections(lib, source, table, channels, source_context)
    return AuthorProgram(
        source["name"],
        table,
        entities,
        tuple(sorted(source["actors"].items())),
        tuple(sorted(source["objects"])),
        tuple(abilities),
        contexts,
        tuple(projections),
        tuple(information),
        tuple(processes),
        terminal,
        reactions,
        settlements,
        activities,
        time,
        periodic,
        random,
        actor_sorts,
        play,
        pure,
        opening=opening,
        report_collections=report_collections,
    )
