"""Private contracts for one profile-declared standalone Event root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel import K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0DeclaredSourceInput,
    _K0OwnerView,
    _K0SealedBinding,
    _K0SealedEvidence,
    _require_unique,
)


@dataclass(frozen=True)
class _K0StandaloneEventFormation:
    """Private profile-declared non-volitional Event-root marker."""

    definition: K0SourceSpecKey

    def __post_init__(self) -> None:
        if type(self.definition) is not K0SourceSpecKey:
            raise K0ProfileError("standalone Event formation has no exact definition")


@dataclass(frozen=True)
class _K0StandaloneEventRequest:
    """Closed focus for one profile-declared standalone Event root."""

    definition: K0SourceSpecKey
    focus: _K0DeclaredSourceInput

    def __post_init__(self) -> None:
        if type(self.definition) is not K0SourceSpecKey or not isinstance(
            self.focus, _K0DeclaredSourceInput
        ):
            raise K0ProfileError("standalone Event request is not closed")
        self.focus.validate_for_k0()


@dataclass(frozen=True)
class _K0StandaloneEventResolution:
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]

    def __post_init__(self) -> None:
        if type(self.bindings) is not tuple:
            raise K0ProfileError(
                "standalone Event resolution bindings must be an exact tuple"
            )


@runtime_checkable
class _K0StandaloneEventResolver(Protocol):
    capability_ref: _K0CapabilityRef

    def resolve(
        self, focus: _K0DeclaredSourceInput, owner_views: tuple[_K0OwnerView, ...]
    ) -> _K0StandaloneEventResolution | None: ...


@dataclass(frozen=True)
class _K0StandaloneEventDefinition:
    source: K0SourceSpecKey
    focus_type: type[object]
    read_owners: tuple[K0OwnerKey, ...]
    resolver: _K0StandaloneEventResolver

    def __post_init__(self) -> None:
        if (
            type(self.source) is not K0SourceSpecKey
            or not isinstance(self.focus_type, type)
            or not isinstance(self.resolver, _K0StandaloneEventResolver)
            or not isinstance(self.resolver.capability_ref, _K0CapabilityRef)
        ):
            raise K0ProfileError("standalone Event definition is malformed")
        _require_unique(self.read_owners, "standalone Event read owners")
        object.__setattr__(self, "read_owners", tuple(sorted(self.read_owners)))
