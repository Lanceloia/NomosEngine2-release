"""Compile activity lifecycles, due completions and cancellation declarations."""

from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .context_state import context_types
from .effects import EffectCompiler
from .reactions import (
    ReactionPlan,
    compile_reactions,
)


def local_dependencies(expression):
    """World captures are not local inputs merely because they share a lexical scope."""
    names = {read.root for read in expression.summary.reads}
    if expression.actor is not None:
        names.add(expression.actor)
    return replace(expression, inputs=tuple(pair for pair in expression.inputs if pair[0] in names))


def local_deliveries(resolution):
    return replace(
        resolution,
        deliveries=tuple(
            replace(
                call,
                arguments=tuple(local_dependencies(arg) for arg in call.arguments),
                pool=None if call.pool is None else local_dependencies(call.pool),
            )
            for call in resolution.deliveries
        ),
        then=None if resolution.then is None else local_deliveries(resolution.then),
        otherwise=None if resolution.otherwise is None else local_deliveries(resolution.otherwise),
    )


@dataclass(frozen=True)
class CancellationPlan:
    name: str
    definition: str
    source: str
    actor: str
    actor_type: str
    where: object
    costs: tuple
    resolution: object
    occurrence_parameters: tuple
    parameters: tuple
    context: object | None
    time_cost: object | None = None

    @property
    def channel_name(self):
        return self.name


@dataclass(frozen=True)
class ActivityPlan:
    completion: ReactionPlan
    actor: str
    duration: object
    cancellation: CancellationPlan | None


@dataclass(frozen=True)
class TimePlan:
    order: tuple[str, ...]
    schedules: tuple = ()


def compile_time(declaration, activities, periodic, scheduling):
    from .frontend import row

    if declaration is None:
        if activities or periodic:
            raise C0LawError("activities/periodic require an explicitly selected time mechanism")
        return None
    row(declaration, {"mechanism", "due_order"}, {"scheduling"}, path="Source.time")
    names = tuple(p.completion.name for p in activities) + tuple(p.event.name for p in periodic)
    order = declaration["due_order"]
    if (
        declaration["mechanism"] != "event_jump"
        or type(order) is not list
        or any(type(name) is not str for name in order)
        or len(order) != len(set(order))
        or set(order) != set(names)
    ):
        raise C0LawError("Source.time needs event_jump and each selected due source exactly once")
    return TimePlan(tuple(order), scheduling)


def compile_activities(
    selected, abilities, table, entities, pure, symbols, disclosures, world_name, context, contexts
):
    from .frontend import row

    normalized = {}
    for name, (definition, declaration, binding) in selected.items():
        row(
            declaration,
            {"actor", "on", "duration", "results", "resolve"},
            {"parameters", "context", "cancel"},
            path="activities." + definition,
        )
        normalized[name] = (
            definition,
            {
                key: value
                for key, value in declaration.items()
                if key not in ("actor", "duration", "cancel")
            }
            | {"when": "True"},
            binding,
        )
    completions = compile_reactions(
        normalized,
        abilities,
        table,
        entities,
        pure,
        symbols,
        disclosures,
        world_name,
        context,
        contexts,
        category="activities",
    )
    starts = {plan.source: plan for plan in abilities}
    result = []
    for completion in completions:
        from .formation import FormedSelector

        if any(type(remote) is FormedSelector for _, remote, _ in completion.captures):
            raise C0LawError(
                "activities.on.bind cannot capture future formation identities at start"
            )
        _, declaration, _ = selected[completion.name]
        path = "activities." + completion.definition
        actor = declaration["actor"]
        captured = {local: (remote, kind) for local, remote, kind in completion.captures}
        if (
            type(actor) is not str
            or actor not in captured
            or any(trigger not in starts for trigger in completion.triggers)
            or any(captured[actor][0] != starts[trigger].actor for trigger in completion.triggers)
        ):
            raise C0LawError(path + ".actor must capture the actual starting Action controller")
        bindings = {local: kind for local, _, kind in completion.captures}
        bindings.update((p.name, p.type_name) for p in completion.parameters)
        actor_bindings = dict(bindings)
        actor_bindings.update(
            context_types(completion.context, local=True) if completion.context else {}
        )
        bindings.update(context_types(completion.context) if completion.context else {})
        compiler = EffectCompiler(
            table,
            bindings,
            library=pure,
            entities=entities,
            actor=actor,
            path=path,
            context=context,
            disclosures=disclosures,
            shared_context=completion.context,
            actor_bindings=actor_bindings,
        )
        duration = local_dependencies(
            compiler.expression(declaration["duration"], None, path + ".duration", context="actor")
        )
        kind = duration.node.value_type
        if kind.kind != "int" or kind.minimum is None or kind.minimum < 1:
            raise C0LawError(path + ".duration requires a statically positive integer range")
        cancellation = None
        if "cancel" in declaration:
            cancel = declaration["cancel"]
            row(
                cancel,
                {"where", "results", "resolve"},
                {"cost", "time_cost"},
                path=path + ".cancel",
            )
            outcome = cancel["results"]
            if type(outcome) is not str or outcome not in dict(table.definitions):
                raise C0LawError(path + ".cancel.results requires a named result type")
            cancellation = CancellationPlan(
                completion.name + ".cancel",
                completion.definition + ".cancel",
                completion.source.removesuffix(".event") + ".cancel.action",
                actor,
                captured[actor][1],
                local_dependencies(
                    compiler.expression(
                        cancel["where"], "Bool", path + ".cancel.where", context="actor"
                    )
                ),
                tuple(
                    replace(
                        cost,
                        target=local_dependencies(cost.target),
                        value=local_dependencies(cost.value),
                    )
                    for cost in compiler.fields(
                        cancel.get("cost", []), costs=True, path=path + ".cancel.cost"
                    )
                ),
                local_deliveries(
                    compiler.resolution(cancel["resolve"], outcome, path=path + ".cancel.resolve")
                ),
                tuple((local, kind) for local, _, kind in completion.captures)
                + tuple((p.name, p.type_name) for p in completion.parameters),
                completion.parameters,
                completion.context,
            )
            from .scheduling import positive_time_cost

            cancellation = replace(
                cancellation,
                time_cost=positive_time_cost(
                    compiler, cancel.get("time_cost"), path + ".cancel.time_cost"
                ),
            )
        result.append(ActivityPlan(completion, actor, duration, cancellation))
    return tuple(result)
