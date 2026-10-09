"""Private, session-local individual references and dynamic owner declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._identity import _checked_label
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0Owner


@dataclass(frozen=True, order=True)
class _K0IndividualRef:
    scope: str
    ordinal: int
    family: str

    def __post_init__(self) -> None:
        _checked_label(self.scope, "individual scope")
        _checked_label(self.family, "individual family")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise K0ProfileError("individual ordinal must be positive")


@dataclass(frozen=True)
class _K0IndividualBinding:
    individual: _K0IndividualRef
    owner: K0OwnerKey
    formed_by: K0OccurrenceRef | None

    def __post_init__(self) -> None:
        if type(self.individual) is not _K0IndividualRef or type(self.owner) is not K0OwnerKey:
            raise K0ProfileError("individual binding is malformed")
        self.individual.__post_init__()
        if self.formed_by is not None and type(self.formed_by) is not K0OccurrenceRef:
            raise K0ProfileError("individual formation basis is malformed")


@dataclass(frozen=True)
class _K0FixedDueIndividualPort:
    name: str
    family: str

    def __post_init__(self) -> None:
        _checked_label(self.name, "fixed due participant name")
        _checked_label(self.family, "fixed due individual family")


@dataclass(frozen=True)
class _K0ReadObjectDomainPort:
    name: str
    family: str

    def __post_init__(self) -> None:
        _checked_label(self.name, "read Object domain name")
        _checked_label(self.family, "read Object domain family")


@runtime_checkable
class _K0DynamicOwnerFactory(Protocol):
    capability_ref: _K0CapabilityRef
    state_type: type[object]

    def build(self, key: K0OwnerKey) -> _K0Owner: ...


@dataclass(frozen=True)
class _K0DynamicOwnerKind:
    family: str
    max_instances: int
    state_type: type[object]
    factory: _K0DynamicOwnerFactory

    def __post_init__(self) -> None:
        _checked_label(self.family, "dynamic owner family")
        if type(self.max_instances) is not int or self.max_instances < 1:
            raise K0ProfileError("dynamic owner limit must be positive")
        if (
            not isinstance(self.state_type, type)
            or not isinstance(self.factory, _K0DynamicOwnerFactory)
            or type(self.factory.capability_ref) is not _K0CapabilityRef
            or self.factory.state_type is not self.state_type
        ):
            raise K0ProfileError("dynamic owner kind lacks a closed factory")


@dataclass(frozen=True)
class _K0IndividualOwnerPort:
    name: str
    payload_field: str
    families: tuple[str, ...]
    write: bool

    def __post_init__(self) -> None:
        _checked_label(self.name, "individual owner port name")
        _checked_label(self.payload_field, "dynamic owner payload field")
        if (
            type(self.families) is not tuple
            or not self.families
            or any(type(family) is not str for family in self.families)
            or self.families != tuple(sorted(set(self.families)))
        ):
            raise K0ProfileError("dynamic owner port families are not finite and canonical")
        for family in self.families:
            _checked_label(family, "dynamic owner port family")
        if type(self.write) is not bool:
            raise K0ProfileError("dynamic owner port write permission is malformed")


@dataclass(frozen=True)
class _K0ClosedOwnerPort:
    name: str
    payload_field: str
    members: tuple[tuple[str, K0OwnerKey], ...]
    write: bool
    nullable: bool

    def __post_init__(self) -> None:
        _checked_label(self.name, "closed owner port name")
        _checked_label(self.payload_field, "closed owner payload field")
        if (
            type(self.members) is not tuple
            or not self.members
            or any(
                type(member) is not tuple
                or len(member) != 2
                or type(member[0]) is not str
                or type(member[1]) is not K0OwnerKey
                for member in self.members
            )
        ):
            raise K0ProfileError("closed owner port members are malformed")
        labels = tuple(label for label, _ in self.members)
        if labels != tuple(sorted(set(labels))):
            raise K0ProfileError("closed owner port labels are not finite and canonical")
        for label in labels:
            _checked_label(label, "closed owner port member")
        for _, owner in self.members:
            try:
                K0OwnerKey.__post_init__(owner)
            except (AttributeError, TypeError, K0ProfileError) as error:
                raise K0ProfileError("closed owner port member key is malformed") from error
        if len({owner for _, owner in self.members}) != len(self.members):
            raise K0ProfileError("closed owner port members must name distinct owners")
        if type(self.write) is not bool or type(self.nullable) is not bool:
            raise K0ProfileError("closed owner port write permission or nullability is malformed")


@dataclass(frozen=True)
class _K0SelectedOwner:
    name: str
    selector: str | _K0IndividualRef | _K0ActorRef
    owner: K0OwnerKey

    def __post_init__(self) -> None:
        _checked_label(self.name, "selected owner port")
        if type(self.selector) is str:
            _checked_label(self.selector, "selected owner label")
        elif type(self.selector) in (_K0IndividualRef, _K0ActorRef):
            self.selector.__post_init__()
        else:
            raise K0ProfileError("selected owner selector is malformed")
        if type(self.owner) is not K0OwnerKey:
            raise K0ProfileError("selected owner key is malformed")
        try:
            K0OwnerKey.__post_init__(self.owner)
        except (AttributeError, TypeError, K0ProfileError) as error:
            raise K0ProfileError("selected owner key is malformed") from error


@dataclass(frozen=True)
class _K0FormOwnerRequest:
    family: str
    initial_state: object

    def __post_init__(self) -> None:
        _checked_label(self.family, "formed owner family")


@dataclass(frozen=True)
class _K0OpeningIndividual:
    family: str
    initial_state: object

    def __post_init__(self) -> None:
        _checked_label(self.family, "opening individual family")
