"""Private temporal definition, resolver-result and formation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from nomos_kernel import K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._coordinates import (
    _K0FixedTime,
    _K0OccurrenceCoordinate,
    _K0TemporalInterval,
)
from nomos_kernel._owner_abi import (
    _checked_label,
    _K0CanonicalWirePayload,
    _K0CapabilityRef,
    _K0ClosedParticipants,
    _K0OwnerView,
    _K0SealedBinding,
    _K0SealedEvidence,
    _require_unique,
    _validate_closed_host_object,
)


@runtime_checkable
class _K0QuiescentOwnerTimeValidator(Protocol):
    """Optional owner-local validation against authoritative fixed time."""

    def validate_quiescent_state_at_time(
        self, state: object, time: _K0FixedTime
    ) -> None: ...


@dataclass(frozen=True, order=True)
class _K0TemporalDefinitionKey:
    value: str

    def __post_init__(self) -> None:
        _checked_label(self.value, "temporal definition key")


@runtime_checkable
class _K0TemporalFocus(Protocol):
    @property
    def canonical_key(self) -> str: ...

    def validate_for_k0(self) -> None: ...


@dataclass(frozen=True)
class _K0TemporalResolution:
    """Closed Slice-1 resolver result; change formation is deliberately deferred."""

    kind: Literal["change", "no_change", "not_applicable"]
    evidence: _K0SealedEvidence | None = None
    participants: _K0ClosedParticipants | None = None
    bindings: tuple[_K0SealedBinding, ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in (
            "change",
            "no_change",
            "not_applicable",
        ):
            raise K0ProfileError("temporal resolution has an unknown kind")
        if type(self.bindings) is not tuple:
            raise K0ProfileError("temporal resolution bindings must be an exact tuple")
        if self.kind != "change":
            if self.evidence is not None or self.participants is not None or self.bindings:
                raise K0ProfileError("no-output temporal resolution cannot carry a payload")
            return
        if not isinstance(self.evidence, _K0SealedEvidence):
            raise K0ProfileError("temporal change resolution lacks sealed evidence")
        if not isinstance(self.participants, _K0ClosedParticipants):
            raise K0ProfileError("temporal change resolution lacks closed participants")
        self.evidence.validate_for_k0()
        self.participants.validate_for_k0()
        for binding in self.bindings:
            if not isinstance(binding, _K0SealedBinding):
                raise K0ProfileError("temporal change resolution has an unsealed binding")
            binding.validate_for_k0()
        keys = tuple(binding.key for binding in self.bindings)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise K0ProfileError("temporal change bindings must be unique and canonical-order")


@runtime_checkable
class _K0TemporalResolver(Protocol):
    capability_ref: _K0CapabilityRef

    def resolve(
        self,
        interval: _K0TemporalInterval,
        focus: _K0TemporalFocus,
        owner_views: tuple[_K0OwnerView, ...],
    ) -> _K0TemporalResolution: ...


@runtime_checkable
class _K0TemporalBasisCodec(Protocol):
    capability_ref: _K0CapabilityRef

    def encode(self, basis: _K0TemporalFormation) -> _K0CanonicalWirePayload: ...

    def decode(self, wire: _K0CanonicalWirePayload) -> _K0TemporalFormation: ...


@dataclass(frozen=True)
class _K0TemporalDefinition:
    key: _K0TemporalDefinitionKey
    version: str
    dependency_stage: int
    depends_on: tuple[_K0TemporalDefinitionKey, ...]
    source: K0SourceSpecKey
    focus_type: type[object]
    focuses: tuple[_K0TemporalFocus, ...]
    read_owners: tuple[K0OwnerKey, ...]
    resolver: _K0TemporalResolver
    basis_codec: _K0TemporalBasisCodec

    def __post_init__(self) -> None:
        if type(self.key) is not _K0TemporalDefinitionKey:
            raise K0ProfileError("temporal definition key must be exact")
        _checked_label(self.version, "temporal definition version")
        if type(self.dependency_stage) is not int or self.dependency_stage < 0:
            raise K0ProfileError("temporal dependency stage must be a non-negative int")
        if type(self.source) is not K0SourceSpecKey:
            raise K0ProfileError("temporal definition source must be exact")
        if type(self.depends_on) is not tuple:
            raise K0ProfileError("temporal definition dependencies must be an exact tuple")
        if any(type(dependency) is not _K0TemporalDefinitionKey for dependency in self.depends_on):
            raise K0ProfileError("temporal definition dependency key must be exact")
        if type(self.focuses) is not tuple:
            raise K0ProfileError("temporal definition focuses must be an exact tuple")
        if type(self.read_owners) is not tuple:
            raise K0ProfileError("temporal definition read owners must be an exact tuple")
        if any(type(owner) is not K0OwnerKey for owner in self.read_owners):
            raise K0ProfileError("temporal definition read owner must be exact")
        if not isinstance(self.focus_type, type):
            raise K0ProfileError("temporal focus type must be one exact closed focus carrier")
        if not isinstance(self.resolver, _K0TemporalResolver) or not isinstance(
            self.resolver.capability_ref, _K0CapabilityRef
        ):
            raise K0ProfileError("temporal definition must bind one stable resolver capability")
        if not isinstance(self.basis_codec, _K0TemporalBasisCodec) or not isinstance(
            self.basis_codec.capability_ref, _K0CapabilityRef
        ):
            raise K0ProfileError("temporal definition must bind one stable basis codec")
        _require_unique(self.depends_on, "temporal definition dependencies")
        _require_unique(self.read_owners, "temporal definition read owners")
        checked_focuses: list[_K0TemporalFocus] = []
        for focus in self.focuses:
            if type(focus) is not self.focus_type or not isinstance(focus, _K0TemporalFocus):
                raise K0ProfileError("temporal focus has the wrong exact closed carrier type")
            _validate_closed_host_object(focus, "temporal focus")
            focus.validate_for_k0()
            _checked_label(focus.canonical_key, "temporal focus canonical key")
            checked_focuses.append(focus)
        focus_keys = tuple(focus.canonical_key for focus in checked_focuses)
        if focus_keys != tuple(sorted(focus_keys)) or len(set(focus_keys)) != len(focus_keys):
            raise K0ProfileError("temporal focuses must be unique and canonical-order")
        object.__setattr__(self, "depends_on", tuple(sorted(self.depends_on)))
        object.__setattr__(self, "read_owners", tuple(sorted(self.read_owners)))


@dataclass(frozen=True)
class _K0TemporalFormation:
    definition: _K0TemporalDefinitionKey
    definition_version: str
    interval: _K0TemporalInterval
    coordinate: _K0OccurrenceCoordinate
    focus: _K0TemporalFocus
    evidence: _K0SealedEvidence
    participants: _K0ClosedParticipants
    bindings: tuple[_K0SealedBinding, ...]

    def __post_init__(self) -> None:
        if type(self.definition) is not _K0TemporalDefinitionKey:
            raise K0ProfileError("temporal formation definition key must be exact")
        _checked_label(self.definition_version, "temporal formation definition version")
        if type(self.interval) is not _K0TemporalInterval:
            raise K0ProfileError("temporal formation interval must be exact")
        if (
            type(self.coordinate) is not _K0OccurrenceCoordinate
            or self.coordinate.dependency_stage is None
            or self.coordinate.causal_wave_depth != 0
        ):
            raise K0ProfileError("temporal formation must use one exact stage root coordinate")
        if not isinstance(self.focus, _K0TemporalFocus):
            raise K0ProfileError("temporal formation focus must be exact")
        _validate_closed_host_object(self.focus, "temporal formation focus")
        self.focus.validate_for_k0()
        _checked_label(self.focus.canonical_key, "temporal formation focus canonical key")
        if not isinstance(self.evidence, _K0SealedEvidence):
            raise K0ProfileError("temporal formation evidence must be sealed")
        if not isinstance(self.participants, _K0ClosedParticipants):
            raise K0ProfileError("temporal formation participants must be closed")
        self.evidence.validate_for_k0()
        self.participants.validate_for_k0()
        if type(self.bindings) is not tuple:
            raise K0ProfileError("temporal formation bindings must be an exact tuple")
        for binding in self.bindings:
            if not isinstance(binding, _K0SealedBinding):
                raise K0ProfileError("temporal formation binding must be sealed")
            binding.validate_for_k0()
        keys = tuple(binding.key for binding in self.bindings)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise K0ProfileError("temporal formation bindings must be unique and canonical-order")
