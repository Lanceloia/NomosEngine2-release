"""Private admission and runtime-Proposition contracts for the causal machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._identity import K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._owner_abi import (
    _K0CanonicalWirePayload,
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0DeclaredSourceInput,
    _K0OwnerView,
    _K0RuntimePropositionRef,
    _K0SealedBinding,
    _K0SealedEvidence,
)


@runtime_checkable
class _K0RuntimePropositionContent(Protocol):
    source: K0SourceSpecKey

    def validate_for_k0(self) -> None: ...


@runtime_checkable
class _K0RuntimePropositionCodec(Protocol):
    capability_ref: _K0CapabilityRef
    source: K0SourceSpecKey
    evidence_type: type[object]

    def seal(self, bindings: tuple[_K0SealedBinding, ...]) -> _K0RuntimePropositionContent: ...

    def bindings(self, evidence: _K0RuntimePropositionContent) -> tuple[_K0SealedBinding, ...]: ...

    def encode(self, evidence: _K0RuntimePropositionContent) -> _K0CanonicalWirePayload: ...

    def decode(self, wire: _K0CanonicalWirePayload) -> _K0RuntimePropositionContent: ...

    def bindings_equal(
        self,
        evidence: _K0RuntimePropositionContent,
        bindings: tuple[_K0SealedBinding, ...],
    ) -> bool: ...


@dataclass(frozen=True)
class _K0RuntimePropositionRecord:
    ref: _K0RuntimePropositionRef
    definition: K0SourceSpecKey
    definition_version: str
    content: _K0RuntimePropositionContent


@dataclass(frozen=True)
class _K0RuntimePropositionState:
    records: tuple[_K0RuntimePropositionRecord, ...] = ()
    cursor: int = 1


@dataclass(frozen=True)
class _K0AdmissionProjection:
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]


@runtime_checkable
class _K0AdmissionCapability(Protocol):
    capability_ref: _K0CapabilityRef

    def admit(
        self, payload: _K0DeclaredSourceInput, owner_views: tuple[_K0OwnerView, ...]
    ) -> _K0AdmissionProjection | None: ...


@runtime_checkable
class _K0RuntimePropositionAdmissionCapability(Protocol):
    capability_ref: _K0CapabilityRef

    def admit_with_runtime_propositions(
        self,
        payload: _K0DeclaredSourceInput,
        owner_views: tuple[_K0OwnerView, ...],
        runtime_propositions: _K0RuntimePropositionState,
    ) -> _K0AdmissionProjection | None: ...


@runtime_checkable
class _K0TimeAdmissionCapability(Protocol):
    capability_ref: _K0CapabilityRef

    def admit_at_time(
        self,
        payload: _K0DeclaredSourceInput,
        owner_views: tuple[_K0OwnerView, ...],
        time: _K0FixedTime,
    ) -> _K0AdmissionProjection | None: ...


@runtime_checkable
class _K0RuntimePropositionInvariant(Protocol):
    capability_ref: _K0CapabilityRef
    read_owners: tuple[K0OwnerKey, ...]

    def validate_with_runtime_propositions(
        self,
        owner_views: tuple[_K0OwnerView, ...],
        runtime_propositions: _K0RuntimePropositionState,
    ) -> None: ...


def _admit_source(
    capability: _K0AdmissionCapability,
    payload: _K0DeclaredSourceInput,
    owner_views: tuple[_K0OwnerView, ...],
    runtime_propositions: _K0RuntimePropositionState,
    time: _K0FixedTime | None = None,
) -> _K0AdmissionProjection | None:
    """Invoke the one admitted capability shape without source-specific dispatch."""
    if time is not None and type(time) is not _K0FixedTime:
        raise K0ProfileError("admission received a malformed authoritative time")
    if time is not None and isinstance(capability, _K0TimeAdmissionCapability):
        return capability.admit_at_time(payload, owner_views, time)
    if isinstance(capability, _K0RuntimePropositionAdmissionCapability):
        return capability.admit_with_runtime_propositions(
            payload, owner_views, runtime_propositions
        )
    return capability.admit(payload, owner_views)


def _validate_admission_projection(
    projection: _K0AdmissionProjection,
    evidence_type: type[object],
    participants_type: type[object],
    binding_keys: tuple[str, ...],
    binding_types: tuple[type[object], ...],
) -> None:
    """Validate one runtime projection against an explicit source schema."""
    if (
        type(evidence_type) is not type
        or type(participants_type) is not type
        or type(binding_keys) is not tuple
        or any(type(key) is not str for key in binding_keys)
        or type(binding_types) is not tuple
        or any(type(item) is not type for item in binding_types)
        or len(binding_keys) != len(binding_types)
    ):
        raise K0ProfileError("admission projection schema is malformed")
    if type(projection) is not _K0AdmissionProjection:
        raise K0ProfileError("admission capability returned a malformed projection")
    if set(vars(projection)) != {"evidence", "participants", "bindings"}:
        raise K0ProfileError("admission capability returned a malformed projection")
    if type(projection.evidence) is not evidence_type:
        raise K0ProfileError("admission evidence has the wrong closed carrier type")
    if type(projection.participants) is not participants_type:
        raise K0ProfileError("admission participants have the wrong closed carrier type")
    try:
        projection.evidence.validate_for_k0()
        projection.participants.validate_for_k0()
    except (AttributeError, TypeError) as error:
        raise K0ProfileError("admission projection payload is malformed") from error
    if type(projection.bindings) is not tuple:
        raise K0ProfileError("admission bindings must use an exact tuple")
    if tuple(type(binding) for binding in projection.bindings) != binding_types:
        raise K0ProfileError("admission binding carriers do not match the source declaration")
    try:
        keys = tuple(binding.key for binding in projection.bindings)
    except (AttributeError, TypeError) as error:
        raise K0ProfileError("admission binding is malformed") from error
    if keys != binding_keys:
        raise K0ProfileError("admission bindings do not match the source declaration")
    for binding in projection.bindings:
        try:
            binding.validate_for_k0()
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("admission binding is malformed") from error


def _find_runtime_proposition(
    state: _K0RuntimePropositionState,
    definition: K0SourceSpecKey,
    content: _K0RuntimePropositionContent,
) -> _K0RuntimePropositionRecord | None:
    return next(
        (
            item
            for item in state.records
            if item.definition == definition and item.content == content
        ),
        None,
    )
