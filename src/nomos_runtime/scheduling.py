"""Selected action-value scheduling, independent of authored rule evaluation."""

from dataclasses import dataclass, replace

from .entities import Reference
from .errors import AdmissionError, SettlementDefect
from .terminals import is_closed

MAX_ACTION_VALUE = (1 << 63) - 1


@dataclass(frozen=True)
class ScheduleDefinition:
    sort: str
    initial: int
    priority: int
    project: object


@dataclass(frozen=True)
class Projection:
    speed: int
    eligible: bool

    def __post_init__(self):
        if (
            type(self.speed) is not int
            or self.speed < 0
            or type(self.eligible) is not bool
            or self.eligible
            and self.speed == 0
        ):
            raise ValueError("eligible scheduling requires positive speed")


@dataclass(frozen=True)
class Debt:
    actor: Reference
    remaining: int
    priority: int

    def __post_init__(self):
        if type(self.remaining) is not int or abs(self.remaining) > MAX_ACTION_VALUE:
            raise ValueError("action-value debt exceeds its finite range")


@dataclass(frozen=True)
class Opportunity:
    actor: Reference
    at: int
    revision: int


@dataclass(frozen=True)
class PreDue:
    before: int
    at: int
    tape_before: int
    keys: tuple


@dataclass(frozen=True)
class ScheduleRecord:
    at: int
    kind: str
    actor: Reference | None
    before: tuple
    after: tuple
    cost: int | None = None
    occurrence: int | None = None


@dataclass(frozen=True)
class ScheduleState:
    debts: tuple
    history: tuple = ()
    opportunity: Opportunity | None = None
    deferred: frozenset = frozenset()
    same_time_actions: int = 0
    pre_due: PreDue | None = None
    revision: int = 0


@dataclass(frozen=True)
class Charge:
    state: ScheduleState
    cost: int


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class ScheduleOffer:
    actor: object
    at: int


@dataclass(frozen=True)
class ScheduleResult:
    status: str
    at: int
    opportunity: ScheduleOffer | None = None
    occurrences: int = 0


def selected(program):
    return program.time is not None and bool(program.time.schedules)


def definition(program, reference):
    return next(plan for plan in program.time.schedules if plan.sort == reference.sort)


def validate_newborn(session, reference, fields, before):
    if selected(session.program) and session.program.schemas[reference.sort].kind == "person":
        definition(session.program, reference).project(
            session, {**before, reference: fields}, reference
        )


def reconcile(session, states, state):
    if state is None:
        return None
    existing = {debt.actor for debt in state.debts}
    debts = list(state.debts)
    for reference in sorted(
        (key for key in states if type(key) is Reference), key=lambda ref: ref.ordinal
    ):
        if session.program.schemas[reference.sort].kind != "person":
            continue
        plan = definition(session.program, reference)
        plan.project(session, states, reference)
        if reference not in existing:
            if type(plan.initial) is not int or not 0 < plan.initial <= MAX_ACTION_VALUE:
                raise ValueError("new Actor needs positive finite initial action-value debt")
            debts.append(Debt(reference, plan.initial, plan.priority))
    return replace(state, debts=tuple(debts))


def opening(session, assets):
    if not selected(session.program):
        return None
    state = reconcile(session, session._states, ScheduleState(()))
    readiness = assets["time"].get("readiness")
    if readiness is not None:
        if (
            type(readiness) is not dict
            or set(readiness) != set(dict(session.program.actors))
            or any(
                type(value) is not int or not 0 <= value <= MAX_ACTION_VALUE
                for value in readiness.values()
            )
        ):
            raise ValueError("readiness requires exact opening Actor names and finite debts")
        symbols = dict(session.symbols)
        by_ref = {symbols[name]: value for name, value in readiness.items()}
        state = replace(
            state, debts=tuple(replace(d, remaining=by_ref[d.actor]) for d in state.debts)
        )
    elif "readiness" in assets["time"]:
        raise ValueError("readiness must not be null")
    return state


def has_opportunity(session, actor):
    state = session._scheduling
    return state is None or state.opportunity is not None and state.opportunity.actor == actor


def charge(session, action, actor, environment, record):
    state = session._scheduling
    if state is None:
        return None
    if not has_opportunity(session, actor):
        raise AdmissionError("NotAdmitted", "Actor has no current action opportunity")
    if state.same_time_actions >= session.limits.same_time_actions:
        session._fatal = True
        raise SettlementDefect("same-time action capacity exceeded")
    cost = action.time_cost(session, session._states, actor, environment, session._receipts, record)
    current = next(debt for debt in state.debts if debt.actor == actor)
    if (
        type(cost) is not int
        or not 1 <= cost <= MAX_ACTION_VALUE
        or current.remaining + cost > MAX_ACTION_VALUE
    ):
        raise AdmissionError("NotAdmitted", "Action cost exceeds its finite debt range")
    debts = tuple(
        replace(d, remaining=d.remaining + cost) if d.actor == actor else d for d in state.debts
    )
    return Charge(replace(state, debts=debts), cost)


def after_action(session, charge, states, actor, root, tip, cancelled, terminal):
    from .temporal import AdvanceRecord

    if charge is None:
        return None, ()
    state = reconcile(session, states, charge.state)
    history = state.history + (
        ScheduleRecord(
            session._time,
            "action",
            actor,
            session._scheduling.debts,
            state.debts,
            charge.cost,
            root,
        ),
    )
    phase, advances = state.pre_due, ()
    if phase is not None:
        phase = replace(phase, keys=tuple(key for key in phase.keys if key not in cancelled))
        if not phase.keys or is_closed(terminal):
            advances = (AdvanceRecord(phase.before, phase.at, phase.tape_before, tip, ()),)
            phase = None
    return replace(
        state,
        history=history,
        opportunity=None,
        deferred=frozenset(),
        pre_due=phase,
        same_time_actions=state.same_time_actions + 1,
        revision=state.revision + 1,
    ), advances


