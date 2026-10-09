"""Check one local-choice witness using C0's production control transitions."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Literal

from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0SettlementDefect

from nomos_c0.author_contract_v1 import C0BindingError, C0ControlBudgetExceeded
from nomos_c0.program_runtime_v1 import (
    C0AuthorSnapshot,
    C0ControlCommand,
    C0FormChoice,
    C0OfferFault,
    C0OwnerGraphProgram,
    C0OwnerGraphSession,
    C0SeatView,
)
from nomos_c0.seat_offers_v0 import C0SeatOffer


@dataclass(frozen=True)
class T0OfferSelector:
    entry: str | None = None
    label: str | None = None
    payload_fields: tuple[tuple[str, object], ...] = ()
    ordinal: int | None = None


@dataclass(frozen=True)
class T0LocalEquals:
    path: str
    value: object


@dataclass(frozen=True)
class T0OfferExists:
    selector: T0OfferSelector


@dataclass(frozen=True)
class T0SelectOffer:
    selector: T0OfferSelector


@dataclass(frozen=True)
class T0Defer:
    pass


@dataclass(frozen=True)
class T0Rule:
    when: tuple[T0LocalEquals | T0OfferExists, ...]
    choose: T0SelectOffer | T0Defer


@dataclass(frozen=True)
class T0SeatPolicy:
    seat: str
    rules: tuple[T0Rule, ...]


@dataclass(frozen=True)
class T0ScheduledTurn:
    operation: Literal["decide", "continue", "advance"]
    seat: str
    target_time: int | None = None


@dataclass(frozen=True)
class T0Witness:
    schedule: tuple[T0ScheduledTurn, ...]
    controllers: tuple[T0SeatPolicy, ...]
    max_steps: int
    external_inputs: tuple[object, ...] = ()


@dataclass(frozen=True)
class T0SourcePublished:
    source: str


@dataclass(frozen=True)
class T0OwnerFieldEquals:
    owner: str
    path: tuple[str, ...]
    value: object


@dataclass(frozen=True)
class T0Goal:
    all_of: tuple[T0SourcePublished | T0OwnerFieldEquals, ...]


@dataclass(frozen=True)
class T0Report:
    stage: Literal["compile", "start", "run"]
    stop_reason: str
    goal_status: Literal["met", "not_met_within_bound", "unknown"]
    steps_completed: int
    requested_step: int | None
    published: tuple[T0TraceRow, ...]
    form_choices: tuple[C0FormChoice, ...]
    detail: str = ""


@dataclass(frozen=True)
class _LocalFrame:
    view: C0SeatView
    offers: tuple[C0SeatOffer, ...]
    faults: tuple[C0OfferFault, ...]


@dataclass(frozen=True)
class T0TraceRow:
    occurrence: int
    family: str
    source: str
    classification: str
    formation_basis: object
    participants: object
    coordinate: object
    semantic_envelope: object


def _freeze(value: object) -> object:
    if _scalar(value):
        return value
    if isinstance(value, Enum):
        return ("enum", type(value).__name__, _freeze(value.value))
    if is_dataclass(value):
        return (
            "record",
            type(value).__name__,
            tuple((item.name, _freeze(getattr(value, item.name))) for item in fields(value)),
        )
    if type(value) in (tuple, list):
        return tuple(_freeze(item) for item in value)
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("C0 author trace has a non-string record key")
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    raise TypeError("C0 author trace contains an unsupported value")


def _trace_row(occurrence: object) -> T0TraceRow:
    return T0TraceRow(
        occurrence.occurrence.value,
        occurrence.family.value,
        occurrence.source.value,
        occurrence.classification.value,
        _freeze(occurrence.formation_basis),
        _freeze(occurrence.participants),
        _freeze(occurrence.coordinate),
        _freeze(occurrence.semantic_envelope),
    )


def _scalar(value: object) -> bool:
    return type(value) in (str, int, bool, type(None))


def _same_scalar(actual: object, expected: object) -> bool:
    return type(actual) is type(expected) and actual == expected


def _valid_selector(selector: object) -> bool:
    if type(selector) is not T0OfferSelector:
        return False
    if selector.entry is not None and (type(selector.entry) is not str or not selector.entry):
        return False
    if selector.label is not None and (type(selector.label) is not str or not selector.label):
        return False
    if type(selector.payload_fields) is not tuple or len(selector.payload_fields) > 16:
        return False
    if selector.ordinal is not None and (type(selector.ordinal) is not int or selector.ordinal < 1):
        return False
    names = []
    for item in selector.payload_fields:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or not item[0]
            or not _scalar(item[1])
        ):
            return False
        names.append(item[0])
    return len(names) == len(set(names)) and bool(
        selector.entry or selector.label or selector.payload_fields or selector.ordinal
    )


def _matches(selector: T0OfferSelector, offer: C0SeatOffer, ordinal: int) -> bool:
    payload = dict(offer.payload)
    return (
        (selector.ordinal is None or selector.ordinal == ordinal)
        and (selector.entry is None or offer.entry == selector.entry)
        and (selector.label is None or offer.label == selector.label)
        and all(
            name in payload and _same_scalar(payload[name], value)
            for name, value in selector.payload_fields
        )
    )


def _valid_witness(witness: object, program: C0OwnerGraphProgram) -> bool:
    if (
        type(witness) is not T0Witness
        or type(witness.schedule) is not tuple
        or len(witness.schedule) > 1024
        or type(witness.controllers) is not tuple
        or type(witness.max_steps) is not int
        or not 1 <= witness.max_steps <= 1024
        or type(witness.external_inputs) is not tuple
    ):
        return False
    seats = {item.symbol: item for item in program.seats}
    policies = {}
    for policy in witness.controllers:
        if (
            type(policy) is not T0SeatPolicy
            or type(policy.seat) is not str
            or policy.seat not in seats
            or policy.seat in policies
            or type(policy.rules) is not tuple
            or not 1 <= len(policy.rules) <= 32
        ):
            return False
        policies[policy.seat] = policy
        for rule in policy.rules:
            if (
                type(rule) is not T0Rule
                or type(rule.when) is not tuple
                or len(rule.when) > 16
                or type(rule.choose) not in (T0SelectOffer, T0Defer)
            ):
                return False
            if type(rule.choose) is T0SelectOffer and not _valid_selector(rule.choose.selector):
                return False
            for condition in rule.when:
                if type(condition) is T0LocalEquals:
                    if (
                        type(condition.path) is not str
                        or condition.path not in seats[policy.seat].read_paths
                        or not _scalar(condition.value)
                    ):
                        return False
                elif type(condition) is T0OfferExists:
                    if not _valid_selector(condition.selector):
                        return False
                else:
                    return False
    for turn in witness.schedule:
        if (
            type(turn) is not T0ScheduledTurn
            or type(turn.seat) is not str
            or turn.seat not in seats
            or turn.operation not in ("decide", "continue", "advance")
        ):
            return False
        if turn.operation == "decide" and (
            turn.seat not in policies or turn.target_time is not None
        ):
            return False
        if turn.operation == "continue" and turn.target_time is not None:
            return False
        if turn.operation == "advance" and type(turn.target_time) is not int:
            return False
    return True


def _valid_goal(goal: object) -> bool:
    if (
        type(goal) is not T0Goal
        or type(goal.all_of) is not tuple
        or not 1 <= len(goal.all_of) <= 32
    ):
        return False
    for clause in goal.all_of:
        if type(clause) is T0SourcePublished:
            if type(clause.source) is not str or not clause.source:
                return False
        elif type(clause) is T0OwnerFieldEquals:
            if (
                type(clause.owner) is not str
                or not clause.owner
                or type(clause.path) is not tuple
                or not clause.path
                or any(type(part) is not str or not part.isidentifier() for part in clause.path)
                or not _scalar(clause.value)
            ):
                return False
        else:
            return False
    return True


def _owner_field(state: object, path: tuple[str, ...]) -> object:
    current = state
    for name in path:
        if current is None:
            return _ABSENT_FIELD
        if not is_dataclass(current) or name not in {item.name for item in fields(current)}:
            raise ValueError("goal field is not in the selected owner state")
        current = getattr(current, name)
    return current


_ABSENT_FIELD = object()


def _goal_status(goal: T0Goal, snapshot: C0AuthorSnapshot) -> tuple[str, str]:
    owners = dict(snapshot.owners)
    matches = []
    for clause in goal.all_of:
        if type(clause) is T0SourcePublished:
            matches.append(any(item.source.value == clause.source for item in snapshot.occurrences))
        elif type(clause) is T0OwnerFieldEquals:
            if clause.owner not in owners:
                return "unknown", "goal owner is not selected by the Program"
            try:
                value = _owner_field(owners[clause.owner], clause.path)
            except ValueError as error:
                return "unknown", str(error)
            matches.append(value is not _ABSENT_FIELD and _same_scalar(value, clause.value))
    return ("met" if all(matches) else "not_met_within_bound"), ""


def _frame(session: C0OwnerGraphSession, seat: str) -> _LocalFrame:
    if session.program.game_form is not None:
        form = session.form_frame(seat)
        return _LocalFrame(form.view, form.offers, form.offer_faults)
    return _LocalFrame(session.read(seat), session.offers(seat), session.offer_faults(seat))


def _rule_matches(rule: T0Rule, frame: _LocalFrame) -> bool:
    values = dict(frame.view.fields)
    for condition in rule.when:
        if type(condition) is T0LocalEquals:
            if condition.path not in values or not _same_scalar(
                values[condition.path], condition.value
            ):
                return False
        elif type(condition) is T0OfferExists:
            if not any(
                _matches(condition.selector, offer, ordinal)
                for ordinal, offer in enumerate(frame.offers, 1)
            ):
                return False
    return True


def _report(
    stage: Literal["compile", "start", "run"],
    reason: str,
    completed: int,
    requested: int | None,
    detail: str,
    session: C0OwnerGraphSession | None,
    goal: T0Goal | None,
) -> T0Report:
    if session is None:
        return T0Report(stage, reason, "unknown", completed, requested, (), (), detail)
    snapshot = session.author_snapshot()
    status, goal_detail = _goal_status(goal, snapshot) if goal is not None else ("unknown", "")
    return T0Report(
        stage,
        reason,
        status,
        completed,
        requested,
        tuple(_trace_row(item) for item in snapshot.occurrences),
        snapshot.form_choices,
        detail or goal_detail,
    )


def check_witness(
    program: C0OwnerGraphProgram,
    assets: str | dict[str, object],
    witness: T0Witness,
    goal: T0Goal,
) -> T0Report:
    """Run one bounded witness; failure says nothing about other possible choices."""
    if type(program) is not C0OwnerGraphProgram:
        return _report("run", "unsupported_program", 0, None, "unknown Program type", None, None)
    if not _valid_witness(witness, program):
        return _report(
            "run", "witness_invalid", 0, None, "witness shape or seat is invalid", None, None
        )
    if witness.external_inputs:
        return _report(
            "run", "unsupported_input", 0, None, "external input is not supported", None, None
        )
    if not _valid_goal(goal):
        return _report("run", "unsupported_goal", 0, None, "goal shape is unsupported", None, None)
    try:
        session = program.start(assets)
    except C0BindingError as error:
        return _report("start", "start_rejected", 0, None, str(error), None, None)
    opening_status, opening_detail = _goal_status(goal, session.author_snapshot())
    if opening_status == "unknown":
        return _report("run", "unsupported_goal", 0, None, opening_detail, session, None)

    policies = {policy.seat: policy for policy in witness.controllers}
    completed = 0
    for index, turn in enumerate(witness.schedule, 1):
        if completed >= witness.max_steps:
            return _report("run", "bound_exhausted", completed, index, "", session, goal)
        try:
            if turn.operation == "decide":
                frame = _frame(session, turn.seat)
                if frame.faults:
                    return _report("run", "offer_fault", completed, index, "", session, goal)
                rule = next(
                    (item for item in policies[turn.seat].rules if _rule_matches(item, frame)),
                    None,
                )
                if rule is None:
                    reason = "no_local_offer" if not frame.offers else "witness_stopped"
                    return _report("run", reason, completed, index, "", session, goal)
                if type(rule.choose) is T0Defer:
                    command = C0ControlCommand("defer", turn.seat)
                else:
                    matches = tuple(
                        offer
                        for ordinal, offer in enumerate(frame.offers, 1)
                        if _matches(rule.choose.selector, offer, ordinal)
                    )
                    if len(matches) != 1:
                        reason = "choice_not_available" if not matches else "ambiguous_choice"
                        return _report("run", reason, completed, index, "", session, goal)
                    command = C0ControlCommand("submit", turn.seat, offer=matches[0])
            else:
                command = C0ControlCommand(turn.operation, turn.seat, target_time=turn.target_time)
            before_snapshot = session.author_snapshot()
            outcome = session.apply_control(command)
            if isinstance(outcome.result, K0NotAdmitted):
                return _report("run", "k0_not_admitted", completed, index, "", session, goal)
            after_snapshot = session.author_snapshot()
            if (
                turn.operation in ("continue", "advance")
                and before_snapshot.time == after_snapshot.time
                and before_snapshot.occurrences == after_snapshot.occurrences
                and before_snapshot.form_choices == after_snapshot.form_choices
            ):
                return _report("run", "control_stalled", completed, index, "", session, goal)
            completed += 1
        except C0ControlBudgetExceeded as error:
            return _report(
                "run", "control_budget_exhausted", completed, index, str(error), session, goal
            )
        except C0BindingError as error:
            return _report("run", "control_rejected", completed, index, str(error), session, goal)
        except K0SettlementDefect as error:
            return _report("run", "settlement_defect", completed, index, str(error), session, None)
    if session.program.game_form is not None:
        seat = witness.schedule[-1].seat if witness.schedule else session.program.seats[0].symbol
        reason = "game_form_finished" if session.form_frame(seat).finished else "witness_stopped"
    else:
        reason = "scheduled_end"
    return _report("run", reason, completed, None, "", session, goal)
