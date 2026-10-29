"""Cohort settlement of compiled reactions, with explicit ordered child closures."""

from dataclasses import dataclass
from types import MappingProxyType

from . import information, records
from .carrying import validate as validate_carrying
from .errors import SettlementDefect
from .records import Occurrence


@dataclass(frozen=True)
class OrderedStep:
    source: str
    required: bool


@dataclass(frozen=True)
class OrderedSettlement:
    trigger: str
    name: str
    steps: tuple


@dataclass
class _Cursor:
    trigger: object
    policy: OrderedSettlement | None
    index: int = 0
    previous: int | None = None

    @property
    def done(self):
        return self.index >= (1 if self.policy is None else len(self.policy.steps))


def _frame(program, frontier):
    return tuple(
        _Cursor(trigger, program.settlements.get(trigger.source))
        for trigger in frontier
        if trigger.source in program.settlements or program.subscriptions.get(trigger.source)
    )


def _apply_stage(session, before, planned):
    changes, states, receipts = set(), dict(before), []
    for _, row, draft in planned:
        if changes & draft.changes.keys():
            raise SettlementDefect("ordinary wave has overlapping actual field writes")
        changes.update(draft.changes)
        after = draft.after()
        receipts.extend(information.deliver(session, draft, row, before, after))
        for (reference, field), value in draft.changes.items():
            states[reference] = MappingProxyType({**states[reference], field: value})
        for key, value in after.items():
            if key not in before:
                if key in states:
                    raise SettlementDefect("ordinary wave has duplicate formed identities")
                states[key] = value
    states = MappingProxyType(states)
    validate_carrying(session.program, session.references.at(states), states)
    return states, tuple(receipts)


def settle_causality(session, root, states, receipts, allocation, *, offset, receipt_prefix):
    rows, receipts = [root], list(receipts)
    stack = [_frame(session.program, (root,))]
    while stack:
        frame = stack[-1]
        if all(cursor.done for cursor in frame):
            stack.pop()
            continue
        before, planned = states, []
        prior_receipts = receipt_prefix + tuple(receipts)
        for cursor in frame:
            if cursor.done:
                continue
            policy, trigger = cursor.policy, cursor.trigger
            basis, required = None, False
            if policy is None:
                reactions = session.program.subscriptions[trigger.source]
            else:
                step = policy.steps[cursor.index]
                required = step.required
                reactions = (session.program.reactions[step.source],)
                basis = records.OrderedBasis(policy.name, cursor.index + 1, cursor.previous)
            cursor.index += 1
            for reaction in reactions:
                occurrence = offset + len(rows) + len(planned) + 1
                draft, environment = reaction.execute(
                    session, before, trigger, prior_receipts, occurrence, allocation
                )
                if draft is None:
                    if required:
                        raise SettlementDefect("required ordered step did not activate")
                    continue
                draft.materialize()
                row = Occurrence(
                    occurrence,
                    "Event",
                    reaction.source,
                    tuple(environment.items()),
                    draft.result,
                    trigger.reference,
                    products=tuple(draft.formed),
                    draws=tuple(draft.random.draws),
                    order=basis,
                    at=root.at,
                )
                planned.append((cursor, row, draft))
        if not planned:
            continue
        states, issued = _apply_stage(session, before, planned)
        wave = tuple(row for _, row, _ in planned)
        rows.extend(wave)
        receipts.extend(issued)
        if len(rows) > session.limits.settlement_occurrences:
            raise SettlementDefect("single settlement occurrence budget exceeded")
        if (
            session.limits.occurrences is not None
            and offset + len(rows) > session.limits.occurrences
        ):
            raise SettlementDefect("occurrence capacity exceeded")
        for cursor, row, _ in planned:
            if cursor.policy is not None:
                cursor.previous = row.reference
        # A whole child closure completes before any cursor takes its next step.
        stack.append(_frame(session.program, wave))
    if len(rows) > session.limits.settlement_occurrences:
        raise SettlementDefect("single settlement occurrence budget exceeded")
    if session.limits.occurrences is not None and offset + len(rows) > session.limits.occurrences:
        raise SettlementDefect("occurrence capacity exceeded")
    return states, tuple(rows), tuple(receipts)
