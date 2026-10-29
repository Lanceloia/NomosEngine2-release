"""Immutable occurrence, delivery and temporal provenance records."""

from dataclasses import dataclass

from .entities import Reference


@dataclass(frozen=True)
class ActivityKey:
    scope: str
    formation: int
    ordinal: int


@dataclass(frozen=True)
class PeriodicKey:
    scope: str
    plan: str
    ordinal: int


@dataclass(frozen=True)
class DueBasis:
    key: ActivityKey | PeriodicKey
    at: int


@dataclass(frozen=True)
class OrderedBasis:
    policy: str
    ordinal: int
    previous_completed: int | None


@dataclass(frozen=True)
class ActionEpoch:
    type_name: str
    value: object


@dataclass(frozen=True)
class Occurrence:
    reference: int
    family: str
    source: str
    participants: tuple
    result: object
    predecessor: int | None
    request: object = None
    supports: tuple = ()
    next_point: str | None = None
    advanced: bool = True
    products: tuple = ()
    draws: tuple = ()
    order: OrderedBasis | None = None
    at: int | None = None
    due: DueBasis | None = None
    scheduled: tuple = ()
    cancelled: tuple = ()
    time_cost: int | None = None
    epoch: ActionEpoch | None = None


@dataclass(frozen=True)
class Receipt:
    occurrence: int
    source: str
    channel: str
    recipient: Reference
    type_name: str
    value: object
    sample: str
    guarantees: tuple
    constraints: tuple
