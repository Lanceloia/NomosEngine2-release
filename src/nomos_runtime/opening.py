"""Initialize declared individual fields before assertions, reports and cognition."""

from dataclasses import dataclass
from types import MappingProxyType

from .expressions import ValueBudget
from .randomness import RandomCursor, RandomKey


@dataclass(frozen=True)
class OpeningDeal:
    name: str
    context: str
    deal: str
    to: str
    sort: str
    field: str
    stream: str


@dataclass(frozen=True)
class OpeningDealRecord:
    source: str
    field: str
    targets: tuple
    values: tuple
    stream: str
    random_before: object
    random_after: object
    draws: tuple


@dataclass(frozen=True)
class EntityInitialRecord:
    source: str
    target: object
    field: str
    value: object


def supplied_fields(program, references, sort):
    return {plan.field for plan in program.opening if references.accepts(plan.sort, sort)}


def initialize(session):
    before = session._states
    states, changes, written, records = dict(before), {}, set(), []
    cursor = RandomCursor(before, changes)
    for plan in session.program.opening:
        parameters = session._contexts[plan.context]
        cards, targets = parameters[plan.deal], parameters[plan.to]
        if len(cards) != len(targets) or len(targets) != len(set(targets)):
            raise ValueError(
                "opening deal requires equal card/recipient counts and unique recipients"
            )
        for target in targets:
            if target not in session.references.references or not session.references.accepts(
                plan.sort, target.sort
            ):
                raise ValueError("opening deal recipient is outside its declared sort")
            cell = (target, plan.field)
            if cell in written or plan.field in before[target]:
                raise ValueError(
                    "opening deal conflicts with another deal or an explicit Assets field"
                )
            written.add(cell)
        key = RandomKey(plan.stream)
        previous = changes.get((key, "state"), before[key]["state"])
        start = len(cursor.draws)
        source = "author." + session.program.name + ".opening." + plan.name
        values = cursor.shuffle(source, cards, plan.stream)
        for target, value in zip(targets, values, strict=True):
            kind = dict(session.program.schemas[target.sort].fields)[plan.field]
            checked = session.program.validators[kind](
                value, ValueBudget(session.limits.value, session.references), ()
            )
            states[target] = MappingProxyType({**states[target], plan.field: checked})
        records.append(
            OpeningDealRecord(
                source,
                plan.field,
                targets,
                values,
                plan.stream,
                previous,
                changes.get((key, "state"), previous),
                tuple(cursor.draws[start:]),
            )
        )
    for reference in session.references.references:
        if set(states[reference]) != set(dict(session.program.schemas[reference.sort].fields)):
            raise ValueError("opening deal left entity fields uninitialized")
    for (key, field), value in changes.items():
        states[key] = MappingProxyType({**states[key], field: value})
    session._states = MappingProxyType(states)
    session._opening_deals = tuple(records)
