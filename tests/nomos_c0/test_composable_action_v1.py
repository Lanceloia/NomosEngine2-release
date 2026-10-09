"""One authored value law writes two nominal owners through actual K0 settlement."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
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
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState

from nomos_c0 import C0LawError
from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.composable_action_v1 import (
    C0ValueActionEvidence,
    C0ValueActionParticipants,
    C0ValueActionPorts,
    compile_composable_action,
)
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError
from nomos_c0.seat_offers_v0 import C0FiniteOfferProvider, compile_seat_offers

SCENE_KEY = K0OwnerKey("c0.parcel.scene")
ACTOR_KEY = K0OwnerKey("c0.parcel.actor")
SOURCE = (
    Path(__file__).resolve().parents[2] / "src/nomos_c0/examples/parcel_dispatch_v1.action.json"
)
READ_SOURCE = (
    Path(__file__).resolve().parents[2] / "src/nomos_c0/examples/parcel_read_v1.action.json"
)


@dataclass(frozen=True)
class Parcel:
    id: str
    status: str
    recipient: str | None = None
    dispatch: K0OccurrenceRef | None = None

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Parcel
            or type(self.id) is not str
            or not self.id
            or self.status not in ("home", "preparing", "queued", "arrived")
            or (self.recipient is not None and type(self.recipient) is not str)
            or (self.dispatch is not None and type(self.dispatch) is not K0OccurrenceRef)
        ):
            raise K0ProfileError("parcel is malformed")


@dataclass(frozen=True)
class Route:
    recipient: str
    travel: int
    content: str

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Route
            or type(self.recipient) is not str
            or type(self.travel) is not int
            or self.travel < 0
            or type(self.content) is not str
        ):
            raise K0ProfileError("route is malformed")


@dataclass(frozen=True)
class Receipt:
    item_id: str
    action: K0OccurrenceRef

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Receipt
            or type(self.item_id) is not str
            or type(self.action) is not K0OccurrenceRef
        ):
            raise K0ProfileError("receipt is malformed")


@dataclass(frozen=True)
class Scene:
    tick: int
    deadline: int
    parcels: tuple[Parcel, ...]
    routes: tuple[Route, ...]

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Scene
            or type(self.tick) is not int
            or type(self.deadline) is not int
            or not 0 <= self.tick <= self.deadline
            or type(self.parcels) is not tuple
            or type(self.routes) is not tuple
        ):
            raise K0ProfileError("scene is malformed")
        for item in (*self.parcels, *self.routes):
            item.validate_for_k0()


@dataclass(frozen=True)
class Actor:
    role: str
    heard: bool
    receipts: tuple[Receipt, ...]

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Actor
            or type(self.role) is not str
            or type(self.heard) is not bool
            or type(self.receipts) is not tuple
        ):
            raise K0ProfileError("actor is malformed")
        for receipt in self.receipts:
            receipt.validate_for_k0()


@dataclass(frozen=True)
class Attempt:
    actor: str
    target: str
    item_id: str

    def validate_for_k0(self) -> None:
        if type(self) is not Attempt or any(
            type(value) is not str or not value for value in (self.actor, self.target, self.item_id)
        ):
            raise K0ProfileError("attempt is malformed")


@dataclass(frozen=True)
class Contribution:
    owner: K0OwnerKey
    state: Scene | Actor

    def validate_for_k0(self) -> None:
        if type(self) is not Contribution or (
            (self.owner == SCENE_KEY and type(self.state) is not Scene)
            or (self.owner == ACTOR_KEY and type(self.state) is not Actor)
            or self.owner not in (SCENE_KEY, ACTOR_KEY)
        ):
            raise K0ProfileError("contribution is malformed")
        self.state.validate_for_k0()


@dataclass(frozen=True)
class WrongContribution:
    owner: K0OwnerKey
    state: str

    def validate_for_k0(self) -> None:
        raise K0ProfileError("wrong contribution must never be constructed")


@dataclass(frozen=True)
class Envelope:
    action: K0OccurrenceRef
    content: str

    def validate_for_k0(self) -> None:
        if (
            type(self) is not Envelope
            or type(self.action) is not K0OccurrenceRef
            or type(self.content) is not str
        ):
            raise K0ProfileError("envelope is malformed")


@dataclass(frozen=True)
class Owner:
    key: K0OwnerKey
    owner_version: str
    state_type: type
    view_type: type
    contribution_type: ClassVar[type] = Contribution
    local_identity_families: ClassVar[tuple[str, ...]] = ()

    def validate_state(self, state: object) -> None:
        if type(state) is not self.state_type:
            raise K0ProfileError("owner state type is wrong")
        state.validate_for_k0()

    def read_view(self, state: object) -> object:
        self.validate_state(state)
        return state

    def validate_contribution(self, contribution: object) -> None:
        if type(contribution) is not Contribution or contribution.owner != self.key:
            raise K0ProfileError("owner contribution is wrong")
        contribution.validate_for_k0()

    def merge_contributions(
        self, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> tuple[_K0OccurrenceContribution, ...]:
        if len(contributions) != 1:
            raise K0ProfileError("owner needs one replacement")
        self.validate_contribution(contributions[0].contribution)
        return contributions

    def apply_contributions(
        self, state: object, contributions: tuple[_K0OccurrenceContribution, ...]
    ) -> object:
        self.validate_state(state)
        if len(contributions) != 1:
            raise K0ProfileError("owner needs one replacement")
        self.validate_contribution(contributions[0].contribution)
        return contributions[0].contribution.state

    def allocate_local_identity(self, state: object, slot: object, occurrence: object) -> object:
        raise K0ProfileError("owner has no local identity")

    def preserved_occurrences(self, state: object) -> tuple[K0OccurrenceRef, ...]:
        self.validate_state(state)
        if type(state) is Scene:
            return tuple(item.dispatch for item in state.parcels if item.dispatch is not None)
        return tuple(item.action for item in state.receipts)

    def encode_state(self, state: object) -> tuple[object, ...]:
        self.validate_state(state)
        if type(state) is Scene:
            return (
                self.owner_version,
                state.tick,
                state.deadline,
                tuple(
                    (
                        item.id,
                        item.status,
                        item.recipient,
                        None if item.dispatch is None else item.dispatch.value,
                    )
                    for item in state.parcels
                ),
                tuple((item.recipient, item.travel, item.content) for item in state.routes),
            )
        return (
            self.owner_version,
            state.role,
            state.heard,
            tuple((item.item_id, item.action.value) for item in state.receipts),
        )

    def decode_state(self, wire: object) -> object:
        if type(wire) is not tuple or not wire or wire[0] != self.owner_version:
            raise K0ProfileError("conformance owner wire is malformed")
        if self.state_type is Scene and len(wire) == 5:
            state = Scene(
                wire[1],
                wire[2],
                tuple(
                    Parcel(a, b, c, None if d is None else K0OccurrenceRef(d))
                    for a, b, c, d in wire[3]
                ),
                tuple(Route(*row) for row in wire[4]),
            )
        elif self.state_type is Actor and len(wire) == 4:
            state = Actor(
                wire[1],
                wire[2],
                tuple(Receipt(item_id, K0OccurrenceRef(ref)) for item_id, ref in wire[3]),
            )
        else:
            raise K0ProfileError("conformance owner wire shape is malformed")
        self.validate_state(state)
        return state


def _ports() -> C0ValueActionPorts:
    paths = frozenset(
        {
            "scene.tick",
            "scene.deadline",
            "scene.parcels",
            "scene.routes",
            "actor.heard",
            "actor.receipts",
            "payload.item_id",
            "payload.target",
        }
    )
    readable_fields = {
        Scene: frozenset({"tick", "deadline", "parcels", "routes"}),
        Actor: frozenset({"heard", "receipts"}),
        Attempt: frozenset({"item_id", "target"}),
        Parcel: frozenset({"id", "status", "recipient", "dispatch"}),
        Route: frozenset({"recipient", "travel", "content"}),
        Receipt: frozenset({"item_id"}),
    }
    value = C0ValuePorts(
        roots={"scene": Scene, "actor": Actor, "payload": Attempt},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=readable_fields,
        admission_readable_fields=readable_fields,
        writable_fields={
            Scene: frozenset({"parcels"}),
            Actor: frozenset({"receipts"}),
            Parcel: frozenset({"status", "recipient", "dispatch"}),
        },
        record_types={"Receipt": Receipt},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={
            "scene.parcels": "id",
            "scene.routes": "recipient",
            "actor.receipts": "item_id",
        },
        outputs={
            "parcels": tuple[Parcel, ...],
            "receipts": tuple[Receipt, ...],
            "action": K0OccurrenceRef,
            "content": str,
        },
    )
    return C0ValueActionPorts(
        K0SourceSpecKey("c0.example.parcel_dispatch.v1"),
        K0EventTypeKey("c0.example.parcel_dispatched.v1"),
        Owner(SCENE_KEY, "scene-v1", Scene, Scene),
        Owner(ACTOR_KEY, "actor-v1", Actor, Actor),
        Attempt,
        Contribution,
        Envelope,
        value,
        "role",
        "actor",
        {"scene": {"parcels": "parcels"}, "actor": {"receipts": "receipts"}},
        {"action": "action", "content": "content"},
    )


def _source() -> dict[str, object]:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def _read_ports() -> C0ValueActionPorts:
    ports = _ports()
    value = replace(
        ports.value_ports,
        readable_paths=ports.value_ports.readable_paths | {"actor.role"},
        admission_readable_paths=ports.value_ports.admission_readable_paths | {"actor.role"},
        readable_fields={
            **ports.value_ports.readable_fields,
            Actor: ports.value_ports.readable_fields[Actor] | {"role"},
        },
        admission_readable_fields={
            **ports.value_ports.admission_readable_fields,
            Actor: ports.value_ports.admission_readable_fields[Actor] | {"role"},
        },
        outputs={
            "receipts": tuple[Receipt, ...],
            "action": K0OccurrenceRef,
            "content": str,
        },
    )
    return replace(
        ports,
        source_key=K0SourceSpecKey("c0.example.parcel_read.v1"),
        event_type=K0EventTypeKey("c0.example.parcel_read_started.v1"),
        value_ports=value,
        state_effects={"scene": {}, "actor": {"receipts": "receipts"}},
    )


def _read_session(scene: Scene | None = None, *, heard: bool = True):
    ports = _read_ports()
    program = compile_composable_action(READ_SOURCE.read_text(encoding="utf-8"), ports)
    spec = program.build_spec()
    owners = tuple(sorted((ports.scene_owner, ports.actor_owner), key=lambda item: item.key))
    opening = scene or Scene(3, 9, (Parcel("P", "arrived", "keeper"),), ())
    runtime = _K0InMemorySession.create(
        _K0InMemoryProfile(owners, (spec,), (), 1, 0),
        tuple(
            _K0OwnerState(
                owner.key, opening if owner.key == SCENE_KEY else Actor("keeper", heard, ())
            )
            for owner in owners
        ),
    )
    return program, runtime


def _session(
    source: dict[str, object] | None = None,
    *,
    heard: bool = True,
    opening_scene: Scene | None = None,
    ports: C0ValueActionPorts | None = None,
):
    ports = ports or _ports()
    program = compile_composable_action(json.dumps(_source() if source is None else source), ports)
    spec = program.build_spec()
    scene = opening_scene or Scene(3, 9, (Parcel("P", "home"),), (Route("chapel", 2, "inspect"),))
    actor = Actor("keeper", heard, ())
    owners = tuple(sorted((ports.scene_owner, ports.actor_owner), key=lambda item: item.key))
    profile = _K0InMemoryProfile(owners, (spec,), (), 1, 0)
    runtime = _K0InMemorySession.create(
        profile,
        tuple(
            _K0OwnerState(owner.key, scene if owner.key == SCENE_KEY else actor) for owner in owners
        ),
    )
    return program, runtime


def _states(runtime):
    return runtime.read_owner(SCENE_KEY).view, runtime.read_owner(ACTOR_KEY).view


def test_authored_law_publishes_both_owner_effects_with_one_k0_ref():
    program, runtime = _session()
    receipt = runtime.settle(
        _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
    )
    assert isinstance(receipt, K0Published)
    ref = receipt.occurrences[0].occurrence
    scene, actor = _states(runtime)
    assert scene.parcels == (Parcel("P", "preparing", "chapel", ref),)
    assert actor.receipts == (Receipt("P", ref),)
    assert receipt.occurrences[0].semantic_envelope == Envelope(ref, "inspect")


def test_authored_count_condition_changes_real_k0_admission() -> None:
    source = _source()
    count = {
        "count_matching": {
            "collection": {"ref": "scene.parcels"},
            "as": "candidate",
            "where": {"eq": [{"ref": "candidate.status"}, {"const": "home"}]},
        }
    }
    threshold = {"const": 1}
    source["value"]["guard"]["all"].append({"eq": [count, threshold]})
    attempt = _K0InMemoryActionAttempt(
        K0SourceSpecKey(source["source_key"]), Attempt("keeper", "chapel", "P")
    )
    permitted, runtime = _session(source)
    assert isinstance(runtime.settle(attempt), K0Published)
    assert len(runtime.occurrence_history()) == 1

    threshold["const"] = 2
    denied, runtime = _session(source)
    assert permitted.source_key == denied.source_key
    before = _states(runtime)
    assert isinstance(runtime.settle(attempt), K0NotAdmitted)
    assert _states(runtime) == before
    assert runtime.occurrence_history() == ()


def test_offer_can_filter_fields_of_a_fully_visible_collection() -> None:
    offer = {
        "entry": "dispatch",
        "label": "Dispatch home parcel",
        "when": {
            "not": {
                "none_matching": {
                    "collection": {"ref": "scene.parcels"},
                    "as": "candidate",
                    "where": {"eq": [{"ref": "candidate.status"}, {"const": "home"}]},
                }
            }
        },
        "payload": {"target": {"const": "chapel"}, "item_id": {"const": "P"}},
    }
    provider = C0FiniteOfferProvider("finite_value", "1", 3)
    declarations = compile_seat_offers(
        [offer],
        ("dispatch",),
        ("scene.parcels",),
        {"dispatch": _ports()},
        {"dispatch": "scene"},
        "actor",
        provider,
    )
    actor = Actor("keeper", True, ())
    home = Scene(3, 9, (Parcel("P", "home"),), ())
    arrived = Scene(3, 9, (Parcel("P", "arrived"),), ())
    assert declarations[0].evaluate(home, actor) is not None
    assert declarations[0].evaluate(arrived, actor) is None
    with pytest.raises(C0LawError, match="read boundary"):
        compile_seat_offers(
            [offer],
            ("dispatch",),
            ("scene.tick",),
            {"dispatch": _ports()},
            {"dispatch": "scene"},
            "actor",
            provider,
        )


def test_offer_range_generates_current_targets_with_typed_labels_and_payloads() -> None:
    offer = {
        "entry": "dispatch",
        "for_each": {"collection": {"ref": "scene.parcels"}, "as": "parcel"},
        "label": {"prefix": "Dispatch ", "value": {"ref": "parcel.id"}},
        "when": {"eq": [{"ref": "parcel.status"}, {"const": "home"}]},
        "payload": {"target": {"const": "chapel"}, "item_id": {"ref": "parcel.id"}},
    }
    provider = C0FiniteOfferProvider("finite_value", "1", 3)
    declarations = compile_seat_offers(
        [offer],
        ("dispatch",),
        ("scene.parcels",),
        {"dispatch": _ports()},
        {"dispatch": "scene"},
        "actor",
        provider,
    )
    actor = Actor("keeper", True, ())
    scene = Scene(3, 9, (Parcel("P", "home"), Parcel("Q", "arrived")), ())
    assert [
        (item.label, dict(item.payload)) for item in declarations[0].evaluate_many(scene, actor)
    ] == [("Dispatch P", {"item_id": "P", "target": "chapel"})]
    with pytest.raises(C0LawError, match="read boundary"):
        compile_seat_offers(
            [offer],
            ("dispatch",),
            ("scene.tick",),
            {"dispatch": _ports()},
            {"dispatch": "scene"},
            "actor",
            provider,
        )
    with pytest.raises(C0ValueStateError, match="finite bound"):
        declarations[0].evaluate_many(
            Scene(
                3,
                9,
                (
                    Parcel("P", "home"),
                    Parcel("Q", "home"),
                    Parcel("R", "home"),
                    Parcel("S", "home"),
                ),
                (),
            ),
            actor,
        )


def test_predicate_unique_lookup_controls_actual_k0_action_without_host_search():
    source = _source()
    source["value"]["bindings"][1] = {
        "name": "route",
        "collection": "scene.routes",
        "as": "candidate",
        "where": {"eq": [{"ref": "candidate.recipient"}, {"ref": "payload.target"}]},
        "required": False,
    }
    base_ports = _ports()
    ports = replace(
        base_ports,
        value_ports=replace(
            base_ports.value_ports,
            collection_keys={
                key: value
                for key, value in base_ports.value_ports.collection_keys.items()
                if key != "scene.routes"
            },
        ),
    )
    attempt = Attempt("keeper", "chapel", "P")
    one, runtime = _session(source, ports=ports)
    receipt = runtime.settle(_K0InMemoryActionAttempt(one.source_key, attempt))
    assert isinstance(receipt, K0Published)
    assert receipt.occurrences[0].semantic_envelope.content == "inspect"
    assert _states(runtime)[0].parcels[0].dispatch == receipt.occurrences[0].occurrence

    for routes in ((), (Route("chapel", 2, "first"), Route("chapel", 3, "second"))):
        scene = Scene(3, 9, (Parcel("P", "home"),), routes)
        program, runtime = _session(source, ports=ports, opening_scene=scene)
        before = _states(runtime)
        assert isinstance(
            runtime.settle(_K0InMemoryActionAttempt(program.source_key, attempt)), K0NotAdmitted
        )
        assert _states(runtime) == before
        assert runtime.occurrence_history() == ()
        assert runtime._fatal is False


def test_predicate_lookup_compiles_with_assets_and_k0_in_one_owner_graph():
    from test_world_binding_v1 import ROOT, _compile, _documents

    from nomos_c0.author_document_v1 import read_author_document

    lib, ports, source = _documents("parcel_delivery_v0")
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    offer = session.offers("sender")[0]
    assert "scene.routes" not in dict(session.read("sender").fields)
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    scene_key = program.world_layout.owners.owner("scene").owner.key
    assert session._runtime.read_owner(scene_key).view.parcel.status == "transit"

    for routes in (
        [],
        [
            {"destination": "dock", "travel": 2},
            {"destination": "dock", "travel": 3},
        ],
    ):
        other_assets = json.loads(json.dumps(assets))
        other_assets["opening"]["scene"]["routes"] = routes
        other = program.start(other_assets)
        assert len(other.offers("sender")) == 1
        assert isinstance(other.submit("sender", offer.entry, dict(offer.payload)), K0NotAdmitted)
        assert other._runtime.occurrence_history() == ()
        assert other._runtime.read_owner(scene_key).view.parcel.status == "home"

    for field, value in (("depart_ref", 1), ("status", "foreign")):
        malformed = json.loads(json.dumps(assets))
        malformed["opening"]["scene"]["parcel"][field] = value
        with pytest.raises(C0BindingError):
            program.start(malformed)

    stricter = json.loads(json.dumps(source))
    route = stricter["lawdefs"][0]["body"]["value"]["bindings"][0]
    route["where"] = {"all": [route["where"], {"le": [{"ref": "candidate.travel"}, {"const": 1}]}]}
    changed = _compile(lib, ports, stricter).start(assets)
    assert len(changed.offers("sender")) == 1
    assert isinstance(changed.submit("sender", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert changed._runtime.occurrence_history() == ()


def test_actor_only_effect_reads_scene_without_writing_it():
    program, runtime = _read_session()
    spec = program.build_spec()
    assert spec.read_owners == tuple(sorted((SCENE_KEY, ACTOR_KEY)))
    assert spec.contribution_owners == (ACTOR_KEY,)
    before_scene, before_actor = _states(runtime)
    rule_result = spec.rule.evaluate(
        _K0InMemoryRuleInput(
            K0OccurrenceRef(1),
            program.source_key,
            C0ValueActionEvidence(before_scene, before_actor, Attempt("keeper", "keeper", "P")),
            C0ValueActionParticipants("keeper"),
            (),
            None,
        )
    )
    assert tuple(item.owner for item in rule_result.result.contributions) == (ACTOR_KEY,)
    result = runtime.settle(
        _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "keeper", "P"))
    )
    assert isinstance(result, K0Published)
    scene, actor = _states(runtime)
    assert scene == before_scene
    assert actor.receipts == (Receipt("P", result.occurrences[0].occurrence),)
    assert result.occurrences[0].semantic_envelope.content == "read-started"


@pytest.mark.parametrize(
    "heard,status,recipient,target",
    (
        (False, "arrived", "keeper", "keeper"),
        (True, "home", "keeper", "keeper"),
        (True, "arrived", "other", "keeper"),
        (True, "arrived", "keeper", "other"),
    ),
)
def test_actor_only_read_rejects_wrong_local_basis_without_write(heard, status, recipient, target):
    opening = Scene(3, 9, (Parcel("P", status, recipient),), ())
    program, runtime = _read_session(opening, heard=heard)
    before = _states(runtime)
    assert isinstance(
        runtime.settle(
            _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", target, "P"))
        ),
        K0NotAdmitted,
    )
    assert _states(runtime) == before


def test_actor_only_read_rejects_repeat_and_invalid_write_declarations():
    program, runtime = _read_session()
    attempt = _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "keeper", "P"))
    assert isinstance(runtime.settle(attempt), K0Published)
    before = _states(runtime)
    assert isinstance(runtime.settle(attempt), K0NotAdmitted)
    assert _states(runtime) == before

    source = READ_SOURCE.read_text(encoding="utf-8")
    with pytest.raises(C0LawError, match="at least one owner"):
        compile_composable_action(
            source, replace(_read_ports(), state_effects={"scene": {}, "actor": {}})
        )
    with pytest.raises(C0LawError, match="typed owner write"):
        compile_composable_action(
            source,
            replace(
                _read_ports(),
                state_effects={"scene": {"parcels": "receipts"}, "actor": {}},
            ),
        )


def test_author_effect_edit_changes_same_k0_world_without_host_branch():
    source = _source()
    source["value"]["outputs"]["parcels"]["replace_unique"]["new"]["copy"]["changes"]["status"] = {
        "const": "queued"
    }
    program, runtime = _session(source)
    result = runtime.settle(
        _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
    )
    assert isinstance(result, K0Published)
    scene, actor = _states(runtime)
    assert scene.parcels[0].status == "queued"
    assert actor.receipts[0].action == scene.parcels[0].dispatch


@pytest.mark.parametrize(
    "actor,target,heard",
    (
        ("other", "chapel", True),
        ("keeper", "unknown", True),
        ("keeper", "chapel", False),
    ),
)
def test_non_admission_has_no_owner_write(actor, target, heard):
    program, runtime = _session(heard=heard)
    before = _states(runtime)
    result = runtime.settle(
        _K0InMemoryActionAttempt(program.source_key, Attempt(actor, target, "P"))
    )
    assert isinstance(result, K0NotAdmitted)
    assert _states(runtime) == before


def test_second_attempt_and_bad_keyed_state_do_not_publish():
    program, runtime = _session()
    attempt = _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
    assert isinstance(runtime.settle(attempt), K0Published)
    before = _states(runtime)
    assert isinstance(runtime.settle(attempt), K0NotAdmitted)
    assert _states(runtime) == before
    duplicate = Scene(
        3,
        9,
        (Parcel("P", "home"), Parcel("P", "home")),
        (Route("chapel", 2, "inspect"),),
    )
    program, runtime = _session(opening_scene=duplicate)
    before = _states(runtime)
    with pytest.raises(K0ProfileError, match="preflight failed") as error:
        runtime.settle(
            _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
        )
    assert isinstance(error.value.__cause__, C0ValueStateError)
    assert _states(runtime) == before


def test_bad_authored_effect_fails_after_admission_without_partial_publication():
    source = _source()
    source["value"]["outputs"]["parcels"]["replace_unique"]["new"]["copy"]["changes"]["status"] = {
        "const": "invalid-owner-mode"
    }
    program, runtime = _session(source)
    before = _states(runtime)
    with pytest.raises(K0SettlementDefect):
        runtime.settle(
            _K0InMemoryActionAttempt(program.source_key, Attempt("keeper", "chapel", "P"))
        )
    assert _states(runtime) == before


def test_wrong_bindings_and_foreign_rule_basis_reject():
    ports = _ports()
    bad = replace(
        ports, state_effects={"scene": {"parcels": "receipts"}, "actor": {"receipts": "parcels"}}
    )
    with pytest.raises(C0LawError, match="typed owner write"):
        compile_composable_action(json.dumps(_source()), bad)
    with pytest.raises(C0LawError, match="misses a nominal owner"):
        compile_composable_action(
            json.dumps(_source()), replace(ports, contribution_type=WrongContribution)
        )
    source = _source()
    source["source_key"] = "c0.foreign.source"
    with pytest.raises(C0LawError, match="trusted binding"):
        compile_composable_action(json.dumps(source), ports)
    source = _source()
    source["event_type"] = "c0.foreign.event"
    with pytest.raises(C0LawError, match="trusted binding"):
        compile_composable_action(json.dumps(source), ports)
    program, runtime = _session()
    scene, actor = _states(runtime)
    bad_input = _K0InMemoryRuleInput(
        K0OccurrenceRef(1),
        K0SourceSpecKey("c0.other"),
        C0ValueActionEvidence(scene, actor, Attempt("keeper", "chapel", "P")),
        C0ValueActionParticipants("keeper"),
        (),
        None,
    )
    with pytest.raises(K0ProfileError, match="foreign rule basis"):
        program.build_spec().rule.evaluate(bad_input)


def test_selected_envelope_expression_cannot_impersonate_another_action():
    ports = replace(
        _ports(),
        sealed_envelope_fields={"content": {"ref": "route.content"}},
    )
    assert compile_composable_action(json.dumps(_source()), ports).build_spec().key == (
        ports.source_key
    )
    source = _source()
    source["value"]["outputs"]["content"] = {"const": "unrelated"}
    with pytest.raises(C0LawError, match="selected identity contract"):
        compile_composable_action(json.dumps(source), ports)
    with pytest.raises(C0LawError, match="lack declared ports"):
        compile_composable_action(
            json.dumps(_source()),
            replace(ports, sealed_envelope_fields={"missing": {"const": "unrelated"}}),
        )
