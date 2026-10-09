"""Read-only occurrence shape and observer protocols for the causal machine."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._admission_abi import _K0RuntimePropositionState
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0OwnerView,
)
from nomos_kernel._rule_products_abi import _K0Activation
from nomos_kernel._semantic_link_abi import _K0PreservedSemanticLinkRequirement
from nomos_kernel._state_image_abi import _K0OccurrenceCursor


@runtime_checkable
class _K0OccurrenceRecordView(Protocol):
    """Domain-neutral read shape of one preserved occurrence."""

    occurrence: K0OccurrenceRef
    family: K0OccurrenceFamily
    source: K0SourceSpecKey
    classification: K0EventTypeKey
    formation_basis: object
    participants: _K0ClosedParticipants
    coordinate: _K0OccurrenceCoordinate
    semantic_envelope: object


@runtime_checkable
class _K0ActivationProjector(Protocol):
    capability_ref: _K0CapabilityRef

    def project(
        self,
        trigger: _K0OccurrenceRecordView,
        owner_views: tuple[_K0OwnerView, ...],
    ) -> tuple[_K0Activation, ...]: ...


@runtime_checkable
class _K0OccurrenceCursorValidator(Protocol):
    """Optional profile-bound validation of the authoritative occurrence cursor."""

    capability_ref: _K0CapabilityRef
    read_owners: tuple[K0OwnerKey, ...]

    def validate_occurrence_cursor(
        self,
        cursor: _K0OccurrenceCursor,
        preserved_occurrences: tuple[_K0OccurrenceRecordView, ...],
        owner_views: tuple[_K0OwnerView, ...],
    ) -> None: ...


@runtime_checkable
class _K0RuntimePropositionSemanticLinkValidator(Protocol):
    capability_ref: _K0CapabilityRef
    requirement_type: type

    def validate_link_with_runtime_propositions(
        self,
        requirement: object,
        primary: _K0OccurrenceRecordView,
        required: tuple[_K0OccurrenceRecordView, ...],
        runtime_propositions: _K0RuntimePropositionState,
    ) -> None: ...


@runtime_checkable
class _K0PreservedSemanticLinkValidator(Protocol):
    """One source-bound stateless validator over a finite resolved link."""

    capability_ref: _K0CapabilityRef
    requirement_type: type[object]

    def validate_link(
        self,
        requirement: _K0PreservedSemanticLinkRequirement,
        primary: _K0OccurrenceRecordView,
        required: tuple[_K0OccurrenceRecordView, ...],
    ) -> None: ...


def _occurrence_order_key(
    occurrence: _K0OccurrenceRecordView,
) -> tuple[int, int, int]:
    """Canonical publication order for one occurrence record."""
    try:
        coordinate = occurrence.coordinate
        reference = occurrence.occurrence
    except (AttributeError, TypeError) as error:
        raise K0ProfileError("occurrence order coordinates are missing") from error
    if type(coordinate) is not _K0OccurrenceCoordinate or type(reference) is not K0OccurrenceRef:
        raise K0ProfileError("occurrence order requires exact coordinates")
    try:
        _K0OccurrenceCoordinate.__post_init__(coordinate)
        K0OccurrenceRef.__post_init__(reference)
    except (AttributeError, TypeError) as error:
        raise K0ProfileError("occurrence order coordinates are malformed") from error
    stage = (
        -1
        if coordinate.dependency_stage is None
        else coordinate.dependency_stage
    )
    return (
        stage,
        coordinate.causal_wave_depth,
        reference.value,
    )
