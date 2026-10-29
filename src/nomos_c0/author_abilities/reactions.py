"""Check automatic Event declarations, captured inputs and actual source dependencies."""

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .context_state import context_types, selected_context
from .effects import EffectCompiler
from .expression_syntax import _identifier
from .formation import FormedSelector, formation_sorts
from .opening import ParameterValue, value_node


@dataclass(frozen=True)
class ReactionPlan:
    name: str
    definition: str
    triggers: tuple[str, ...]
    captures: tuple
    parameters: tuple
    when: object
    resolution: object
    source: str
    context: object | None = None

    @property
    def channel_name(self):
        return self.name


def signature(plan):
    if type(plan) is ReactionPlan:
        parameters = {name: kind for name, _, kind in plan.captures}
        parameters.update((p.name, p.type_name) for p in plan.parameters)
    else:
        parameters = dict(plan.occurrence_parameters)
    if "result" in parameters:
        raise C0LawError("Reaction trigger parameter 'result' conflicts with the result selector")
    return {**parameters, "result": plan.resolution.leaves()[0].result.result.name}


def common_capture_type(table, names, path):
    kinds = tuple(table[name] for name in names)
    if all(kind.type_id == kinds[0].type_id for kind in kinds):
        return names[0]
    if all(kind.kind == "ref" for kind in kinds):
        parents = tuple(
            sort.name
            for sort in table.sorts
            if all(table.accepts_sort(sort.name, kind.sort) for kind in kinds)
        )
        nearest = tuple(
            parent
            for parent in parents
            if all(table.accepts_sort(other, parent) for other in parents)
        )
        if len(nearest) == 1:
            return table.reference(nearest[0]).name
    raise C0LawError(f"{path}.on.bind: captured types differ without a unique nominal Ref parent")


def compile_reactions(
    selected,
    abilities,
    table,
    entities,
    pure,
    symbols,
    disclosures,
    world_name,
    context=None,
    contexts=(),
    category="reactions",
):
    from .frontend import row

    known = {plan.name: plan for plan in abilities}
    pending = dict(selected)
    result = []
    while pending:
        progressed = False
        for name, (definition, declaration, binding) in tuple(pending.items()):
            path = category + "." + definition
            row(binding, {"definition", "after"}, {"with", "context"}, path="use." + name)
            row(
                declaration,
                {"on", "when", "results", "resolve"},
                {"parameters", "context"},
                path=path,
            )
            row(declaration["on"], {"definition", "bind"}, path=path + ".on")
            parents = binding["after"]
            parents = [parents] if type(parents) is str else parents
            allowed = declaration["on"]["definition"]
            allowed = [allowed] if type(allowed) is str else allowed
            if (
                type(parents) is not list
                or not parents
                or any(type(parent) is not str for parent in parents)
                or len(parents) != len(set(parents))
                or type(allowed) is not list
                or not allowed
                or any(type(item) is not str for item in allowed)
                or len(allowed) != len(set(allowed))
            ):
                raise C0LawError(f"{path}.on/use.{name}.after: finite unique source names required")
            if any(parent not in known for parent in parents):
                if any(parent not in known and parent not in pending for parent in parents):
                    raise C0LawError(f"use.{name}.after: unknown selected occurrence source")
                continue
            triggers = tuple(known[parent] for parent in parents)
            if any(trigger.definition not in allowed for trigger in triggers):
                raise C0LawError(
                    f"{path}.on: selected source does not implement trigger definition"
                )
            parameters = declaration.get("parameters", {})
            supplied = binding.get("with", {})
            captures = declaration["on"]["bind"]
            if (
                not isinstance(parameters, Mapping)
                or not isinstance(supplied, Mapping)
                or set(parameters) != set(supplied)
                or not isinstance(captures, Mapping)
                or set(captures) & set(parameters)
            ):
                raise C0LawError(f"{path}: exact disjoint captured and fixed parameters required")
            interfaces = tuple(signature(trigger) for trigger in triggers)
            captured = []
            for local, remote in captures.items():
                if isinstance(remote, Mapping):
                    schemas = dict(entities.entities)
                    sort = remote.get("formed")
                    if (
                        not _identifier(local)
                        or set(remote) != {"formed"}
                        or type(sort) is not str
                        or sort not in schemas
                        or any(
                            not any(
                                table.accepts_sort(sort, actual)
                                for actual in formation_sorts(trigger, kind=schemas[sort].kind)
                            )
                            for trigger in triggers
                        )
                    ):
                        raise C0LawError(
                            path
                            + ".on.bind: formed capture requires a declared producer entity type"
                        )
                    captured.append(
                        (
                            local,
                            FormedSelector(sort),
                            table.collection(table.reference(sort).name).name,
                        )
                    )
                    continue
                if (
                    not _identifier(local)
                    or type(remote) is not str
                    or any(remote not in interface for interface in interfaces)
                ):
                    raise C0LawError(f"{path}.on.bind: unknown trigger parameter or result")
                kind = common_capture_type(table, tuple(i[remote] for i in interfaces), path)
                captured.append((local, remote, kind))
            bound = []
            for key, kind in parameters.items():
                if (
                    not _identifier(key)
                    or type(kind) is not str
                    or kind not in dict(table.definitions)
                ):
                    raise C0LawError(f"{path}.parameters: invalid named parameter type")
                try:
                    node = value_node(table, table[kind], supplied[key], symbols)
                except ValueError as error:
                    raise C0LawError(f"use.{name}.with.{key}: {error}") from None
                bound.append(ParameterValue(key, kind, node))
            bindings = {local: kind for local, _, kind in captured} | dict(parameters)
            shared = selected_context(declaration, binding, contexts)
            shared_types = {} if shared is None else context_types(shared)
            if set(shared_types) & set(bindings):
                raise C0LawError(f"{path}: context conflicts with captured or fixed parameters")
            bindings.update(shared_types)
            compiler = EffectCompiler(
                table,
                bindings,
                library=pure,
                entities=entities,
                actor=None,
                path=path,
                context=context,
                disclosures=disclosures,
                shared_context=shared,
            )
            outcome = declaration["results"]
            if type(outcome) is not str or outcome not in dict(table.definitions):
                raise C0LawError(f"{path}.results: named result type required")
            plan = ReactionPlan(
                name,
                definition,
                tuple(trigger.source for trigger in triggers),
                tuple(captured),
                tuple(bound),
                compiler.expression(declaration["when"], "Bool", path + ".when"),
                compiler.resolution(declaration["resolve"], outcome),
                f"author.{world_name}.{name}.event",
                shared,
            )
            known[name] = plan
            result.append(plan)
            del pending[name]
            progressed = True
        if not progressed:
            raise C0LawError("ReactionCycle: selected automatic subscriptions form a cycle")
    return tuple(result)
