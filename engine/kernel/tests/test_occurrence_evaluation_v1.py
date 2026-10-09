"""One exact evaluation is consumed per occurrence on every in-memory path."""

from collections import Counter
from dataclasses import dataclass, fields, replace

import pytest
from nomos_kernel import K0CausalLawKey, K0EventTypeKey, K0ProfileError
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemorySession,
    _K0InMemorySourceSpec,
)
from nomos_kernel._coordinates import _K0FixedTime, _K0TemporalAdvanceRequest, _K0TemporalInterval
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._settlement_outcome_abi import (
    K0Published,
    K0SettlementDefect,
    _K0TemporalPublished,
)
from nomos_kernel._state_image_abi import _K0OwnerState
from test_causal_object_formation_v1 import (
    EVENT,
    FORM,
    SCENE,
    SECOND,
    _OrderedPolicy,
    _Payload,
    _ProductRule,
    _profile,
    _Projector,
    _State,
)
from test_event_jump_inmemory import FINISH, OWNER, START, _Attempt, _session


@dataclass(frozen=True)
class _ObservedRule:
    original: object
    target: object
    fault: str
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.evaluation.observer")

    def evaluate(self, rule_input):
        evaluation = self.original.evaluate(rule_input)
        if rule_input.source != self.target:
            return evaluation
        if self.fault == "old_result":
            return evaluation.result
        if self.fault == "pair":
            return (evaluation.result, evaluation.envelope)
        if self.fault == "result":
            return replace(evaluation, result=None)
        if self.fault == "envelope":
            return replace(evaluation, envelope=None)
        if self.fault == "construction":
            raise K0ProfileError("publication construction failed")
        return evaluation


def runtime_and_operation(path, fault=""):
    if path in ("action", "due"):
        base = _session()
        profile = base._profile
        states = base._states
        target = START if path == "action" else FINISH
        initial_time = _K0FixedTime(0)
    else:
        profile = _profile()
        states = (_K0OwnerState(SCENE, _State(0)),)
        target = EVENT
        initial_time = None
        if path == "ordered":
            action, event = profile.source_specs
            first = replace(event, contribution_owners=(SCENE,), rule=_ProductRule(write=True))
            second = replace(
                first,
                key=SECOND,
                event_type=K0EventTypeKey("individual.second.event"),
            )
            law = profile.causal_laws[0]
            other = replace(
                law,
                key=K0CausalLawKey("individual.second.law"),
                resulting_source=SECOND,
                activation_projector=_Projector(target=SECOND),
            )
            profile = replace(
                profile,
                source_specs=(action, first, second),
                causal_laws=(law, other),
                max_events=3,
                ordered_policy=_OrderedPolicy(),
            )
            target = SECOND
    profile = replace(
        profile,
        source_specs=tuple(
            replace(spec, rule=_ObservedRule(spec.rule, target, fault))
            for spec in profile.source_specs
        ),
    )
    runtime = _K0InMemorySession.create(profile, states, initial_time=initial_time)
    if path == "due":
        runtime.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))

    def operation():
        if path == "due":
            return runtime.advance(
                _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(3)))
            )
        if path == "action":
            return runtime.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
        return runtime.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))

    return runtime, operation, OWNER if path in ("action", "due") else SCENE


@pytest.mark.parametrize("path", ["action", "due", "causal", "ordered"])
def test_every_occurrence_consumes_one_current_evaluation(path, monkeypatch):
    runtime, operation, _ = runtime_and_operation(path)
    calls = []
    original = _ObservedRule.evaluate

    def observe(self, rule_input):
        calls.append((rule_input.source, rule_input.occurrence))
        return original(self, rule_input)

    monkeypatch.setattr(_ObservedRule, "evaluate", observe)
    published = operation()
    assert isinstance(published, _K0TemporalPublished if path == "due" else K0Published)
    assert calls == [(item.source, item.occurrence) for item in published.occurrences]
    assert set(Counter(calls).values()) == {1}


@pytest.mark.parametrize("path", ["action", "due", "causal", "ordered"])
@pytest.mark.parametrize("fault", ["old_result", "pair", "result", "envelope", "construction"])
def test_invalid_product_or_publication_rolls_back_entire_operation(path, fault):
    runtime, operation, owner = runtime_and_operation(path, fault)
    before = (runtime.read_owner(owner), runtime.occurrence_history(), runtime.individuals())
    time = runtime._time
    due = runtime._pending_due
    cursor = runtime._cursor
    with pytest.raises(K0SettlementDefect) as failure:
        operation()
    assert isinstance(failure.value.__cause__, K0ProfileError)
    after = (runtime.read_owner(owner), runtime.occurrence_history(), runtime.individuals())
    assert after == before
    assert (runtime._time, runtime._pending_due, runtime._cursor) == (time, due, cursor)
    assert runtime._fatal


def test_source_has_no_legacy_publication_callback():
    assert "envelope_builder" not in {field.name for field in fields(_K0InMemorySourceSpec)}
    assert {field.name for field in fields(_K0InMemoryEvaluation)} == {"result", "envelope"}
