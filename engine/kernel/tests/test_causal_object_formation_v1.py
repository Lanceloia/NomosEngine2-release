"""Causal Object formation follows declared families and the existing atomic candidate."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0OrderedStep,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._dynamic_owner_abi import _K0DynamicOwnerKind, _K0FormOwnerRequest
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_dynamic_individual_owner_v1 import (
    FORM,
    SCENE,
    _Envelope,
    _Evidence,
    _Factory,
    _Owner,
    _Participants,
    _Payload,
    _Replace,
    _source,
    _State,
)

EVENT = K0SourceSpecKey("individual.causal_product")


@dataclass(frozen=True)
class _EmptyRule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.empty")

    def evaluate(self, rule_input):
        return _K0InMemoryEvaluation(K0RuleResult((), ()), _Envelope("form"))


@dataclass(frozen=True)
class _ProductRule:
    fault: str = ""
    write: bool = False
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.product")

    def evaluate(self, rule_input):
        state = (
            "not nominal" if self.fault == "type" else _State(-1 if self.fault == "state" else 0)
        )
        request = _K0FormOwnerRequest("other" if self.fault == "family" else "object", state)
        products = (
            ()
            if self.fault == "missing"
            else (request, request)
            if self.fault == "duplicate"
            else (request,)
        )
        return _K0InMemoryEvaluation(
            K0RuleResult(
                (_Replace(SCENE, _State(0)),) if self.write else (), (), formed_owners=products
            ),
            _Envelope("form"),
        )


@dataclass(frozen=True)
class _Projector:
    active: bool = True
    target: K0SourceSpecKey = EVENT
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.project")

    def project(self, trigger, views):
        return (
            (_K0Activation(self.target.value, _Evidence(None, 0), _Participants(), ()),)
            if self.active
            else ()
        )


def _profile(*, fault="", active=True, family="object", capacity=2):
    action = replace(_source("form"), rule=_EmptyRule(), form_owner_family=None)
    event = replace(
        action,
        key=EVENT,
        event_type=K0EventTypeKey("individual.product.event"),
        occurrence_family=K0OccurrenceFamily.EVENT,
        payload_type=type(None),
        admission_capability=None,
        rule=_ProductRule(fault),
        form_owner_family=family,
    )
    law = K0CausalLawDefinition(
        K0CausalLawKey("individual.product.law"),
        action.event_type,
        EVENT,
        1,
        (SCENE,),
        _Projector(active),
    )
    return _K0InMemoryProfile(
        (_Owner(SCENE),),
        (action, event),
        (law,),
        2,
        2,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", capacity, _State, _Factory()),),
    )


def _session(**kwargs):
    return _K0InMemorySession.create(_profile(**kwargs), (_K0OwnerState(SCENE, _State(0)),))


def test_registered_event_family_forms_two_independent_objects_with_event_birth():
    session = _session()
    for _ in range(2):
        result = session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
        assert isinstance(result, K0Published)
        action, event = result.occurrences
        binding = session.individuals()[-1]
        assert binding.formed_by == event.occurrence != action.occurrence
        assert event.formation_basis.predecessor == action.occurrence
    left, right = session.individuals()
    assert left.individual != right.individual and left.owner != right.owner
    before = session.occurrence_history()
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert session.individuals() == (left, right) and session.occurrence_history() == before


@pytest.mark.parametrize("fault", ["family", "missing", "duplicate", "type", "state"])
def test_malformed_product_is_fatal_and_publishes_neither_trigger_nor_identity(fault):
    session = _session(fault=fault)
    before = session.read_owner(SCENE)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert session.individuals() == () and session.occurrence_history() == ()
    assert session.read_owner(SCENE) == before


def test_undeclared_family_is_rejected_by_registered_profile():
    with pytest.raises(K0ProfileError):
        _profile(family="other")


def test_no_activation_does_not_form_an_object():
    session = _session(active=False)
    result = session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert isinstance(result, K0Published) and len(result.occurrences) == 1
    assert session.individuals() == ()


SECOND = K0SourceSpecKey("individual.second_product")


@dataclass(frozen=True)
class _OrderedPolicy:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("test.ordered")
    owner: object = SCENE
    trigger_source: K0SourceSpecKey = FORM
    trigger_event: K0EventTypeKey = K0EventTypeKey("individual.form")
    steps: tuple = (
        _K0OrderedStep(K0CausalLawKey("individual.product.law"), EVENT, True),
        _K0OrderedStep(K0CausalLawKey("individual.second.law"), SECOND, True),
    )

    def validate_current_basis(self, step, activation, views):
        if len(views) != 1 or views[0].owner != SCENE:
            raise K0ProfileError("ordered product lost its Scene basis")


@pytest.mark.parametrize("fault", ["", "family"])
def test_ordered_causal_products_use_the_same_declared_family_validation(fault):
    profile = _profile()
    action, event = profile.source_specs
    first = replace(event, contribution_owners=(SCENE,), rule=_ProductRule(write=True))
    second = replace(
        first,
        key=SECOND,
        event_type=K0EventTypeKey("individual.second.event"),
        rule=_ProductRule(fault, True),
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
    session = _K0InMemorySession.create(profile, (_K0OwnerState(SCENE, _State(0)),))
    if fault:
        with pytest.raises(K0SettlementDefect):
            session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
        assert session.individuals() == () and session.occurrence_history() == ()
    else:
        result = session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
        assert isinstance(result, K0Published)
        assert [row.formed_by for row in session.individuals()] == [
            row.occurrence for row in result.occurrences[1:]
        ]
