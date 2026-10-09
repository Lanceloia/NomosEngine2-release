"""Private session-local carriers for sourced, one-shot event-jump obligations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias, runtime_checkable

from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._coordinates import _K0FixedTime, _K0TemporalInterval
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OwnerView


@dataclass(frozen=True, order=True)
class _K0PendingDueKey:
    formation: K0OccurrenceRef
    ordinal: int

    def __post_init__(self) -> None:
        if (
            type(self.formation) is not K0OccurrenceRef
            or type(self.ordinal) is not int
            or self.ordinal < 0
        ):
            raise K0ProfileError("pending due key needs an Action ref and local ordinal")


@dataclass(frozen=True, order=True)
class _K0PeriodicDueKey:
    plan: _K0CapabilityRef
    ordinal: int

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not _K0CapabilityRef
            or type(self.ordinal) is not int
            or self.ordinal < 0
        ):
            raise K0ProfileError("periodic due key needs a plan and non-negative ordinal")


_K0DueKey: TypeAlias = _K0PendingDueKey | _K0PeriodicDueKey


@dataclass(frozen=True)
class _K0DueIndividualSelection:
    name: str
    individual: _K0IndividualRef
    owner: K0OwnerKey

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or not self.name
            or type(self.individual) is not _K0IndividualRef
            or type(self.owner) is not K0OwnerKey
        ):
            raise K0ProfileError("fixed due individual selection is malformed")
        self.individual.__post_init__()


@dataclass(frozen=True)
class _K0PeriodicDuePlan:
    capability_ref: _K0CapabilityRef
    source: K0SourceSpecKey
    interval: int
    max_occurrences: int | None
    subject: str

    def __post_init__(self) -> None:
        if (
            type(self.capability_ref) is not _K0CapabilityRef
            or type(self.source) is not K0SourceSpecKey
            or type(self.interval) is not int
            or self.interval < 1
            or (
                self.max_occurrences is not None
                and (type(self.max_occurrences) is not int or not 1 <= self.max_occurrences <= 1024)
            )
            or type(self.subject) is not str
            or not self.subject
        ):
            raise K0ProfileError("periodic due plan is malformed")


@dataclass(frozen=True)
class _K0PeriodicDueOpening:
    plan: _K0CapabilityRef
    first_at: _K0FixedTime

    def __post_init__(self) -> None:
        if type(self.plan) is not _K0CapabilityRef or type(self.first_at) is not _K0FixedTime:
            raise K0ProfileError("periodic due opening is malformed")


@dataclass(frozen=True)
class _K0ScheduleOnce:
    at: _K0FixedTime
    source: K0SourceSpecKey
    subject: str

    def __post_init__(self) -> None:
        if (
            type(self.at) is not _K0FixedTime
            or type(self.source) is not K0SourceSpecKey
            or type(self.subject) is not str
            or not self.subject
        ):
            raise K0ProfileError("scheduled due has malformed time, source or subject")


@dataclass(frozen=True)
class _K0PendingDue:
    key: _K0DueKey
    at: _K0FixedTime
    source: K0SourceSpecKey
    subject: str
    selected_individuals: tuple[_K0DueIndividualSelection, ...] = ()

    def __post_init__(self) -> None:
        _K0ScheduleOnce(self.at, self.source, self.subject)
        if type(self.key) not in (_K0PendingDueKey, _K0PeriodicDueKey):
            raise K0ProfileError("pending due has no exact local key")
        if (
            type(self.selected_individuals) is not tuple
            or any(
                type(item) is not _K0DueIndividualSelection for item in self.selected_individuals
            )
            or len({item.name for item in self.selected_individuals})
            != len(self.selected_individuals)
        ):
            raise K0ProfileError("pending due has malformed fixed individual selections")
        self.key.__post_init__()


@dataclass(frozen=True)
class _K0DueFormation:
    key: _K0DueKey
    scheduled_at: _K0FixedTime

    def __post_init__(self) -> None:
        if (
            type(self.key)
            not in (
                _K0PendingDueKey,
                _K0PeriodicDueKey,
            )
            or type(self.scheduled_at) is not _K0FixedTime
        ):
            raise K0ProfileError("due Event formation is malformed")
        self.key.__post_init__()


@dataclass(frozen=True)
class _K0AdvanceRecord:
    interval: _K0TemporalInterval
    tape_before: int
    tape_after: int
    dues: tuple[_K0DueKey, ...]
    policy: _K0CapabilityRef

    def __post_init__(self) -> None:
        if (
            type(self.interval) is not _K0TemporalInterval
            or type(self.tape_before) is not int
            or type(self.tape_after) is not int
            or self.tape_before < 0
            or self.tape_after < self.tape_before
            or type(self.dues) is not tuple
            or any(type(key) not in (_K0PendingDueKey, _K0PeriodicDueKey) for key in self.dues)
            or len(set(self.dues)) != len(self.dues)
            or self.tape_after < self.tape_before + len(self.dues)
            or type(self.policy) is not _K0CapabilityRef
        ):
            raise K0ProfileError("temporal audit record is malformed")


@dataclass(frozen=True)
class _K0OrderedTemporalPolicy:
    """Empty source order with zero capacity supports a clock without due work."""

    capability_ref: _K0CapabilityRef
    source_order: tuple[K0SourceSpecKey, ...]
    max_pending: int
    periodic_plans: tuple[_K0PeriodicDuePlan, ...] = ()
    pre_due_action_sources: tuple[K0SourceSpecKey, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.capability_ref) is not _K0CapabilityRef
            or type(self.source_order) is not tuple
            or any(type(key) is not K0SourceSpecKey for key in self.source_order)
            or len(set(self.source_order)) != len(self.source_order)
            or type(self.max_pending) is not int
            or self.max_pending < 0
            or self.max_pending > 64
            or (not self.source_order) != (self.max_pending == 0)
            or type(self.periodic_plans) is not tuple
            or any(type(plan) is not _K0PeriodicDuePlan for plan in self.periodic_plans)
            or type(self.pre_due_action_sources) is not tuple
            or any(type(source) is not K0SourceSpecKey for source in self.pre_due_action_sources)
            or len(set(self.pre_due_action_sources)) != len(self.pre_due_action_sources)
        ):
            raise K0ProfileError("ordered temporal policy is malformed")
        for plan in self.periodic_plans:
            plan.__post_init__()
        if (
            len({plan.capability_ref for plan in self.periodic_plans}) != len(self.periodic_plans)
            or len({plan.source for plan in self.periodic_plans}) != len(self.periodic_plans)
            or len(self.periodic_plans) > self.max_pending
        ):
            raise K0ProfileError("periodic due plans are not a closed finite selection")


@runtime_checkable
class _K0DueProjector(Protocol):
    capability_ref: _K0CapabilityRef

    def project_due(
        self,
        pending: _K0PendingDue,
        time: _K0FixedTime,
        owner_views: tuple[_K0OwnerView, ...],
    ) -> _K0AdmissionProjection: ...
