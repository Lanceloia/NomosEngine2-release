"""Authored self-state schedules and admitted local Action time costs."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .activities import local_dependencies
from .effects import EffectCompiler
from .expressions import compile_value_expression
from .fixed_values import evaluate_fixed
from .opening import ParameterValue, value_node


def positive_time_cost(compiler, text, path):
    if text is None:
        return None
    expression = local_dependencies(compiler.expression(text, None, path, context="actor"))
    kind = expression.node.value_type
    if kind.kind != "int" or kind.minimum is None or kind.minimum < 1:
        raise C0LawError(path + ": statically positive integer time cost required")
    return expression


def contains_reference(kind):
    if kind.kind == "ref":
        return True
    return any(contains_reference(child) for _, child in (*kind.fields, *kind.cases)) or (
        kind.element is not None and contains_reference(kind.element)
    )


@dataclass(frozen=True)
class SchedulePlan:
    family: str
    definition: str
    actor: str
    actor_type: str
    parameters: tuple
    speed: object
    eligible: object
    initial: int
    priority: int


def compile_schedules(
    declaration, definitions, abilities, activities, table, entities, pure, symbols, actors, context
):
    from .frontend import row

    if type(definitions) is not dict:
        raise C0LawError("Lib.schedules needs named definitions")
    if declaration is None:
        return ()
    row(declaration, {"actors", "wait"}, path="Source.time.scheduling")
    if (
        declaration["wait"] != "next_world_change"
        or type(declaration["actors"]) is not dict
        or set(declaration["actors"]) != set(actors)
    ):
        raise C0LawError(
            "scheduling needs every selected Actor sort and explicit next_world_change wait"
        )
    if type(definitions) is not dict:
        raise C0LawError("Lib.schedules needs named definitions")
    result = []
    for family, binding in declaration["actors"].items():
        row(binding, {"definition"}, {"with", "priority"}, path="Source.time.scheduling." + family)
        priority = binding.get("priority", 0)
        if type(priority) is not int or priority < 0:
            raise C0LawError("schedule priority must be a nonnegative integer")
        name = binding["definition"]
        if type(name) is not str or name not in definitions:
            raise C0LawError("scheduling selects an unknown definition")
        definition = definitions[name]
        path = "schedules." + name
        row(definition, {"actor", "speed", "eligible", "initial"}, {"parameters"}, path=path)
        if type(definition["actor"]) is not dict or len(definition["actor"]) != 1:
            raise C0LawError(path + ": one named Actor Ref required")
        actor, kind = next(iter(definition["actor"].items()))
        if (
            type(kind) is not str
            or kind not in dict(table.definitions)
            or table[kind].kind != "ref"
            or not table.accepts_sort(table[kind].sort, family)
        ):
            raise C0LawError(path + ": schedule Actor type does not accept the selected sort")
        parameters = definition.get("parameters", {})
        supplied = binding.get("with", {})
        if (
            type(parameters) is not dict
            or type(supplied) is not dict
            or set(parameters) != set(supplied)
            or actor in parameters
        ):
            raise C0LawError(path + ": exact disjoint fixed parameters required")
        bound = []
        for key, type_name in parameters.items():
            if (
                type(type_name) is not str
                or type_name not in dict(table.definitions)
                or contains_reference(table[type_name])
            ):
                raise C0LawError(
                    path + ": schedule configuration must be fixed data without entity refs"
                )
            try:
                bound.append(
                    ParameterValue(
                        key, type_name, value_node(table, table[type_name], supplied[key], symbols)
                    )
                )
            except ValueError as error:
                raise C0LawError(path + ": " + str(error)) from None
        compiler = EffectCompiler(
            table,
            {actor: kind, **parameters},
            library=pure,
            entities=entities,
            actor=actor,
            path=path,
            context=context,
        )
        speed = local_dependencies(
            compiler.expression(definition["speed"], None, path + ".speed", context="actor")
        )
        if (
            speed.node.value_type.kind != "int"
            or speed.node.value_type.minimum is None
            or speed.node.value_type.minimum < 0
        ):
            raise C0LawError(path + ".speed: statically nonnegative integer speed required")
        eligible = local_dependencies(
            compiler.expression(definition["eligible"], "Bool", path + ".eligible", context="actor")
        )
        for expression in (speed, eligible):
            if (
                expression is None
                or expression.summary.reference_domains
                or any(
                    read.selector is None or read.selector.root != actor or read.selector.steps
                    for read in expression.summary.owner_reads
                )
            ):
                raise C0LawError(
                    path + ": scheduling may read only its own Actor fields and fixed data"
                )
        initial_expr = compile_value_expression(
            definition["initial"],
            table,
            parameters,
            returns=None,
            library=pure,
            entities=entities,
            context="world",
            path=path + ".initial",
        )
        initial_kind = initial_expr.node.value_type
        if (
            initial_kind.kind != "int"
            or initial_kind.minimum is None
            or initial_kind.minimum < 1
            or actor in dict(initial_expr.inputs)
        ):
            raise C0LawError(path + ".initial: positive fixed action value required")
        initial = evaluate_fixed(initial_expr, bound, symbols).value
        result.append(
            SchedulePlan(
                family, name, actor, kind, tuple(bound), speed, eligible, initial, priority
            )
        )
    actions = (*abilities, *(p.cancellation for p in activities if p.cancellation is not None))
    if any(p.time_cost is None for p in actions):
        raise C0LawError(
            "each scheduled Action, process step and cancellation needs explicit time_cost"
        )
    return tuple(result)
