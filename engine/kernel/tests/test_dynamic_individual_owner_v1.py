"""Opening and formed individuals use the same checked K0 owner path."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
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
from nomos_kernel._dynamic_owner_abi import (
    _K0ClosedOwnerPort,
    _K0DynamicOwnerKind,
    _K0FormOwnerRequest,
    _K0IndividualOwnerPort,
    _K0IndividualRef,
    _K0OpeningIndividual,
)
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0OccurrenceContribution
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState

SCENE = K0OwnerKey("individual.scene")
FORM = K0SourceSpecKey("individual.form")
TOUCH = K0SourceSpecKey("individual.touch")
DUAL = K0SourceSpecKey("individual.dual")
PERSON_A = K0OwnerKey("individual.person.a")
PERSON_B = K0OwnerKey("individual.person.b")


@dataclass(frozen=True)
class _State:
    value: int

    def validate_for_k0(self) -> None:
        if type(self.value) is not int or self.value < 0:
            raise K0ProfileError("invalid individual state")


@dataclass(frozen=True)
class _Payload:
    target: _K0IndividualRef | None
    permit: bool = True

    def validate_for_k0(self) -> None:
        if self.target is not None and type(self.target) is not _K0IndividualRef:
            raise K0ProfileError("invalid target")


@dataclass(frozen=True)
class _TouchPayload:
    target: _K0IndividualRef
    permit: bool = True

    def validate_for_k0(self) -> None:
        if type(self.target) is not _K0IndividualRef:
            raise K0ProfileError("invalid target")


@dataclass(frozen=True)
class _Evidence:
    target: K0OwnerKey | None
    value: int

    def validate_for_k0(self) -> None:
        if self.target is not None and type(self.target) is not K0OwnerKey:
            raise K0ProfileError("invalid target owner")


@dataclass(frozen=True)
class _Participants:
    actor: str = "maker"

    def validate_for_k0(self) -> None:
        if self.actor != "maker":
            raise K0ProfileError("invalid actor")


@dataclass(frozen=True)
class _Envelope:
    kind: str

    def validate_for_k0(self) -> None:
        if self.kind not in ("form", "touch"):
            raise K0ProfileError("invalid envelope")


@dataclass(frozen=True)
class _Replace:
    owner: K0OwnerKey
    state: _State

    def validate_for_k0(self) -> None:
        if type(self.owner) is not K0OwnerKey or type(self.state) is not _State:
            raise K0ProfileError("invalid replacement")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey
    owner_version: str = "individual-v1"
    state_type: ClassVar[type] = _State
    view_type: ClassVar[type] = _State
    contribution_type: ClassVar[type] = _Replace
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not _State:
            raise K0ProfileError("invalid state type")
        state.validate_for_k0()

    def read_view(self, state: object) -> _State:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _Replace or contribution.owner != self.key:
            raise K0ProfileError("wrong owner replacement")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if len(contributions) != 1:
            raise K0ProfileError("one replacement required")
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> _State:
        self.validate_state(state)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("no local identity")

    def preserved_occurrences(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return ()

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return (self.owner_version, state.value)

    def decode_state(self, wire: tuple[object, ...]) -> _State:
        if type(wire) is not tuple or len(wire) != 2 or wire[0] != self.owner_version:
            raise K0ProfileError("invalid state wire")
        state = _State(wire[1])
        self.validate_state(state)
        return state


@dataclass(frozen=True)
class _Factory:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("individual.factory")
    state_type: type = _State

    def build(self, key: K0OwnerKey) -> _Owner:
        return _Owner(key)


def test_dynamic_kind_rejects_factory_declaring_a_foreign_state_type() -> None:
    with pytest.raises(K0ProfileError, match="factory"):
        _K0DynamicOwnerKind("object", 2, _State, replace(_Factory(), state_type=int))


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef
    kind: str

    def admit(
        self, payload: object, owner_views: tuple[object, ...]
    ) -> _K0AdmissionProjection | None:
        if not payload.permit:
            return None
        if self.kind == "form":
            return _K0AdmissionProjection(_Evidence(None, 0), _Participants(), ())
        target = next((view for view in owner_views if view.owner != SCENE), None)
        if target is None:
            return None
        return _K0AdmissionProjection(
            _Evidence(target.owner, target.view.value), _Participants(), ()
        )


@dataclass(frozen=True)
class _Rule:
    capability_ref: _K0CapabilityRef
    kind: str
    malformed: bool = False
    fail_after_stage: bool = False
    wrong_target: bool = False

    def evaluate(self, rule_input: object) -> _K0InMemoryEvaluation:
        if self.kind == "form":
            family = "wrong" if self.malformed else "object"
            contributions = (_Replace(SCENE, _State(1)),) if self.fail_after_stage else ()
            return _K0InMemoryEvaluation(
                K0RuleResult(
                    contributions, (), formed_owners=(_K0FormOwnerRequest(family, _State(0)),)
                ),
                _Envelope(self.kind),
            )
        target = rule_input.evidence.target
        if self.wrong_target:
            target = SCENE
        return _K0InMemoryEvaluation(
            K0RuleResult((_Replace(target, _State(rule_input.evidence.value + 1)),), ()),
            _Envelope(self.kind),
        )


def _source(
    kind: str,
    *,
    malformed: bool = False,
    fail_after_stage: bool = False,
    wrong_target: bool = False,
) -> _K0InMemorySourceSpec:
    form = kind == "form"
    return _K0InMemorySourceSpec(
        FORM if form else TOUCH,
        K0OccurrenceFamily.ACTION,
        K0EventTypeKey(f"individual.{kind}"),
        _Payload if form else _TouchPayload,
        _Evidence,
        _Participants,
        (SCENE,),
        (SCENE,) if form and fail_after_stage else (),
        (),
        (),
        _Admission(_K0CapabilityRef(f"admit.{kind}"), kind),
        _Rule(_K0CapabilityRef(f"rule.{kind}"), kind, malformed, fail_after_stage, wrong_target),
        _Envelope,
        participant_ports=()
        if form
        else (_K0IndividualOwnerPort("target", "target", ("object",), True),),
        form_owner_family="object" if form else None,
    )


@dataclass(frozen=True)
class _RejectChangedScene:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("individual.invariant")
    read_owners: tuple[K0OwnerKey, ...] = (SCENE,)

    def validate(self, owner_views: tuple[object, ...]) -> None:
        if owner_views[0].view.value != 0:
            raise K0ProfileError("scene must stay unchanged")


def _session(
    *,
    limit: int = 3,
    malformed: bool = False,
    fail_after_stage: bool = False,
    wrong_target: bool = False,
    opening: bool = True,
) -> _K0InMemorySession:
    profile = _K0InMemoryProfile(
        (_Owner(SCENE),),
        (
            _source("form", malformed=malformed, fail_after_stage=fail_after_stage),
            _source("touch", wrong_target=wrong_target),
        ),
        (),
        1,
        0,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", limit, _State, _Factory()),),
    )
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(SCENE, _State(0)),),
        invariants=(_RejectChangedScene(),) if fail_after_stage else (),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),) if opening else (),
    )


def test_opening_and_formed_individuals_have_independent_owner_state() -> None:
    session = _session()
    original = session.individuals()[0]
    assert original.formed_by is None
    assert session.read_individual(original.individual).view.value == 3
    assert len(session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None))).occurrences) == 1
    formed = session.individuals()[1]
    assert formed.owner != original.owner
    assert formed.formed_by == session.occurrence_history()[0].occurrence
    session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(formed.individual)))
    assert session.read_individual(formed.individual).view.value == 1
    assert session.read_individual(original.individual).view.value == 3
    session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(original.individual)))
    assert session.read_individual(original.individual).view.value == 4
    session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    newest = session.individuals()[2]
    assert len({item.owner for item in session.individuals()}) == 3
    assert newest.individual.ordinal > formed.individual.ordinal
    assert session.read_individual(newest.individual).view.value == 0


def test_one_dynamic_source_can_resolve_two_declared_families() -> None:
    touch = replace(
        _source("touch"),
        participant_ports=(
            _K0IndividualOwnerPort("target", "target", ("object", "special"), True),
        ),
    )
    profile = _K0InMemoryProfile(
        (_Owner(SCENE),),
        (touch,),
        (),
        1,
        0,
        dynamic_owner_kinds=(
            _K0DynamicOwnerKind("object", 2, _State, _Factory()),
            _K0DynamicOwnerKind("special", 2, _State, _Factory()),
        ),
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(SCENE, _State(0)),),
        opening_individuals=(
            _K0OpeningIndividual("object", _State(2)),
            _K0OpeningIndividual("special", _State(4)),
        ),
    )
    for binding in session.individuals():
        session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(binding.individual)))
    assert [
        session.read_individual(item.individual).view.value for item in session.individuals()
    ] == [3, 5]
    assert len(session.occurrence_history()) == 2


def test_individual_port_rejects_undeclared_or_repeated_families() -> None:
    with pytest.raises(K0ProfileError):
        _K0IndividualOwnerPort("target", "target", ("object", "object"), True)
    with pytest.raises(K0ProfileError):
        _K0IndividualOwnerPort("target", "target", (), True)
    with pytest.raises(K0ProfileError):
        _K0InMemoryProfile(
            (_Owner(SCENE),),
            (
                replace(
                    _source("touch"),
                    participant_ports=(
                        _K0IndividualOwnerPort("target", "target", ("object", "special"), True),
                    ),
                ),
            ),
            (),
            1,
            0,
            dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 2, _State, _Factory()),),
        )


def test_foreign_wrong_family_and_unadmitted_attempts_do_not_write() -> None:
    session = _session()
    original = session.individuals()[0]
    foreign = _session().individuals()[0].individual
    wrong = _K0IndividualRef(original.individual.scope, original.individual.ordinal, "other")
    unknown = _K0IndividualRef(original.individual.scope, 900, "object")
    for ref in (foreign, wrong, unknown):
        assert isinstance(
            session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(ref))), K0NotAdmitted
        )
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(original.individual, False))),
        K0NotAdmitted,
    )
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None, False))), K0NotAdmitted
    )
    assert session.occurrence_history() == ()
    assert session.individuals() == (original,)


def test_formed_owner_failure_rolls_back_and_marks_session_fatal() -> None:
    session = _session(malformed=True)
    original = session.individuals()[0]
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert session.individuals() == (original,)
    assert session.occurrence_history() == ()
    assert session.read_individual(original.individual).view.value == 3
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))


def test_declared_owner_limit_cannot_publish_a_partial_second_individual() -> None:
    session = _session(limit=1)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert len(session.individuals()) == 1
    assert session.occurrence_history() == ()


def test_post_formation_invariant_failure_rolls_back_topology_and_state() -> None:
    session = _session(fail_after_stage=True)
    original = session.individuals()[0]
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
    assert session.individuals() == (original,)
    assert session.read_owner(SCENE).view.value == 0
    assert session.read_individual(original.individual).view.value == 3
    assert session.occurrence_history() == ()


def test_dynamic_target_port_rejects_a_rule_write_to_another_owner() -> None:
    session = _session(wrong_target=True)
    original = session.individuals()[0]
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(TOUCH, _TouchPayload(original.individual)))
    assert session.read_owner(SCENE).view.value == 0
    assert session.read_individual(original.individual).view.value == 3
    assert session.occurrence_history() == ()


@dataclass(frozen=True)
class _ReentrantPayload:
    target: _K0IndividualRef
    session: _K0InMemorySession

    def __getattribute__(self, name: str) -> object:
        if name == "target":
            session = object.__getattribute__(self, "session")
            session.settle(_K0InMemoryActionAttempt(FORM, _Payload(None)))
        return object.__getattribute__(self, name)


def test_dynamic_target_lookup_cannot_publish_a_nested_action() -> None:
    form, touch = _source("form"), _source("touch")
    profile = _K0InMemoryProfile(
        (_Owner(SCENE),),
        (form, replace(touch, payload_type=_ReentrantPayload)),
        (),
        1,
        0,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 3, _State, _Factory()),),
    )
    session = _K0InMemorySession.create(
        profile,
        (_K0OwnerState(SCENE, _State(0)),),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )
    original = session.individuals()[0]
    with pytest.raises(K0SettlementDefect, match="nested"):
        session.settle(
            _K0InMemoryActionAttempt(TOUCH, _ReentrantPayload(original.individual, session))
        )
    assert session.individuals() == (original,)
    assert session.occurrence_history() == ()


@dataclass(frozen=True)
class _DualPayload:
    person: str
    tool: _K0IndividualRef
    permit: bool = True

    def validate_for_k0(self) -> None:
        if type(self.person) is not str or type(self.tool) is not _K0IndividualRef:
            raise K0ProfileError("invalid dual payload")


@dataclass(frozen=True)
class _DualEvidence:
    person: K0OwnerKey
    tool: K0OwnerKey
    person_value: int
    tool_value: int

    def validate_for_k0(self) -> None:
        if type(self.person) is not K0OwnerKey or type(self.tool) is not K0OwnerKey:
            raise K0ProfileError("invalid dual evidence")


@dataclass(frozen=True)
class _DualAdmission:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("individual.dual.admission")

    def admit(
        self, payload: _DualPayload, owner_views: tuple[object, ...]
    ) -> _K0AdmissionProjection | None:
        if not payload.permit:
            return None
        if len(owner_views) != 3:
            raise K0ProfileError("unselected owner entered dual admission")
        selected = {view.participant: view for view in owner_views if view.participant is not None}
        if set(selected) != {"person", "tool"}:
            return None
        person = selected["person"]
        tool = selected["tool"]
        return _K0AdmissionProjection(
            _DualEvidence(person.owner, tool.owner, person.view.value, tool.view.value),
            _Participants(),
            (),
        )


@dataclass(frozen=True)
class _DualRule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("individual.dual.rule")
    wrong_owner: bool = False

    def evaluate(self, rule_input: object) -> _K0InMemoryEvaluation:
        evidence = rule_input.evidence
        person = SCENE if self.wrong_owner else evidence.person
        return _K0InMemoryEvaluation(
            K0RuleResult(
                (
                    _Replace(person, _State(evidence.person_value + 1)),
                    _Replace(evidence.tool, _State(evidence.tool_value + 2)),
                ),
                (),
            ),
            _Envelope("touch"),
        )


def _dual_source(*, wrong_owner: bool = False) -> _K0InMemorySourceSpec:
    return _K0InMemorySourceSpec(
        DUAL,
        K0OccurrenceFamily.ACTION,
        K0EventTypeKey("individual.dual"),
        _DualPayload,
        _DualEvidence,
        _Participants,
        (SCENE,),
        (),
        (),
        (),
        _DualAdmission(),
        _DualRule(wrong_owner=wrong_owner),
        _Envelope,
        participant_ports=(
            _K0ClosedOwnerPort("person", "person", (("a", PERSON_A), ("b", PERSON_B)), True, False),
            _K0IndividualOwnerPort("tool", "tool", ("object",), True),
        ),
    )


def _dual_session(*, wrong_owner: bool = False) -> _K0InMemorySession:
    profile = _K0InMemoryProfile(
        (_Owner(SCENE), _Owner(PERSON_A), _Owner(PERSON_B)),
        (_dual_source(wrong_owner=wrong_owner),),
        (),
        1,
        0,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 2, _State, _Factory()),),
    )
    return _K0InMemorySession.create(
        profile,
        (
            _K0OwnerState(SCENE, _State(0)),
            _K0OwnerState(PERSON_A, _State(4)),
            _K0OwnerState(PERSON_B, _State(7)),
        ),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )


def test_two_named_ports_select_only_actual_person_and_tool_owners() -> None:
    session = _dual_session()
    tool = session.individuals()[0]
    result = session.settle(_K0InMemoryActionAttempt(DUAL, _DualPayload("b", tool.individual)))
    assert len(result.occurrences) == 1
    assert tuple(
        (item.name, item.selector, item.owner) for item in result.occurrences[0].selected_owners
    ) == (
        ("person", "b", PERSON_B),
        ("tool", tool.individual, tool.owner),
    )
    assert session.read_owner(PERSON_A).view.value == 4
    assert session.read_owner(PERSON_B).view.value == 8
    assert session.read_individual(tool.individual).view.value == 5
    assert session.read_owner(SCENE).view.value == 0


def test_two_named_ports_reject_foreign_or_unselected_participants_without_writes() -> None:
    session = _dual_session()
    tool = session.individuals()[0]
    foreign = _dual_session().individuals()[0]
    for payload in (
        _DualPayload("unknown", tool.individual),
        _DualPayload("b", foreign.individual),
        _DualPayload("b", tool.individual, False),
    ):
        assert isinstance(session.settle(_K0InMemoryActionAttempt(DUAL, payload)), K0NotAdmitted)
    assert session.read_owner(PERSON_A).view.value == 4
    assert session.read_owner(PERSON_B).view.value == 7
    assert session.read_individual(tool.individual).view.value == 3
    assert session.occurrence_history() == ()


def test_two_named_ports_reject_an_undeclared_rule_write_atomically() -> None:
    session = _dual_session(wrong_owner=True)
    tool = session.individuals()[0]
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(DUAL, _DualPayload("b", tool.individual)))
    assert session.read_owner(SCENE).view.value == 0
    assert session.read_owner(PERSON_B).view.value == 7
    assert session.read_individual(tool.individual).view.value == 3
    assert session.occurrence_history() == ()


def test_two_named_ports_enforce_read_only_permission_and_static_alias() -> None:
    source = _dual_source()
    read_only = replace(
        source,
        participant_ports=(
            _K0ClosedOwnerPort(
                "person", "person", (("a", PERSON_A), ("b", PERSON_B)), False, False
            ),
            source.participant_ports[1],
        ),
    )
    profile = _K0InMemoryProfile(
        (_Owner(SCENE), _Owner(PERSON_A), _Owner(PERSON_B)),
        (read_only,),
        (),
        1,
        0,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 2, _State, _Factory()),),
    )
    session = _K0InMemorySession.create(
        profile,
        (
            _K0OwnerState(SCENE, _State(0)),
            _K0OwnerState(PERSON_A, _State(4)),
            _K0OwnerState(PERSON_B, _State(7)),
        ),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )
    tool = session.individuals()[0]
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(DUAL, _DualPayload("b", tool.individual)))
    assert session.read_owner(PERSON_B).view.value == 7
    assert session.read_individual(tool.individual).view.value == 3
    assert session.occurrence_history() == ()

    alias = replace(
        source,
        participant_ports=(
            _K0ClosedOwnerPort("person", "person", (("scene", SCENE),), True, False),
            source.participant_ports[1],
        ),
    )
    alias_session = _K0InMemorySession.create(
        replace(profile, source_specs=(alias,)),
        (
            _K0OwnerState(SCENE, _State(0)),
            _K0OwnerState(PERSON_A, _State(4)),
            _K0OwnerState(PERSON_B, _State(7)),
        ),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )
    assert isinstance(
        alias_session.settle(
            _K0InMemoryActionAttempt(
                DUAL, _DualPayload("scene", alias_session.individuals()[0].individual)
            )
        ),
        K0NotAdmitted,
    )
    assert alias_session.occurrence_history() == ()


def test_closed_port_profile_rejects_invalid_domain_and_payload_schema() -> None:
    with pytest.raises(K0ProfileError):
        _K0ClosedOwnerPort("person", "person", (("b", PERSON_B), ("a", PERSON_A)), True, False)
    with pytest.raises(K0ProfileError, match="participant payload"):
        replace(
            _dual_source(),
            participant_ports=(
                _K0ClosedOwnerPort("person", "tool", (("a", PERSON_A),), True, False),
            ),
        )
    with pytest.raises(K0ProfileError, match="undeclared owner"):
        _K0InMemoryProfile(
            (_Owner(SCENE), _Owner(PERSON_A)),
            (_dual_source(),),
            (),
            1,
            0,
            dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 2, _State, _Factory()),),
        )
    bad = object.__new__(K0OwnerKey)
    object.__setattr__(bad, "value", 42)
    with pytest.raises(K0ProfileError, match="member key"):
        _K0ClosedOwnerPort("person", "person", (("bad", bad),), True, False)
    hollow = object.__new__(K0OwnerKey)
    with pytest.raises(K0ProfileError, match="member key"):
        _K0ClosedOwnerPort("person", "person", (("hollow", hollow),), True, False)
