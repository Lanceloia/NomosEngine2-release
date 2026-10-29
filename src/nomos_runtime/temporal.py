"""Atomic event-jump time over compiled activity and periodic callbacks."""

from dataclasses import dataclass, replace

from . import information, records
from . import scheduling as actor_scheduling
from .actions import ActionResult
from .errors import AdmissionError, SettlementDefect
from .formation import FormationBatch
from .local_inputs import stage_inputs
from .records import Occurrence
from .settlement import settle_causality
from .terminals import CheckpointBasis, checkpoint, gate, is_closed


@dataclass(frozen=True)
class ActivityRequest:
    name: str
    actor: object
    duration: int
    values: tuple


@dataclass(frozen=True)
class PendingDue:
    key: records.ActivityKey | records.PeriodicKey
    name: str
    at: int
    values: tuple
    actor: object = None


@dataclass(frozen=True)
class ActivityDefinition:
    name: str
    source: str
    execute: object
    cancel: object


@dataclass(frozen=True)
class PeriodicDefinition:
    name: str
    source: str
    interval: int
    first_after: int
    opening: object
    execute: object


@dataclass(frozen=True)
class TimeDefinition:
    order: tuple
    activities: tuple
    periodic: tuple
    schedules: tuple

    def definition(self, name):
        return next(p for p in (*self.activities, *self.periodic) if p.name == name)


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class ActivityOffer:
    actor: object
    name: str
    due_at: int


@dataclass(frozen=True)
class TimeAdvanceResult:
    status: str
    at: int
    occurrences: int = 0


@dataclass(frozen=True)
class AdvanceRecord:
    before: int
    after: int
    tape_before: int
    tape_after: int
    consumed: tuple


@dataclass(frozen=True)
class CancellationRecord:
    key: records.ActivityKey
    occurrence: int
    at: int


def opening(session, assets):
    plan = session.program.time
    if plan is None:
        return None, ()
    value = assets["time"]
    if (
        type(value) is not dict
        or not {"at"} <= set(value) <= ({"at", "readiness"} if plan.schedules else {"at"})
        or type(value["at"]) is not int
        or value["at"] < 0
    ):
        raise ValueError("time opening requires exactly one nonnegative integer at")
    at = value["at"]
    pending = tuple(
        PendingDue(
            records.PeriodicKey(session._scope, p.name, 0),
            p.name,
            at + p.first_after,
            p.opening(session),
        )
        for p in plan.periodic
    )
    if len(pending) > session.limits.pending_due:
        raise ValueError("opening exceeds pending due capacity")
    return at, pending


def schedule(session, draft, cancelled):
    pending = tuple(due for due in session._pending_due if due.key not in cancelled)
    created = []
    for ordinal, request in enumerate(draft.scheduled):
        if session._time is None or type(request.duration) is not int or request.duration < 1:
            raise SettlementDefect("activity requires selected time and positive duration")
        created.append(
            PendingDue(
                records.ActivityKey(session._scope, draft.occurrence, ordinal),
                request.name,
                session._time + request.duration,
                request.values,
                request.actor,
            )
        )
    if len(pending) + len(created) > session.limits.pending_due:
        raise SettlementDefect("pending due capacity exceeded")
    return (*pending, *created), tuple(due.key for due in created)


def activity_offers(session, actor):
    from .expressions import ExpressionError, ValueBindingError

    controller = session._actor(actor)
    if (
        session.program.time is None
        or session._terminal is not None
        or not actor_scheduling.has_opportunity(session, controller)
    ):
        return ()
    offers = []
    for pending in session._pending_due:
        if pending.actor != controller:
            continue
        definition = session.program.time.definition(pending.name)
        if definition.cancel is None:
            continue
        try:
            definition.cancel.admit(session, controller, pending, None)
        except (AdmissionError, ValueBindingError, ExpressionError):
            continue
        offer = ActivityOffer(actor, definition.name, pending.at)
        session._activity_handles[offer] = (controller, pending, offer.name, offer.due_at)
        offers.append(offer)
    return tuple(offers)


def cancel_activity(session, actor, offer):
    from .expressions import ExpressionError, ValueBindingError

    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot cancel during settlement or after a fatal defect")
    controller = session._actor(actor)
    selected = session._activity_handles.get(offer) if type(offer) is ActivityOffer else None
    if selected is None:
        raise AdmissionError("UnknownActivity", "activity handle was not issued by this Session")
    actual, pending, name, at = selected
    if actual != controller or offer.actor != actor:
        raise AdmissionError("WrongController", "activity belongs to another Actor")
    if offer.name != name or offer.due_at != at:
        raise AdmissionError("UnknownActivity", "activity handle was modified")
    try:
        gate(session._terminal, None)
        if pending not in session._pending_due:
            raise AdmissionError("NotAdmitted", "activity is no longer pending")
        definition = session.program.time.definition(pending.name).cancel
        admission = definition.admit(session, controller, pending, None)
    except (AdmissionError, ValueBindingError, ExpressionError) as error:
        code = (
            error.code
            if type(error) is AdmissionError and error.code.startswith("World")
            else "NotAdmitted"
        )
        return ActionResult("rejected", code=code)
    return session._commit_action(
        definition, controller, admission.participants, None, (pending.key,), admission.epoch
    )


