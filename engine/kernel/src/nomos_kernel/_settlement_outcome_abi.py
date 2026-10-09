"""Domain-neutral negative outcomes and settlement defect boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from nomos_kernel._coordinates import _K0TemporalInterval
from nomos_kernel._identity import K0OccurrenceRef, K0ProfileError, K0SourceSpecKey
from nomos_kernel._occurrence_record_abi import (
    _K0OccurrenceRecordView,
    _occurrence_order_key,
)
from nomos_kernel._terminal_settlement_abi import _K0SessionClosed


class K0SettlementDefect(RuntimeError):
    """A runtime capability violated an already validated machine contract."""


@dataclass(frozen=True)
class K0NotAdmitted:
    """Normal non-admission before an Action occurrence exists."""

    source: K0SourceSpecKey
    reason: Literal["not_admitted"] = "not_admitted"

    def __post_init__(self) -> None:
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("non-admission must name one exact source")
        if type(self.reason) is not str or self.reason != "not_admitted":
            raise K0ProfileError("non-admission reason is fixed")


@dataclass(frozen=True)
class _K0TemporalRejected:
    """Normal refusal of an illegal temporal interval."""

    reason: Literal["illegal_interval"] = "illegal_interval"

    def __post_init__(self) -> None:
        if type(self.reason) is not str or self.reason != "illegal_interval":
            raise K0ProfileError("temporal rejection reason is fixed")


def _publication_occurrence_identities(
    occurrences: tuple[_K0OccurrenceRecordView, ...],
) -> tuple[K0OccurrenceRef, ...]:
    identities: list[K0OccurrenceRef] = []
    for item in occurrences:
        try:
            reference = item.occurrence
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("publication occurrence reference is missing") from error
        if type(reference) is not K0OccurrenceRef:
            raise K0ProfileError("publication occurrence reference must be exact")
        try:
            K0OccurrenceRef.__post_init__(reference)
        except (AttributeError, TypeError) as error:
            raise K0ProfileError("publication occurrence reference is malformed") from error
        identities.append(reference)
    return tuple(identities)


@dataclass(frozen=True)
class K0Published:
    """Ephemeral receipt for exactly one quiescent root publication."""

    occurrences: tuple[_K0OccurrenceRecordView, ...]
    publication_count: Literal[1] = 1

    def __post_init__(self) -> None:
        if not self.occurrences:
            raise K0ProfileError("a K0 publication must contain at least one occurrence")
        identities = _publication_occurrence_identities(self.occurrences)
        if len(set(identities)) != len(identities):
            raise K0ProfileError("a K0 publication receipt cannot repeat occurrence identity")
        if any(not isinstance(item, _K0OccurrenceRecordView) for item in self.occurrences):
            raise K0ProfileError("publication must contain closed occurrence records")
        expected = tuple(sorted(self.occurrences, key=_occurrence_order_key))
        if self.occurrences != expected:
            raise K0ProfileError("K0 publication occurrences must use canonical wave order")


@dataclass(frozen=True)
class _K0TemporalPublished:
    interval: _K0TemporalInterval
    occurrences: tuple[_K0OccurrenceRecordView, ...]
    publication_count: Literal[1] = 1

    def __post_init__(self) -> None:
        if type(self.interval) is not _K0TemporalInterval:
            raise K0ProfileError("temporal publication must carry one exact interval")
        identities = _publication_occurrence_identities(self.occurrences)
        if len(set(identities)) != len(identities):
            raise K0ProfileError("temporal publication cannot repeat occurrence identity")
        if any(not isinstance(item, _K0OccurrenceRecordView) for item in self.occurrences):
            raise K0ProfileError("temporal publication must contain closed occurrence records")
        # A temporal publication consists of successive complete root closures,
        # not a single causal wave. Allocation order preserves those closures.
        for item in self.occurrences:
            _occurrence_order_key(item)
        if tuple(ref.value for ref in identities) != tuple(sorted(ref.value for ref in identities)):
            raise K0ProfileError("temporal publication occurrences must use execution order")


_K0TemporalAdvanceResult: TypeAlias = _K0TemporalRejected | _K0TemporalPublished | _K0SessionClosed
