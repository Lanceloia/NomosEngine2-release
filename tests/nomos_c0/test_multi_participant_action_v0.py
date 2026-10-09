"""Authored C0 Action selects one Object and one closed-domain Actor owner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_binding_v1 import bind_program

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _world():
    return tuple(
        read_author_document(ROOT / f"multi_participant_v0.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )


def _compile(lib, ports, source):
    return compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def _owners(session):
    return dict(session.author_snapshot().owners)


def test_one_law_selects_two_distinct_actor_owners_and_object_owners() -> None:
    lib, ports, source, assets = _world()
    assert [item["name"] for item in lib["lawdefs"]] == ["action.enable"]
    assert [item["name"] for item in source["actions"]] == ["enable"]
    session = _compile(lib, ports, source).start(assets)
    assert [offer.label for offer in session.offers("maker")] == [
        "Use one on a",
        "Use one on b",
        "Use two on a",
        "Use two on b",
    ]

    first = next(offer for offer in session.offers("maker") if offer.label == "Use one on a")
    assert first.label_fragments == (
        ("Use ", False),
        ("one", True),
        (" on ", False),
        ("a", True),
    )
    published = session.submit("maker", first.entry, dict(first.payload))
    assert isinstance(published, K0Published)
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False
    assert [item.current_state.ready for item in session.author_object_instances()] == [
        False,
        True,
    ]
    selected = published.occurrences[0].selected_owners
    assert [(item.name, item.selector) for item in selected] == [
        ("tool", first.payload[0][1]),
        ("victim", "a"),
    ]
    assert selected[0].owner != selected[1].owner

    second = next(offer for offer in session.offers("maker") if offer.label == "Use two on b")
    assert isinstance(session.submit("maker", second.entry, dict(second.payload)), K0Published)
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is True
    assert [item.current_state.ready for item in session.author_object_instances()] == [
        False,
        False,
    ]
    assert {item.source for item in session._runtime.occurrence_history()} == {
        dict(session.program.actions)["enable"].source_key
    }


def test_stale_guard_rejects_without_partial_owner_write() -> None:
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "a"))
        ),
        K0Published,
    )
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "b"))
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before


@pytest.mark.parametrize("victim", ["maker", "absent"])
def test_foreign_closed_domain_target_is_rejected(victim: str) -> None:
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, victim))
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before


def test_foreign_session_individual_is_rejected() -> None:
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    foreign = program.start(assets).author_object_instances()[0].individual
    action = dict(program.actions)["enable"]
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", foreign, "a"))
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before


def test_actor_local_candidates_do_not_expose_other_closed_members() -> None:
    lib, ports, source, assets = _world()
    assets["opening"]["maker"]["known"] = [{"name": "a"}]
    session = _compile(lib, ports, source).start(assets)
    assert [item.label for item in session.offers("maker")] == [
        "Use one on a",
        "Use two on a",
    ]
    assert "b.enabled" not in dict(session.read("maker").fields)


def test_source_closed_domain_bounds_offers_and_k0_admission() -> None:
    lib, ports, source, assets = _world()
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    session = _compile(lib, ports, source).start(assets)
    assert [item.label for item in session.offers("maker")] == [
        "Use one on a",
        "Use two on a",
    ]
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "b"))
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before


def test_opening_rejects_closed_owner_identity_mismatch() -> None:
    lib, ports, source, assets = _world()
    assets["opening"]["a"]["name"] = "other"
    with pytest.raises(C0BindingError, match="closed participant opening identity"):
        _compile(lib, ports, source).start(assets)


def test_closed_participant_identity_cannot_be_a_law_effect() -> None:
    lib, ports, source, _ = _world()
    action = ports["actions"][0]
    action["effects"]["victim"]["name"] = "new_name"
    action["value"]["write_paths"].append("victim.name")
    lib["lawdefs"][0]["body"]["value"]["outputs"]["new_name"] = {"const": "b"}
    with pytest.raises(C0LawError, match="owner write port"):
        _compile(lib, ports, source)


def test_unhashable_offer_read_is_a_finite_author_error() -> None:
    lib, ports, source, _ = _world()
    source["seats"][0]["offers"][0]["for_each_participants"]["tool"]["read"] = [{}]
    with pytest.raises(C0LawError, match="Object domain or read grant"):
        _compile(lib, ports, source)


def test_ranged_offer_can_bind_an_additional_singleton_participant() -> None:
    lib, ports, source, assets = _world()
    lib["records"][4]["fields"].append({"name": "witness", "type": {"str": [1, 32]}})
    action = ports["actions"][0]
    action["participants"].append(
        {
            "name": "witness",
            "selector": "closed_domain",
            "state": "Person",
            "payload_field": "witness",
            "write": False,
        }
    )
    action["participants"].sort(key=lambda item: item["name"])
    action["effects"]["witness"] = {}
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    source["actions"][0]["participants"]["witness"] = {"actors": ["b"]}
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["witness"] = {"fixed_actor": "b"}
    offer["payload"]["witness"] = {"const": "b"}

    session = _compile(lib, ports, source).start(assets)
    assert [item.label for item in session.offers("maker")] == [
        "Use one on a",
        "Use two on a",
    ]
    selected = session.offers("maker")[0]
    published = session.submit("maker", selected.entry, dict(selected.payload))
    assert isinstance(published, K0Published)
    assert [(item.name, item.selector) for item in published.occurrences[0].selected_owners] == [
        ("tool", dict(selected.payload)["tool"]),
        ("victim", "a"),
        ("witness", "b"),
    ]
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False

    offer["for_each_participants"]["witness"] = {"fixed_actor": "a"}
    with pytest.raises(C0LawError, match="selected singleton"):
        _compile(lib, ports, source)


def _fixed_world():
    lib, ports, source, assets = _world()
    lib["object_kinds"][0]["max_instances"] = 1
    assets["opening_objects"] = assets["opening_objects"][:1]
    lib["object_kinds"].append(
        {
            "symbol": "token",
            "sort": "EXAMPLE.PARTICIPANT_TOKEN@1",
            "state": "Tool",
            "version": "token-v1",
            "max_instances": 1,
        }
    )
    assets["opening_objects"].append(
        {"kind": "token", "state": {"label": "token", "ready": True, "visible": True}}
    )
    lib["records"][4]["fields"].append({"name": "token", "type": "individual_ref"})
    lib["records"][4]["fields"].append({"name": "witness", "type": {"str": [1, 32]}})
    ports["actions"][0]["participants"].append(
        {
            "name": "token",
            "selector": "individual",
            "state": "Tool",
            "payload_field": "token",
            "write": False,
        }
    )
    ports["actions"][0]["participants"].append(
        {
            "name": "witness",
            "selector": "closed_domain",
            "state": "Person",
            "payload_field": "witness",
            "write": False,
        }
    )
    ports["actions"][0]["participants"].sort(key=lambda item: item["name"])
    ports["actions"][0]["effects"]["token"] = {}
    ports["actions"][0]["effects"]["witness"] = {}
    ports["actions"][0]["value"]["read"].append("token.ready")
    ports["actions"][0]["value"]["read"].append("witness.enabled")
    lib["lawdefs"][0]["body"]["value"]["guard"]["all"].append({"ref": "token.ready"})
    lib["lawdefs"][0]["body"]["value"]["guard"]["all"].append({"not": {"ref": "witness.enabled"}})
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    source["actions"][0]["participants"]["token"] = {"kind": "token"}
    source["actions"][0]["participants"]["witness"] = {"actors": ["b"]}
    source["object_kinds"].append({"kind": "token", "sort": "EXAMPLE.PARTICIPANT_TOKEN@1"})
    source["seats"][0]["offers"] = [
        {
            "entry": "enable",
            "fixed_participants": True,
            "label": "Check the device",
            "when": {"not": {"ref": "actor.enabled"}},
            "payload": {},
        }
    ]
    return lib, ports, source, assets


def test_fixed_participants_are_hidden_until_trusted_submission() -> None:
    lib, ports, source, assets = _fixed_world()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")
    assert [(item.entry, item.label, item.payload) for item in offer] == [
        ("enable", "Check the device", ()),
    ]
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", {"victim": "b"})
    assert session.author_snapshot() == before
    published = session.submit("maker", "enable", {})
    assert isinstance(published, K0Published)
    assert [(item.name, item.selector) for item in published.occurrences[0].selected_owners][
        1:
    ] == [
        (
            "tool",
            next(
                item.individual
                for item in session.author_object_instances()
                if item.individual.family == "tool"
            ),
        ),
        ("victim", "a"),
        ("witness", "b"),
    ]
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False
    before = session.author_snapshot()
    assert isinstance(session.submit("maker", "enable", {}), K0NotAdmitted)
    assert session.author_snapshot() == before


def _fixed_actor_world():
    lib, ports, source, assets = _world()
    lib["records"][4]["fields"] = [
        field for field in lib["records"][4]["fields"] if field["name"] != "tool"
    ]
    value = lib["lawdefs"][0]["body"]["value"]
    value["guard"] = {"not": {"ref": "victim.enabled"}}
    del value["outputs"]["ready"]
    action = ports["actions"][0]
    action["participants"] = [p for p in action["participants"] if p["name"] == "victim"]
    del action["effects"]["tool"]
    action["value"]["read"] = ["victim.enabled"]
    action["value"]["write_paths"] = ["victim.enabled"]
    source["actions"][0]["participants"] = {"victim": {"actors": ["a"]}}
    source["seats"][0]["offers"] = [
        {
            "entry": "enable",
            "fixed_participants": True,
            "label": "Ask locally",
            "when": {"const": True},
            "payload": {},
        }
    ]
    return lib, ports, source, assets


def test_actor_only_fixed_offer_hides_selector_and_rechecks_current_state():
    lib, ports, source, assets = _fixed_actor_world()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    assert (offer.label, offer.payload) == ("Ask locally", ())
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", {"victim": "b"})
    assert session.author_snapshot() == before
    published = session.submit("maker", "enable", {})
    assert isinstance(published, K0Published)
    assert [(p.name, p.selector) for p in published.occurrences[0].selected_owners] == [
        ("victim", "a")
    ]
    assert _owners(session)["a"].enabled and not _owners(session)["b"].enabled
    before = session.author_snapshot()
    assert isinstance(session.submit("maker", "enable", {}), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_actor_only_fixed_offer_rejects_non_singleton_actor_domain():
    lib, ports, source, _ = _fixed_actor_world()
    source["actions"][0]["participants"]["victim"]["actors"] = ["a", "b"]
    with pytest.raises(C0LawError, match="fixed participant"):
        _compile(lib, ports, source)


def test_bind_rechecks_fixed_actor_singleton_without_frontend():
    lib, ports, source, _ = _fixed_actor_world()
    program = _compile(lib, ports, source)
    ir = program.program_ir
    transition = ir.world.transitions[0]
    participant = transition.action.selected[0]
    widened = replace(participant, members=(*participant.members, ("b", "b")))
    transition = replace(transition, action=replace(transition.action, selected=(widened,)))
    world = replace(ir.world, transitions=(transition,))
    changed = replace(
        ir,
        world=world,
        control=replace(ir.control, world=world),
        visibility=replace(ir.visibility, world=world),
    )
    with pytest.raises(C0LawError, match="fixed participants"):
        bind_program(changed, replace(program.world_layout, world=world))


def test_fixed_participant_offer_needs_current_singleton_object() -> None:
    lib, ports, source, assets = _fixed_world()
    assets["opening_objects"] = []
    session = _compile(lib, ports, source).start(assets)
    assert session.offers("maker") == ()
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", {})
    assert session.author_snapshot() == before


def _fixed_scalar_world():
    lib, ports, source, assets = _fixed_world()
    lib["records"][4]["fields"].append({"name": "allowed", "type": "bool"})
    ports["actions"][0]["value"]["read"].append("payload.allowed")
    lib["lawdefs"][0]["body"]["value"]["guard"]["all"].append({"ref": "payload.allowed"})
    source["seats"][0]["offers"][0]["payload"] = {"allowed": {"not": {"ref": "actor.enabled"}}}
    return lib, ports, source, assets


def test_fixed_participants_keep_local_scalar_projection_through_ir_and_submission():
    lib, ports, source, assets = _fixed_scalar_world()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    assert dict(offer.payload) == {"allowed": True}
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", offer.entry, {"allowed": False})
    assert session.author_snapshot() == before
    published = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(published, K0Published)
    assert _owners(session)["a"].enabled
    assert not _owners(session)["b"].enabled
    assert len(published.occurrences[0].selected_owners) == 4


@pytest.mark.parametrize("fault", ["missing", "extra", "wrong_type", "private_read", "selector"])
def test_fixed_scalar_projection_is_exact_typed_and_seat_local(fault):
    lib, ports, source, _ = _fixed_scalar_world()
    payload = source["seats"][0]["offers"][0]["payload"]
    if fault == "missing":
        payload.clear()
    elif fault == "extra":
        payload["extra"] = {"const": True}
    elif fault == "wrong_type":
        payload["allowed"] = {"const": 1}
    elif fault == "private_read":
        payload["allowed"] = {"ref": "witness.enabled"}
    else:
        payload["victim"] = {"const": "b"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    [
        "multiple_objects",
        "duplicate_family",
        "multiple_actors",
        "same_actor",
        "public_payload",
        "private_when",
    ],
)
def test_fixed_participant_offer_rejects_unbounded_or_public_selectors(fault: str) -> None:
    lib, ports, source, assets = _fixed_world()
    if fault == "multiple_objects":
        lib["object_kinds"][0]["max_instances"] = 2
    elif fault == "duplicate_family":
        source["actions"][0]["participants"]["token"] = {"kind": "tool"}
    elif fault == "multiple_actors":
        source["actions"][0]["participants"]["witness"]["actors"] = ["a", "b"]
    elif fault == "same_actor":
        source["actions"][0]["participants"]["witness"]["actors"] = ["a"]
    elif fault == "private_when":
        source["seats"][0]["offers"][0]["when"] = {"ref": "witness.enabled"}
    else:
        source["seats"][0]["offers"][0]["payload"] = {"victim": {"const": "a"}}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    ("missing_victim", "wrong_kind", "wrong_owner_state", "unbound_effect"),
)
def test_compile_rejects_incomplete_or_foreign_binding(fault: str) -> None:
    lib, ports, source, _ = _world()
    if fault == "missing_victim":
        del source["actions"][0]["participants"]["victim"]
    elif fault == "wrong_kind":
        source["actions"][0]["participants"]["tool"]["kind"] = "unknown"
    elif fault == "wrong_owner_state":
        source["actions"][0]["participants"]["victim"]["actors"] = ["scene"]
    else:
        ports["actions"][0]["participants"][1]["write"] = False
    with pytest.raises((C0BindingError, C0LawError)):
        _compile(lib, ports, source)
