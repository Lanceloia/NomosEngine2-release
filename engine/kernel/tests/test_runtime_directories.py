"""Storage indexes never replace validation, isolation or snapshot identity."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceFamily, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemorySession,
)
from nomos_kernel._candidate_owner_state_runtime import (
    _K0CandidateOwnerTopology,
    _K0OwnerStateCandidate,
)
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._owner_state_runtime import (
    _build_candidate_owner_views,
    _K0OwnerStateDirectory,
)
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_causal_wave_stage_isolation import (
    ACTION,
    ACTION_TYPE,
    EVENT_TYPE,
    OTHER_ACTION,
    OTHER_TYPE,
    OWNER,
    _law,
    _Owner,
    _Participants,
    _session,
    _Value,
)


def _candidate():
    owner = _Owner(OWNER)
    return _K0OwnerStateCandidate(
        _K0CandidateOwnerTopology((owner,)),
        (),
        (),
        (),
        (_K0OwnerState(OWNER, _Value(0)),),
        None,
        None,
        None,
    )


@pytest.mark.parametrize("shape", ["missing", "extra", "duplicate_state", "duplicate_owner"])
def test_directory_rejects_incomplete_or_duplicate_storage(shape):
    owner = _Owner(OWNER)
    owners = (owner, owner) if shape == "duplicate_owner" else (owner,)
    entry = _K0OwnerState(OWNER, _Value(0))
    states = {
        "missing": (),
        "extra": (entry, _K0OwnerState(K0OwnerKey("unknown"), _Value(0))),
        "duplicate_state": (entry, entry),
        "duplicate_owner": (entry,),
    }[shape]
    with pytest.raises(K0ProfileError, match="directory shape"):
        _K0OwnerStateDirectory(_K0CandidateOwnerTopology(owners), states)


def test_directory_reuses_exact_stage_and_replaces_it_after_write_and_formation():
    candidate = _candidate()
    first = candidate.owner_directory
    assert candidate.owner_directory is first
    with pytest.raises(TypeError):
        first.states[OWNER] = _Value(99)
    candidate._replace_owner_state(OWNER, _Value(0))
    second = candidate.owner_directory
    assert second is not first
    assert first.states[OWNER] == _Value(0)
    assert second.states[OWNER] == _Value(0)
    assert second.states[OWNER] is not first.states[OWNER]
    candidate._replace_owner_state(OWNER, _Value(3))
    new_owner = _Owner(K0OwnerKey("new"))
    candidate.stage_owner(new_owner, _Value(7))
    third = candidate.owner_directory
    assert third is not second
    assert new_owner.key not in second.owners
    assert candidate.owner_views((new_owner.key,))[0].view == _Value(7)
    assert candidate._state_for(OWNER) == _Value(3)


def test_cross_owner_invariant_reads_and_validates_each_new_stage():
    observed = []

    class Invariant:
        read_owners = (OWNER,)

        def validate(self, views):
            value = views[0].view.value
            observed.append(value)
            if value > 1:
                raise K0ProfileError("invariant rejected current stage")

    candidate = _candidate()
    candidate._invariants = (Invariant(),)
    candidate.validate_cross_owner_invariants()
    candidate._replace_owner_state(OWNER, _Value(1))
    candidate.validate_cross_owner_invariants()
    candidate._replace_owner_state(OWNER, _Value(2))
    with pytest.raises(K0ProfileError, match="current stage"):
        candidate.validate_cross_owner_invariants()
    assert observed == [0, 1, 2]


def test_repeated_directory_reads_still_validate_and_isolate_each_current_value(monkeypatch):
    candidate = _candidate()
    directory = candidate.owner_directory
    original = _Owner.read_view
    seen = []

    def read(owner, state):
        seen.append(state)
        return original(owner, state)

    monkeypatch.setattr(_Owner, "read_view", read)
    first = _build_candidate_owner_views(directory, (OWNER,))[0].view
    object.__setattr__(first, "value", 999)
    second = _build_candidate_owner_views(directory, (OWNER,))[0].view
    assert second == _Value(0)
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert all(state is not directory.states[OWNER] for state in seen)
    with pytest.raises(K0ProfileError):
        _build_candidate_owner_views(directory, (OWNER, OWNER))
    with pytest.raises(K0ProfileError):
        _build_candidate_owner_views(directory, (K0OwnerKey("unknown"),))

    def reject(owner, state):
        raise K0ProfileError("current validator rejected")

    monkeypatch.setattr(_Owner, "validate_state", reject)
    with pytest.raises(K0ProfileError, match="current validator"):
        _build_candidate_owner_views(directory, (OWNER,))


def test_declaration_index_keeps_profile_order_and_exact_source_identity():
    laws = (
        _law("empty", key="z"),
        _law("unexpected", key="other", trigger_type=OTHER_TYPE),
        _law("empty", key="a"),
    )
    session = _session(laws)
    assert session._laws_by_event[ACTION_TYPE] == (laws[0], laws[2])
    assert session._laws_by_event[OTHER_TYPE] == (laws[1],)
    assert session._laws_by_event.get(object(), ()) == ()
    assert all(session._sources_by_key[spec.key] is spec for spec in session._profile.source_specs)
    with pytest.raises(TypeError):
        session._sources_by_key[ACTION] = None
    with pytest.raises(K0ProfileError, match="no declared Action"):
        session.settle(_K0InMemoryActionAttempt(K0SourceSpecKey("unknown"), _Value(1)))


def test_session_directory_tracks_publication_but_not_failed_candidate():
    session = _session((_law("mutate_raise"),))
    initial = session._current_owner_directory()
    session.settle(_K0InMemoryActionAttempt(OTHER_ACTION, _Value(1)))
    committed = session._current_owner_directory()
    assert committed is not initial
    assert session.read_owner(OWNER).view == _Value(1)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert session._current_owner_directory() is committed
    assert committed.states[OWNER] == _Value(1)


@dataclass(frozen=True)
class _TwoActivations:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("two-activations")

    def project(self, trigger, views):
        return tuple(
            _K0Activation(str(index), _Value(index), _Participants(), ()) for index in range(2)
        )


@dataclass(frozen=True)
class _NoWrite:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("no-write")

    def evaluate(self, rule_input):
        return _K0InMemoryEvaluation(K0RuleResult((), ()), rule_input.evidence)


def test_indexed_bound_still_counts_one_law_across_multiple_same_wave_triggers():
    seed = replace(
        _law("empty", key="seed"), max_activations=2, activation_projector=_TwoActivations()
    )
    follow = _law("activate", key="follow", trigger_type=EVENT_TYPE)
    base = _session((seed, follow))
    profile = replace(
        base._profile,
        source_specs=tuple(
            replace(spec, contribution_owners=(), rule=_NoWrite())
            if spec.occurrence_family is K0OccurrenceFamily.EVENT
            else spec
            for spec in base._profile.source_specs
        ),
        max_events=5,
        max_waves=2,
    )
    session = _K0InMemorySession.create(profile, base._states)
    before = session._current_owner_directory()
    with pytest.raises(K0SettlementDefect) as failure:
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert isinstance(failure.value.__cause__, K0ProfileError)
    assert "exceeded the law bound" in str(failure.value.__cause__)
    assert session._current_owner_directory() is before
    assert session.occurrence_history() == () and session._fatal
