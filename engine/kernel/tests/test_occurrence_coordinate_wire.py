"""Focused tests for the occurrence-coordinate wire boundary."""

from __future__ import annotations

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._occurrence_coordinate_wire import (
    _dump_occurrence_coordinate,
    _restore_occurrence_coordinate,
)


@pytest.mark.parametrize(
    "coordinate",
    (_K0OccurrenceCoordinate(None, 0), _K0OccurrenceCoordinate(2, 3)),
)
def test_coordinate_wire_round_trip_is_exact(
    coordinate: _K0OccurrenceCoordinate,
) -> None:
    wire = _dump_occurrence_coordinate(coordinate)
    assert _restore_occurrence_coordinate(wire) == coordinate
    assert _restore_occurrence_coordinate(wire) is not coordinate


@pytest.mark.parametrize(
    "wire",
    (
        ("foreign", None, 0),
        ("coordinate", None),
        ("coordinate", None, False),
        ("coordinate", -1, 0),
        ("coordinate", None, -1),
    ),
)
def test_coordinate_wire_rejects_malformed_values(wire: object) -> None:
    with pytest.raises(K0ProfileError):
        _restore_occurrence_coordinate(wire)  # type: ignore[arg-type]


def test_coordinate_wire_dump_requires_the_exact_carrier() -> None:
    with pytest.raises(K0ProfileError, match="exact coordinate"):
        _dump_occurrence_coordinate(object())  # type: ignore[arg-type]
