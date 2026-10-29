"""Checked periodic Event schedules and author duration constants."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .activities import local_dependencies
from .context_state import context_types, selected_context
from .effects import EffectCompiler
from .expression_syntax import _identifier
from .fixed_values import evaluate_fixed
from .opening import ParameterValue, value_node
from .reactions import ReactionPlan


@dataclass(frozen=True)
class PeriodicPlan:
    event: ReactionPlan
    interval: int
    first_after: int
    key: str


def compile_periodic(
    selected, table, entities, pure, symbols, disclosures, world_name, context, contexts
):
    from .frontend import row

    result = []
    for name, (definition, declaration, binding) in selected.items():
        path = "periodic." + definition
        row(binding, {"definition"}, {"with", "context"}, path="use." + name)
        row(
            declaration,
            {"interval", "results", "resolve"},
            {"parameters", "context", "first_after"},
            path=path,
        )
        parameters = declaration.get("parameters", {})
        supplied = binding.get("with", {})
        if (
            type(parameters) is not dict
            or type(supplied) is not dict
            or set(parameters) != set(supplied)
        ):
            raise C0LawError(path + ": exact named parameter bindings required")
        bound = []
        for key, kind in parameters.items():
            if not _identifier(key) or type(kind) is not str or kind not in dict(table.definitions):
                raise C0LawError(path + ".parameters: invalid parameter name/type")
            try:
                node = value_node(table, table[kind], supplied[key], symbols)
            except ValueError as error:
                raise C0LawError(f"use.{name}.with.{key}: {error}") from None
            bound.append(ParameterValue(key, kind, node))
        shared = selected_context(declaration, binding, contexts)
        bindings = dict(parameters)
        shared_types = {} if shared is None else context_types(shared)
        if set(shared_types) & set(bindings):
            raise C0LawError(path + ": context conflicts with fixed parameters")
        compiler = EffectCompiler(
            table,
            bindings | shared_types,
            library=pure,
            entities=entities,
            actor=None,
            path=path,
            context=context,
            disclosures=disclosures,
            shared_context=shared,
        )

        def duration(text, label):
            expression = local_dependencies(compiler.expression(text, None, path + "." + label))
            kind = expression.node.value_type
            if (
                kind.kind != "int"
                or kind.minimum is None
                or kind.minimum < 1
                or expression.summary.owner_reads
                or expression.summary.reference_domains
                or any(key not in parameters for key, _ in expression.inputs)
            ):
                raise C0LawError(path + "." + label + ": positive fixed duration required")
            try:
                value = evaluate_fixed(expression, bound, symbols).value
            except ValueError as error:
                raise C0LawError(path + "." + label + ": " + str(error)) from None
            if type(value) is not int or value < 1:
                raise C0LawError(path + "." + label + ": positive fixed duration required")
            return value

        interval = duration(declaration["interval"], "interval")
        first_after = duration(
            declaration.get("first_after", declaration["interval"]), "first_after"
        )
        outcome = declaration["results"]
        if type(outcome) is not str or outcome not in dict(table.definitions):
            raise C0LawError(path + ".results: named result type required")
        event = ReactionPlan(
            name,
            definition,
            (),
            (),
            tuple(bound),
            compiler.expression("True", "Bool", path + ".when"),
            compiler.resolution(declaration["resolve"], outcome),
            f"author.{world_name}.{name}.event",
            shared,
        )
        result.append(
            PeriodicPlan(
                event,
                interval,
                first_after,
                f"author.{world_name}.{name}.periodic",
            )
        )
    return tuple(result)