def advance(session, to):
    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot advance during settlement or after a fatal defect")
    plan = session.program.time
    if plan is None:
        raise AdmissionError("NoTimeMechanism", "Program has no selected time mechanism")
    if plan.schedules:
        raise AdmissionError("ScheduledTime", "use next_opportunity under Actor scheduling")
    if is_closed(session._terminal):
        return TimeAdvanceResult("closed", session._time)
    if to is not None and (type(to) is not int or to <= session._time):
        raise AdmissionError("InvalidTime", "advance target must be an integer after current time")
    earliest = min((due.at for due in session._pending_due), default=None)
    if to is None and earliest is None:
        return TimeAdvanceResult("no_due", session._time)
    at = earliest if to is None else min(to, earliest) if earliest is not None else to
    return settle_at(session, at, scheduling=None)


def settle_at(session, at, *, scheduling):
    from .cognition import checkpoint as cognition_checkpoint

    plan = session.program.time
    selected = sorted(
        (due for due in session._pending_due if due.at == at),
        key=lambda due: (
            plan.order.index(due.name),
            (due.key.formation, due.key.ordinal)
            if type(due.key) is records.ActivityKey
            else (0, due.key.ordinal),
        ),
    )
    session._busy = True
    try:
        allocation = FormationBatch(session.references, session.limits, session._scope)
        states, rows, receipts, consumed = session._states, [], [], []
        terminal = session._terminal
        minds = session._minds
        for due in selected:
            definition = plan.definition(due.name)
            offset = len(session._history) + len(rows)
            prefix = session._receipts + tuple(receipts)
            draft, environment = definition.execute(
                session, states, due, prefix, offset + 1, allocation
            )
            draft.materialize()
            root = Occurrence(
                offset + 1,
                "Event",
                definition.source,
                tuple(environment.items()),
                draft.result,
                None,
                products=tuple(draft.formed),
                draws=tuple(draft.random.draws),
                at=at,
                due=records.DueBasis(due.key, at),
            )
            after = draft.after()
            issued = information.deliver(session, draft, root, states, after)
            states, closure, issued = settle_causality(
                session, root, after, issued, allocation, offset=offset, receipt_prefix=prefix
            )
            rows.extend(closure)
            receipts.extend(issued)
            consumed.append(due.key)
            scheduling = actor_scheduling.reconcile(session, states, scheduling)
            terminal = checkpoint(
                session,
                states,
                session._processes,
                CheckpointBasis(session._scope, root.reference, rows[-1].reference),
                prior=terminal,
            )
            minds = cognition_checkpoint(
                session,
                states,
                session._receipts + tuple(receipts),
                CheckpointBasis(session._scope, root.reference, rows[-1].reference),
                minds,
            )
            if is_closed(terminal):
                break
        pending = [due for due in session._pending_due if due.key not in consumed]
        if not is_closed(terminal):
            pending.extend(
                replace(
                    due,
                    key=replace(due.key, ordinal=due.key.ordinal + 1),
                    at=due.at + plan.definition(due.name).interval,
                )
                for due in selected
                if type(due.key) is records.PeriodicKey and due.key in consumed
            )
        else:
            pending.clear()
        if len(pending) > session.limits.pending_due:
            raise SettlementDefect("pending due capacity exceeded")
        references = session.references.at(states)
        individuals = session._individuals + tuple(allocation.products)
        record = AdvanceRecord(
            scheduling.pre_due.before
            if scheduling is not None and scheduling.pre_due
            else session._time,
            at,
            scheduling.pre_due.tape_before
            if scheduling is not None and scheduling.pre_due
            else len(session._history),
            len(session._history) + len(rows),
            tuple(consumed),
        )
        scheduling = actor_scheduling.after_due(session, scheduling)
        local_inputs = stage_inputs(session, receipts, terminal)
    except Exception as error:
        session._fatal = True
        raise SettlementDefect("generated time advance rolled back; Session is fatal") from error
    finally:
        session._busy = False
    session._states, session.references, session._individuals = states, references, individuals
    session._history += tuple(rows)
    session._receipts += tuple(receipts)
    session._time, session._pending_due, session._terminal = at, tuple(pending), terminal
    session._advances += (record,)
    session._scheduling = scheduling
    session._minds = minds
    session._local_inputs = local_inputs
    return TimeAdvanceResult("published", at, len(rows))
