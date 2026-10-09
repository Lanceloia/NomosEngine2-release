"""Private finite Actor formation and instance-relative capability contracts."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._action_value_abi import (
    _K0_MAX_ACTION_VALUE,
    _K0ActionValueProjector,
    _K0ActionValueSeat,
    _K0ActionValueState,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._dynamic_owner_abi import (
    _K0DynamicOwnerFactory,
    _K0DynamicOwnerKind,
    _K0IndividualBinding,
)
from nomos_kernel._identity import _checked_label
from nomos_kernel._owner_abi import _K0CapabilityRef


@dataclass(frozen=True)
class _K0ActorOwnerPort:
    payload_field: str
    family: str
    write: bool

    def __post_init__(self) -> None:
        _checked_label(self.payload_field, "Actor self payload field")
        _checked_label(self.family, "Actor self family")
        if type(self.write) is not bool:
            raise K0ProfileError("Actor self write permission is malformed")


@dataclass(frozen=True)
class _K0ActorParticipantPort:
    name: str
    payload_field: str
    family: str
    write: bool

    def __post_init__(self) -> None:
        _checked_label(self.name, "Actor participant name")
        _checked_label(self.payload_field, "Actor participant payload field")
        _checked_label(self.family, "Actor participant family")
        if self.name == "actor" or type(self.write) is not bool:
            raise K0ProfileError("Actor participant name or write permission is malformed")


@dataclass(frozen=True)
class _K0ActorProductSlot:
    family: str
    required: bool

    def __post_init__(self) -> None:
        _checked_label(self.family, "formed Actor family")
        if type(self.required) is not bool:
            raise K0ProfileError("Actor product cardinality is malformed")


@dataclass(frozen=True)
class _K0ActorDomainPort:
    name: str
    families: tuple[str, ...]
    write: bool

    def __post_init__(self) -> None:
        _checked_label(self.name, "Actor domain port")
        if (
            type(self.families) is not tuple
            or not self.families
            or self.families != tuple(sorted(set(self.families)))
            or any(type(item) is not str for item in self.families)
            or type(self.write) is not bool
        ):
            raise K0ProfileError(
                "Actor domain requires finite canonical kinds and write permission"
            )
        for family in self.families:
            _checked_label(family, "Actor domain family")


@dataclass(frozen=True)
class _K0FormActorProduct:
    """None is an explicit absent product, not an omitted result slot."""

    family: str
    initial_state: object | None

    def __post_init__(self) -> None:
        _checked_label(self.family, "Actor product family")


@dataclass(frozen=True)
class _K0ActorKind:
    family: str
    max_instances: int
    state_type: type[object]
    factory: _K0DynamicOwnerFactory
    action_sources: tuple[K0SourceSpecKey, ...]
    projector: _K0ActionValueProjector
    initial_debt: int
    tie_priority: int
    control: _K0CapabilityRef

    def __post_init__(self) -> None:
        _K0DynamicOwnerKind(
            self.family, self.max_instances, self.state_type, self.factory
        ).__post_init__()
        if (
            type(self.initial_debt) is not int
            or not 0 < self.initial_debt <= _K0_MAX_ACTION_VALUE
            or type(self.tie_priority) is not int
            or self.tie_priority < 0
            or type(self.control) is not _K0CapabilityRef
        ):
            raise K0ProfileError("Actor kind has no finite birth debt or control template")
        _K0ActionValueSeat(
            "template", K0OwnerKey("actor.template"), self.action_sources, self.projector
        ).__post_init__()


@dataclass(frozen=True)
class _K0OpeningActor:
    family: str
    initial_state: object
    debt: int

    def __post_init__(self) -> None:
        _checked_label(self.family, "opening Actor family")
        if type(self.debt) is not int or not 0 <= self.debt <= _K0_MAX_ACTION_VALUE:
            raise K0ProfileError("opening Actor debt must be nonnegative and finite")


@dataclass(frozen=True)
class _K0ActorBinding:
    actor: _K0ActorRef
    owner: K0OwnerKey
    formed_by: K0OccurrenceRef | None
    born_at: _K0FixedTime
    seat: str
    control: _K0CapabilityRef

    def __post_init__(self) -> None:
        if (
            type(self.actor) is not _K0ActorRef
            or type(self.owner) is not K0OwnerKey
            or (self.formed_by is not None and type(self.formed_by) is not K0OccurrenceRef)
            or type(self.born_at) is not _K0FixedTime
            or type(self.control) is not _K0CapabilityRef
        ):
            raise K0ProfileError("Actor binding is malformed")
        self.actor.__post_init__()
        _checked_label(self.seat, "Actor seat")


@dataclass
class _K0FormationCandidate:
    """Owner topology and its instance capabilities share one unpublished transaction."""

    individual_bindings: tuple[_K0IndividualBinding, ...]
    actor_bindings: tuple[_K0ActorBinding, ...]
    next_ordinal: int
    seats: tuple[_K0ActionValueSeat, ...]
    debts: tuple[_K0ActionValueState, ...]
