"""An absent closed role grants no source view, participant record or write slot."""

from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OwnerKey, K0ProfileError
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
)
from nomos_kernel._dynamic_owner_abi import (
    _K0ClosedOwnerPort,
    _K0DynamicOwnerKind,
    _K0IndividualRef,
    _K0OpeningIndividual,
)
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_dynamic_individual_owner_v1 import (
    DUAL,
    PERSON_A,
    PERSON_B,
    SCENE,
    _dual_source,
    _Envelope,
    _Factory,
    _Owner,
    _Participants,
    _Replace,
    _State,
)


@dataclass(frozen=True)
class _Payload:
    person: str | None
    tool: _K0IndividualRef

    def validate_for_k0(self):
        if self.person is not None and type(self.person) is not str:
            raise K0ProfileError("invalid closed selector")
        if type(self.tool) is not _K0IndividualRef:
            raise K0ProfileError("invalid individual selector")


@dataclass(frozen=True)
class _Evidence:
    person: K0OwnerKey | None
    person_value: int | None
    tool: K0OwnerKey
    tool_value: int

    def validate_for_k0(self):
        if (self.person is None) != (self.person_value is None):
            raise K0ProfileError("absent participant has no value")
        if self.person is not None and type(self.person) is not K0OwnerKey:
            raise K0ProfileError("invalid selected owner")
        if type(self.tool) is not K0OwnerKey or type(self.tool_value) is not int:
            raise K0ProfileError("invalid tool basis")


@dataclass(frozen=True)
class _Admission:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("optional.closed.admission")

    def admit(self, payload, owner_views):
        views = {view.participant: view for view in owner_views}
        scene = views[None]
        expected = {0: None, 1: "a", 2: "b"}[scene.view.value]
        if payload.person != expected:
            return None
        required = {None, "tool"} | ({"person"} if expected is not None else set())
        if set(views) != required or len(owner_views) != len(required):
            raise K0ProfileError("absent owner leaked into source admission")
        person = views.get("person")
        tool = views["tool"]
        return _K0AdmissionProjection(
            _Evidence(
                None if person is None else person.owner,
                None if person is None else person.view.value,
                tool.owner,
                tool.view.value,
            ),
            _Participants(),
            (),
        )


@dataclass(frozen=True)
class _Rule:
    capability_ref: _K0CapabilityRef = _K0CapabilityRef("optional.closed.rule")
    write_absent: bool = False
    bad_present: bool = False

    def evaluate(self, rule_input):
        evidence = rule_input.evidence
        contributions = [_Replace(evidence.tool, _State(evidence.tool_value + 2))]
        if evidence.person is not None:
            contributions.append(
                _Replace(
                    evidence.person, _State(-1 if self.bad_present else evidence.person_value + 1)
                )
            )
        elif self.write_absent:
            contributions.append(_Replace(PERSON_A, _State(99)))
        return _K0InMemoryEvaluation(K0RuleResult(tuple(contributions), ()), _Envelope("touch"))


@dataclass(frozen=True)
class _UnreadOwner(_Owner):
    def read_view(self, state):
        raise K0ProfileError("unselected owner must not provide a source view")


def _source(*, writable=True, write_absent=False, bad_present=False):
    source = _dual_source()
    return replace(
        source,
        payload_type=_Payload,
        evidence_type=_Evidence,
        admission_capability=_Admission(),
        rule=_Rule(write_absent=write_absent, bad_present=bad_present),
        participant_ports=(
            _K0ClosedOwnerPort(
                "person", "person", (("a", PERSON_A), ("b", PERSON_B)), writable, True
            ),
            source.participant_ports[1],
        ),
    )


def _session(*, roster=0, writable=True, write_absent=False, bad_present=False):
    profile = _K0InMemoryProfile(
        (_Owner(SCENE), _UnreadOwner(PERSON_A), _Owner(PERSON_B)),
        (_source(writable=writable, write_absent=write_absent, bad_present=bad_present),),
        (),
        1,
        0,
        dynamic_owner_kinds=(_K0DynamicOwnerKind("object", 2, _State, _Factory()),),
    )
    return _K0InMemorySession.create(
        profile,
        (
            _K0OwnerState(SCENE, _State(roster)),
            _K0OwnerState(PERSON_A, _State(4)),
            _K0OwnerState(PERSON_B, _State(7)),
        ),
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )


