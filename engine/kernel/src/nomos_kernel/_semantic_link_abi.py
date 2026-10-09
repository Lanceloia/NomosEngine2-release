"""Transient semantic-link declarations owned by the causal kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._owner_abi import _validate_closed_host_object


@runtime_checkable
class _K0PreservedSemanticLinkRequirement(Protocol):
    """One closed owner-derived payload; it is never authoritative material."""

    def validate_for_k0(self) -> None: ...


@dataclass(frozen=True)
class _K0PreservedSemanticLink:
    """Transient exact refs used to route one closed semantic-link validation."""

    primary_occurrence: K0OccurrenceRef
    required_occurrences: tuple[K0OccurrenceRef, ...]
    requirement: _K0PreservedSemanticLinkRequirement

    def __post_init__(self) -> None:
        if (
            type(self.primary_occurrence) is not K0OccurrenceRef
            or type(self.required_occurrences) is not tuple
            or any(
                type(occurrence) is not K0OccurrenceRef
                for occurrence in self.required_occurrences
            )
            or self.required_occurrences != tuple(sorted(self.required_occurrences))
            or len(set(self.required_occurrences)) != len(self.required_occurrences)
            or self.primary_occurrence in self.required_occurrences
            or not isinstance(
                self.requirement, _K0PreservedSemanticLinkRequirement
            )
        ):
            raise K0ProfileError(
                "preserved semantic link must name canonical exact occurrences"
            )
        _validate_closed_host_object(
            self.requirement, "preserved semantic link requirement"
        )
        self.requirement.validate_for_k0()


@runtime_checkable
class _K0PreservedSemanticLinkOwner(Protocol):
    """Optional owner capability for transient semantic-link requirements."""

    def preserved_semantic_links(
        self, state: object
    ) -> tuple[_K0PreservedSemanticLink, ...]: ...