def after_due(session, state):
    if state is None:
        return None
    history = state.history
    if state.pre_due is None:
        history = (*history[:-1], replace(history[-1], after=state.debts))
    else:
        history += (
            ScheduleRecord(session._time, "due", None, session._scheduling.debts, state.debts),
        )
    return replace(
        state,
        history=history,
        pre_due=None,
        opportunity=None,
        deferred=frozenset(),
        same_time_actions=0,
        revision=state.revision + 1,
    )


def _select(state, projections, at):
    ready = [
        debt
        for debt in state.debts
        if debt.actor not in state.deferred
        and projections[debt.actor].eligible
        and debt.remaining <= 0
    ]
    if not ready:
        return None
    chosen = min(ready, key=lambda debt: (debt.priority, debt.actor.ordinal))
    return Opportunity(chosen.actor, at, state.revision)


def _projections(session, state):
    return {
        debt.actor: definition(session.program, debt.actor).project(
            session, session._states, debt.actor
        )
        for debt in state.debts
    }


def _require_control(session):
    if session._scheduling is None:
        raise AdmissionError("NoScheduling", "Program has no selected Actor schedule")
    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot schedule during settlement or after a fatal defect")


def next_opportunity(session):
    from .temporal import AdvanceRecord, settle_at

    _require_control(session)
    if is_closed(session._terminal):
        return ScheduleResult("closed", session._time)
    session._busy = True
    try:
        # A control call crosses at most one real due boundary, or reaches a ready Actor.
        for _ in range(2):
            state = session._scheduling
            projections = _projections(session, state)
            opportunity = _select(state, projections, session._time)
            if opportunity is not None:
                session._scheduling = replace(state, opportunity=opportunity)
                actor = session._controller(opportunity.actor)
                offer = ScheduleOffer(actor, session._time)
                session._schedule_handles[offer] = (opportunity, actor, session._time)
                return ScheduleResult("ready", session._time, offer)
            if state.pre_due is not None:
                count = settle_at(session, session._time, scheduling=state).occurrences
                return ScheduleResult(
                    "closed" if is_closed(session._terminal) else "due",
                    session._time,
                    occurrences=count,
                )
            deltas = [
                (debt.remaining + projections[debt.actor].speed - 1)
                // projections[debt.actor].speed
                for debt in state.debts
                if projections[debt.actor].eligible and debt.remaining > 0
            ]
            due = min((item.at for item in session._pending_due), default=None)
            if due is not None:
                deltas.append(due - session._time)
            if not deltas:
                return ScheduleResult("idle", session._time)
            delta = min(deltas)
            if delta <= 0:
                raise SettlementDefect("scheduler cannot make progress")
            at = session._time + delta
            debts = tuple(
                replace(debt, remaining=debt.remaining - delta * projections[debt.actor].speed)
                if projections[debt.actor].eligible and debt.actor not in state.deferred
                else debt
                for debt in state.debts
            )
            moved = replace(
                state,
                debts=debts,
                opportunity=None,
                deferred=frozenset(),
                same_time_actions=0,
                revision=state.revision + 1,
                history=state.history + (ScheduleRecord(at, "advance", None, state.debts, debts),),
            )
            if due == at:
                if any(projections[d.actor].eligible and d.remaining <= 0 for d in debts):
                    phase = PreDue(
                        session._time,
                        at,
                        len(session._history),
                        tuple(item.key for item in session._pending_due if item.at == at),
                    )
                    session._time, session._scheduling = at, replace(moved, pre_due=phase)
                    continue
                count = settle_at(session, at, scheduling=moved).occurrences
                return ScheduleResult(
                    "closed" if is_closed(session._terminal) else "due",
                    session._time,
                    occurrences=count,
                )
            record = AdvanceRecord(
                session._time, at, len(session._history), len(session._history), ()
            )
            session._time, session._scheduling = at, moved
            session._advances += (record,)
        raise SettlementDefect("scheduler failed to reach its next boundary")
    except Exception as error:
        session._fatal = True
        raise SettlementDefect(
            "generated scheduling transition failed; Session is fatal"
        ) from error
    finally:
        session._busy = False


def defer_opportunity(session, actor, offer):
    from .controllers import require_writer

    _require_control(session)
    controller = session._actor(actor)
    require_writer(session, controller)
    selected = session._schedule_handles.get(offer) if type(offer) is ScheduleOffer else None
    if selected is None:
        raise AdmissionError("UnknownOpportunity", "opportunity was not issued by this Session")
    opportunity, actual, at = selected
    if controller != opportunity.actor or offer.actor != actual or actor != actual:
        raise AdmissionError("WrongController", "opportunity belongs to another Actor")
    if offer.at != at:
        raise AdmissionError("UnknownOpportunity", "opportunity handle was modified")
    session._schedule_handles.pop(offer)
    state = session._scheduling
    if is_closed(session._terminal) or state.opportunity != opportunity:
        return ScheduleResult("rejected", session._time)
    session._busy = True
    try:
        projections = _projections(session, state)
        state = replace(
            state,
            deferred=state.deferred | {controller},
            revision=state.revision + 1,
            history=state.history
            + (ScheduleRecord(session._time, "defer", controller, state.debts, state.debts),),
        )
        state = replace(state, opportunity=_select(state, projections, session._time))
    except Exception as error:
        session._fatal = True
        raise SettlementDefect("generated scheduling defer failed; Session is fatal") from error
    finally:
        session._busy = False
    session._scheduling = state
    return ScheduleResult("deferred", session._time)