@pytest.mark.parametrize("roster,selector", [(0, None), (2, "b")])
def test_nullable_role_selects_only_present_owner_and_has_no_placeholder_record(roster, selector):
    session = _session(roster=roster)
    tool = session.individuals()[0]
    result = session.settle(_K0InMemoryActionAttempt(DUAL, _Payload(selector, tool.individual)))
    selected = result.occurrences[0].selected_owners
    assert {row.name for row in selected} == ({"tool"} if selector is None else {"person", "tool"})
    assert all(row.selector is not None for row in selected)
    assert session.read_owner(PERSON_B).view.value == (7 if selector is None else 8)
    assert session.read_individual(tool.individual).view.value == 5


@pytest.mark.parametrize("roster,selector", [(0, "b"), (2, None), (2, "unknown")])
def test_source_rechecks_roster_and_rejects_missing_extra_or_unknown_member(roster, selector):
    session = _session(roster=roster)
    tool = session.individuals()[0]
    before = (session._states, session._cursor, session.occurrence_history(), session.individuals())
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(DUAL, _Payload(selector, tool.individual))),
        K0NotAdmitted,
    )
    assert (
        session._states,
        session._cursor,
        session.occurrence_history(),
        session.individuals(),
    ) == before


@pytest.mark.parametrize("case", ["absent_write", "readonly_write", "invalid_state"])
def test_selected_write_scope_and_all_owner_rollback_remain_exact(case):
    session = _session(
        roster=0 if case == "absent_write" else 2,
        writable=case != "readonly_write",
        write_absent=case == "absent_write",
        bad_present=case == "invalid_state",
    )
    tool = session.individuals()[0]
    before = (session._states, session._cursor, session.individuals())
    with pytest.raises(K0SettlementDefect):
        session.settle(
            _K0InMemoryActionAttempt(
                DUAL, _Payload(None if case == "absent_write" else "b", tool.individual)
            )
        )
    assert session.read_individual(tool.individual).view.value == 3
    assert session.read_owner(PERSON_B).view.value == 7
    assert session.occurrence_history() == ()
    assert (session._states, session._cursor, session.individuals()) == before
    assert session._fatal
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.settle(_K0InMemoryActionAttempt(DUAL, _Payload(None, tool.individual)))


def test_nullable_flag_and_payload_type_are_an_exact_profile_contract():
    with pytest.raises(K0ProfileError, match="participant payload"):
        replace(_source(), payload_type=_dual_source().payload_type)
    port = _source().participant_ports[0]
    with pytest.raises(K0ProfileError, match="participant payload"):
        replace(_source(), participant_ports=(replace(port, nullable=False),))
    with pytest.raises(K0ProfileError):
        replace(port, nullable=1)
    with pytest.raises(TypeError):
        _K0ClosedOwnerPort("person", "person", (("a", PERSON_A),), True)


def test_absence_does_not_alias_static_roots_but_a_present_alias_is_rejected():
    source = _source()
    alias = replace(source.participant_ports[0], members=(("scene", SCENE),))
    session = _session()
    session = _K0InMemorySession.create(
        replace(
            session._profile,
            source_specs=(replace(source, participant_ports=(alias, source.participant_ports[1])),),
        ),
        session._states[:3],
        opening_individuals=(_K0OpeningIndividual("object", _State(3)),),
    )
    tool = session.individuals()[0]
    before = (session._states, session._cursor, session.occurrence_history())
    assert isinstance(
        session.settle(_K0InMemoryActionAttempt(DUAL, _Payload("scene", tool.individual))),
        K0NotAdmitted,
    )
    assert (session._states, session._cursor, session.occurrence_history()) == before
    result = session.settle(_K0InMemoryActionAttempt(DUAL, _Payload(None, tool.individual)))
    assert [row.name for row in result.occurrences[0].selected_owners] == ["tool"]


@pytest.mark.parametrize("annotation", [int | None, str | int | None, str, type(None)])
def test_nullable_payload_requires_exact_string_or_none_without_extra_cases(annotation):
    @dataclass(frozen=True)
    class WrongPayload:
        person: annotation
        tool: _K0IndividualRef

        def validate_for_k0(self):
            pass

    # The local annotation is intentionally supplied as a resolved type, not a forward name.
    WrongPayload.__annotations__["person"] = annotation
    with pytest.raises(K0ProfileError, match="participant payload"):
        replace(_source(), payload_type=WrongPayload)
