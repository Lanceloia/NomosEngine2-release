"""One authored due-transition LawDef has two real non-GV K0 consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemoryRuleInput,
    _K0InMemorySession,
    _K0SameWaveProposal,
)
from nomos_kernel._owner_abi import _K0OccurrenceContribution
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState

from nomos_c0 import C0LawError
from nomos_c0.scene_action_v1 import (
    C0SceneActionCatalog,
    C0SceneActionLibraryRegistration,
    C0SceneActionPorts,
)
from nomos_c0.scene_due_ordered_v1 import (
    C0SceneDueOrderedCatalog,
    C0SceneDueOrderedRegistration,
)
from nomos_c0.scene_due_v1 import (
    C0SceneDueCatalog,
    C0SceneDueLibraryRegistration,
    C0SceneDuePorts,
)
from nomos_c0.scene_due_wave_v1 import C0SceneDueWaveCatalog, C0SceneDueWaveRegistration

OWNER = K0OwnerKey("c0.scene_due.test.scene")
EXAMPLES = Path(__file__).resolve().parents[2] / "src" / "nomos_c0" / "examples"
STEP_SOURCE = K0SourceSpecKey("c0.scene_due.test.step")
STEP_EVENT = K0EventTypeKey("c0.scene_due.test.step.event")
START_SOURCE = K0SourceSpecKey("c0.scene_due.test.start")
START_EVENT = K0EventTypeKey("c0.scene_due.test.start.event")
END_SOURCE = K0SourceSpecKey("c0.scene_due.test.end")
END_EVENT = K0EventTypeKey("c0.scene_due.test.end.event")
OTHER_OWNER = K0OwnerKey("c0.scene_due.test.other")
OTHER_SOURCE = K0SourceSpecKey("c0.scene_due.test.other.event")
OTHER_EVENT = K0EventTypeKey("c0.scene_due.test.other.classification")


@dataclass(frozen=True)
class _Token:
    token_id: str
    status: str = "ready"
    address: str | None = "desk"
    start_due: int | None = 1
    end_due: int | None = 2
    started: K0OccurrenceRef | None = None
    ended: K0OccurrenceRef | None = None

    def validate_for_k0(self) -> None:
        if type(self) is not _Token or self.token_id not in ("token-A", "token-B"):
            raise K0ProfileError("test token is malformed")


@dataclass(frozen=True)
class _Scene:
    clock: int = 0
    tokens: tuple[_Token, ...] = (_Token("token-A"),)

    def validate_for_k0(self) -> None:
        if type(self) is not _Scene or type(self.clock) is not int or self.clock < 0:
            raise K0ProfileError("test scene is malformed")
        if tuple(item.token_id for item in self.tokens) not in (
            ("token-A",),
            ("token-A", "token-B"),
        ):
            raise K0ProfileError("test scene repeats or omits its token")
        for item in self.tokens:
            item.validate_for_k0()
        if (
            len(self.tokens) == 2
            and self.tokens[0].address == "blocked"
            and self.tokens[0].status == "moving"
            and self.tokens[1].status == "reached"
        ):
            raise K0ProfileError("test scene disallows this joint state")


@dataclass(frozen=True)
class _Attempt:
    actor: str
    kind: str

    def validate_for_k0(self) -> None:
        if type(self) is not _Attempt or self.actor != "clock" or self.kind != "step":
            raise K0ProfileError("test attempt is malformed")


@dataclass(frozen=True)
class _Evidence:
    phase: str
    scene: _Scene
    actors: tuple[_Scene, ...]
    actor: str
    kind: str
    item_id: str | None = None
    address: str | None = None

    def validate_for_k0(self) -> None:
        if type(self) is not _Evidence or type(self.actors) is not tuple:
            raise K0ProfileError("test evidence is malformed")
        self.scene.validate_for_k0()


@dataclass(frozen=True)
class _Participants:
    actor: str

    def validate_for_k0(self) -> None:
        if type(self) is not _Participants or self.actor != "clock":
            raise K0ProfileError("test participants are malformed")


@dataclass(frozen=True)
class _Envelope:
    phase: str
    tick: int
    content: None = None

    def validate_for_k0(self) -> None:
        if type(self) is not _Envelope or type(self.tick) is not int or self.content is not None:
            raise K0ProfileError("test envelope is malformed")


@dataclass(frozen=True)
class _Replace:
    owner: K0OwnerKey
    state: _Scene

    def validate_for_k0(self) -> None:
        if type(self) is not _Replace or self.owner != OWNER:
            raise K0ProfileError("test replacement is malformed")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey = OWNER
    owner_version: str = "c0-scene-due-test-v1"
    state_type: ClassVar[type] = _Scene
    view_type: ClassVar[type] = _Scene
    contribution_type: ClassVar[type] = _Replace
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not _Scene:
            raise K0ProfileError("test owner has foreign state")
        state.validate_for_k0()

    def read_view(self, state: object) -> object:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _Replace:
            raise K0ProfileError("test owner has foreign contribution")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if len(contributions) != 1:
            raise K0ProfileError("test owner needs one replacement")
        self.validate_contribution(contributions[0].contribution)
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> object:
        self.validate_state(state)
        self.merge_contributions(contributions)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("test owner has no local identities")

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        return ()

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        return (
            self.owner_version,
            state.clock,
            tuple(
                (
                    item.token_id,
                    item.status,
                    item.address,
                    item.start_due,
                    item.end_due,
                    None if item.started is None else item.started.value,
                    None if item.ended is None else item.ended.value,
                )
                for item in state.tokens
            ),
        )

    def decode_state(self, wire: object) -> object:
        if type(wire) is not tuple or len(wire) != 3 or wire[0] != self.owner_version:
            raise K0ProfileError("test owner wire is malformed")
        tokens = tuple(
            _Token(
                item[0],
                item[1],
                item[2],
                item[3],
                item[4],
                None if item[5] is None else K0OccurrenceRef(item[5]),
                None if item[6] is None else K0OccurrenceRef(item[6]),
            )
            for item in wire[2]
        )
        state = _Scene(wire[1], tokens)
        self.validate_state(state)
        return state


@dataclass(frozen=True)
class _OtherReplace:
    owner: K0OwnerKey
    state: _Scene

    def validate_for_k0(self) -> None:
        if type(self) is not _OtherReplace or self.owner != OTHER_OWNER:
            raise K0ProfileError("other replacement is malformed")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _OtherOwner(_Owner):
    key: K0OwnerKey = OTHER_OWNER
    contribution_type: ClassVar[type] = _OtherReplace

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _OtherReplace:
            raise K0ProfileError("other owner has foreign contribution")
        contribution.validate_for_k0()


@dataclass(frozen=True)
class _OtherRule:
    capability_ref: object

    def evaluate(self, rule_input):
        other_scene = replace(rule_input.evidence.scene, clock=99)
        return _K0InMemoryEvaluation(
            K0RuleResult((_OtherReplace(OTHER_OWNER, other_scene),), ()),
            _Envelope("other", rule_input.evidence.scene.clock),
        )


@dataclass(frozen=True)
class _ExtraSceneRule:
    capability_ref: object

    def evaluate(self, rule_input):
        scene = replace(rule_input.evidence.scene, clock=99)
        return _K0InMemoryEvaluation(
            K0RuleResult((_Replace(OWNER, scene),), ()),
            _Envelope("other", rule_input.evidence.scene.clock),
        )


def _step_spec():
    manifest = {
        "schema": "c0.lib.scene_action.v1",
        "id": "c0.test.scene_due.clock",
        "revision": "v1",
        "exports": {
            "step": {
                "native": "step",
                "scene_owner": OWNER.value,
                "source_key": STEP_SOURCE.value,
                "event_type": STEP_EVENT.value,
                "field": "clock",
                "increment": 1,
            }
        },
    }
    source = {
        "schema": "c0.source.scene_action.v1",
        "lib": {"id": manifest["id"], "revision": "v1"},
        "action": {
            "export": "step",
            "when": {"const": True},
            "set": {"clock": {"add": [{"ref": "scene.clock"}, {"const": 1}]}},
        },
    }
    ports = C0SceneActionPorts(
        OWNER,
        STEP_SOURCE,
        STEP_EVENT,
        _Scene,
        _Attempt("clock", "step"),
        _Evidence,
        _Participants,
        _Envelope,
        _Replace,
        "clock",
        1,
        "step",
    )
    catalog = C0SceneActionCatalog(
        (C0SceneActionLibraryRegistration(json.dumps(manifest), {"step": ports}),)
    )
    return catalog.compile(json.dumps(source)).source_spec()


def _due_manifest() -> dict[str, object]:
    return {
        "schema": "c0.lib.scene_due.v1",
        "id": "c0.test.scene_due",
        "revision": "v1",
        "lawdefs": {
            "token_due": {
                "opcode": "collection_member_due_transition.v1",
                "formals": ["carrier_id", "from_status", "due_field", "to_status", "receipt_field"],
            }
        },
        "exports": {
            "start": {
                "native": "start",
                "lawdef": "token_due",
                "scene_owner": OWNER.value,
                "law_key": "c0.test.token.start.law",
                "trigger_source": STEP_SOURCE.value,
                "trigger_event": STEP_EVENT.value,
                "result_source": START_SOURCE.value,
                "result_event": START_EVENT.value,
                "carrier_id": "token-A",
                "evidence_member_field": "item_id",
                "evidence_recipient_field": "address",
                "transition": ["ready", "start_due", "moving", "started"],
            },
            "end": {
                "native": "end",
                "lawdef": "token_due",
                "scene_owner": OWNER.value,
                "law_key": "c0.test.token.end.law",
                "trigger_source": STEP_SOURCE.value,
                "trigger_event": STEP_EVENT.value,
                "result_source": END_SOURCE.value,
                "result_event": END_EVENT.value,
                "carrier_id": "token-A",
                "evidence_member_field": "item_id",
                "evidence_recipient_field": "address",
                "transition": ["moving", "end_due", "reached", "ended"],
            },
        },
    }


def _due_source(start_when: object = None) -> dict[str, object]:
    manifest = _due_manifest()
    events = []
    for name in ("start", "end"):
        transition = manifest["exports"][name]["transition"]
        events.append(
            {
                "export": name,
                "lawdef": {"ref": "token_due"},
                "arguments": dict(
                    zip(
                        ("carrier_id", "from_status", "due_field", "to_status", "receipt_field"),
                        ("token-A", *transition),
                        strict=True,
                    )
                ),
                "when": {"const": True} if name != "start" or start_when is None else start_when,
            }
        )
    return {
        "schema": "c0.source.scene_due.v1",
        "lib": {"id": manifest["id"], "revision": "v1"},
        "events": events,
    }


def _due_programs(*, manifest=None, source=None):
    manifest = manifest or _due_manifest()
    base = (
        OWNER,
        STEP_SOURCE,
        STEP_EVENT,
        _Scene,
        _Token,
        _Evidence,
        _Participants,
        _Envelope,
        _Replace,
        "tokens",
        "clock",
        "token_id",
        "status",
        "address",
        "item_id",
        "address",
    )
    ports = {
        "start": C0SceneDuePorts(
            base[0],
            K0CausalLawKey("c0.test.token.start.law"),
            base[1],
            base[2],
            START_SOURCE,
            START_EVENT,
            *base[3:],
            manifest["exports"]["start"]["carrier_id"],
            tuple(manifest["exports"]["start"]["transition"]),
            "start",
            "step",
            "clock",
            "step",
        ),
        "end": C0SceneDuePorts(
            base[0],
            K0CausalLawKey("c0.test.token.end.law"),
            base[1],
            base[2],
            END_SOURCE,
            END_EVENT,
            *base[3:],
            manifest["exports"]["end"]["carrier_id"],
            tuple(manifest["exports"]["end"]["transition"]),
            "end",
            "step",
            "clock",
            "step",
        ),
    }
    catalog = C0SceneDueCatalog((C0SceneDueLibraryRegistration(json.dumps(manifest), ports),))
    return catalog.compile(json.dumps(source or _due_source()))


def _session(source=None, manifest=None, opening=None):
    specs_and_laws = tuple(
        program.bind() for program in _due_programs(source=source, manifest=manifest)
    )
    profile = _K0InMemoryProfile(
        (_Owner(),),
        (_step_spec(), *(item[0] for item in specs_and_laws)),
        tuple(item[1] for item in specs_and_laws),
        4,
        2,
    )
    return _K0InMemorySession.create(
        profile, (_K0OwnerState(OWNER, opening if opening is not None else _Scene()),)
    )


def _wave_inputs(*, same_target=False, strategy="merge_distinct_due_members.v1", start_when=None):
    manifest = json.loads((EXAMPLES / "scene_due_wave_v2.lib.json").read_text())
    source_file = (
        "scene_due_wave_reject_v2.source.json"
        if strategy == "reject_unproven_same_wave.v1"
        else "scene_due_wave_merge_v2.source.json"
    )
    source = json.loads((EXAMPLES / source_file).read_text())
    manifest["exports"]["end"]["carrier_id"] = "token-A" if same_target else "token-B"
    manifest["exports"]["end"]["transition"] = [
        "ready",
        "start_due" if same_target else "end_due",
        "reached",
        "ended",
    ]
    source["settlement"]["lawdef"]["ref"] = strategy
    source["events"][1]["arguments"] = dict(
        zip(
            ("carrier_id", "from_status", "due_field", "to_status", "receipt_field"),
            (manifest["exports"]["end"]["carrier_id"], *manifest["exports"]["end"]["transition"]),
            strict=True,
        )
    )
    if start_when is not None:
        source["events"][0]["when"] = start_when
    return manifest, source


def _wave_session(
    *,
    same_target=False,
    strategy="merge_distinct_due_members.v1",
    start_when=None,
    tamper=False,
    opening=None,
    source_mutator=None,
    manifest_mutator=None,
):
    manifest, source = _wave_inputs(
        same_target=same_target, strategy=strategy, start_when=start_when
    )
    if source_mutator is not None:
        source_mutator(source)
    if manifest_mutator is not None:
        manifest_mutator(manifest)
    ports_manifest = _due_manifest()
    ports_manifest["exports"]["end"]["carrier_id"] = manifest["exports"]["end"]["carrier_id"]
    ports_manifest["exports"]["end"]["transition"] = manifest["exports"]["end"]["transition"]
    ports = {
        item.export: item._bound.ports
        for item in _due_programs(
            manifest=ports_manifest,
            source={
                "schema": "c0.source.scene_due.v1",
                "lib": {"id": source["lib"]["id"], "revision": "v1"},
                "events": source["events"],
            },
        )
    }
    bundle = C0SceneDueWaveCatalog(C0SceneDueWaveRegistration(json.dumps(manifest), ports)).compile(
        json.dumps(source)
    )
    specs, laws, policy = bundle.bind()
    if tamper:
        original = specs[1].rule

        @dataclass(frozen=True)
        class _ForgedRule:
            capability_ref: object = original.capability_ref

            def evaluate(self, rule_input):
                evaluation = original.evaluate(rule_input)
                contribution = evaluation.result.contributions[0]
                scene = contribution.state
                altered = replace(scene.tokens[1], address="forged")
                forged_scene = replace(scene, tokens=(scene.tokens[0], altered))
                return replace(
                    evaluation,
                    result=K0RuleResult((replace(contribution, state=forged_scene),), ()),
                )

        specs = (specs[0], replace(specs[1], rule=_ForgedRule()))
    profile = _K0InMemoryProfile((_Owner(),), (_step_spec(), *specs), laws, 4, 2, policy)
    opening = opening or _Scene(tokens=(_Token("token-A"), _Token("token-B", end_due=1)))
    return _K0InMemorySession.create(profile, (_K0OwnerState(OWNER, opening),))


def _sealed_wave_proposals(session, scene):
    proposals = []
    for ref, program, spec in zip(
        (2, 3),
        session._profile.same_wave_policy.programs,
        session._profile.source_specs[1:],
        strict=True,
    ):
        bound = program._bound
        evidence = bound.evidence(scene, bound.member(scene))
        rule_input = _K0InMemoryRuleInput(
            K0OccurrenceRef(ref),
            bound.ports.result_source,
            evidence,
            bound.ports.participants_type(actor="clock"),
            (),
            K0OccurrenceRef(1),
        )
        proposals.append(
            _K0SameWaveProposal(spec.key, rule_input, spec.rule.evaluate(rule_input).result)
        )
    return tuple(proposals)


def test_author_selected_same_wave_merge_preserves_both_events_and_effects() -> None:
    session = _wave_session()
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert tuple(item.source for item in receipt.occurrences) == (
        STEP_SOURCE,
        START_SOURCE,
        END_SOURCE,
    )
    assert tuple(item.coordinate.causal_wave_depth for item in receipt.occurrences[1:]) == (1, 1)
    a, b = session.read_owner(OWNER).view.tokens
    assert (a.status, a.started) == ("moving", receipt.occurrences[1].occurrence)
    assert (b.status, b.ended) == ("reached", receipt.occurrences[2].occurrence)


def test_author_selected_same_wave_rejection_rolls_back_entire_action() -> None:
    session = _wave_session(strategy="reject_unproven_same_wave.v1")
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view.clock == 0
    assert session._tape == ()
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))


def test_author_merge_rejects_two_due_events_on_one_member() -> None:
    session = _wave_session(same_target=True)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view.clock == 0
    assert session._tape == ()


def test_scene_due_wave_source_requires_exact_strategy_and_ports() -> None:
    with pytest.raises(C0LawError):
        _wave_session(strategy="unknown.v1")
    with pytest.raises(C0LawError):
        _wave_session(source_mutator=lambda row: row.pop("settlement"))
    with pytest.raises(C0LawError):
        _wave_session(
            source_mutator=lambda row: row["settlement"]["arguments"].update(owner="foreign")
        )
    with pytest.raises(C0LawError):
        _wave_session(
            manifest_mutator=lambda row: row["wave_lawdefs"][
                "merge_distinct_due_members.v1"
            ].update(collection="foreign")
        )


def test_same_wave_profile_rejects_swapped_causal_law_port_before_session() -> None:
    session = _wave_session()
    profile = session._profile
    wrong_laws = (
        replace(profile.causal_laws[0], resulting_source=END_SOURCE),
        replace(profile.causal_laws[1], resulting_source=START_SOURCE),
    )
    with pytest.raises(K0ProfileError):
        _K0InMemoryProfile(
            profile.owners,
            profile.source_specs,
            wrong_laws,
            4,
            2,
            profile.same_wave_policy,
        )


def test_shipped_wave_sources_differ_only_by_selected_lawdef() -> None:
    merge = json.loads((EXAMPLES / "scene_due_wave_merge_v2.source.json").read_text())
    reject = json.loads((EXAMPLES / "scene_due_wave_reject_v2.source.json").read_text())
    assert merge["settlement"]["lawdef"]["ref"] == "merge_distinct_due_members.v1"
    assert reject["settlement"]["lawdef"]["ref"] == "reject_unproven_same_wave.v1"
    reject["settlement"]["lawdef"]["ref"] = merge["settlement"]["lawdef"]["ref"]
    assert merge == reject


def test_scene_due_wave_single_due_event_keeps_ordinary_source() -> None:
    session = _wave_session(start_when={"const": False})
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert tuple(item.source for item in receipt.occurrences) == (STEP_SOURCE, END_SOURCE)
    a, b = session.read_owner(OWNER).view.tokens
    assert a.status == "ready" and a.started is None
    assert b.status == "reached" and b.ended == receipt.occurrences[1].occurrence


def test_same_wave_merge_rejects_undeclared_scene_change() -> None:
    session = _wave_session(tamper=True)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view.clock == 0
    assert session._tape == ()


def test_same_wave_merge_rejects_stale_basis_and_duplicate_ref() -> None:
    session = _wave_session()
    policy = session._profile.same_wave_policy
    scene = _Scene(1, (_Token("token-A"), _Token("token-B", end_due=1)))
    proposals = _sealed_wave_proposals(session, scene)
    stale = replace(
        proposals[1].rule_input,
        evidence=replace(proposals[1].rule_input.evidence, scene=replace(scene, clock=2)),
    )
    with pytest.raises(K0ProfileError):
        policy.merge(scene, (proposals[0], replace(proposals[1], rule_input=stale)))
    duplicate = replace(proposals[1].rule_input, occurrence=K0OccurrenceRef(2))
    with pytest.raises(K0ProfileError):
        policy.merge(scene, (proposals[0], replace(proposals[1], rule_input=duplicate)))


def test_same_wave_merge_rejects_invalid_joint_scene_atomically() -> None:
    opening = _Scene(tokens=(_Token("token-A", address="blocked"), _Token("token-B", end_due=1)))
    session = _wave_session(opening=opening)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view == opening
    assert session._tape == ()


def test_same_wave_policy_does_not_capture_unrelated_owner_event() -> None:
    original = _wave_session()
    profile = original._profile
    start_spec = profile.source_specs[1]
    start_law = profile.causal_laws[0]
    other_spec = replace(
        start_spec,
        key=OTHER_SOURCE,
        event_type=OTHER_EVENT,
        read_owners=(OWNER, OTHER_OWNER),
        contribution_owners=(OTHER_OWNER,),
        rule=_OtherRule(start_spec.rule.capability_ref),
    )
    other_law = replace(
        start_law,
        key=K0CausalLawKey("c0.scene_due.test.other.law"),
        resulting_source=OTHER_SOURCE,
    )
    extended = _K0InMemoryProfile(
        (*profile.owners, _OtherOwner()),
        (*profile.source_specs, other_spec),
        (*profile.causal_laws, other_law),
        5,
        2,
        profile.same_wave_policy,
    )
    session = _K0InMemorySession.create(
        extended,
        (*original._states, _K0OwnerState(OTHER_OWNER, _Scene())),
    )
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert tuple(item.source for item in receipt.occurrences) == (
        STEP_SOURCE,
        START_SOURCE,
        END_SOURCE,
        OTHER_SOURCE,
    )
    assert session.read_owner(OWNER).view.tokens[0].status == "moving"
    assert session.read_owner(OWNER).view.tokens[1].status == "reached"
    assert session.read_owner(OTHER_OWNER).view.clock == 99


def test_same_wave_policy_rejects_undeclared_write_to_selected_owner() -> None:
    original = _wave_session()
    profile = original._profile
    start_spec = profile.source_specs[1]
    start_law = profile.causal_laws[0]
    extra_spec = replace(
        start_spec,
        key=OTHER_SOURCE,
        event_type=OTHER_EVENT,
        rule=_ExtraSceneRule(start_spec.rule.capability_ref),
    )
    extra_law = replace(
        start_law,
        key=K0CausalLawKey("c0.scene_due.test.extra.law"),
        resulting_source=OTHER_SOURCE,
    )
    extended = _K0InMemoryProfile(
        profile.owners,
        (*profile.source_specs, extra_spec),
        (*profile.causal_laws, extra_law),
        5,
        2,
        profile.same_wave_policy,
    )
    session = _K0InMemorySession.create(extended, original._states)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view.clock == 0
    assert session._tape == ()


def _ordered_session(*, reverse=False, opening=None, source_mutator=None, invariants=()):
    manifest = json.loads((EXAMPLES / "scene_due_ordered_v1.lib.json").read_text())
    name = (
        "scene_due_ordered_reverse_v1.source.json"
        if reverse
        else "scene_due_ordered_forward_v1.source.json"
    )
    source = json.loads((EXAMPLES / name).read_text())
    if source_mutator is not None:
        source_mutator(source)
    legacy_manifest = dict(manifest)
    legacy_manifest["schema"] = "c0.lib.scene_due.v1"
    del legacy_manifest["order_lawdef"]
    legacy_source = dict(source)
    legacy_source["schema"] = "c0.source.scene_due.v1"
    del legacy_source["settlement"]
    ports = {
        program.export: program._bound.ports
        for program in _due_programs(manifest=legacy_manifest, source=legacy_source)
    }
    bundle = C0SceneDueOrderedCatalog(
        C0SceneDueOrderedRegistration(json.dumps(manifest), ports)
    ).compile(json.dumps(source))
    specs, laws, policy = bundle.bind()
    profile = _K0InMemoryProfile(
        (_Owner(),), (_step_spec(), *specs), laws, 4, 2, ordered_policy=policy
    )
    opening = opening or _Scene(tokens=(_Token("token-A", end_due=1),))
    return _K0InMemorySession.create(profile, (_K0OwnerState(OWNER, opening),), invariants)


def test_author_ordered_microsteps_reproject_current_scene() -> None:
    session = _ordered_session()
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert tuple(item.source for item in receipt.occurrences) == (
        STEP_SOURCE,
        START_SOURCE,
        END_SOURCE,
    )
    token = session.read_owner(OWNER).view.tokens[0]
    assert token.status == "reached"
    assert (token.started, token.ended) == tuple(
        item.occurrence for item in receipt.occurrences[1:]
    )
    start, end = receipt.occurrences[1:]
    assert (
        start.formation_basis.trigger
        == end.formation_basis.trigger
        == receipt.occurrences[0].occurrence
    )
    assert end.formation_basis.previous_completed == start.occurrence
    assert (start.formation_basis.ordinal, end.formation_basis.ordinal) == (1, 2)


@dataclass(frozen=True)
class _CaptureCurrentRule:
    original: object
    seen: list[K0OccurrenceRef | None]
    capability_ref: object

    def evaluate(self, rule_input):
        self.seen.append(rule_input.evidence.scene.tokens[0].started)
        return self.original.evaluate(rule_input)


def test_second_microstep_sealed_basis_contains_first_receipt() -> None:
    original = _ordered_session()
    profile = original._profile
    seen: list[K0OccurrenceRef | None] = []
    second = profile.source_specs[2]
    captured = replace(
        second,
        rule=_CaptureCurrentRule(second.rule, seen, second.rule.capability_ref),
    )
    changed = _K0InMemoryProfile(
        profile.owners,
        (*profile.source_specs[:2], captured),
        profile.causal_laws,
        4,
        2,
        ordered_policy=profile.ordered_policy,
    )
    session = _K0InMemorySession.create(changed, original._states)
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert seen == [receipt.occurrences[1].occurrence]


def test_author_order_changes_result_and_optional_step_can_be_empty() -> None:
    forward = _ordered_session()
    reverse = _ordered_session(reverse=True)
    first = forward.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    second = reverse.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(first) is type(second) is K0Published
    assert tuple(item.source for item in first.occurrences) == (
        STEP_SOURCE,
        START_SOURCE,
        END_SOURCE,
    )
    assert tuple(item.source for item in second.occurrences) == (STEP_SOURCE, START_SOURCE)
    assert forward.read_owner(OWNER).view.tokens[0].status == "reached"
    token = reverse.read_owner(OWNER).view.tokens[0]
    assert token.status == "moving" and token.ended is None
    assert second.occurrences[1].formation_basis.ordinal == 2
    assert second.occurrences[1].formation_basis.previous_completed is None


def test_ordered_example_sources_differ_only_in_step_order() -> None:
    forward = json.loads((EXAMPLES / "scene_due_ordered_forward_v1.source.json").read_text())
    reverse = json.loads((EXAMPLES / "scene_due_ordered_reverse_v1.source.json").read_text())
    reverse["settlement"]["steps"].reverse()
    assert reverse == forward


def test_required_empty_ordered_step_rolls_back_prior_step() -> None:
    def require_unavailable_end(row):
        row["events"][1]["when"] = {"const": False}
        row["settlement"]["steps"][1]["required"] = True

    session = _ordered_session(source_mutator=require_unavailable_end)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view == _Scene(tokens=(_Token("token-A", end_due=1),))
    assert session._tape == () and session._cursor.next_value == 1


@dataclass(frozen=True)
class _RejectIntermediateMoving:
    read_owners: tuple[K0OwnerKey, ...] = (OWNER,)

    def validate(self, views):
        if views[0].view.tokens[0].status == "moving":
            raise K0ProfileError("intermediate movement is forbidden")


def test_intermediate_invariant_rejects_even_if_second_step_would_repair() -> None:
    opening = _Scene(tokens=(_Token("token-A", end_due=1),))
    session = _ordered_session(opening=opening, invariants=(_RejectIntermediateMoving(),))
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view == opening
    assert session._tape == () and session._cursor.next_value == 1


@dataclass(frozen=True)
class _StaleOrderedProjector:
    original: object
    capability_ref: object

    def project(self, trigger, views):
        activations = self.original.project(trigger, views)
        if not activations:
            return activations
        activation = activations[0]
        scene = activation.evidence.scene
        forged_token = replace(scene.tokens[0], started=K0OccurrenceRef(999))
        forged_scene = replace(scene, tokens=(forged_token,))
        return (replace(activation, evidence=replace(activation.evidence, scene=forged_scene)),)


def test_ordered_step_rejects_stale_projector_basis_before_rule() -> None:
    original = _ordered_session()
    profile = original._profile
    law = profile.causal_laws[1]
    forged = replace(
        law,
        activation_projector=_StaleOrderedProjector(
            law.activation_projector, law.activation_projector.capability_ref
        ),
    )
    changed = _K0InMemoryProfile(
        profile.owners,
        profile.source_specs,
        (profile.causal_laws[0], forged),
        4,
        2,
        ordered_policy=profile.ordered_policy,
    )
    session = _K0InMemorySession.create(changed, original._states)
    with pytest.raises(K0SettlementDefect):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view.clock == 0
    assert session._tape == () and session._cursor.next_value == 1


def test_ordered_source_and_registered_ports_are_closed() -> None:
    with pytest.raises(C0LawError):
        _ordered_session(
            source_mutator=lambda row: row["settlement"]["steps"].append(
                {"export": "start", "required": True}
            )
        )
    with pytest.raises(C0LawError):
        _ordered_session(
            source_mutator=lambda row: row["settlement"]["steps"][1].update(export="start")
        )
    with pytest.raises(C0LawError):
        _ordered_session(
            source_mutator=lambda row: row["settlement"]["lawdef"].update(ref="foreign")
        )
    session = _ordered_session()
    profile = session._profile
    with pytest.raises(K0ProfileError):
        _K0InMemoryProfile(
            profile.owners,
            profile.source_specs,
            (replace(profile.causal_laws[0], resulting_source=END_SOURCE), profile.causal_laws[1]),
            4,
            2,
            ordered_policy=profile.ordered_policy,
        )
    with pytest.raises(K0ProfileError):
        _K0InMemoryProfile(
            profile.owners,
            profile.source_specs,
            (
                *profile.causal_laws,
                replace(profile.causal_laws[0], key=K0CausalLawKey("c0.test.unlisted.law")),
            ),
            5,
            2,
            ordered_policy=profile.ordered_policy,
        )


def test_two_bindings_of_one_lawdef_publish_distinct_due_events() -> None:
    session = _session()
    first = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(first) is K0Published
    assert tuple(item.source for item in first.occurrences) == (STEP_SOURCE, START_SOURCE)
    moving = session.read_owner(OWNER).view.tokens[0]
    assert moving.status == "moving" and moving.started == first.occurrences[1].occurrence
    second = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(second) is K0Published
    assert tuple(item.source for item in second.occurrences) == (STEP_SOURCE, END_SOURCE)
    reached = session.read_owner(OWNER).view.tokens[0]
    assert reached.status == "reached" and reached.ended == second.occurrences[1].occurrence


def test_false_authored_condition_prevents_only_the_due_event() -> None:
    source = _due_source({"const": False})
    session = _session(source)
    receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert type(receipt) is K0Published
    assert tuple(item.source for item in receipt.occurrences) == (STEP_SOURCE,)
    assert session.read_owner(OWNER).view.clock == 1
    token = session.read_owner(OWNER).view.tokens[0]
    assert token.status == "ready" and token.started is None


def test_unselected_same_wave_whole_scene_replacements_roll_back() -> None:
    manifest, source = _due_manifest(), _due_source()
    transition = ["ready", "start_due", "reached", "ended"]
    manifest["exports"]["end"]["transition"] = transition
    source["events"][1]["arguments"] = dict(
        zip(
            ("carrier_id", "from_status", "due_field", "to_status", "receipt_field"),
            ("token-A", *transition),
            strict=True,
        )
    )
    session = _session(source, manifest)
    opening = session.read_owner(OWNER).view
    with pytest.raises(K0SettlementDefect, match="in-memory settlement"):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view == opening
    assert session._tape == ()
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))


def test_unselected_same_wave_independent_members_also_roll_back() -> None:
    manifest, source = _due_manifest(), _due_source()
    transition = ["ready", "start_due", "moving", "started"]
    manifest["exports"]["end"]["carrier_id"] = "token-B"
    manifest["exports"]["end"]["transition"] = transition
    source["events"][1]["arguments"] = dict(
        zip(
            ("carrier_id", "from_status", "due_field", "to_status", "receipt_field"),
            ("token-B", *transition),
            strict=True,
        )
    )
    opening = _Scene(tokens=(_Token("token-A"), _Token("token-B")))
    session = _session(source, manifest, opening)
    with pytest.raises(K0SettlementDefect, match="in-memory settlement"):
        session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    assert session.read_owner(OWNER).view == opening
    assert session._tape == ()


def test_prior_due_transition_can_suppress_a_later_stale_due() -> None:
    manifest, source = _due_manifest(), _due_source()
    first = ["ready", "start_due", "cancelled", "started"]
    second = ["ready", "end_due", "reached", "ended"]
    for index, transition in enumerate((first, second)):
        name = ("start", "end")[index]
        manifest["exports"][name]["transition"] = transition
        source["events"][index]["arguments"] = dict(
            zip(
                ("carrier_id", "from_status", "due_field", "to_status", "receipt_field"),
                ("token-A", *transition),
                strict=True,
            )
        )
    session = _session(source, manifest)
    first_receipt = session.settle(_K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step")))
    second_receipt = session.settle(
        _K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step"))
    )
    assert type(first_receipt) is K0Published and type(second_receipt) is K0Published
    assert tuple(item.source for item in first_receipt.occurrences) == (STEP_SOURCE, START_SOURCE)
    assert tuple(item.source for item in second_receipt.occurrences) == (STEP_SOURCE,)
    assert session.read_owner(OWNER).view.clock == 2
    token = session.read_owner(OWNER).view.tokens[0]
    assert token.status == "cancelled" and token.ended is None

    control = _session(source, manifest, _Scene(1, (_Token("token-A", start_due=0),)))
    control_receipt = control.settle(
        _K0InMemoryActionAttempt(STEP_SOURCE, _Attempt("clock", "step"))
    )
    assert type(control_receipt) is K0Published
    assert tuple(item.source for item in control_receipt.occurrences) == (STEP_SOURCE, END_SOURCE)


@pytest.mark.parametrize(
    "change",
    [
        "mixed_due",
        "mixed_receipt",
        "foreign_source",
        "foreign_evidence",
        "missing_lawdef",
        "malformed_lawdef",
        "malformed_native",
    ],
)
def test_incoherent_transition_or_port_rejects_before_session(change: str) -> None:
    manifest, source = _due_manifest(), _due_source()
    if change == "mixed_due":
        source["events"][0]["arguments"]["due_field"] = "end_due"
    elif change == "mixed_receipt":
        source["events"][0]["arguments"]["receipt_field"] = "ended"
    elif change == "foreign_source":
        manifest["exports"]["start"]["result_source"] = "foreign"
    elif change == "foreign_evidence":
        manifest["exports"]["start"]["evidence_member_field"] = "foreign"
    elif change == "malformed_lawdef":
        manifest["exports"]["start"]["lawdef"] = ["carrier_due_transition"]
    elif change == "malformed_native":
        manifest["exports"]["start"]["native"] = ["start"]
    else:
        source["events"][0]["lawdef"]["ref"] = "missing"
    with pytest.raises(C0LawError):
        _due_programs(manifest=manifest, source=source)
