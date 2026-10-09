"""Temporal resolver and formation validation for the causal machine."""

from __future__ import annotations

from typing import Protocol

from nomos_kernel import K0ProfileError, K0SourceSpecKey
from nomos_kernel._coordinates import _K0FixedTime, _K0OccurrenceCoordinate
from nomos_kernel._owner_abi import _K0ClosedParticipants
from nomos_kernel._temporal_abi import (
    _K0TemporalDefinition,
    _K0TemporalFormation,
    _K0TemporalResolution,
)


class _K0TemporalSourceSpec(Protocol):
    key: K0SourceSpecKey
    evidence_type: type[object]
    participants_type: type[object]
    binding_keys: tuple[str, ...]
    binding_types: tuple[type[object], ...]


def _validate_temporal_resolution(
    spec: _K0TemporalSourceSpec,
    resolution: _K0TemporalResolution,
) -> None:
    if type(resolution) is not _K0TemporalResolution:
        raise K0ProfileError("temporal resolver returned a malformed result")
    # Re-enter the carrier law so post-construction mutation cannot slip past.
    _K0TemporalResolution.__post_init__(resolution)
    if resolution.kind != "change":
        return
    if type(resolution.evidence) is not spec.evidence_type:
        raise K0ProfileError(
            "temporal resolution evidence has the wrong source carrier"
        )
    if type(resolution.participants) is not spec.participants_type:
        raise K0ProfileError(
            "temporal resolution participants have the wrong source carrier"
        )
    keys = tuple(binding.key for binding in resolution.bindings)
    if keys != spec.binding_keys or tuple(
        type(binding) for binding in resolution.bindings
    ) != (spec.binding_types):
        raise K0ProfileError(
            "temporal resolution bindings do not match the source declaration"
        )


def _validate_temporal_formation(
    profile: object,
    definition: _K0TemporalDefinition,
    spec: _K0TemporalSourceSpec,
    formation: _K0TemporalFormation,
    *,
    occurrence_participants: _K0ClosedParticipants | None = None,
    authoritative_time: _K0FixedTime | None = None,
) -> None:
    if type(formation) is not _K0TemporalFormation:
        raise K0ProfileError("temporal basis codec returned a malformed formation")
    if (
        formation.definition != definition.key
        or formation.definition_version != definition.version
        or definition.source != spec.key
        or formation.coordinate
        != _K0OccurrenceCoordinate(definition.dependency_stage, 0)
    ):
        raise K0ProfileError(
            "temporal formation conflicts with its exact definition"
        )
    if (
        authoritative_time is not None
        and formation.interval.t1.ordinal > authoritative_time.ordinal
    ):
        raise K0ProfileError(
            "preserved temporal formation interval exceeds world time"
        )
    if type(formation.focus) is not definition.focus_type or not any(
        formation.focus == declared for declared in definition.focuses
    ):
        raise K0ProfileError("temporal formation has an unknown exact focus")
    resolution = _K0TemporalResolution(
        "change",
        formation.evidence,
        formation.participants,
        formation.bindings,
    )
    _validate_temporal_resolution(spec, resolution)
    if (
        occurrence_participants is not None
        and formation.participants != occurrence_participants
    ):
        raise K0ProfileError(
            "temporal formation participants conflict with the occurrence"
        )
    _ = profile
