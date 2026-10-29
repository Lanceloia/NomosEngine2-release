"""Typed shared bindings and explicit current-world disclosure plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier
from .expressions import compile_value_expression
from .opening import ParameterValue, value_node


@dataclass(frozen=True)
class OpeningDomain:
    sort: str


@dataclass(frozen=True)
class ContextPlan:
    name: str
    definition: str
    parameters: tuple[ParameterValue, ...]
    assertion: object | None
    state: object | None = None
    world_parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionPlan:
    name: str
    definition: str
    context: ContextPlan
    viewer: str
    viewer_type: str
    audience: object
    value: object


def compile_contexts(
    table, entities, pure, declarations, selected, symbols, selected_sorts, *, context=None
):
    from .context_state import compile_context_state
    from .frontend import row

    if not isinstance(declarations, Mapping) or not isinstance(selected, Mapping):
        raise C0LawError("contexts require named declarations and bindings")
    definitions = {}
    for name, declaration in declarations.items():
        if not _identifier(name):
            raise C0LawError("context definition name is malformed")
        row(
            declaration,
            {"parameters"},
            {"require_opening", "state", "world_parameters"},
            path="contexts." + name,
        )
        local_parameters = declaration["parameters"]
        world_parameters = declaration.get("world_parameters", {})
        if not isinstance(local_parameters, Mapping) or not isinstance(world_parameters, Mapping):
            raise C0LawError("context parameters require named value types")
        if set(local_parameters) & set(world_parameters):
            raise C0LawError("context local/world parameter names must be disjoint")
        parameters = {**local_parameters, **world_parameters}
        for key, type_name in parameters.items():
            if (
                not _identifier(key)
                or type(type_name) is not str
                or type_name not in dict(table.definitions)
            ):
                raise C0LawError("context parameter name/type is malformed")
        if "state" in declaration and declaration["state"] is None:
            raise C0LawError("context state requires its explicit field schema")
        state = compile_context_state(name, declaration.get("state"), table, parameters)
        bindings = {
            **parameters,
            **({} if state is None else {key: kind.name for key, kind in state.fields}),
        }
        assertion = None
        if "require_opening" in declaration:
            assertion = compile_value_expression(
                declaration["require_opening"],
                table,
                bindings,
                returns="Bool",
                library=pure,
                context="world",
                entities=entities,
                path="contexts." + name + ".require_opening",
                span=None
                if context is None
                else context.locate("contexts." + name + ".require_opening"),
            )
        definitions[name] = (parameters, assertion, state, tuple(world_parameters))
    plans = []
    for name, binding in selected.items():
        if not _identifier(name):
            raise C0LawError("context instance name is malformed")
        row(binding, {"definition", "with"}, path="Source.contexts." + name)
        if type(binding["definition"]) is not str or binding["definition"] not in definitions:
            raise C0LawError("Source selects an unknown context")
        parameters, assertion, state, world_parameters = definitions[binding["definition"]]
        supplied = binding["with"]
        if not isinstance(supplied, Mapping) or set(supplied) != set(parameters):
            raise C0LawError("context needs exact named parameter bindings")
        bound = []
        for key, type_name in parameters.items():
            wire, value_type = supplied[key], table[type_name]
            if type(wire) is dict and set(wire) == {"opening_domain"}:
                sort = wire["opening_domain"]
                if (
                    type(sort) is not str
                    or sort not in dict(entities.entities)
                    or value_type.kind != "set"
                    or value_type.element.kind != "ref"
                    or not table.accepts_sort(value_type.element.sort, sort)
                    or not any(
                        table.accepts_sort(sort, selected_sort) for selected_sort in selected_sorts
                    )
                ):
                    raise C0LawError("opening_domain needs a compatible selected Set<Ref>")
                node = OpeningDomain(sort)
            else:
                node = value_node(table, value_type, wire, symbols)
            bound.append(ParameterValue(key, type_name, node))
        plans.append(
            ContextPlan(
                name, binding["definition"], tuple(bound), assertion, state, world_parameters
            )
        )
    return tuple(plans)


def compile_projection(
    name,
    definition,
    declaration,
    binding,
    contexts,
    table,
    entities,
    pure,
    actors,
    *,
    context=None,
    category="projections",
):
    from .frontend import row

    path = category + "." + definition
    row(declaration, {"viewer", "context", "audience", "returns", "value"}, path=path)
    row(binding, {"definition", "context"}, path="use." + name)
    plan = next((plan for plan in contexts if plan.name == binding["context"]), None)
    if plan is None or plan.definition != declaration["context"]:
        raise C0LawError("projection must bind its declared context")
    viewer = declaration["viewer"]
    if not isinstance(viewer, Mapping) or len(viewer) != 1:
        raise C0LawError("projection needs exactly one named viewer")
    viewer_name, type_name = next(iter(viewer.items()))
    if (
        not _identifier(viewer_name)
        or type(type_name) is not str
        or type_name not in dict(table.definitions)
    ):
        raise C0LawError("projection viewer name/type is malformed")
    viewer_type = table[type_name]
    if (
        viewer_type.kind != "ref"
        or dict(entities.entities)[viewer_type.sort].kind != "person"
        or not any(table.accepts_sort(viewer_type.sort, sort) for sort in actors)
    ):
        raise C0LawError("projection viewer requires a selected Person Ref")
    from .context_state import context_types

    parameters = context_types(plan)
    if viewer_name in parameters:
        raise C0LawError("projection viewer conflicts with a context parameter")
    inputs = {viewer_name: type_name, **parameters}

    def expression(field, result):
        compiled = compile_value_expression(
            declaration[field],
            table,
            inputs,
            returns=result,
            library=pure,
            context="world",
            entities=entities,
            actor=viewer_name,
            path=path + "." + field,
            span=None if context is None else context.locate(path + "." + field),
        )
        needed = {viewer_name, *(read.root for read in compiled.summary.reads)}
        return replace(compiled, inputs=tuple(p for p in compiled.inputs if p[0] in needed))

    return ProjectionPlan(
        name,
        definition,
        plan,
        viewer_name,
        type_name,
        expression("audience", "Bool"),
        expression("value", declaration["returns"]),
    )
