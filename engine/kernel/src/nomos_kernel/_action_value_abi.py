"""Private selected action-value scheduling contracts for fixed-discrete Sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel import K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OwnerView

_K0_MAX_ACTION_VALUE = (1 << 63) - 1


@dataclass(frozen=True)
class _K0ActionValueProjection:
    tempo: int
    eligible: bool

    def __post_init__(self) -> None:
        if type(self.tempo) is not int or self.tempo < 1 or type(self.eligible) is not bool:
            raise K0ProfileError("action-value projection is malformed")


@runtime_checkable
class _K0ActionValueProjector(Protocol):
    """Pure query of the supplied owner view, with no external state or re-entry.

    Invocation counts are not part of the contract. One scheduling decision may
    reuse its projection; a subsequent transition independently rechecks it.
    """

    capability_ref: _K0CapabilityRef

    def project(self, owner_view: _K0OwnerView) -> _K0ActionValueProjection: ...


@runtime_checkable
class _K0ActionCostProjector(Protocol):
    capability_ref: _K0CapabilityRef

    def project_cost(self, payload: object, admission: object) -> int | None: ...


@dataclass(frozen=True)
class _K0ActionValueSeat:
    seat: str
    owner: K0OwnerKey
    action_sources: tuple[K0SourceSpecKey, ...]
    projector: _K0ActionValueProjector

    def __post_init__(self) -> None:
        if (
            type(self.seat) is not str
            or not self.seat
            or type(self.owner) is not K0OwnerKey
            or type(self.action_sources) is not tuple
            or not self.action_sources
            or any(type(source) is not K0SourceSpecKey for source in self.action_sources)
            or len(set(self.action_sources)) != len(self.action_sources)
            or not isinstance(self.projector, _K0ActionValueProjector)
            or type(self.projector.capability_ref) is not _K0CapabilityRef
        ):
            raise K0ProfileError("action-value seat is malformed")


@dataclass(frozen=True)
class _K0ActionValuePolicy:
    capability_ref: _K0CapabilityRef
    seats: tuple[_K0ActionValueSeat, ...]
    end_at: _K0FixedTime | None
    max_same_time_actions: int

    def __post_init__(self) -> None:
        if (
            type(self.capability_ref) is not _K0CapabilityRef
            or type(self.seats) is not tuple
            or not self.seats
            or any(type(seat) is not _K0ActionValueSeat for seat in self.seats)
            or (self.end_at is not None and type(self.end_at) is not _K0FixedTime)
            or type(self.max_same_time_actions) is not int
            or not 1 <= self.max_same_time_actions <= 1024
        ):
            raise K0ProfileError("action-value policy is malformed")
        for seat in self.seats:
            seat.__post_init__()
        if len({seat.seat for seat in self.seats}) != len(self.seats) or len(
            {seat.owner for seat in self.seats}
        ) != len(self.seats):
            raise K0ProfileError("action-value seats must have unique names and owners")


@dataclass(frozen=True)
class _K0ActionValueOpening:
    seat: str
    debt: int
    tie_priority: int

    def __post_init__(self) -> None:
        if (
            type(self.seat) is not str
            or not self.seat
            or type(self.debt) is not int
            or not -_K0_MAX_ACTION_VALUE <= self.debt <= _K0_MAX_ACTION_VALUE
            or type(self.tie_priority) is not int
            or self.tie_priority < 0
        ):
            raise K0ProfileError("action-value opening is malformed")


@dataclass(frozen=True)
class _K0ActionValueState:
    seat: str
    debt: int
    tie_priority: int
    formation_order: int = 0

    def __post_init__(self) -> None:
        _K0ActionValueOpening(self.seat, self.debt, self.tie_priority).__post_init__()
        if type(self.formation_order) is not int or self.formation_order < 0:
            raise K0ProfileError("action-value formation order is malformed")


@dataclass(frozen=True)
class _K0ActionOpportunity:
    seat: str
    owner: K0OwnerKey
    at: _K0FixedTime

    def __post_init__(self) -> None:
        if (
            type(self.seat) is not str
            or not self.seat
            or type(self.owner) is not K0OwnerKey
            or type(self.at) is not _K0FixedTime
        ):
            raise K0ProfileError("action opportunity is malformed")


@dataclass(frozen=True)
class _K0ActionValueDueBoundary:
    at: _K0FixedTime

    def __post_init__(self) -> None:
        if type(self.at) is not _K0FixedTime:
            raise K0ProfileError("action-value due boundary is malformed")


@dataclass(frozen=True)
class _K0ActionValueRecord:
    at: _K0FixedTime
    kind: str
    seat: str | None
    debt_before: tuple[_K0ActionValueState, ...]
    debt_after: tuple[_K0ActionValueState, ...]
    cost: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.at) is not _K0FixedTime
            or self.kind not in ("advance", "action", "due")
            or (self.seat is not None and (type(self.seat) is not str or not self.seat))
            or type(self.debt_before) is not tuple
            or type(self.debt_after) is not tuple
            or any(type(item) is not _K0ActionValueState for item in self.debt_before)
            or any(type(item) is not _K0ActionValueState for item in self.debt_after)
            or (self.cost is not None and (type(self.cost) is not int or self.cost < 1))
        ):
            raise K0ProfileError("action-value audit record is malformed")
