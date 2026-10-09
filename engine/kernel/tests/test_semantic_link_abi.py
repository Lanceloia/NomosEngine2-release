"""Focused tests for transient semantic-link declarations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._semantic_link_abi import _K0PreservedSemanticLink


@dataclass(frozen=True)
class _Requirement:
    label: str

    def validate_for_k0(self) -> None:
        if type(self.label) is not str or not self.label:
            raise K0ProfileError("requirement label is malformed")


def test_semantic_link_keeps_canonical_distinct_occurrence_refs() -> None:
    link = _K0PreservedSemanticLink(
        K0OccurrenceRef(3),
        (K0OccurrenceRef(1), K0OccurrenceRef(2)),
        _Requirement("test"),
    )
    assert link.required_occurrences == (K0OccurrenceRef(1), K0OccurrenceRef(2))


@pytest.mark.parametrize(
    ("primary", "required"),
    (
        (K0OccurrenceRef(1), (K0OccurrenceRef(1),)),
        (K0OccurrenceRef(3), (K0OccurrenceRef(2), K0OccurrenceRef(1))),
        (K0OccurrenceRef(3), (K0OccurrenceRef(1), K0OccurrenceRef(1))),
    ),
)
def test_semantic_link_rejects_ambiguous_occurrence_topology(
    primary: K0OccurrenceRef,
    required: tuple[K0OccurrenceRef, ...],
) -> None:
    with pytest.raises(K0ProfileError, match="canonical exact occurrences"):
        _K0PreservedSemanticLink(primary, required, _Requirement("test"))


def test_semantic_link_rejects_mutable_or_invalid_requirements() -> None:
    class MutableRequirement:
        def validate_for_k0(self) -> None:
            return None

    with pytest.raises(K0ProfileError, match="recursively frozen"):
        _K0PreservedSemanticLink(
            K0OccurrenceRef(2),
            (K0OccurrenceRef(1),),
            MutableRequirement(),
        )
    with pytest.raises(K0ProfileError, match="requirement label"):
        _K0PreservedSemanticLink(
            K0OccurrenceRef(2),
            (K0OccurrenceRef(1),),
            _Requirement(""),
        )
