"""A current Actor participant grants one exact owner, not an Actor domain."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0EventTypeKey, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._action_value_abi import _K0ActionValueOpening
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemorySession,
)
from nomos_kernel._dynamic_actor_abi import (
    _K0ActorDomainPort,
    _K0ActorOwnerPort,
    _K0ActorParticipantPort,
    _K0ActorRef,
    _K0OpeningActor,
)
from nomos_kernel._dynamic_owner_abi import (
    _K0DynamicOwnerKind,
    _K0IndividualOwnerPort,
    _K0IndividualRef,
    _K0OpeningIndividual,
)
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_dynamic_actor_v1 import (
    KEYS,
    WORLD,
    _Envelope,
    _Payload,
    _SelfPayload,
    _session,
    _spec,
    _state,
)
from test_dynamic_individual_owner_v1 import _Factory, _Replace, _State

SELECT = K0SourceSpecKey("actor_test.select")


@dataclass(frozen=True)
class _TargetPayload:
    target: _K0ActorRef
    permit: bool = True

    def validate_for_k0(self):
        if type(self.target) is not _K0ActorRef or type(self.permit) is not bool:
            raise K0ProfileError("invalid target payload")
        self.target.__post_init__()


@dataclass(frozen=True)
class _PairPayload:
    other: _K0ActorRef
    target: _K0ActorRef
    permit: bool = True

    def validate_for_k0(self):
        _TargetPayload(self.target, self.permit).validate_for_k0()
        _TargetPayload(self.other).validate_for_k0()


@dataclass(frozen=True)
class _SelfTargetPayload:
    actor: _K0ActorRef
    target: _K0ActorRef
    permit: bool = True

    def validate_for_k0(self):
        _TargetPayload(self.actor).validate_for_k0()
        _TargetPayload(self.target, self.permit).validate_for_k0()


@dataclass(frozen=True)
class _ObjectTargetPayload:
    target: _K0ActorRef
    tool: _K0IndividualRef
    permit: bool = True

    def validate_for_k0(self):
        _TargetPayload(self.target, self.permit).validate_for_k0()
        if type(self.tool) is not _K0IndividualRef:
            raise K0ProfileError("invalid Object participant")
        self.tool.__post_init__()


@dataclass(frozen=True)
class _Selection:
    target: _K0ActorRef

    def validate_for_k0(self):
        _TargetPayload(self.target).validate_for_k0()


@dataclass(frozen=True)
class _Evidence:
    owner: K0OwnerKey
    current: int
    resource: int
    other: K0OwnerKey | None = None
    resource_owner: K0OwnerKey = WORLD

    def validate_for_k0(self):
        if type(self.owner) is not K0OwnerKey:
            raise K0ProfileError("invalid selected owner")
        _State(self.current).validate_for_k0()
        _State(self.resource).validate_for_k0()
        if self.other is not None and type(self.other) is not K0OwnerKey:
            raise K0ProfileError("invalid other selected owner")
        if type(self.resource_owner) is not K0OwnerKey:
            raise K0ProfileError("invalid resource owner")


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.selected.admission")

    def admit(self, payload, views):
        selected = next(view for view in views if view.participant == "target")
        resource = next(
            (view for view in views if view.participant == "tool"),
            next(view for view in views if view.owner == WORLD),
        )
        assert selected.actor_ref == payload.target
        if not payload.permit or selected.view.value >= 9 or resource.view.value == 0:
            return None
        return _K0AdmissionProjection(
            _Evidence(
                selected.owner,
                selected.view.value,
                resource.view.value,
                next((view.owner for view in views if view.participant == "other"), None),
                resource.owner,
            ),
            _Selection(payload.target),
            (),
        )


@dataclass(frozen=True)
class _Rule:
    mode: str = "write"
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.selected.rule")

    def evaluate(self, inp):
        writes = (_Replace(inp.evidence.resource_owner, _State(inp.evidence.resource - 1)),)
        if self.mode != "readonly":
            owner = inp.evidence.other if self.mode == "foreign" else inp.evidence.owner
            value = -1 if self.mode == "invalid" else inp.evidence.current + 1
            writes += (_Replace(owner, _State(value)),)
        return _K0InMemoryEvaluation(K0RuleResult(writes, ()), _Envelope(inp.source.value))


def _profile(
    *,
    write=True,
    mode="write",
    ports=None,
    payload=_TargetPayload,
    self_actor=False,
    object_kinds=(),
    world_write=True,
):
    base = _session()._profile
    selected = replace(
        _spec("start"),
        key=SELECT,
        event_type=K0EventTypeKey("actor_test.select.action"),
        payload_type=payload,
        evidence_type=_Evidence,
        participants_type=_Selection,
        contribution_owners=(WORLD,) if world_write else (),
        admission_capability=_Admission(),
        rule=_Rule(mode),
        participant_ports=ports or (_K0ActorParticipantPort("target", "target", "spark", write),),
        actor_self=_K0ActorOwnerPort("actor", "spark", True) if self_actor else None,
        action_value_owner=None if self_actor else WORLD,
    )
    policy = base.action_value_policy
    seat = replace(policy.seats[0], action_sources=policy.seats[0].action_sources + (SELECT,))
    kinds = base.actor_kinds
    if self_actor:
        seat = policy.seats[0]
        kinds = (replace(kinds[0], action_sources=kinds[0].action_sources + (SELECT,)),)
    return replace(
        base,
        source_specs=base.source_specs + (selected,),
        actor_kinds=kinds,
        dynamic_owner_kinds=object_kinds,
        temporal_policy=replace(
            base.temporal_policy,
            pre_due_action_sources=base.temporal_policy.pre_due_action_sources + (SELECT,),
        ),
        action_value_policy=replace(policy, seats=(seat,)),
    )


def _open(profile=None, *, values=(5,), objects=(), extra_actors=()):
    base = _session(opening=(_K0OpeningActor("spark", _State(5), 6),))
    return _K0InMemorySession.create(
        profile or _profile(),
        (_K0OwnerState(WORLD, _State(10)),),
        initial_time=base.read_time(),
        opening_action_values=(_K0ActionValueOpening("maker", 0, 0),),
        opening_actors=tuple(_K0OpeningActor("spark", _State(value), 6) for value in values)
        + extra_actors,
        opening_individuals=objects,
    )


def _ready_maker(session):
    for _ in range(8):
        opportunity = session.continue_action_value()
        if opportunity.seat == "maker":
            return
        actor = next(binding for binding in session.actors() if binding.seat == opportunity.seat)
        assert isinstance(
            session.settle(_K0InMemoryActionAttempt(KEYS["step"], _SelfPayload(actor.actor))),
            K0Published,
        )
    raise AssertionError("maker opportunity not reached")


@pytest.mark.parametrize("formed", [False, True])
def test_opening_and_formed_target_use_the_same_selected_port_with_exact_provenance(formed):
    session = _open()
    other = session.actors()[0]
    if formed:
        birth = session.settle(_K0InMemoryActionAttempt(KEYS["form"], _Payload()))
        _ready_maker(session)
        target = session.actors()[-1]
        assert target.formed_by == birth.occurrences[0].occurrence
    else:
        target = other
        assert target.formed_by is None
    before = session.read_actor(target.actor).view.value
    other_before = session.read_actor(other.actor).view
    resource = session.read_owner(WORLD).view.value
    result = session.settle(_K0InMemoryActionAttempt(SELECT, _TargetPayload(target.actor)))
    assert isinstance(result, K0Published)
    assert session.read_actor(target.actor).view.value == before + 1
    assert session.read_owner(WORLD).view.value == resource - 1
    if target != other:
        assert session.read_actor(other.actor).view == other_before
    assert session.actors()[-1] == target
    selected = result.occurrences[0].selected_owners
    assert [(row.name, row.selector, row.owner) for row in selected] == [
        ("target", target.actor, target.owner)
    ]
    assert session.action_value_history()[-1].cost == 10


@pytest.mark.parametrize("fault", ["foreign", "family", "missing", "not_permitted"])
def test_invalid_or_currently_refused_target_changes_no_state_history_or_debt(fault):
    session = _open()
    target = session.actors()[0].actor
    if fault == "foreign":
        target = _open().actors()[0].actor
    elif fault == "family":
        target = replace(target, family="other")
    elif fault == "missing":
        target = replace(target, ordinal=90)
    before = _state(session)
    result = session.settle(
        _K0InMemoryActionAttempt(SELECT, _TargetPayload(target, fault != "not_permitted"))
    )
    assert isinstance(result, K0NotAdmitted)
    assert _state(session) == before and not session._fatal


def test_previous_permitted_target_is_rechecked_against_its_current_state():
    session = _open(values=(8,))
    actor = session.actors()[0].actor
    payload = _TargetPayload(actor)
    assert isinstance(session.settle(_K0InMemoryActionAttempt(SELECT, payload)), K0Published)
    _ready_maker(session)
    assert session.read_actor(actor).view.value >= 9
    before = _state(session)
    assert isinstance(session.settle(_K0InMemoryActionAttempt(SELECT, payload)), K0NotAdmitted)
    assert _state(session) == before and not session._fatal


def test_real_actor_of_another_family_is_not_substitutable_by_shared_state_shape():
    profile = _profile()
    step_key = K0SourceSpecKey("actor_test.other.step")
    other_step = replace(
        _spec("step"),
        key=step_key,
        event_type=K0EventTypeKey("actor_test.other.step.action"),
        actor_self=_K0ActorOwnerPort("actor", "other", True),
    )
    other_kind = replace(profile.actor_kinds[0], family="other", action_sources=(step_key,))
    profile = replace(
        profile,
        actor_kinds=profile.actor_kinds + (other_kind,),
        source_specs=profile.source_specs + (other_step,),
        temporal_policy=replace(
            profile.temporal_policy,
            pre_due_action_sources=profile.temporal_policy.pre_due_action_sources + (step_key,),
        ),
    )
    session = _open(profile, extra_actors=(_K0OpeningActor("other", _State(5), 6),))
    target = session.actors()[-1]
    assert session.read_actor(target.actor).view == _State(5)
    before = _state(session)
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(SELECT, _TargetPayload(target.actor))),
        K0NotAdmitted,
    )
    assert _state(session) == before and not session._fatal


def test_readonly_target_is_readable_but_cannot_be_written():
    session = _open(_profile(write=False, mode="readonly"))
    actor = session.actors()[0]
    before = session.read_actor(actor.actor).view
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(SELECT, _TargetPayload(actor.actor))), K0Published
    )
    assert session.read_actor(actor.actor).view == before
    assert session.read_owner(WORLD).view.value == 9
    illegal = _open(_profile(write=False))
    before = _state(illegal)
    with pytest.raises(K0SettlementDefect):
        illegal.settle(_K0InMemoryActionAttempt(SELECT, _TargetPayload(illegal.actors()[0].actor)))
    assert _state(illegal) == before and illegal._fatal


def test_invalid_selected_effect_rolls_back_resource_and_target_together():
    session = _open(_profile(mode="invalid"))
    before = _state(session)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(SELECT, _TargetPayload(session.actors()[0].actor)))
    assert _state(session) == before and session._fatal


@pytest.mark.parametrize("mode", ["write", "invalid"])
def test_selected_object_resource_and_actor_effect_are_one_atomic_action(mode):
    profile = _profile(
        ports=(
            _K0ActorParticipantPort("target", "target", "spark", True),
            _K0IndividualOwnerPort("tool", "tool", ("tool",), True),
        ),
        payload=_ObjectTargetPayload,
        mode=mode,
        object_kinds=(_K0DynamicOwnerKind("tool", 2, _State, _Factory()),),
        world_write=False,
    )
    session = _open(profile, objects=(_K0OpeningIndividual("tool", _State(4)),))
    target = session.actors()[0]
    tool = session.individuals()[0]
    before = _state(session)
    attempt = _K0InMemoryActionAttempt(SELECT, _ObjectTargetPayload(target.actor, tool.individual))
    if mode == "invalid":
        with pytest.raises(K0SettlementDefect):
            session.settle(attempt)
        assert _state(session) == before and session._fatal
    else:
        result = session.settle(attempt)
        assert isinstance(result, K0Published)
        assert session.read_owner(tool.owner).view == _State(3)
        assert session.read_actor(target.actor).view == _State(6)
        assert session.read_owner(WORLD).view == _State(10)
        assert [(row.name, row.selector) for row in result.occurrences[0].selected_owners] == [
            ("target", target.actor),
            ("tool", tool.individual),
        ]


def test_two_named_roles_cannot_alias_one_target_owner():
    profile = _profile(
        ports=(
            _K0ActorParticipantPort("other", "other", "spark", False),
            _K0ActorParticipantPort("target", "target", "spark", True),
        ),
        payload=_PairPayload,
    )
    session = _open(profile)
    actor = session.actors()[0].actor
    before = _state(session)
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(SELECT, _PairPayload(actor, actor))), K0NotAdmitted
    )
    assert _state(session) == before and not session._fatal


@pytest.mark.parametrize("mode", ["write", "foreign"])
def test_two_distinct_roles_keep_their_separate_read_and_write_permissions(mode):
    profile = _profile(
        ports=(
            _K0ActorParticipantPort("other", "other", "spark", False),
            _K0ActorParticipantPort("target", "target", "spark", True),
        ),
        payload=_PairPayload,
        mode=mode,
    )
    session = _open(profile, values=(5, 7))
    other, target = session.actors()
    before = _state(session)
    attempt = _K0InMemoryActionAttempt(SELECT, _PairPayload(other.actor, target.actor))
    if mode == "foreign":
        with pytest.raises(K0SettlementDefect):
            session.settle(attempt)
        assert _state(session) == before and session._fatal
    else:
        published = session.settle(attempt)
        assert isinstance(published, K0Published)
        assert session.read_actor(other.actor).view == _State(5)
        assert session.read_actor(target.actor).view == _State(8)
        assert session.read_owner(WORLD).view == _State(9)
        assert [(row.name, row.selector) for row in published.occurrences[0].selected_owners] == [
            ("other", other.actor),
            ("target", target.actor),
        ]


def test_self_and_selected_actor_cannot_alias_one_owner():
    session = _open(_profile(payload=_SelfTargetPayload, self_actor=True))
    session.settle(_K0InMemoryActionAttempt(KEYS["form"], _Payload()))
    opportunity = session.continue_action_value()
    assert opportunity.seat != "maker"
    actor = next(row.actor for row in session.actors() if row.seat == opportunity.seat)
    before = _state(session)
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(SELECT, _SelfTargetPayload(actor, actor))),
        K0NotAdmitted,
    )
    assert _state(session) == before and not session._fatal


def test_profile_rejects_unselected_kind_wrong_payload_type_and_domain_overlap():
    profile = _profile()
    selected = profile.source_specs[-1]
    with pytest.raises(K0ProfileError, match="selected kind"):
        replace(
            profile,
            source_specs=profile.source_specs[:-1]
            + (
                replace(
                    selected,
                    participant_ports=(_K0ActorParticipantPort("target", "target", "other", True),),
                ),
            ),
        )
    with pytest.raises(K0ProfileError, match="wrong exact type"):
        replace(selected, payload_type=_Payload)
    with pytest.raises(K0ProfileError, match="alias"):
        replace(selected, actor_domains=(_K0ActorDomainPort("domain", ("spark",), False),))
    with pytest.raises(K0ProfileError, match="permission"):
        _K0ActorParticipantPort("target", "target", "spark", 1)
    with pytest.raises(K0ProfileError, match="name"):
        _K0ActorParticipantPort("actor", "target", "spark", True)
