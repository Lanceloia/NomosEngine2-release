"""Canonical wire codec for one occurrence coordinate."""

from __future__ import annotations

from nomos_kernel import K0ProfileError
from nomos_kernel._canonical_wire import _read_wire_record, _wire_record
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._owner_abi import _K0CanonicalWirePayload


def _dump_occurrence_coordinate(
    coordinate: _K0OccurrenceCoordinate,
) -> _K0CanonicalWirePayload:
    if type(coordinate) is not _K0OccurrenceCoordinate:
        raise K0ProfileError("occurrence coordinate wire requires one exact coordinate")
    return _wire_record(
        "coordinate",
        (coordinate.dependency_stage, coordinate.causal_wave_depth),
    )


def _restore_occurrence_coordinate(
    wire: _K0CanonicalWirePayload,
) -> _K0OccurrenceCoordinate:
    dependency_stage, causal_wave_depth = _read_wire_record(wire, "coordinate", 2)
    return _K0OccurrenceCoordinate(dependency_stage, causal_wave_depth)  # type: ignore[arg-type]
