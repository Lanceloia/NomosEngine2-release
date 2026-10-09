"""Actor formation publishes identity, owner and finite capabilities atomically."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._action_value_abi import (
    _K0ActionValueOpening,
    _K0ActionValuePolicy,
    _K0ActionValueProjection,
    _K0ActionValueSeat,
)
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._dynamic_actor_abi import (
    _K0ActorDomainPort,
    _K0ActorKind,
    _K0ActorOwnerPort,
    _K0ActorProductSlot,
    _K0ActorRef,
    _K0FormActorProduct,
    _K0OpeningActor,
)
from nomos_kernel._event_jump_abi import (
    _K0OrderedTemporalPolicy,
    _K0PeriodicDueOpening,
    _K0PeriodicDuePlan,
)
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from nomos_kernel._terminal_settlement_abi import _K0TerminalClause, _K0TerminalPolicy
from test_dynamic_individual_owner_v1 import _Factory, _Owner, _Replace, _State

WORLD = K0OwnerKey("actor_test.world")
KEYS = {
    name: K0SourceSpecKey(f"actor_test.{name}")
    for name in ("form", "step", "start", "child_a", "child_b", "pulse")
}


@dataclass(frozen=True)
class _Payload:
    permit: bool = True

    def validate_for_k0(self):
        if type(self.permit) is not bool:
            raise K0ProfileError("invalid permit")


@dataclass(frozen=True)
class _SelfPayload:
    actor: _K0ActorRef
    permit: bool = True

    def validate_for_k0(self):
        if type(self.actor) is not _K0ActorRef:
            raise K0ProfileError("invalid Actor ref")
        self.actor.__post_init__()


@dataclass(frozen=True)
class _Evidence:
    owner: K0OwnerKey
    state: _State

    def validate_for_k0(self):
        if type(self.owner) is not K0OwnerKey or type(self.state) is not _State:
            raise K0ProfileError("invalid evidence")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Participants:
    actor: _K0ActorRef | None = None

    def validate_for_k0(self):
        if self.actor is not None and type(self.actor) is not _K0ActorRef:
            raise K0ProfileError("invalid participants")


@dataclass(frozen=True)
class _Envelope:
    event: str

    def validate_for_k0(self):
        if type(self.event) is not str:
            raise K0ProfileError("invalid envelope")


@dataclass(frozen=True)
class _Projector:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.projection")

    def admit(self, payload, views):
        if not payload.permit:
            return None
        selected = next((item for item in views if item.participant == "actor"), views[0])
        return _K0AdmissionProjection(
            _Evidence(selected.owner, selected.view),
            _Participants(getattr(payload, "actor", None)),
            (),
        )

    def project(self, trigger, views):
        p = self.admit(_Payload(), views)
        return (_K0Activation("one", p.evidence, p.participants, ()),)

    def project_due(self, pending, time, views):
        return self.admit(_Payload(), views)


@dataclass(frozen=True)
class _Tempo:
    tempo: int = 2
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.tempo")

    def project(self, view):
        return _K0ActionValueProjection(self.tempo, True)


@dataclass(frozen=True)
class _Cost:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.cost")

    def project_cost(self, payload, admission):
        return 10


@dataclass(frozen=True)
class _Rule:
    mode: str
    defect: str = ""
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.rule")

    def evaluate(self, inp):
        if self.defect == "fault":
            raise K0ProfileError("failed child")
        if self.mode == "step":
            return _K0InMemoryEvaluation(
                K0RuleResult(
                    (_Replace(inp.evidence.owner, _State(inp.evidence.state.value + 1)),), ()
                ),
                _Envelope(inp.source.value),
            )
        if self.mode == "start":
            return _K0InMemoryEvaluation(K0RuleResult((), ()), _Envelope(inp.source.value))
        state = None if self.mode == "pulse" and inp.evidence.state.value else _State(0)
        if self.defect == "absent":
            state = None
        if self.defect == "wrong_state":
            state = 7
        products = () if self.defect == "omitted" else (_K0FormActorProduct("spark", state),)
        if self.defect == "duplicate":
            products += products
        contributions = (
            (_Replace(WORLD, _State(inp.evidence.state.value + 1)),) if self.mode == "pulse" else ()
        )
        return _K0InMemoryEvaluation(
            K0RuleResult(contributions, (), formed_actors=products), _Envelope(inp.source.value)
        )


def _spec(name, *, defect=""):
    family = (
        K0OccurrenceFamily.EVENT
        if name in ("child_a", "child_b", "pulse")
        else K0OccurrenceFamily.ACTION
    )
    dynamic = name == "step"
    product = None if name in ("step", "start") else _K0ActorProductSlot("spark", name != "pulse")
    return _K0InMemorySourceSpec(
        KEYS[name],
        family,
        K0EventTypeKey(f"actor_test.{name}.event"),
        _SelfPayload if dynamic else _Payload,
        _Evidence,
        _Participants,
        (WORLD,),
        (WORLD,) if name == "pulse" else (),
        (),
        (),
        _Projector() if family is K0OccurrenceFamily.ACTION else None,
        _Rule(name, defect),
        _Envelope,
        due_projector=_Projector() if name == "pulse" else None,
        action_value_owner=WORLD if family is K0OccurrenceFamily.ACTION and not dynamic else None,
        action_cost_projector=_Cost() if family is K0OccurrenceFamily.ACTION else None,
        actor_self=_K0ActorOwnerPort("actor", "spark", True) if dynamic else None,
        actor_product=product,
    )


def _session(*, path="action", capacity=4, defect="", opening=()):
    root = "start" if path == "causal" else "form"
    specs = [_spec(root, defect=defect if path == "action" else ""), _spec("step")]
    laws = []
    if path == "causal":
        for name in ("child_a", "child_b"):
            target = _spec(name, defect=defect if name == "child_b" else "")
            specs.append(target)
            laws.append(
                K0CausalLawDefinition(
                    K0CausalLawKey(f"actor_test.to.{name}"),
                    K0EventTypeKey("actor_test.start.event"),
                    target.key,
                    1,
                    (WORLD,),
                    _Projector(),
                )
            )
    plans = ()
    openings = ()
    specs.append(_spec("pulse", defect=defect if path == "due" else ""))
    if path == "due":
        plan = _K0PeriodicDuePlan(
            _K0CapabilityRef("actor_test.periodic"), KEYS["pulse"], 3, 2, "clock"
        )
        plans = (plan,)
        openings = (_K0PeriodicDueOpening(plan.capability_ref, _K0FixedTime(3)),)
    profile = _K0InMemoryProfile(
        (_Owner(WORLD),),
        tuple(specs),
        tuple(laws),
        5,
        1,
        temporal_policy=_K0OrderedTemporalPolicy(
            _K0CapabilityRef("actor_test.time"),
            (KEYS["pulse"],),
            4,
            plans,
            (KEYS[root], KEYS["step"]),
        ),
        action_value_policy=_K0ActionValuePolicy(
            _K0CapabilityRef("actor_test.schedule"),
            (_K0ActionValueSeat("maker", WORLD, (KEYS[root],), _Tempo(1)),),
            _K0FixedTime(30),
            16,
        ),
        actor_kinds=(
            _K0ActorKind(
                "spark",
                capacity,
                _State,
                _Factory(),
                (KEYS["step"],),
                _Tempo(),
                6,
                1,
                _K0CapabilityRef("actor_test.control"),
            ),
        ),
    )
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(WORLD, _State(0)),),
        initial_time=_K0FixedTime(0),
        opening_action_values=(_K0ActionValueOpening("maker", 0 if path != "due" else 20, 0),),
        opening_actors=opening,
        opening_periodic_dues=openings,
    )


def _state(session):
    return (
        session._topology,
        session._states,
        session._cursor,
        session._tape,
        session.actors(),
        session.action_value_state(),
        session._action_seats,
        session._next_individual,
        session._pending_due,
        session.read_time(),
        session.action_value_history(),
        session.temporal_history(),
        session.action_opportunity(),
    )


@pytest.mark.parametrize("path", ["action", "causal"])
def test_opening_and_new_actors_use_one_self_ability_and_independent_owner(path):
    session = _session(path=path, opening=(_K0OpeningActor("spark", _State(5), 10),))
    specs = session._profile.source_specs
    root = "start" if path == "causal" else "form"
    receipt = session.settle(_K0InMemoryActionAttempt(KEYS[root], _Payload()))
    actors = session.actors()
    assert len(actors) == (3 if path == "causal" else 2)
    assert actors[0].formed_by is None
    assert {item.formed_by for item in actors[1:]} == {
        item.occurrence for item in receipt.occurrences if item.source != KEYS["start"]
    }
    assert len({item.actor.ordinal for item in actors}) == len(actors)
    assert len({item.owner for item in actors}) == len(actors)
    assert session.individuals() == ()  # Actors are not disguised Object refs.
    assert session._profile.source_specs is specs  # No post-publication source registration.
    first = session.continue_action_value()
    assert first.at == _K0FixedTime(3) and first.seat == actors[1].seat
    before_opening = session.read_actor(actors[0].actor).view
    result = session.settle(_K0InMemoryActionAttempt(KEYS["step"], _SelfPayload(actors[1].actor)))
    assert type(result) is K0Published
    assert result.occurrences[0].participants.actor == actors[1].actor
    assert session.read_actor(actors[1].actor).view.value == 1
    assert session.read_actor(actors[0].actor).view == before_opening
    if path == "causal":
        second = session.continue_action_value()
        assert second.at == first.at and second.seat == actors[2].seat
        session.settle(_K0InMemoryActionAttempt(KEYS["step"], _SelfPayload(actors[2].actor)))
        assert session.read_actor(actors[2].actor).view.value == 1
        assert session.read_actor(actors[1].actor).view.value == 1


def test_due_birth_gets_no_preformation_time_credit_and_absent_is_actual_event():
    session = _session(path="due", capacity=1)
    session.continue_action_value()
    actor = session.actors()[0]
    assert actor.born_at == _K0FixedTime(3)
    assert session.action_value_state()[-1].debt == 6
    opportunity = session.continue_action_value()  # Actor-first at the second pulse boundary.
    assert session.read_time() == _K0FixedTime(6)
    assert len(session.actors()) == 1
    assert opportunity.seat == actor.seat and opportunity.at == _K0FixedTime(6)
    assert session.action_value_state()[-1].debt == 0
    session.settle(_K0InMemoryActionAttempt(KEYS["step"], _SelfPayload(actor.actor)))
    assert session.read_actor(actor.actor).view.value == 1
    session.continue_action_value()  # Required second pulse emits an explicit absent product.
    assert len(session.actors()) == 1
    assert [event.source for event in session.occurrence_history()] == [
        KEYS["pulse"],
        KEYS["step"],
        KEYS["pulse"],
    ]


@pytest.mark.parametrize("defect", ["absent", "omitted", "duplicate", "wrong_state"])
def test_invalid_product_rolls_back_identity_owner_capabilities_debts_and_occurrences(defect):
    session = _session(defect=defect)
    before = _state(session)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(KEYS["form"], _Payload()))
    assert _state(session) == before
    assert session._fatal


@pytest.mark.parametrize("capacity, defect", [(1, ""), (4, "fault")])
def test_second_child_failure_rolls_back_first_birth(capacity, defect):
    session = _session(path="causal", capacity=capacity, defect=defect)
    before = _state(session)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(KEYS["start"], _Payload()))
    assert _state(session) == before and session._fatal


def test_wrong_instance_foreign_ref_and_not_admitted_form_make_no_changes():
    session = _session(opening=(_K0OpeningActor("spark", _State(5), 6),))
    before = _state(session)
    assert (
        type(session.settle(_K0InMemoryActionAttempt(KEYS["form"], _Payload(False))))
        is K0NotAdmitted
    )
    assert _state(session) == before
    session.settle(_K0InMemoryActionAttempt(KEYS["form"], _Payload()))
    session.continue_action_value()
    a, b = session.actors()
    before = _state(session)
    wrong = (
        b.actor,
        replace(a.actor, scope="foreign"),
        replace(a.actor, family="other"),
        replace(a.actor, ordinal=90),
    )
    for ref in wrong:
        assert (
            type(session.settle(_K0InMemoryActionAttempt(KEYS["step"], _SelfPayload(ref))))
            is K0NotAdmitted
        )
        assert _state(session) == before


def test_actor_template_must_bind_exact_self_and_positive_debt():
    profile = _session()._profile
    kind = profile.actor_kinds[0]
    with pytest.raises(K0ProfileError, match="debt"):
        replace(kind, initial_debt=0)
    with pytest.raises(K0ProfileError, match="bound"):
        replace(profile, actor_kinds=(replace(kind, action_sources=(KEYS["form"],)),))


@dataclass(frozen=True)
class _DomainEvidence:
    members: tuple[tuple[K0OwnerKey, _K0ActorRef, _State], ...]

    def validate_for_k0(self):
        for owner, actor, state in self.members:
            if type(owner) is not K0OwnerKey or type(actor) is not _K0ActorRef:
                raise K0ProfileError("invalid Actor domain evidence")
            state.validate_for_k0()


@dataclass(frozen=True)
class _DomainProjector:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.domain")

    def project_due(self, pending, time, views):
        members = tuple(
            (view.owner, view.actor_ref, view.view) for view in views if view.participant == "units"
        )
        return _K0AdmissionProjection(_DomainEvidence(members), _Participants(), ())

    def project(self, trigger, views):
        admitted = self.project_due(None, None, views)
        return (_K0Activation("domain", admitted.evidence, admitted.participants, ()),)


@dataclass(frozen=True)
class _DomainRule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.domain_rule")

    def evaluate(self, inp):
        return _K0InMemoryEvaluation(
            K0RuleResult(
                tuple(
                    _Replace(owner, _State(state.value + 2))
                    for owner, _, state in inp.evidence.members
                ),
                (),
            ),
            _Envelope(inp.source.value),
        )


@pytest.mark.parametrize("write", [True, False])
def test_explicit_domain_selects_current_instances_and_enforces_each_write_port(write):
    base = _session(
        path="due",
        opening=(
            _K0OpeningActor("spark", _State(4), 20),
            _K0OpeningActor("spark", _State(8), 20),
        ),
    )
    pulse = next(spec for spec in base._profile.source_specs if spec.key == KEYS["pulse"])
    pulse = replace(
        pulse,
        evidence_type=_DomainEvidence,
        due_projector=_DomainProjector(),
        rule=_DomainRule(),
        actor_product=None,
        contribution_owners=(),
        actor_domains=(_K0ActorDomainPort("units", ("spark",), write),),
    )
    profile = replace(
        base._profile,
        source_specs=tuple(
            pulse if spec.key == pulse.key else spec for spec in base._profile.source_specs
        ),
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(WORLD, _State(0)),),
        initial_time=_K0FixedTime(0),
        opening_action_values=(_K0ActionValueOpening("maker", 20, 0),),
        opening_actors=(
            _K0OpeningActor("spark", _State(4), 20),
            _K0OpeningActor("spark", _State(8), 20),
        ),
        opening_periodic_dues=base._profile.temporal_policy.periodic_plans
        and (
            _K0PeriodicDueOpening(
                base._profile.temporal_policy.periodic_plans[0].capability_ref, _K0FixedTime(3)
            ),
        ),
    )
    before = _state(session)
    if not write:
        with pytest.raises(K0SettlementDefect):
            session.continue_action_value()
        assert _state(session) == before
    else:
        session.continue_action_value()
        assert [session.read_actor(b.actor).view.value for b in session.actors()] == [6, 10]
        assert session.read_owner(WORLD).view.value == 0


def test_due_formation_failure_rolls_back_clock_debts_topology_and_cursor():
    session = _session(path="due", defect="wrong_state")
    before = _state(session)
    with pytest.raises(K0SettlementDefect):
        session.continue_action_value()
    assert _state(session) == before
    assert session._fatal


def test_static_seat_cannot_alias_the_dynamic_actor_namespace():
    profile = _session()._profile
    policy = profile.action_value_policy
    with pytest.raises(K0ProfileError, match="namespace"):
        replace(
            profile,
            action_value_policy=replace(
                policy, seats=(replace(policy.seats[0], seat="actor.spark.1"),)
            ),
        )


@dataclass(frozen=True)
class _MixedRule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.mixed")

    def evaluate(self, inp):
        evaluation = _DomainRule().evaluate(inp)
        return replace(
            evaluation,
            result=replace(
                evaluation.result,
                contributions=(_Replace(WORLD, _State(1)),) + evaluation.result.contributions,
            ),
        )


@dataclass(frozen=True)
class _Never:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.never")

    def project(self, trigger, views):
        return ()


@dataclass(frozen=True)
class _Policy:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.same_wave")
    owner: K0OwnerKey = WORLD
    sources: tuple[K0SourceSpecKey, ...] = (KEYS["child_a"], KEYS["child_b"])
    law_keys: tuple[K0CausalLawKey, ...] = (
        K0CausalLawKey("actor_test.to.child_a"),
        K0CausalLawKey("actor_test.to.child_b"),
    )
    trigger_source: K0SourceSpecKey = KEYS["start"]
    trigger_event: K0EventTypeKey = K0EventTypeKey("actor_test.start.event")

    def merge(self, prior_state, proposals):
        raise K0ProfileError("test expects one policy-owned proposal")


def test_same_wave_policy_does_not_drop_the_events_other_actor_domain_contribution():
    base = _session(path="causal")
    specs = tuple(
        replace(
            spec,
            actor_product=None,
            contribution_owners=(WORLD,),
            evidence_type=_DomainEvidence,
            rule=_MixedRule(),
            actor_domains=(_K0ActorDomainPort("units", ("spark",), True),),
        )
        if spec.key in (KEYS["child_a"], KEYS["child_b"])
        else spec
        for spec in base._profile.source_specs
    )
    laws = tuple(
        replace(
            law,
            activation_projector=_DomainProjector()
            if law.resulting_source == KEYS["child_a"]
            else _Never(),
            actor_domains=(_K0ActorDomainPort("units", ("spark",), False),),
        )
        for law in base._profile.causal_laws
    )
    profile = replace(
        base._profile, source_specs=specs, causal_laws=laws, same_wave_policy=_Policy()
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(WORLD, _State(0)),),
        initial_time=_K0FixedTime(0),
        opening_action_values=(_K0ActionValueOpening("maker", 0, 0),),
        opening_actors=(_K0OpeningActor("spark", _State(4), 20),),
    )
    receipt = session.settle(_K0InMemoryActionAttempt(KEYS["start"], _Payload()))
    assert type(receipt) is K0Published
    assert session.read_owner(WORLD).view.value == 1
    assert session.read_actor(session.actors()[0].actor).view.value == 6


@dataclass(frozen=True)
class _Terminal:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("actor_test.stop")

    def project(self, views):
        return views[0].view.value == 1


def test_terminal_due_prefix_does_not_allocate_suffix_actor_identity():
    base = _session(path="due")
    first = replace(
        next(s for s in base._profile.source_specs if s.key == KEYS["pulse"]),
        actor_product=None,
        rule=_Rule("step"),
    )
    suffix = replace(_spec("child_a"), due_projector=_Projector())
    plan = _K0PeriodicDuePlan(_K0CapabilityRef("actor_test.suffix"), suffix.key, 3, 1, "other")
    policy = replace(
        base._profile.temporal_policy,
        source_order=(first.key, suffix.key),
        periodic_plans=(*base._profile.temporal_policy.periodic_plans, plan),
    )
    profile = replace(
        base._profile,
        source_specs=tuple(first if s.key == first.key else s for s in base._profile.source_specs)
        + (suffix,),
        temporal_policy=policy,
        terminal_policy=_K0TerminalPolicy(
            _K0CapabilityRef("actor_test.terminal"),
            (_K0TerminalClause("finished", (WORLD,), _Terminal()),),
        ),
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(WORLD, _State(0)),),
        initial_time=_K0FixedTime(0),
        opening_action_values=(_K0ActionValueOpening("maker", 20, 0),),
        opening_periodic_dues=tuple(
            _K0PeriodicDueOpening(p.capability_ref, _K0FixedTime(3)) for p in policy.periodic_plans
        ),
    )
    session.continue_action_value()
    assert session.actors() == () and session._next_individual == 1
    assert len(session.occurrence_history()) == 1
    assert session.terminal_state().not_reached[0].pending.source == suffix.key
