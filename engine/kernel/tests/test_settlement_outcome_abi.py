from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._coordinates import (
    _K0FixedTime,
    _K0OccurrenceCoordinate,
    _K0TemporalInterval,
)
from nomos_kernel._settlement_outcome_abi import (
    K0NotAdmitted,
    K0Published,
    K0SettlementDefect,
    _K0TemporalPublished,
    _K0TemporalRejected,
)


class SourceEqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


@dataclass(frozen=True)
class _Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Occurrence:
    occurrence: K0OccurrenceRef
    family: K0OccurrenceFamily
    source: K0SourceSpecKey
    classification: K0EventTypeKey
    formation_basis: object
    participants: _Participants
    coordinate: _K0OccurrenceCoordinate
    semantic_envelope: object


def _occurrence(value: int, stage: int | None, wave: int) -> _Occurrence:
    return _Occurrence(
        K0OccurrenceRef(value),
        K0OccurrenceFamily.EVENT,
        K0SourceSpecKey("test-source"),
        K0EventTypeKey("test-event"),
        object(),
        _Participants(),
        _K0OccurrenceCoordinate(stage, wave),
        (),
    )


def _published(occurrences: tuple[object, ...], *, temporal: bool) -> object:
    if temporal:
        return _K0TemporalPublished(
            _K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(1)), occurrences
        )
    return K0Published(occurrences)


def test_negative_outcomes_are_exact_closed_values() -> None:
    source = K0SourceSpecKey("test-source")
    assert K0NotAdmitted(source).source == source
    assert _K0TemporalRejected().reason == "illegal_interval"
    assert issubclass(K0SettlementDefect, RuntimeError)


def test_negative_outcomes_reject_foreign_and_post_mutated_values() -> None:
    with pytest.raises(K0ProfileError):
        K0NotAdmitted(SourceEqualitySpoof())
    with pytest.raises(K0ProfileError):
        replace(K0NotAdmitted(K0SourceSpecKey("test-source")), reason="foreign")
    rejected = _K0TemporalRejected()
    object.__setattr__(rejected, "reason", "foreign")
    with pytest.raises(K0ProfileError):
        rejected.__post_init__()


def test_publication_outcomes_require_canonical_unique_occurrence_order() -> None:
    first = _occurrence(1, None, 0)
    second = _occurrence(2, 0, 1)
    assert K0Published((first, second)).occurrences == (first, second)
    interval = _K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(1))
    assert _K0TemporalPublished(interval, (first, second)).interval == interval

    with pytest.raises(K0ProfileError):
        K0Published(())
    with pytest.raises(K0ProfileError):
        K0Published((second, first))
    with pytest.raises(K0ProfileError):
        K0Published((first, first))
    with pytest.raises(K0ProfileError):
        _K0TemporalPublished(interval, (second, first))
    with pytest.raises(K0ProfileError):
        _K0TemporalPublished(interval, (first, first))


@pytest.mark.parametrize("temporal", (False, True))
def test_duplicate_identity_precedes_order_coordinate_validation(temporal: bool) -> None:
    broken = replace(_occurrence(1, None, 0), coordinate=object.__new__(_K0OccurrenceCoordinate))
    with pytest.raises(K0ProfileError, match="repeat occurrence identity"):
        _published((broken, broken), temporal=temporal)


@pytest.mark.parametrize("temporal", (False, True))
def test_publication_rejects_hollow_record_and_reference_finitely(temporal: bool) -> None:
    hollow_ref = replace(_occurrence(1, None, 0), occurrence=object.__new__(K0OccurrenceRef))
    for record in (object(), object.__new__(_Occurrence), hollow_ref):
        with pytest.raises(K0ProfileError):
            _published((record,), temporal=temporal)


@pytest.mark.parametrize("temporal", (False, True))
def test_publication_rejects_incomplete_or_post_mutated_record(temporal: bool) -> None:
    incomplete = SimpleNamespace(
        occurrence=K0OccurrenceRef(1), coordinate=_K0OccurrenceCoordinate(None, 0)
    )
    with pytest.raises(K0ProfileError):
        _published((incomplete,), temporal=temporal)
    ref = K0OccurrenceRef(1)
    object.__setattr__(ref, "value", True)
    with pytest.raises(K0ProfileError):
        _published((replace(_occurrence(1, None, 0), occurrence=ref),), temporal=temporal)
