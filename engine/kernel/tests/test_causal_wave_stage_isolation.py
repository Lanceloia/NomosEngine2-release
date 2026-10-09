"""Neutral settlement evidence for causal trigger filtering and stage isolation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryActionBasis,
    _K0InMemoryEvaluation,
    _K0InMemoryOccurrence,
    _K0InMemoryProfile,
    _K0InMemoryRuleInput,
    _K0InMemorySession,
    _K0InMemorySourceSpec,
)
from nomos_kernel._candidate_owner_state_runtime import _K0OwnerStateCandidate
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._occurrence_record_abi import _K0OccurrenceRecordView
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OccurrenceContribution, _K0OwnerView
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OccurrenceCursor, _K0OwnerState

OWNER = K0OwnerKey("owner.00")
ACTION = K0SourceSpecKey("action")
OTHER_ACTION = K0SourceSpecKey("other-action")
EVENT = K0SourceSpecKey("event")
ACTION_TYPE = K0EventTypeKey("type.action")
OTHER_TYPE = K0EventTypeKey("type.action.other")
EVENT_TYPE = K0EventTypeKey("type.event")


@dataclass(frozen=True)
class _Value:
    value: int

    def validate_for_k0(self) -> None:
        if type(self.value) is not int:
            raise K0ProfileError("value must be an exact int")


@dataclass(frozen=True)
class _Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Replace:
    owner: K0OwnerKey
    state: _Value

    def validate_for_k0(self) -> None:
        if type(self.owner) is not K0OwnerKey or type(self.state) is not _Value:
            raise K0ProfileError("invalid replacement")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey
    owner_version: str = "stage-isolation-v1"
    state_type: ClassVar[type] = _Value
    view_type: ClassVar[type] = _Value
    contribution_type: ClassVar[type] = _Replace
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not _Value:
            raise K0ProfileError("invalid state")
        state.validate_for_k0()

    def read_view(self, state: _Value) -> _Value:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: _Replace) -> None:
        if type(contribution) is not _Replace or contribution.owner != self.key:
            raise K0ProfileError("invalid owner contribution")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if len(contributions) != 1:
            raise K0ProfileError("one replacement required")
        return contributions

    def apply_contributions(
        self, state: _Value, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> _Value:
        self.validate_state(state)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("no local identity")

    def preserved_occurrences(self, state: _Value) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        return ()

    def encode_state(self, state: _Value) -> tuple[int]:
        self.validate_state(state)
        return (state.value,)

    def decode_state(self, wire: tuple[int]) -> _Value:
        if type(wire) is not tuple or len(wire) != 1:
            raise K0ProfileError("invalid state wire")
        state = _Value(wire[0])
        self.validate_state(state)
        return state


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("admission")

    def admit(
        self, payload: _Value, owner_views: tuple[_K0OwnerView, ...]
    ) -> _K0AdmissionProjection:
        return _K0AdmissionProjection(
            _Value(owner_views[0].view.value + payload.value), _Participants(), ()
        )


@dataclass(frozen=True)
class _Rule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("rule")

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        return _K0InMemoryEvaluation(
            K0RuleResult((_Replace(OWNER, rule_input.evidence),), ()), rule_input.evidence
        )


@dataclass(frozen=True)
class _Projector:
    capability_ref: _K0CapabilityRef
    mode: str

    def project(
        self, trigger: _K0OccurrenceRecordView, owner_views: tuple[_K0OwnerView, ...]
    ) -> tuple[_K0Activation, ...]:
        if self.mode == "unexpected":
            raise AssertionError("unmatched projector must not run")
        prior = owner_views[0].view.value
        if self.mode.startswith("mutate"):
            object.__setattr__(owner_views[0].view, "value", 999)
        if self.mode == "mutate_raise":
            raise K0ProfileError("projector failed after mutating its view")
        if self.mode in ("empty", "mutate_empty"):
            return ()
        return (_K0Activation(self.capability_ref.value, _Value(prior + 1), _Participants(), ()),)


def _law(
    mode: str, *, key: str = "law", trigger_type: K0EventTypeKey = ACTION_TYPE
) -> K0CausalLawDefinition:
    return K0CausalLawDefinition(
        K0CausalLawKey(key),
        trigger_type,
        EVENT,
        1,
        (OWNER,),
        _Projector(_K0CapabilityRef(key), mode),
    )


def _source(
    key: K0SourceSpecKey, family: K0OccurrenceFamily, event_type: K0EventTypeKey
) -> _K0InMemorySourceSpec:
    return _K0InMemorySourceSpec(
        key,
        family,
        event_type,
        _Value,
        _Value,
        _Participants,
        (OWNER,),
        (OWNER,),
        (),
        (),
        _Admission() if family is K0OccurrenceFamily.ACTION else None,
        _Rule(),
        _Value,
    )


def _session(
    laws: tuple[K0CausalLawDefinition, ...], *, owner_count: int = 2
) -> _K0InMemorySession:
    owners = tuple(_Owner(K0OwnerKey(f"owner.{index:02d}")) for index in range(owner_count))
    profile = _K0InMemoryProfile(
        owners,
        (
            _source(ACTION, K0OccurrenceFamily.ACTION, ACTION_TYPE),
            _source(OTHER_ACTION, K0OccurrenceFamily.ACTION, OTHER_TYPE),
            _source(EVENT, K0OccurrenceFamily.EVENT, EVENT_TYPE),
        ),
        laws,
        2,
        1,
    )
    return _K0InMemorySession.create(
        profile, tuple(_K0OwnerState(o.key, _Value(0)) for o in owners)
    )


def _stage_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    snapshots: list[tuple[object, ...]] = []
    original = _K0OwnerStateCandidate._snapshot_states

    def snapshot(candidate: _K0OwnerStateCandidate) -> tuple[_K0OwnerState, ...]:
        prior = candidate._states
        states = original(candidate)
        snapshots.append((candidate, prior, states))
        return states

    monkeypatch.setattr(_K0OwnerStateCandidate, "_snapshot_states", snapshot)
    return snapshots


def _expected_action(ordinal: int, value: int) -> _K0InMemoryOccurrence:
    return _K0InMemoryOccurrence(
        K0OccurrenceRef(ordinal),
        K0OccurrenceFamily.ACTION,
        ACTION,
        ACTION_TYPE,
        _K0InMemoryActionBasis(ACTION),
        _Participants(),
        _K0OccurrenceCoordinate(None, 0),
        _Value(value),
    )


@pytest.mark.parametrize("has_unmatched_law", [False, True])
def test_unmatched_trigger_skips_stage_snapshot_without_changing_publication(
    monkeypatch: pytest.MonkeyPatch, has_unmatched_law: bool
) -> None:
    laws = (_law("unexpected", trigger_type=OTHER_TYPE),) if has_unmatched_law else ()
    session = _session(laws)
    snapshots = _stage_spy(monkeypatch)
    for ordinal in (1, 2):
        result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        assert type(result) is K0Published
        assert result.occurrences == (_expected_action(ordinal, ordinal),)
        assert session._states == (
            _K0OwnerState(OWNER, _Value(ordinal)),
            _K0OwnerState(K0OwnerKey("owner.01"), _Value(0)),
        )
        assert session._cursor == _K0OccurrenceCursor(ordinal + 1)
        assert len(snapshots) == ordinal  # Only the publication snapshot remains.
    assert session.occurrence_history() == (_expected_action(1, 1), _expected_action(2, 2))


@pytest.mark.parametrize("mode", ["empty", "mutate_empty"])
def test_matching_zero_activation_shares_internal_stage_but_isolates_projector_input(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    session = _session((_law(mode),))
    snapshots = _stage_spy(monkeypatch)
    original = _Projector.project
    observed = []

    def project(projector, trigger, views):
        observed.append((len(snapshots), views[0].view))
        return original(projector, trigger, views)

    monkeypatch.setattr(_Projector, "project", project)
    result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert result.occurrences == (_expected_action(1, 1),)
    assert len(snapshots) == 2  # One trigger-stage snapshot, then publication.
    assert observed[0][0] == 1
    candidate, prior, pinned = snapshots[0]
    assert pinned is prior
    assert len(pinned) == len(session._states) == 2
    assert observed[0][1] is not pinned[0].state
    assert candidate._state_for(OWNER) == session._states[0].state == _Value(1)
    assert session._cursor == _K0OccurrenceCursor(2)


def test_matching_laws_keep_order_and_same_wave_state_despite_malicious_view_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    laws = (
        _law("mutate_empty", key="first"),
        _law("unexpected", key="unmatched", trigger_type=OTHER_TYPE),
        _law("activate", key="last"),
    )
    session = _session(laws)
    snapshots = _stage_spy(monkeypatch)
    original = _Projector.project
    observed = []

    def project(projector, trigger, views):
        observed.append((projector.capability_ref.value, trigger.occurrence, views[0].view.value))
        return original(projector, trigger, views)

    monkeypatch.setattr(_Projector, "project", project)
    result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert observed == [("first", K0OccurrenceRef(1), 1), ("last", K0OccurrenceRef(1), 1)]
    assert result.occurrences == (
        _expected_action(1, 1),
        _K0InMemoryOccurrence(
            K0OccurrenceRef(2),
            K0OccurrenceFamily.EVENT,
            EVENT,
            EVENT_TYPE,
            _K0CausalFormation(K0OccurrenceRef(1), K0CausalLawKey("last")),
            _Participants(),
            _K0OccurrenceCoordinate(None, 1),
            _Value(2),
        ),
    )
    assert session._states[0].state == _Value(2)
    assert session._cursor == _K0OccurrenceCursor(3)
    assert session.occurrence_history() == result.occurrences
    assert len(snapshots) == 2  # The unmatched leaf Event needs no stage snapshot.


def test_matching_malicious_projector_failure_keeps_live_state_and_rolls_back_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session((_law("mutate_raise"),))
    session.settle(_K0InMemoryActionAttempt(OTHER_ACTION, _Value(1)))
    snapshots = _stage_spy(monkeypatch)
    live = session._states
    cursor = session._cursor
    history = session.occurrence_history()
    with pytest.raises(K0SettlementDefect, match="engine defect") as error:
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert isinstance(error.value.__cause__, K0ProfileError)
    assert "projector failed" in str(error.value.__cause__)
    assert len(snapshots) == 1
    candidate, _, isolated = snapshots[0]
    assert candidate._state_for(OWNER) == isolated[0].state == _Value(2)
    assert session._states is live
    assert session._states[0].state == _Value(1)
    assert session._cursor is cursor
    assert session.occurrence_history() == history
    assert not session._settling
    with pytest.raises(K0SettlementDefect, match="fatal in-memory session"):
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
