"""Stable root checkpoints and authored closure, separate from world occurrences."""

from dataclasses import dataclass, replace

from .errors import AdmissionError, SettlementDefect


@dataclass(frozen=True)
class TerminalDefinition:
    name: str
    boundary: str
    triggered: object
    outcome: object
    result_type: str


@dataclass(frozen=True)
class OpeningBasis:
    scope: str


@dataclass(frozen=True)
class CheckpointBasis:
    scope: str
    root: int
    tip: int


@dataclass(frozen=True)
class TerminalState:
    rule: str
    trigger: object
    waiting: tuple
    closed: object = None
    value: object = None
    recipients: frozenset = frozenset()


def gate(terminal, binding):
    if terminal is None:
        return
    if terminal.closed is not None:
        raise AdmissionError("WorldClosed", "world is closed")
    if binding is None or (binding.process, binding.start) not in terminal.waiting:
        raise AdmissionError("WorldDraining", "only previously pending processes may finish")


def is_closed(terminal):
    return terminal is not None and terminal.closed is not None


def checkpoint(session, states, processes, basis, *, prior):
    plan = session.program.terminal
    terminal = prior
    if plan is None:
        return None
    if terminal is None:
        if not plan.triggered(session, states):
            return None
        waiting = tuple((r.process, r.start) for r in processes.active)
        terminal = TerminalState(plan.name, basis, waiting)
    pending = {(r.process, r.start) for r in processes.active}
    if plan.boundary == "action" or not pending.intersection(terminal.waiting):
        value, recipients = plan.outcome(session, states)
        for recipient in recipients:
            session.context(states).references.require(recipient, recipient.sort)
            if session.program.schemas[recipient.sort].kind != "person":
                raise SettlementDefect("terminal recipient is not an Actor")
        terminal = replace(terminal, closed=basis, value=value, recipients=recipients)
    return terminal


def ending(session, actor):
    controller = session._actor(actor)
    terminal = session._terminal
    if terminal is None:
        return {"status": "active", "available": False, "value": None}
    if terminal.closed is None:
        return {"status": "draining", "available": False, "value": None}
    available = controller in terminal.recipients
    return {
        "status": "closed",
        "available": available,
        "value": terminal.value if available else None,
    }
