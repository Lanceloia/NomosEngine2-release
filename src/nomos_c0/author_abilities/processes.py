"""Typed authored decision graphs sharing the ordinary input/effect compiler."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .effects import EffectCompiler
from .expression_syntax import _identifier
from .inputs import compile_inputs
from .local_views import LocalViewPlan, compile_local_views
from .opening import ParameterValue, value_node
from .process_graph import process_graph
from .stages import compile_stage
from .windows import compile_window


@dataclass(frozen=True)
class Capture:
    name: str
    type_name: str
    chooser: str | None


@dataclass(frozen=True)
class ProcessNode:
    process: str
    point: str
    prompt: str
    prefix: tuple[Capture, ...]
    inputs: tuple[Capture, ...]
    completion: object | None = None
    window: object | None = None
    resets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessPlan:
    name: str
    definition: str
    initiator: str
    nodes: tuple
    fingerprint: str
    stage: object | None = None

    def node(self, point):
        return next(plan for plan in self.nodes if plan.process.point == point)


def compile_process(
    name,
    definition,
    declaration,
    selected,
    table,
    entities,
    pure,
    symbols,
    actors,
    channels,
    disclosures,
    world_name,
    context,
):
    from .frontend import row
    from .program import AbilityPlan

    path = "processes." + definition
    row(selected, {"definition"}, {"with", "views"}, path="use." + name)
    row(
        declaration,
        {"actor", "where", "results", "instances", "begin", "decisions"},
        {"parameters", "inputs", "views", "stage"},
        path=path,
    )
    if declaration["instances"] != "one_pending_per_initiator":
        raise C0LawError(f"UnsupportedFeature: {path}.instances: unknown instance policy")
    actor = declaration["actor"]
    if not isinstance(actor, Mapping) or len(actor) != 1:
        raise C0LawError(f"{path}: exactly one named actor parameter required")
    initiator, actor_type = next(iter(actor.items()))
    schemas = dict(entities.entities)
    if not _identifier(initiator) or actor_type not in dict(table.definitions):
        raise C0LawError(f"{path}: invalid actor binding")
    actor_plan = table[actor_type]
    if actor_plan.kind != "ref" or schemas[actor_plan.sort].kind != "person":
        raise C0LawError(f"{path}: actor must be a Person reference")
    parameters, supplied = declaration.get("parameters", {}), selected.get("with", {})
    if (
        not isinstance(parameters, Mapping)
        or not isinstance(supplied, Mapping)
        or set(parameters) != set(supplied)
    ):
        raise C0LawError(f"use.{name}: exact process parameter bindings required")
    bound = []
    for symbol, kind in parameters.items():
        if not _identifier(symbol) or symbol == initiator or kind not in dict(table.definitions):
            raise C0LawError(f"{path}: invalid process parameter")
        bound.append(
            ParameterValue(symbol, kind, value_node(table, table[kind], supplied[symbol], symbols))
        )
    result_type = declaration["results"]
    if type(result_type) is not str or result_type not in dict(table.definitions):
        raise C0LawError(f"{path}: named result type required")
    nodes, order, parents, dominators, resets = process_graph(declaration, path)
    entry_base = {initiator: actor_type, **parameters}
    external_views = compile_local_views(
        declaration.get("views", {}),
        selected.get("views", {}),
        table,
        pure,
        entities,
        {*entry_base, *declaration.get("inputs", {})},
        channels,
    )
    plans, outgoing, slots, slot_definitions = {}, {}, {}, {}
    stage = None
    for point in order:
        node = nodes[point]
        node_path = path + (".begin" if point == "begin" else ".decisions." + point)
        if point == "begin":
            row(node, {"resolve"}, {"cost", "time_cost"}, path=node_path)
            prefix = ()
            chooser = initiator
            base = entry_base
            local_base = base
            views = external_views
            inputs_row = declaration.get("inputs", {})
            where_row = declaration["where"]
            prompt = ""
        else:
            row(
                node,
                {"actor", "prompt", "where", "resolve"},
                {"inputs", "views", "cost", "window", "time_cost"},
                path=node_path,
            )
            inherited = [outgoing[p] for p in parents[point]]
            common = set.intersection(*(set(values) for values in inherited))
            if any(len({values[key] for values in inherited}) != 1 for key in common):
                raise C0LawError(f"{node_path}: inconsistent predecessor bindings")
            prefix = tuple(inherited[0][key] for key in sorted(common))
            base = {capture.name: capture.type_name for capture in prefix}
            chooser = node["actor"]
            if "window" in node:
                if not isinstance(chooser, Mapping) or len(chooser) != 1:
                    raise C0LawError(f"{node_path}.actor: one named window chooser type required")
                chooser, chooser_type = next(iter(chooser.items()))
                if (
                    not _identifier(chooser)
                    or chooser in base
                    or chooser_type not in dict(table.definitions)
                ):
                    raise C0LawError(f"{node_path}.actor: fresh typed window chooser required")
                base = {**base, chooser: chooser_type}
            if (
                type(chooser) is not str
                or chooser not in base
                or table[base[chooser]].kind != "ref"
                or schemas[table[base[chooser]].sort].kind != "person"
            ):
                raise C0LawError(f"{node_path}.actor: captured Person chooser required")
            if schemas[table[base[chooser]].sort].reference != "public":
                raise C0LawError(
                    f"UnsupportedFeature: {node_path}.actor: public captured chooser required"
                )

            def locally_available(capture):
                kind = table[capture.type_name]
                return (
                    capture.chooser is None
                    or capture.chooser == chooser
                    or (kind.kind == "ref" and schemas[kind.sort].reference == "public")
                )

            local_base = {c.name: c.type_name for c in prefix if locally_available(c)}
            if "window" in node:
                local_base[chooser] = base[chooser]
            inputs_row = node.get("inputs", {})
            views = list(
                compile_local_views(
                    declaration.get("views", {}),
                    selected.get("views", {}),
                    table,
                    pure,
                    entities,
                    {*base, *inputs_row},
                    channels,
                )
            )
            view_rows = node.get("views", {})
            if not isinstance(view_rows, Mapping):
                raise C0LawError(f"{node_path}.views: named local receipt bindings required")
            for alias, view in view_rows.items():
                if alias in dict(views):
                    raise C0LawError(f"{node_path}.views.{alias}: duplicate process view alias")
                row(view, {"reports", "from"}, path=node_path + ".views." + str(alias))
                parts = view["from"].split(".") if type(view["from"]) is str else []
                if (
                    len(parts) != 2
                    or parts[0] not in dominators[point]
                    or tuple(parts) not in slots
                ):
                    raise C0LawError(f"{node_path}.views.{alias}: non-ancestor or unknown receipt")
                source_point, label = parts
                channel = f"{name}.{source_point}.{label}"
                signature = (
                    slots[tuple(parts)],
                    plans[source_point].source,
                    label,
                )
                checked = compile_local_views(
                    {alias: {"reports": view["reports"]}},
                    {alias: channel},
                    table,
                    pure,
                    entities,
                    {*base, *inputs_row},
                    {("reports", channel): signature},
                )[0][1]
                views.append(
                    (
                        alias,
                        LocalViewPlan(
                            checked.kind,
                            checked.type_name,
                            checked.channel,
                            checked.source,
                            checked.slot,
                            source_point,
                        ),
                    )
                )
            views = tuple(views)
            prompt = node["prompt"]
            if type(prompt) is not str or not prompt.strip():
                raise C0LawError(f"{node_path}.prompt: static public prompt required")
            where_row = node["where"]
        if not any(table.accepts_sort(table[base[chooser]].sort, sort) for sort in actors):
            raise C0LawError(f"{node_path}: chooser sort is not selected")
        inputs = compile_inputs(
            table,
            inputs_row,
            local_base,
            library=pure,
            entities=entities,
            actor=chooser,
            path=node_path + ".inputs",
            context=context,
            local_views=views,
        )
        if set(inputs_row) & set(base):
            raise C0LawError(f"{node_path}: input shadows a captured binding")
        current = tuple(Capture(item.name, item.type_name, chooser) for item in inputs.inputs)
        all_bindings = {**base, **{c.name: c.type_name for c in current}}
        local_bindings = {**local_base, **{c.name: c.type_name for c in current}}
        if point == "begin":
            if "stage" in declaration and declaration["stage"] is None:
                raise C0LawError(f"{path}.stage: explicit stage requires a declaration")
            stage = compile_stage(
                declaration.get("stage"), all_bindings, table, entities, initiator, path + ".stage"
            )
        compiler = EffectCompiler(
            table,
            all_bindings,
            library=pure,
            entities=entities,
            actor=chooser,
            path=node_path,
            context=context,
            local_views=views,
            disclosures=disclosures,
            actor_bindings=local_bindings,
            successors={*nodes, "finish"} - {"begin"},
        )
        where = compiler.expression(where_row, "Bool", node_path + ".where", context="actor")
        costs = compiler.fields(node.get("cost", []), costs=True)
        from .scheduling import positive_time_cost

        time_cost = positive_time_cost(compiler, node.get("time_cost"), node_path + ".time_cost")
        resolution = compiler.resolution(node["resolve"], result_type)
        window = None
        if "window" in node:
            window = compile_window(
                node["window"],
                {c.name: c.type_name for c in prefix},
                base[chooser],
                table,
                entities,
                {leaf.next_point for leaf in resolution.leaves()},
                node_path + ".window",
            )
        if stage is not None and (
            (window.participants if window is not None else chooser) not in stage.actors
        ):
            raise C0LawError(f"{node_path}.actor: stage chooser must be a declared participant")
        completion = None
        if stage is not None and any(leaf.next_point == "finish" for leaf in resolution.leaves()):
            boundary_compiler = EffectCompiler(
                table,
                all_bindings,
                library=pure,
                entities=entities,
                actor=chooser,
                path=node_path,
                context=context,
                actor_bindings=local_bindings,
            )
            completion = boundary_compiler.expression(
                declaration["stage"]["complete_when"],
                "Bool",
                node_path + ".stage.complete_when",
                context="actor",
            )
        for leaf in resolution.leaves():
            for call in leaf.deliveries:
                key = (point, call.label)
                if key in slot_definitions and slot_definitions[key] != call.definition:
                    raise C0LawError(
                        f"{node_path}: delivery label changes its disclosure definition"
                    )
                slots[key] = call.definition.value.result.name
                slot_definitions[key] = call.definition
        metadata = ProcessNode(
            name, point, prompt, prefix, current, completion, window, resets[point]
        )
        summary = compiler.summary(costs, resolution)
        if completion is not None:
            summary = replace(summary, expressions=(*summary.expressions, completion))
        plans[point] = AbilityPlan(
            name if point == "begin" else f"{name}.{point}",
            definition,
            chooser,
            base[chooser],
            tuple(bound) if point == "begin" else (),
            inputs,
            where,
            costs,
            resolution,
            summary,
            f"author.{world_name}.{name}.{point}.action",
            views,
            metadata,
            time_cost=time_cost,
        )
        initial = (
            {
                initiator: Capture(initiator, actor_type, initiator),
                **{key: Capture(key, kind, None) for key, kind in parameters.items()},
            }
            if point == "begin"
            else {c.name: c for c in prefix}
        )
        outgoing[point] = (
            initial if window is not None else {**initial, **{c.name: c for c in current}}
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            [world_name, name, declaration, selected, entities.fingerprint],
            sort_keys=True,
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return ProcessPlan(
        name, definition, initiator, tuple(plans[point] for point in order), fingerprint, stage
    )
