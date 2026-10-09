"""A Scene-only Action compiles once and settles repeatedly in private K0."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

import pytest
from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryProfile,
    _K0InMemoryRuleInput,
    _K0InMemorySession,
)
from nomos_kernel._owner_abi import _K0OccurrenceContribution
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from nomos_kernel._state_image_abi import _K0OwnerState

from nomos_c0 import C0LawError
from nomos_c0.scene_action_v1 import (
    C0SceneActionCatalog,
    C0SceneActionLibraryRegistration,
    C0SceneActionPorts,
)

SCENE = K0OwnerKey("c0.scene_action.test.scene")
SOURCE = K0SourceSpecKey("c0.scene_action.test.step")
EVENT = K0EventTypeKey("c0.scene_action.test.step.event")


@dataclass(frozen=True)
class _Scene:
    counter: int

    def validate_for_k0(self) -> None:
        if type(self) is not _Scene or type(self.counter) is not int or self.counter < 0:
            raise K0ProfileError("test Scene is malformed")


@dataclass(frozen=True)
class _Attempt:
    actor: str
    kind: str

    def validate_for_k0(self) -> None:
        if type(self) is not _Attempt or type(self.actor) is not str or type(self.kind) is not str:
            raise K0ProfileError("test Action is malformed")


@dataclass
class _MutableAttempt:
    actor: str
    kind: str

    def validate_for_k0(self) -> None:
        if type(self) is not _MutableAttempt:
            raise K0ProfileError("test mutable Action is malformed")


@dataclass(frozen=True)
class _Evidence:
    phase: str
    scene: _Scene
    actors: tuple[_Scene, ...]
    actor: str
    kind: str

    def validate_for_k0(self) -> None:
        if type(self) is not _Evidence or type(self.actors) is not tuple:
            raise K0ProfileError("test evidence is malformed")
        self.scene.validate_for_k0()


@dataclass(frozen=True)
class _Participants:
    actor: str

    def validate_for_k0(self) -> None:
        if type(self) is not _Participants or type(self.actor) is not str:
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
        if type(self) is not _Replace or self.owner != SCENE:
            raise K0ProfileError("test contribution is malformed")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey = SCENE
    owner_version: str = "c0-scene-action-test-v1"
    state_type: ClassVar[type] = _Scene
    view_type: ClassVar[type] = _Scene
    contribution_type: ClassVar[type] = _Replace
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not _Scene:
            raise K0ProfileError("test owner state is foreign")
        state.validate_for_k0()

    def read_view(self, state: object) -> object:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not _Replace:
            raise K0ProfileError("test owner contribution is foreign")
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
        return (self.owner_version, state.counter)

    def decode_state(self, wire: object) -> object:
        if type(wire) is not tuple or len(wire) != 2 or wire[0] != self.owner_version:
            raise K0ProfileError("test owner wire is malformed")
        state = _Scene(wire[1])
        self.validate_state(state)
        return state


def _manifest() -> dict[str, object]:
    return {
        "schema": "c0.lib.scene_action.v1",
        "id": "c0.test.scene_action",
        "revision": "v1",
        "exports": {
            "step": {
                "native": "step",
                "scene_owner": SCENE.value,
                "source_key": SOURCE.value,
                "event_type": EVENT.value,
                "field": "counter",
                "increment": 1,
            }
        },
    }


def _source(when: object = None) -> dict[str, object]:
    return {
        "schema": "c0.source.scene_action.v1",
        "lib": {"id": "c0.test.scene_action", "revision": "v1"},
        "action": {
            "export": "step",
            "when": {"const": True} if when is None else when,
            "set": {"counter": {"add": [{"ref": "scene.counter"}, {"const": 1}]}},
        },
    }


def _catalog(manifest: dict[str, object] | None = None) -> C0SceneActionCatalog:
    ports = C0SceneActionPorts(
        SCENE,
        SOURCE,
        EVENT,
        _Scene,
        _Attempt("clock", "step"),
        _Evidence,
        _Participants,
        _Envelope,
        _Replace,
        "counter",
        1,
        "step",
    )
    return C0SceneActionCatalog(
        (C0SceneActionLibraryRegistration(json.dumps(manifest or _manifest()), {"step": ports}),)
    )


def _runtime(when: object = None) -> tuple[_K0InMemorySession, object]:
    spec = _catalog().compile(json.dumps(_source(when))).source_spec()
    profile = _K0InMemoryProfile((_Owner(),), (spec,), (), 4, 0)
    return _K0InMemorySession.create(profile, (_K0OwnerState(SCENE, _Scene(0)),)), spec


def test_scene_only_spec_settles_twice_without_an_actor_or_occurrence_slot() -> None:
    runtime, spec = _runtime()
    receipts = tuple(
        runtime.settle(_K0InMemoryActionAttempt(SOURCE, _Attempt("clock", "step")))
        for _ in range(2)
    )
    assert all(type(item) is K0Published for item in receipts)
    assert tuple(item.occurrences[0].occurrence.value for item in receipts) == (1, 2)
    assert runtime.read_owner(SCENE).view.counter == 2
    assert spec.read_owners == spec.contribution_owners == (SCENE,)


def test_false_condition_and_wrong_payload_do_not_consume_an_occurrence() -> None:
    runtime, _ = _runtime({"const": False})
    assert (
        type(runtime.settle(_K0InMemoryActionAttempt(SOURCE, _Attempt("clock", "step"))))
        is K0NotAdmitted
    )
    assert runtime.read_owner(SCENE).view.counter == 0
    runtime, _ = _runtime()
    assert (
        type(runtime.settle(_K0InMemoryActionAttempt(SOURCE, _Attempt("other", "step"))))
        is K0NotAdmitted
    )
    published = runtime.settle(_K0InMemoryActionAttempt(SOURCE, _Attempt("clock", "step")))
    assert published.occurrences[0].occurrence.value == 1


@pytest.mark.parametrize(
    "change", ["owner", "source", "event", "delta", "author_owner", "author_delta", "author_field"]
)
def test_source_and_library_reject_untrusted_identity_or_effect(change: str) -> None:
    manifest, source = _manifest(), _source()
    if change in ("owner", "source", "event", "delta"):
        key = {
            "owner": "scene_owner",
            "source": "source_key",
            "event": "event_type",
            "delta": "increment",
        }[change]
        manifest["exports"]["step"][key] = "foreign" if change != "delta" else 2
    elif change == "author_owner":
        source["action"]["scene_owner"] = SCENE.value
    elif change == "author_delta":
        source["action"]["set"]["counter"]["add"][1] = {"const": 2}
    else:
        source["action"]["set"] = {"other": {"add": [{"ref": "scene.counter"}, {"const": 1}]}}
    with pytest.raises(C0LawError):
        _catalog(manifest).compile(json.dumps(source))


def test_mismatched_sealed_evidence_cannot_drive_the_rule() -> None:
    _, spec = _runtime()
    forged = _K0InMemoryRuleInput(
        K0OccurrenceRef(1),
        SOURCE,
        _Evidence("step", _Scene(0), (), "other", "step"),
        _Participants("clock"),
        (),
        None,
    )
    with pytest.raises(K0ProfileError, match="admitted evidence"):
        spec.rule.evaluate(forged)


def test_mutable_trusted_payload_cannot_change_step_identity_after_registration() -> None:
    payload = _MutableAttempt("clock", "step")
    ports = C0SceneActionPorts(
        SCENE,
        SOURCE,
        EVENT,
        _Scene,
        payload,
        _Evidence,
        _Participants,
        _Envelope,
        _Replace,
        "counter",
        1,
        "step",
    )
    with pytest.raises(C0LawError, match="recursively frozen"):
        C0SceneActionCatalog(
            (C0SceneActionLibraryRegistration(json.dumps(_manifest()), {"step": ports}),)
        )
    payload.kind = "skip"
