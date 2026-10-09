"""Small K0 proofs for variable, occurrence-sourced Collective membership."""

from dataclasses import dataclass

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
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._collective_abi import (
    _K0CollectiveAdd,
    _K0CollectiveDeclaration,
    _K0CollectiveMemberRef,
    _K0CollectiveOwner,
    _K0CollectiveRef,
    _K0CollectiveState,
    _K0Membership,
)
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OccurrenceContribution
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState

OWNER = K0OwnerKey("collectives")
GROUP = _K0CollectiveRef("group")
DECLARATION = _K0CollectiveDeclaration(GROUP, "item")
MEMBER_A = _K0CollectiveMemberRef("item", "a")
MEMBER_B = _K0CollectiveMemberRef("item", "b")
ACTION = K0SourceSpecKey("choose")
EVENT_A = K0SourceSpecKey("add-a")
EVENT_B = K0SourceSpecKey("add-b")
TRIGGER = K0EventTypeKey("chosen")


@dataclass(frozen=True)
class _Payload:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Evidence:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Envelope:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("collective-admission")

    def admit(self, payload: object, owner_views: tuple[object, ...]) -> _K0AdmissionProjection:
        assert type(payload) is _Payload
        assert len(owner_views) == 1
        return _K0AdmissionProjection(_Evidence(), _Participants(), ())


@dataclass(frozen=True)
class _Rule:
    member: _K0CollectiveMemberRef | None
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("collective-rule")

    def evaluate(self, rule_input: object) -> _K0InMemoryEvaluation:
        contributions = (
            () if self.member is None else (_K0CollectiveAdd(OWNER, GROUP, self.member),)
        )
        return _K0InMemoryEvaluation(K0RuleResult(contributions, ()), _Envelope())


@dataclass(frozen=True)
class _Projector:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("collective-activation")

    def project(
        self, trigger: object, owner_views: tuple[object, ...]
    ) -> tuple[_K0Activation, ...]:
        assert len(owner_views) == 1
        return (_K0Activation("one", _Evidence(), _Participants(), ()),)


def _spec(
    key: K0SourceSpecKey,
    family: K0OccurrenceFamily,
    event_type: K0EventTypeKey,
    member: _K0CollectiveMemberRef | None,
) -> _K0InMemorySourceSpec:
    return _K0InMemorySourceSpec(
        key,
        family,
        event_type,
        _Payload,
        _Evidence,
        _Participants,
        (OWNER,),
        () if member is None else (OWNER,),
        (),
        (),
        _Admission() if family is K0OccurrenceFamily.ACTION else None,
        _Rule(member),
        _Envelope,
    )


def _session(second: _K0CollectiveMemberRef = MEMBER_B) -> _K0InMemorySession:
    owner = _K0CollectiveOwner(OWNER, (DECLARATION,))
    specs = (
        _spec(ACTION, K0OccurrenceFamily.ACTION, TRIGGER, None),
        _spec(EVENT_A, K0OccurrenceFamily.EVENT, K0EventTypeKey("added-a"), MEMBER_A),
        _spec(EVENT_B, K0OccurrenceFamily.EVENT, K0EventTypeKey("added-b"), second),
    )
    laws = (
        K0CausalLawDefinition(
            K0CausalLawKey("cause-a"), TRIGGER, EVENT_A, 1, (OWNER,), _Projector()
        ),
        K0CausalLawDefinition(
            K0CausalLawKey("cause-b"), TRIGGER, EVENT_B, 1, (OWNER,), _Projector()
        ),
    )
    profile = _K0InMemoryProfile((owner,), specs, laws, 3, 1)
    return _K0InMemorySession.create(
        profile, (_K0OwnerState(OWNER, _K0CollectiveState((DECLARATION,))),)
    )


