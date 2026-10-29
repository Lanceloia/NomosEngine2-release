"""Normalize acquired structured counts and call the pure local propagator."""

from dataclasses import dataclass, replace

from .analysis import Preparation, PreparationBudget, budget_error, collect, select
from .cognition import holder
from .expressions import ExpressionError, ValueBindingError


@dataclass(frozen=True)
class LocalDefinition:
    inputs: tuple
    universe: str
    normalize: object
    categories: object
    period: str
    assumptions: tuple
    relation: object
    limits: object


def analyze(definition, model, session, codec, actor, receipts):
    from nomos_cognition.local import Context, Query, propagate
    from nomos_cognition.local_analysis import LocalAnalysis, LocalBound

    context = Context(
        (actor.scope, holder(actor)), definition.period, definition.assumptions, definition.relation
    )
    selection = select(definition.inputs, actor, receipts)
    selected, grounds, cutoff = (), (), selection.cutoff
    meter = Preparation(definition.limits.work)

    def outcome(status, bounds=(), work=None, reason=None, conflict=()):
        return LocalAnalysis(
            model,
            context,
            cutoff,
            grounds,
            status,
            bounds,
            meter.work if work is None else work,
            reason,
            conflict,
        )

    try:
        if sum(len(reports) for _, reports in selection.rows) > definition.limits.inputs:
            return outcome("pending", reason="input_budget")
        acquired = collect(selection, actor, codec, meter)
        grounds = tuple(v.ground for v in acquired)
        if selection.missing:
            return outcome("pending", reason="missing_inputs")
        normalized = []
        for value in acquired:
            meter.spend()
            value = definition.normalize(session, codec, actor, value, context)
            meter.spend(
                len(value.members)
                + len(value.labels if hasattr(value, "labels") else value.matching)
            )
            normalized.append(value)
        selected = tuple(normalized)
        universe = tuple(v for v in selected if v.ground.input == definition.universe)
        if len(universe) != 1:
            raise ValueError("local universe needs one actual opening guarantee")
        universe = universe[0].members
        if len(universe) > definition.limits.subjects or len(selected) > definition.limits.inputs:
            return outcome("pending", reason="input_budget")
        categories = definition.categories(session, codec, actor)
        if len({key for key, _ in categories}) != len(categories):
            raise ValueError("local category keys must be distinct")
        groups = tuple(
            dict.fromkeys((universe, *((p,) for p in universe), *(v.members for v in selected)))
        )
        meter.spend(len(groups) * len(categories) + 1)
        queries = tuple(Query(group, labels) for group in groups for _, labels in categories)
        remaining = definition.limits.work - meter.work
        if remaining < 1:
            raise PreparationBudget
        if session._local_calculation is None:
            from .local_calculation import LocalCalculation

            session._local_calculation = LocalCalculation()
        result = session._local_calculation.run(
            propagate,
            context,
            universe,
            selected,
            queries,
            limits=replace(definition.limits, work=remaining),
        )
        work = meter.work + result.work
        if result.status != "complete":
            return outcome(result.status, work=work, reason=result.reason, conflict=result.conflict)
        bounds = []
        values = iter(result.bounds_for(queries))
        for group in groups:
            for key, labels in categories:
                value = next(values)
                bounds.append(
                    LocalBound(
                        value.members,
                        key,
                        value.minimum,
                        value.maximum,
                        value.lower_grounds,
                        value.upper_grounds,
                    )
                )
        return outcome("complete", tuple(bounds), work)
    except PreparationBudget:
        return outcome("pending", reason="preparation_budget")
    except (ExpressionError, ValueBindingError) as error:
        if not budget_error(error):
            raise
        return outcome("pending", reason=error.diagnostic.code)
