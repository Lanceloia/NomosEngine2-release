"""Focused tests for the domain-neutral occurrence read boundary."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._occurrence_record_abi import _K0OccurrenceRecordView, _occurrence_order_key
from nomos_kernel._settlement_outcome_abi import K0Published


@dataclass(frozen=True)
class _Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Record:
    occurrence: K0OccurrenceRef
    family: K0OccurrenceFamily
    source: K0SourceSpecKey
    classification: K0EventTypeKey
    formation_basis: object
    participants: _Participants
    coordinate: _K0OccurrenceCoordinate
    semantic_envelope: object


def _record(
    coordinate: _K0OccurrenceCoordinate,
    occurrence: K0OccurrenceRef | None = None,
) -> _Record:
    return _Record(
        K0OccurrenceRef(1) if occurrence is None else occurrence,
        K0OccurrenceFamily.EVENT,
        K0SourceSpecKey("test-source"),
        K0EventTypeKey("test-event"),
        object(),
        _Participants(),
        coordinate,
        ("closed-envelope",),
    )


def test_occurrence_record_view_is_structural_and_read_only() -> None:
    record = _record(_K0OccurrenceCoordinate(None, 0))
    assert isinstance(record, _K0OccurrenceRecordView)
    assert record.occurrence == K0OccurrenceRef(1)


def test_publication_order_preserves_valid_stage_wave_and_reference_order() -> None:
    first = _record(_K0OccurrenceCoordinate(None, 0), K0OccurrenceRef(1))
    later = _record(_K0OccurrenceCoordinate(0, 1), K0OccurrenceRef(2))
    assert _occurrence_order_key(first) == (-1, 0, 1)
    assert _occurrence_order_key(later) == (0, 1, 2)
    assert K0Published((first, later)).occurrences == (first, later)


def test_publication_order_rejects_hollow_coordinate_finitely() -> None:
    record = _record(object.__new__(_K0OccurrenceCoordinate))
    with pytest.raises(K0ProfileError):
        K0Published((record,))


def test_publication_order_reenters_nested_order_coordinates() -> None:
    coordinate = _K0OccurrenceCoordinate(None, 0)
    object.__setattr__(coordinate, "causal_wave_depth", True)
    with pytest.raises(K0ProfileError):
        _occurrence_order_key(_record(coordinate))

    occurrence = K0OccurrenceRef(1)
    object.__setattr__(occurrence, "value", True)
    with pytest.raises(K0ProfileError):
        K0Published((_record(_K0OccurrenceCoordinate(None, 0), occurrence),))
