"""Explicit same-wave policy and rollback without an obsolete C0 catalog."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0CausalLawKey, K0EventTypeKey, K0OccurrenceFamily, K0ProfileError
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryProfile,
    _K0InMemorySession,
)
from nomos_kernel._identity import K0SourceSpecKey
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_causal_wave_stage_isolation import (
    ACTION,
    ACTION_TYPE,
    EVENT,
    EVENT_TYPE,
    OWNER,
    _law,
    _Owner,
    _source,
    _Value,
)

SECOND_EVENT = K0SourceSpecKey("event.second")


@dataclass(frozen=True)
class _Policy:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.same-wave.sum")
    owner: object = OWNER
    sources: tuple = (EVENT, SECOND_EVENT)
    law_keys: tuple = (K0CausalLawKey("first"), K0CausalLawKey("second"))
    trigger_source: object = ACTION
    trigger_event: object = ACTION_TYPE
    reject: bool = False

    def merge(self, prior, proposals):
        if self.reject:
            raise K0ProfileError("selected policy rejects this wave")
        assert tuple(row.source for row in proposals) == self.sources
        assert len({row.rule_input.occurrence for row in proposals}) == 2
        return _Value(
            prior.value
            + sum(row.result.contributions[0].state.value - prior.value for row in proposals)
        )


@dataclass(frozen=True)
class _LimitedOwner(_Owner):
    def validate_state(self, state):
        super().validate_state(state)
        if state.value >= 3:
            raise K0ProfileError("combined state exceeds the selected invariant")


def _session(policy, *, limited=False):
    profile = _K0InMemoryProfile(
        ((_LimitedOwner if limited else _Owner)(OWNER),),
        (
            _source(ACTION, K0OccurrenceFamily.ACTION, ACTION_TYPE),
            _source(EVENT, K0OccurrenceFamily.EVENT, EVENT_TYPE),
            _source(SECOND_EVENT, K0OccurrenceFamily.EVENT, K0EventTypeKey("type.event.second")),
        ),
        (
            _law("activate", key="first"),
            replace(_law("activate", key="second"), resulting_source=SECOND_EVENT),
        ),
        3,
        1,
        same_wave_policy=policy,
    )
    return _K0InMemorySession.create(profile, (_K0OwnerState(OWNER, _Value(0)),))


def test_explicit_policy_preserves_two_events_and_both_effects():
    session = _session(_Policy())
    result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert isinstance(result, K0Published)
    assert [row.source for row in result.occurrences] == [ACTION, EVENT, SECOND_EVENT]
    assert session.read_owner(OWNER).view == _Value(3)
    assert all(row.semantic_envelope == _Value(2) for row in result.occurrences[1:])
    assert all(
        row.formation_basis.predecessor == result.occurrences[0].occurrence
        for row in result.occurrences[1:]
    )


@pytest.mark.parametrize("case", ["unselected", "rejected", "joint_invariant"])
def test_conflict_or_failed_merge_rolls_back_the_entire_action(case):
    policy = None if case == "unselected" else _Policy(reject=case == "rejected")
    session = _session(policy, limited=case == "joint_invariant")
    before = (session._states, session.occurrence_history(), session._cursor)
    with pytest.raises(K0SettlementDefect) as failure:
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    expected = {
        "unselected": "effect-preservation proof",
        "rejected": "selected policy rejects this wave",
        "joint_invariant": "combined state exceeds the selected invariant",
    }[case]
    assert expected in str(failure.value.__cause__)
    assert (session._states, session.occurrence_history(), session._cursor) == before
    assert session._fatal is True


@pytest.mark.parametrize("field", ["sources", "law_keys"])
def test_policy_must_bind_exact_registered_law_and_source_ports(field):
    policy = _Policy()
    changed = replace(policy, **{field: tuple(reversed(getattr(policy, field)))})
    with pytest.raises(K0ProfileError, match="exact Event owner ports"):
        _session(changed)
