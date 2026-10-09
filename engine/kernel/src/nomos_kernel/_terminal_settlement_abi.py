"""Private, read-only terminal policy and normal closure evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._event_jump_abi import _K0PendingDue
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OwnerView, _validate_closed_host_object


@runtime_checkable
class _K0TerminalProjector(Protocol):
    capability_ref: _K0CapabilityRef

    def project(self, owner_views: tuple[_K0OwnerView, ...]) -> bool: ...


@dataclass(frozen=True)
class _K0TerminalClause:
    outcome: str
    read_owners: tuple[K0OwnerKey, ...]
    projector: _K0TerminalProjector

    def __post_init__(self) -> None:
        if (
            type(self.outcome) is not str
            or not self.outcome
            or type(self.read_owners) is not tuple
            or not self.read_owners
            or any(type(key) is not K0OwnerKey for key in self.read_owners)
            or len(set(self.read_owners)) != len(self.read_owners)
            or not isinstance(self.projector, _K0TerminalProjector)
            or type(self.projector.capability_ref) is not _K0CapabilityRef
        ):
            raise K0ProfileError("terminal clause requires exact read-only ports")
        _validate_closed_host_object(self.projector, "terminal projector")


@dataclass(frozen=True)
class _K0TerminalPolicy:
    capability_ref: _K0CapabilityRef
    clauses: tuple[_K0TerminalClause, ...]

    def __post_init__(self) -> None:
        if (
            type(self.capability_ref) is not _K0CapabilityRef
            or type(self.clauses) is not tuple
            or not 1 <= len(self.clauses) <= 64
            or any(type(clause) is not _K0TerminalClause for clause in self.clauses)
            or len({clause.outcome for clause in self.clauses}) != len(self.clauses)
        ):
            raise K0ProfileError("terminal policy requires finite ordered clauses")
        for clause in self.clauses:
            clause.__post_init__()


@dataclass(frozen=True)
class _K0NotReachedDue:
    pending: _K0PendingDue
    disposition: Literal["not_reached"] = "not_reached"

    def __post_init__(self) -> None:
        if type(self.pending) is not _K0PendingDue or self.disposition != "not_reached":
            raise K0ProfileError("terminal due disposition is malformed")


@dataclass(frozen=True)
class _K0ClosedPeriodicPlan:
    plan: _K0CapabilityRef
    last_occurrence: K0OccurrenceRef | None

    def __post_init__(self) -> None:
        if type(self.plan) is not _K0CapabilityRef or (
            self.last_occurrence is not None and type(self.last_occurrence) is not K0OccurrenceRef
        ):
            raise K0ProfileError("terminal periodic closure is malformed")


@dataclass(frozen=True)
class _K0TerminalState:
    policy: _K0CapabilityRef
    clause: int
    outcome: str
    checkpoint: Literal["opening", "action", "due"]
    time: _K0FixedTime | None
    trigger: K0OccurrenceRef | None
    not_reached: tuple[_K0NotReachedDue, ...]
    closed_plans: tuple[_K0ClosedPeriodicPlan, ...]

    def __post_init__(self) -> None:
        if (
            type(self.policy) is not _K0CapabilityRef
            or type(self.clause) is not int
            or self.clause < 0
            or type(self.outcome) is not str
            or not self.outcome
            or self.checkpoint not in ("opening", "action", "due")
            or (self.time is not None and type(self.time) is not _K0FixedTime)
            or (self.checkpoint == "opening") != (self.trigger is None)
            or (self.trigger is not None and type(self.trigger) is not K0OccurrenceRef)
            or type(self.not_reached) is not tuple
            or any(type(row) is not _K0NotReachedDue for row in self.not_reached)
            or len({row.pending.key for row in self.not_reached}) != len(self.not_reached)
            or type(self.closed_plans) is not tuple
            or any(type(row) is not _K0ClosedPeriodicPlan for row in self.closed_plans)
            or len({row.plan for row in self.closed_plans}) != len(self.closed_plans)
        ):
            raise K0ProfileError("terminal state is malformed")


@dataclass(frozen=True)
class _K0SessionClosed:
    """Normal zero-write refusal, distinct from non-admission and fatal failure."""

    terminal: _K0TerminalState
    reason: Literal["session_closed"] = "session_closed"

    def __post_init__(self) -> None:
        if type(self.terminal) is not _K0TerminalState or self.reason != "session_closed":
            raise K0ProfileError("normal closure receipt is malformed")
