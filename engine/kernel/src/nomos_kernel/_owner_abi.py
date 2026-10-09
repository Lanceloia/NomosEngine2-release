"""Private owner and local-identity contracts for the causal machine."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import ClassVar, Protocol, TypeAlias, runtime_checkable

from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._identity import (
    K0LocalIdentitySlot,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    _checked_label,
    _require_local_identity_slot,
)

_K0WireAtom: TypeAlias = None | bool | int | str
_K0CanonicalWirePayload: TypeAlias = _K0WireAtom | tuple["_K0CanonicalWirePayload", ...]


def _require_unique(values: tuple[object, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise K0ProfileError(f"{label} must be unique")


def _validate_closed_host_object(value: object, label: str) -> None:
    """Reject mutable/opaque instance configuration on reviewed host capabilities."""

    def validate_item(item: object, parent: tuple[str, ...], segment: str) -> None:
        carrier = type(item)
        if item is None or carrier in (bool, int, str) or isinstance(item, (Enum, type)):
            return
        path = (*parent, segment)
        if carrier is tuple:
            for index, child in enumerate(item):
                validate_item(child, path, f"[{index}]")
            return
        if carrier is frozenset:
            for index, child in enumerate(sorted(item, key=repr)):
                validate_item(child, path, f"[{index}]")
            return
        if carrier is MappingProxyType:
            for key, child in item.items():
                validate_item(key, path, ".key")
                validate_item(child, path, f"[{key!r}]")
            return
        parameters = getattr(carrier, "__dataclass_params__", None)
        if not is_dataclass(item) or parameters is None or not parameters.frozen:
            raise K0ProfileError(
                f"{''.join(path)} must use recursively frozen closed configuration"
            )
        for field in fields(item):
            validate_item(getattr(item, field.name), path, f".{field.name}")

    # Keep diagnostic fragments local; render the complete path only on failure.
    validate_item(value, (), label)


@dataclass(frozen=True, order=True)
class _K0MotivatingIntentionRef:
    value: int
    family: ClassVar[str] = "mind-motivating-intention"

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise K0ProfileError("motivating Intention reference must be a positive int")

    def validate_for_k0(self) -> None:
        _K0MotivatingIntentionRef.__post_init__(self)


@dataclass(frozen=True, order=True)
class _K0RuntimePropositionRef:
    """Opaque world-local identity for immutable runtime Proposition content."""

    value: int
    family: ClassVar[str] = "runtime-proposition"

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise K0ProfileError("runtime Proposition reference must be a positive int")

    def validate_for_k0(self) -> None:
        _K0RuntimePropositionRef.__post_init__(self)


@dataclass(frozen=True)
class _K0CapabilityRef:
    """A closed capability identity, not a dynamic callback or registry key."""

    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "capability reference")


@runtime_checkable
class _K0DeclaredSourceInput(Protocol):
    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0SealedEvidence(Protocol):
    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0ClosedParticipants(Protocol):
    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0SealedBinding(Protocol):
    key: str

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0SealedIntentionBasis(Protocol):
    intention: _K0MotivatingIntentionRef
    proposition: _K0RuntimePropositionRef
    deciding_deliberation: K0OccurrenceRef

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0FixedFamilyReferent(Protocol):
    family: str

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0ReadOnlyOwnerView(Protocol):
    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0OwnerContribution(Protocol):
    owner: K0OwnerKey

    def validate_for_k0(self) -> None: ...


@dataclass(frozen=True)
class _K0LocalIdentityValue:
    """Runtime-only materialization of one settlement-local identity slot."""

    occurrence: K0OccurrenceRef
    slot: K0LocalIdentitySlot
    referent: _K0FixedFamilyReferent

    def __post_init__(self) -> None:
        if type(self.occurrence) is not K0OccurrenceRef:
            raise K0ProfileError("local identity value occurrence must be an exact reference")
        try:
            K0OccurrenceRef.__post_init__(self.occurrence)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("local identity value occurrence is malformed") from error
        _require_local_identity_slot(self.slot, "local identity value slot")
        if not isinstance(self.referent, _K0FixedFamilyReferent):
            raise K0ProfileError("local identity value must carry a fixed-family referent")
        self.referent.validate_for_k0()
        if self.referent.family != self.slot.output_family:
            raise K0ProfileError("local identity value has the wrong fixed reference family")


@dataclass(frozen=True)
class _K0OwnerView:
    owner: K0OwnerKey
    view: _K0ReadOnlyOwnerView
    participant: str | None = None
    actor_ref: _K0ActorRef | None = None
    # The exact runtime check avoids an owner/dynamic-owner ABI import cycle.
    individual_ref: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.view, _K0ReadOnlyOwnerView):
            raise K0ProfileError("owner view is not a closed immutable projection")
        self.view.validate_for_k0()
        if self.participant is not None:
            _checked_label(self.participant, "selected participant")
        if self.actor_ref is not None:
            if type(self.actor_ref) is not _K0ActorRef or self.participant is None:
                raise K0ProfileError("Actor view has no exact selected identity")
            self.actor_ref.__post_init__()
        if self.individual_ref is not None:
            from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

            if (
                type(self.individual_ref) is not _K0IndividualRef
                or self.participant is None
                or self.actor_ref is not None
            ):
                raise K0ProfileError("Object view has no exact exclusive individual identity")
            self.individual_ref.__post_init__()


@runtime_checkable
class _K0CrossOwnerInvariant(Protocol):
    """Profile-selected invariant over an exact declared owner-view set."""

    capability_ref: _K0CapabilityRef
    read_owners: tuple[K0OwnerKey, ...]

    def validate(self, owner_views: tuple[_K0OwnerView, ...]) -> None: ...


@dataclass(frozen=True)
class _K0OccurrenceContribution:
    """One owner-typed direct contribution and its same-occurrence identities."""

    occurrence: K0OccurrenceRef
    contribution: _K0OwnerContribution
    resolved_identities: tuple[_K0LocalIdentityValue, ...]

    def __post_init__(self) -> None:
        if type(self.occurrence) is not K0OccurrenceRef:
            raise K0ProfileError("occurrence contribution must use an exact occurrence reference")
        try:
            K0OccurrenceRef.__post_init__(self.occurrence)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("occurrence contribution reference is malformed") from error
        if not isinstance(self.contribution, _K0OwnerContribution):
            raise K0ProfileError("occurrence contribution is not owner-typed")
        self.contribution.validate_for_k0()
        if any(value.occurrence != self.occurrence for value in self.resolved_identities):
            raise K0ProfileError(
                "occurrence contribution received an identity from another occurrence"
            )
        for value in self.resolved_identities:
            _require_local_identity_slot(value.slot, "occurrence contribution slot")
        slots = tuple(value.slot for value in self.resolved_identities)
        if tuple(sorted(slots)) != slots or len(set(slots)) != len(slots):
            raise K0ProfileError(
                "occurrence contribution identities must be unique and canonical-order"
            )


@runtime_checkable
class _K0Owner(Protocol):
    """Closed exact-owner contract; all state and views remain owner-defined."""

    key: K0OwnerKey
    owner_version: str
    state_type: type[object]
    view_type: type[object]
    contribution_type: type[object]
    local_identity_families: tuple[str, ...]

    def validate_state(self, state: object) -> None: ...

    def read_view(self, state: object) -> _K0ReadOnlyOwnerView: ...

    def validate_contribution(self, contribution: _K0OwnerContribution) -> None: ...

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]: ...

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> object: ...

    def allocate_local_identity(
        self, state: object, slot: K0LocalIdentitySlot, occurrence: K0OccurrenceRef
    ) -> tuple[object, _K0FixedFamilyReferent]: ...

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]: ...

    def encode_state(self, state: object) -> _K0CanonicalWirePayload: ...

    def decode_state(self, wire: _K0CanonicalWirePayload) -> object: ...


@runtime_checkable
class _K0SameWaveEffectProofOwner(Protocol):
    """Trusted owner proof that every same-wave Event write survives publication."""

    def prove_same_wave_effects(
        self,
        prior_state: object,
        contributions: tuple[_K0OccurrenceContribution, ...],
        final_state: object,
    ) -> None: ...


@runtime_checkable
class _K0OpeningStateValidator(Protocol):
    """Optional owner gate for facts that must be formed by published occurrences."""

    def validate_opening_state(self, state: object) -> None: ...


@runtime_checkable
class _K0ValidationOperationOwner(Protocol):
    """Optional pure-validation receipts, confined to one owner-state operation.

    The backend must establish immutable, deterministic validation dependencies.
    A receipt belongs to one actual value and validator, never an equal clone.
    Exit, failure and independent re-entry discard all receipts. No K0 check,
    read/write permission or atomic settlement boundary is delegated to this scope.
    """

    def validation_operation(self) -> AbstractContextManager[None]: ...


def _validate_owner(owner: _K0Owner) -> None:
    if not isinstance(owner, _K0Owner):
        raise K0ProfileError("profile owner does not implement the closed K0 owner contract")
    if not isinstance(owner.key, K0OwnerKey):
        raise K0ProfileError("profile owner has an invalid owner key")
    _checked_label(owner.owner_version, "owner version")
    for owner_type, label in (
        (owner.state_type, "owner state type"),
        (owner.view_type, "owner view type"),
        (owner.contribution_type, "owner contribution type"),
    ):
        if not isinstance(owner_type, type):
            raise K0ProfileError(f"{label} must be one exact closed type")
    families = tuple(
        _checked_label(family, "local identity family") for family in owner.local_identity_families
    )
    _require_unique(families, "owner local identity families")
    if tuple(sorted(families)) != families:
        raise K0ProfileError("owner local identity families must be canonical-order")
    _validate_closed_host_object(owner, "profile owner")