def test_two_same_wave_events_add_distinct_members_without_lost_update() -> None:
    session = _session()
    result = session.settle(_K0InMemoryActionAttempt(ACTION, _Payload()))
    assert type(result) is K0Published
    assert tuple(item.source for item in result.occurrences) == (ACTION, EVENT_A, EVENT_B)
    view = session.read_owner(OWNER).view
    members = view.members_of(GROUP)
    assert tuple(item.member for item in members) == (MEMBER_A, MEMBER_B)
    assert tuple(item.added_by for item in members) == (
        result.occurrences[1].occurrence,
        result.occurrences[2].occurrence,
    )


def test_same_wave_add_proof_rejects_a_final_state_missing_one_member() -> None:
    owner = _K0CollectiveOwner(OWNER, (DECLARATION,))
    prior = _K0CollectiveState((DECLARATION,))
    contributions = (
        _K0OccurrenceContribution(K0OccurrenceRef(2), _K0CollectiveAdd(OWNER, GROUP, MEMBER_A), ()),
        _K0OccurrenceContribution(K0OccurrenceRef(3), _K0CollectiveAdd(OWNER, GROUP, MEMBER_B), ()),
    )
    missing = _K0CollectiveState(
        (DECLARATION,), (_K0Membership(GROUP, MEMBER_B, K0OccurrenceRef(3)),)
    )
    with pytest.raises(K0ProfileError, match="lost a membership"):
        owner.prove_same_wave_effects(prior, contributions, missing)


def test_duplicate_membership_fails_atomically_and_session_is_fatal() -> None:
    session = _session(MEMBER_A)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(ACTION, _Payload()))
    assert session.read_owner(OWNER).view.members_of(GROUP) == ()
    assert session._tape == ()
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.settle(_K0InMemoryActionAttempt(ACTION, _Payload()))


def test_opening_cannot_import_membership_with_an_unpublished_ref() -> None:
    session = _session()
    forged = _K0CollectiveState(
        (DECLARATION,), (_K0Membership(GROUP, MEMBER_A, K0OccurrenceRef(999)),)
    )
    with pytest.raises(K0ProfileError, match="published occurrence"):
        _K0InMemorySession.create(session._profile, (_K0OwnerState(OWNER, forged),))


def test_collective_identity_and_family_are_not_a_python_tuple_alias() -> None:
    owner = _K0CollectiveOwner(OWNER, (DECLARATION,))
    opening = _K0CollectiveState((DECLARATION,))
    with pytest.raises(K0ProfileError, match="wrong identity or member family"):
        owner.validate_contribution(
            _K0CollectiveAdd(OWNER, GROUP, _K0CollectiveMemberRef("person", "a"))
        )
    with pytest.raises(K0ProfileError, match="wrong identity or member family"):
        owner.validate_contribution(_K0CollectiveAdd(OWNER, _K0CollectiveRef("other"), MEMBER_A))
    assert owner.decode_state(owner.encode_state(opening)) == opening
    with pytest.raises(K0ProfileError, match="membership wire row"):
        owner.decode_state((("group", "item", "a", True),))
    hollow = object.__new__(_K0CollectiveRef)
    with pytest.raises(K0ProfileError, match="Collective reference"):
        owner.read_view(opening).members_of(hollow)


def test_membership_is_scoped_to_one_whole_and_requires_a_real_ref_shape() -> None:
    other = _K0CollectiveRef("other")
    declarations = (DECLARATION, _K0CollectiveDeclaration(other, "item"))
    state = _K0CollectiveState(
        declarations,
        (
            _K0Membership(GROUP, MEMBER_A, K0OccurrenceRef(1)),
            _K0Membership(other, MEMBER_A, K0OccurrenceRef(2)),
        ),
    )
    state.validate_for_k0()
    assert state.members_of(GROUP)[0].added_by == K0OccurrenceRef(1)
    assert state.members_of(other)[0].added_by == K0OccurrenceRef(2)
    with pytest.raises(K0ProfileError, match="membership source"):
        _K0Membership(GROUP, MEMBER_A, object.__new__(K0OccurrenceRef))
