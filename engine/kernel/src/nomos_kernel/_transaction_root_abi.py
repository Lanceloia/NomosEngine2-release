"""Domain-neutral ABI for one atomic, declared two-stage transaction root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._identity import (
    K0EventTypeKey,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
    _checked_label,
)
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._owner_abi import (
    _K0CanonicalWirePayload,
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0DeclaredSourceInput,
    _K0LocalIdentityValue,
    _K0OwnerContribution,
    _K0OwnerView,
    _K0SealedBinding,
    _K0SealedEvidence,
    _validate_closed_host_object,
)
from nomos_kernel._rule_products_abi import K0RuleResult


def _require_capability(value: object, label: str) -> None:
    capability_ref = getattr(value, "capability_ref", None)
    if type(capability_ref) is not _K0CapabilityRef:
        raise K0ProfileError(f"{label} must carry one exact capability reference")


def _require_version(value: object, label: str) -> None:
    _checked_label(value, f"{label} version")


@runtime_checkable
class _K0FormationResolver(Protocol):
    capability_ref: _K0CapabilityRef
    version: str

    def resolve(
        self,
        attempt: _K0DeclaredSourceAttempt,
        owner_views: tuple[_K0OwnerView, ...],
    ) -> object | None: ...


@runtime_checkable
class _K0FormationBasisCodec(Protocol):
    capability_ref: _K0CapabilityRef
    version: str
    basis_type: type[object]

    def validate_for_k0(self, basis: object) -> None: ...

    def encode(self, basis: object) -> _K0CanonicalWirePayload: ...

    def decode(self, payload: _K0CanonicalWirePayload) -> object: ...


@runtime_checkable
class _K0FormationValidator(Protocol):
    capability_ref: _K0CapabilityRef
    version: str

    def validate_contributions(
        self,
        basis: object,
        contributions: tuple[_K0OwnerContribution, ...],
    ) -> None: ...

    def validate_preserved(
        self,
        basis: object,
        participants: _K0ClosedParticipants,
        source: K0SourceSpecKey,
        receipt: _K0TransactionalStageReceipt,
    ) -> None: ...


DECLARED_RULE_WITNESS = "k0-declared-rule-v1"
DECLARED_BUILDER_WITNESS = "k0-declared-builder-v1"


def _require_declared_witness(
    value: object, attribute: str, expected: str, label: str
) -> None:
    """Construction-time declaration witness: exact fixed v1 value or reject."""
    witness = getattr(value, attribute, None)
    if type(witness) is not str or witness != expected:
        raise K0ProfileError(f"{label} must carry the exact declaration witness")


@runtime_checkable
class _K0DeclaredRuleCapability(Protocol):
    capability_ref: _K0CapabilityRef
    declared_rule_witness: str

    def evaluate(self, rule_input: _K0DeclaredRuleInput) -> K0RuleResult: ...


@runtime_checkable
class _K0DeclaredEnvelopeBuilder(Protocol):
    capability_ref: _K0CapabilityRef
    declared_builder_witness: str

    def build(self, rule_input: _K0DeclaredRuleInput) -> object: ...


@runtime_checkable
class _K0ContinuationResolver(Protocol):
    capability_ref: _K0CapabilityRef
    version: str

    def resolve(
        self,
        stage1_receipt: _K0TransactionalStageReceipt,
        owner_views: tuple[_K0OwnerView, ...],
        requirement: object | None,
    ) -> _K0DeclaredSourceAttempt: ...


@dataclass(frozen=True)
class _K0DeclaredFormationDefinition:
    basis_type: type[object]
    requirement_type: type[object]
    resolver: _K0FormationResolver
    codec: _K0FormationBasisCodec
    validator: _K0FormationValidator

    def __post_init__(self) -> None:
        if type(self.basis_type) is not type or type(self.requirement_type) is not type:
            raise K0ProfileError("declared formation types must be exact types")
        if not isinstance(self.resolver, _K0FormationResolver):
            raise K0ProfileError("declared formation resolver is not closed")
        if not isinstance(self.codec, _K0FormationBasisCodec):
            raise K0ProfileError("declared formation codec is not closed")
        if not isinstance(self.validator, _K0FormationValidator):
            raise K0ProfileError("declared formation validator is not closed")
        for capability, label in (
            (self.resolver, "declared formation resolver"),
            (self.codec, "declared formation codec"),
            (self.validator, "declared formation validator"),
        ):
            _require_capability(capability, label)
            _require_version(getattr(capability, "version", None), label)
            _validate_closed_host_object(capability, label)
        if self.codec.basis_type is not self.basis_type:
            raise K0ProfileError("declared formation codec has the wrong exact basis type")


@dataclass(frozen=True)
class _K0DeclaredFormationBasis:
    source: K0SourceSpecKey
    basis: object

    def __post_init__(self) -> None:
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("declared formation basis has the wrong source type")
        _validate_closed_host_object(self.basis, "declared formation basis")


@dataclass(frozen=True)
class _K0DeclaredSourceAttempt:
    source: K0SourceSpecKey
    payload: _K0DeclaredSourceInput
    requirement: object | None = None

    def __post_init__(self) -> None:
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("declared source attempt has the wrong source type")
        if not isinstance(self.payload, _K0DeclaredSourceInput):
            raise K0ProfileError("declared source attempt payload is not closed")
        try:
            self.payload.validate_for_k0()
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("declared source attempt payload is malformed") from error
        _validate_closed_host_object(self.requirement, "declared source requirement")


@dataclass(frozen=True)
class _K0DeclaredRuleInput:
    occurrence: K0OccurrenceRef
    formation_basis: _K0DeclaredFormationBasis | _K0CausalFormation
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]
    resolved_slots: tuple[_K0LocalIdentityValue, ...]
    requirement: object | None

    def __post_init__(self) -> None:
        if type(self.occurrence) is not K0OccurrenceRef:
            raise K0ProfileError("declared rule input occurrence must be exact")
        if type(self.formation_basis) not in (
            _K0DeclaredFormationBasis,
            _K0CausalFormation,
        ):
            raise K0ProfileError("declared rule input formation basis must be exact")
        if not isinstance(self.evidence, _K0SealedEvidence):
            raise K0ProfileError("declared rule input evidence is not closed")
        if not isinstance(self.participants, _K0ClosedParticipants):
            raise K0ProfileError("declared rule input participants are not closed")
        try:
            self.evidence.validate_for_k0()
            self.participants.validate_for_k0()
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("declared rule input payload is malformed") from error
        if type(self.bindings) is not tuple or any(
            not isinstance(item, _K0SealedBinding) for item in self.bindings
        ):
            raise K0ProfileError("declared rule input bindings are not closed")
        for binding in self.bindings:
            try:
                binding.validate_for_k0()
            except (AttributeError, TypeError) as error:
                raise K0ProfileError("declared rule input binding is malformed") from error
        if type(self.resolved_slots) is not tuple or any(
            type(item) is not _K0LocalIdentityValue for item in self.resolved_slots
        ):
            raise K0ProfileError("declared rule input local identities are not exact")
        _validate_closed_host_object(self.requirement, "declared rule requirement")


@dataclass(frozen=True)
class _K0TransactionalStageReceipt:
    occurrence: K0OccurrenceRef
    source: K0SourceSpecKey
    event_type: K0EventTypeKey
    coordinate: _K0OccurrenceCoordinate

    def __post_init__(self) -> None:
        if (
            type(self.occurrence) is not K0OccurrenceRef
            or type(self.source) is not K0SourceSpecKey
            or type(self.event_type) is not K0EventTypeKey
            or type(self.coordinate) is not _K0OccurrenceCoordinate
        ):
            raise K0ProfileError("transactional stage receipt is malformed")


@dataclass(frozen=True)
class K0TransactionalRootDefinition:
    root_identity: str
    version: str
    schema_revision: int
    stage1_source: K0SourceSpecKey
    stage2_source: K0SourceSpecKey
    continuation_read_owners: tuple[K0OwnerKey, ...]
    continuation: _K0ContinuationResolver

    def __post_init__(self) -> None:
        _checked_label(self.root_identity, "transactional root identity")
        _checked_label(self.version, "transactional root version")
        if type(self.schema_revision) is not int or self.schema_revision < 1:
            raise K0ProfileError("transactional root schema revision must be positive")
        if (
            type(self.stage1_source) is not K0SourceSpecKey
            or type(self.stage2_source) is not K0SourceSpecKey
            or self.stage1_source == self.stage2_source
        ):
            raise K0ProfileError("transactional root sources are malformed")
        owners = self.continuation_read_owners
        if (
            type(owners) is not tuple
            or any(type(owner) is not K0OwnerKey for owner in owners)
            or tuple(sorted(owners)) != owners
            or len(set(owners)) != len(owners)
        ):
            raise K0ProfileError(
                "transactional continuation owners must be unique canonical-order"
            )
        if not isinstance(self.continuation, _K0ContinuationResolver):
            raise K0ProfileError("transactional continuation is not closed")
        _require_capability(self.continuation, "transactional continuation")
        _require_version(self.continuation.version, "transactional continuation")
        _validate_closed_host_object(self.continuation, "transactional continuation")
