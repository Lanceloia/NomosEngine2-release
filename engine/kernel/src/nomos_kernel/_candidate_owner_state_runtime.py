"""Domain-neutral owner-state candidate runtime shared by K sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nomos_kernel import (
    K0LocalIdentitySlot,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
)
from nomos_kernel._admission_abi import (
    _K0RuntimePropositionInvariant,
    _K0RuntimePropositionState,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._identity import _require_local_identity_slot
from nomos_kernel._owner_abi import (
    _K0CrossOwnerInvariant,
    _K0LocalIdentityValue,
    _K0OccurrenceContribution,
    _K0Owner,
    _K0OwnerView,
)
from nomos_kernel._owner_state_runtime import (
    _build_candidate_owner_views,
    _isolate_candidate_owner_state,
    _K0OwnerStateDirectory,
)
from nomos_kernel._state_image_abi import _K0OccurrenceCursor, _K0OwnerState


@runtime_checkable
class _K0DeclaredSourceLike(Protocol):
    """Structural source declaration consumed by candidate source views."""

    read_owners: tuple[K0OwnerKey, ...]


@dataclass(frozen=True)
class _K0CandidateOwnerTopology:
    """Minimal owner topology consumed by candidate view construction."""

    owners: tuple[_K0Owner, ...]

    def __post_init__(self) -> None:
        if type(self.owners) is not tuple or not self.owners:
            raise K0ProfileError("candidate owner topology is not closed")


class _K0OwnerStateCandidate:
    """Unpublishable isolated candidate state and candidate-local cursor."""

    def __init__(
        self,
        topology: _K0CandidateOwnerTopology,
        source_specs: tuple[_K0DeclaredSourceLike, ...],
        causal_laws: tuple[K0CausalLawDefinition, ...],
        cross_owner_invariants: tuple[_K0CrossOwnerInvariant, ...],
        owner_states: tuple[_K0OwnerState, ...],
        cursor: _K0OccurrenceCursor,
        time: _K0FixedTime | None,
        runtime_propositions: _K0RuntimePropositionState,
    ) -> None:
        if (
            type(topology) is not _K0CandidateOwnerTopology
            or type(owner_states) is not tuple
            or len(topology.owners) != len(owner_states)
            or any(
                owner.key != entry.owner
                for owner, entry in zip(topology.owners, owner_states, strict=True)
            )
        ):
            raise K0ProfileError("candidate owner topology is not closed")
        self._topology = topology
        self._source_specs = source_specs
        self._causal_laws = causal_laws
        self._invariants = cross_owner_invariants
        self._states = owner_states
        self._directory: _K0OwnerStateDirectory | None = None
        self._cursor = cursor
        self._time = time
        self._runtime_propositions = runtime_propositions

    @property
    def owners(self) -> tuple[_K0Owner, ...]:
        return self._topology.owners

    @property
    def topology(self) -> _K0CandidateOwnerTopology:
        return self._topology

    @property
    def time(self) -> _K0FixedTime | None:
        return self._time

    @property
    def owner_directory(self) -> _K0OwnerStateDirectory:
        directory = self._directory
        if (
            directory is None
            or directory.topology is not self._topology
            or directory.owner_states is not self._states
        ):
            directory = _K0OwnerStateDirectory(self._topology, self._states)
            self._directory = directory
        return directory

    def stage_owner(self, owner: _K0Owner, state: object) -> None:
        if not isinstance(owner, _K0Owner) or any(
            item.key == owner.key for item in self._topology.owners
        ):
            raise K0ProfileError("formed owner is not a fresh closed owner")
        isolated = _isolate_candidate_owner_state(owner, state)
        self._topology = _K0CandidateOwnerTopology((*self._topology.owners, owner))
        self._states = (*self._states, _K0OwnerState(owner.key, isolated))

    def _state_for(self, owner_key: K0OwnerKey) -> object:
        try:
            return self.owner_directory.states[owner_key]
        except KeyError as error:
            raise K0ProfileError("candidate requested an undeclared owner") from error

    def isolated_owner_state(self, owner_key: K0OwnerKey) -> object:
        owner = self.owner_directory.owners.get(owner_key)
        if owner is None:
            raise K0ProfileError("candidate requested an undeclared owner")
        return _isolate_candidate_owner_state(owner, self._state_for(owner_key))

    def owner_views(self, read_owners: tuple[K0OwnerKey, ...]) -> tuple[_K0OwnerView, ...]:
        return _build_candidate_owner_views(self.owner_directory, read_owners)

    def _snapshot_states(self) -> tuple[_K0OwnerState, ...]:
        """Pin an internal stage; never pass these states to executable callbacks.

        Entries already belong to K0: opening, formation and every replacement
        isolate incoming state. Updates replace entries rather than mutate them.
        Views and owner apply inputs still get independent isolated values.
        Consequently old stages and failed transactions retain their state,
        without copying owners that this transaction never changes.
        """
        return self._states

    def source_owner_views(self, spec: _K0DeclaredSourceLike) -> tuple[_K0OwnerView, ...]:
        if not any(spec is declared for declared in self._source_specs):
            raise K0ProfileError("candidate source read request is not profile-bound")
        return self.owner_views(spec.read_owners)

    def causal_owner_views(self, law: K0CausalLawDefinition) -> tuple[_K0OwnerView, ...]:
        if not any(law is declared for declared in self._causal_laws):
            raise K0ProfileError("candidate causal read request is not profile-bound")
        return self.owner_views(law.read_owners)

    def validate_cross_owner_invariants(self) -> None:
        """Private S2 seam for read-only validation after joint owner application."""
        for invariant in self._invariants:
            views = self.owner_views(invariant.read_owners)
            if isinstance(invariant, _K0RuntimePropositionInvariant):
                invariant.validate_with_runtime_propositions(views, self._runtime_propositions)
            else:
                invariant.validate(views)

    def allocate_occurrence(self) -> K0OccurrenceRef:
        occurrence = K0OccurrenceRef(self._cursor.next_value)
        self._cursor = _K0OccurrenceCursor(self._cursor.next_value + 1)
        return occurrence

    def materialize_local_identity(
        self, slot: K0LocalIdentitySlot, occurrence: K0OccurrenceRef
    ) -> _K0LocalIdentityValue:
        _require_local_identity_slot(slot, "candidate local identity slot")
        owner = self.owner_directory.owners.get(slot.owner)
        if owner is None or slot.output_family not in owner.local_identity_families:
            raise K0ProfileError("local identity slot owner/family is not profile-declared")
        prior_state = _isolate_candidate_owner_state(owner, self._state_for(slot.owner))
        updated_state, referent = owner.allocate_local_identity(prior_state, slot, occurrence)
        if updated_state is prior_state:
            raise K0ProfileError("local identity allocation must return a fresh owner state")
        self._replace_owner_state(slot.owner, _isolate_candidate_owner_state(owner, updated_state))
        return _K0LocalIdentityValue(occurrence, slot, referent)

    def apply_owner_contributions(
        self,
        owner_key: K0OwnerKey,
        contributions: tuple[_K0OccurrenceContribution, ...],
    ) -> None:
        """Private S2 seam: apply only one exact owner's occurrence-tagged values."""
        owner = self.owner_directory.owners.get(owner_key)
        if owner is None or not contributions:
            raise K0ProfileError(
                "candidate contribution apply requires one declared owner and values"
            )
        if any(item.contribution.owner != owner_key for item in contributions):
            raise K0ProfileError("candidate contribution apply crossed exact owner boundaries")
        for item in contributions:
            if type(item.contribution) is not owner.contribution_type:
                raise K0ProfileError("candidate contribution has the wrong exact owner type")
            owner.validate_contribution(item.contribution)
        merged = owner.merge_contributions(contributions)
        allowed_occurrences = {item.occurrence for item in contributions}
        if not merged or any(item.contribution.owner != owner_key for item in merged):
            raise K0ProfileError("owner merge returned malformed exact-owner contributions")
        for item in merged:
            if item.occurrence not in allowed_occurrences:
                raise K0ProfileError("owner merge invented an occurrence reference")
            if type(item.contribution) is not owner.contribution_type:
                raise K0ProfileError("owner merge returned the wrong exact contribution type")
            owner.validate_contribution(item.contribution)
        prior_state = _isolate_candidate_owner_state(owner, self._state_for(owner_key))
        updated_state = owner.apply_contributions(prior_state, merged)
        if updated_state is prior_state:
            raise K0ProfileError("owner contribution apply must return a fresh owner state")
        self._replace_owner_state(owner_key, _isolate_candidate_owner_state(owner, updated_state))

    def apply_verified_same_wave_state(self, owner_key: K0OwnerKey, state: object) -> None:
        """Install a trusted same-wave result without attributing it to one Event."""
        owner = self.owner_directory.owners.get(owner_key)
        if owner is None:
            raise K0ProfileError("same-wave state has no declared owner")
        owner.validate_state(state)
        self._replace_owner_state(owner_key, _isolate_candidate_owner_state(owner, state))

    def _replace_owner_state(self, owner_key: K0OwnerKey, state: object) -> None:
        replaced = False
        entries: list[_K0OwnerState] = []
        for entry in self._states:
            if entry.owner == owner_key:
                entries.append(_K0OwnerState(owner_key, state))
                replaced = True
            else:
                entries.append(entry)
        if not replaced:
            raise K0ProfileError("candidate attempted to replace an undeclared owner state")
        self._states = tuple(entries)
