"""Selected Actor refs compile, bind and settle without a static shadow owner."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _record, _value
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_actor_domain_observation_v1 import observation_documents
from test_actor_formation_v1 import submit_first
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.world_binding_v1 import bind_world


def documents():
    lib, ports, source, assets = observation_documents()
    # The observation Event, not formation or the host, records this finite local set.
    actor = next(record for record in lib["records"] if record["name"] == "Actor")
    actor["fields"].append({"name": "known", "type": {"tuple": {"item": "Sighting", "max": 4}}})
    for name in ("actor_0", "actor_1"):
        assets["opening"][name]["known"] = []
    lib["owners"][1]["seat_read"].append("known")
    source["seats"][0]["read"].append("actor_0.known")
    observe = next(row for row in ports["events"] if row["symbol"] == "observe")
    observe["value"]["write_paths"].append("actor.known")
    observe["value"]["outputs"]["known"] = "actor.known"
    outputs = source["lawdefs"][-1]["body"]["law"]["outputs"]
    known = deepcopy(outputs["sighting"])
    known["record"]["fields"]["subject"] = {"ref": "observed.ref"}
    outputs["known"] = {
        "collect_matching": {
            "collection": {"ref": "sprites.members"},
            "as": "observed",
            "where": "observed.count == 0",
            "value": known,
        }
    }
    lib["records"].append(
        _record("FundAttempt", {"actor": {"str": [1, 64]}, "recipient": "actor_ref"})
    )
    ports["actions"].append(
        {
            "symbol": "fund",
            "actor": "actor_0",
            "payload": "FundAttempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "participants": [
                {
                    "name": "recipient",
                    "selector": "actor",
                    "state": "Sprite",
                    "payload_field": "recipient",
                    "write": True,
                }
            ],
            "effects": {
                "scene": {},
                "actor": {"count": "remaining"},
                "recipient": {"count": "count"},
            },
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": _value(
                ["actor.count", "recipient.count", "recipient.awake"],
                ["actor.count", "recipient.count"],
            ),
        }
    )
    source["lawdefs"].append(
        {
            "name": "fund",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "actor.count > 0 and recipient.awake and recipient.count < 100",
                    "outputs": {
                        "remaining": {"sub": [{"ref": "actor.count"}, 1]},
                        "count": {"add": [{"ref": "recipient.count"}, 1]},
                        "action": {"ref": "occurrence"},
                    },
                }
            },
        }
    )
    source["actions"].append(
        {
            "name": "fund",
            "template": "fund",
            "actor": "actor_0",
            "source_key": "c0.test.sprite.fund",
            "event_type": "c0.test.sprite.fund.action",
            "participants": {"recipient": {"kind": "sprite"}},
            "law": {"ref": "fund", "args": {}},
        }
    )
    source["seats"][0]["entries"].append("fund")
    source["game_form"]["seats"][0]["costs"]["fund"] = 1
    source["actor_templates"][0]["first_debt"] = 20
    source["seats"][0]["offers"].append(
        {
            "entry": "fund",
            "for_each_participants": {
                "recipient": {
                    "collection": {"ref": "actor.known"},
                    "as": "candidate",
                    "identity_field": "subject",
                }
            },
            "label": [{"const": "Fund observed sprite"}],
            "visible_when": True,
            "when": True,
            "payload": {"recipient": {"ref": "candidate.subject"}},
        }
    )
    return lib, ports, source, assets


def _fund(session, ref):
    action = dict(session.program.actions)["fund"]
    return session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type("person_0", ref))
    )


@pytest.mark.parametrize("rebind", [False, True])
def test_actor_candidate_carries_acquired_occurrence_metadata(rebind):
    lib, ports, source, assets = documents()
    lib["records"][-1]["fields"].append({"name": "basis", "type": "occurrence_ref"})
    offer = source["seats"][0]["offers"][-1]
    offer["payload"]["basis"] = {"ref": "candidate.observation"}
    program = _compile(lib, ports, source)
    if rebind:
        program = bind_program(program.program_ir, _layout(program))
    session = program.start(assets)
    submit_first(session)
    session.continue_form("seat_0")
    (offer,) = [row for row in session.offers("seat_0") if row.entry == "fund"]
    known = dict(session.author_snapshot().owners)["actor_0"].known[0]
    assert dict(offer.payload)["basis"] == known.observation
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)


def test_actor_candidate_metadata_does_not_grant_target_owner_reads():
    lib, ports, source, _ = documents()
    source["seats"][0]["offers"][-1]["when"] = {"eq": [{"ref": "recipient.count"}, 0]}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_real_formation_observation_offer_and_atomic_selected_owner_update():
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    assert not any(offer.entry == "fund" for offer in session.offers("seat_0"))
    submit_first(session)
    (target,) = session.author_actor_instances()
    session.continue_form("seat_0")
    (offer,) = [offer for offer in session.offers("seat_0") if offer.entry == "fund"]
    assert dict(offer.payload) == {"recipient": target.actor}
    result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert session._runtime.read_actor(target.actor).view.count == 1
    assert dict(session.author_snapshot().owners)["actor_0"].count == 0
    selected = result.occurrences[0].selected_owners
    assert [(item.name, item.selector) for item in selected] == [("recipient", target.actor)]
    assert selected[0].owner == target.owner
    before = session.author_snapshot()
    assert isinstance(_fund(session, target.actor), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_real_actor_without_local_observation_never_becomes_an_offer():
    lib, ports, source, assets = documents()
    observe = next(law for law in source["lawdefs"] if law["name"] == "observe")
    observe["body"]["law"]["guard"] = {"all": ["visible is not None", False]}
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    assert len(session.author_actor_instances()) == 1
    assert not any(offer.entry == "fund" for offer in session.offers("seat_0"))


def test_foreign_ref_is_rejected_with_no_resource_or_history_write():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session, other = program.start(assets), program.start(assets)
    submit_first(session)
    submit_first(other)
    session.continue_form("seat_0")
    before = session.author_snapshot()
    assert isinstance(_fund(session, other.author_actor_instances()[0].actor), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_independent_bind_uses_fresh_nominal_carriers_and_selected_actor_factory():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    rebound = bind_program(program.program_ir, _layout(program))
    session = rebound.start(assets)
    submit_first(session)
    target = session.author_actor_instances()[0]
    session.continue_form("seat_0")
    assert isinstance(_fund(session, target.actor), K0Published)
    assert session._runtime.read_actor(target.actor).view.count == 1


@pytest.mark.parametrize("fault", ["kind", "carrier", "payload", "permission", "local_identity"])
def test_compile_rejects_foreign_or_incomplete_actor_contract(fault):
    lib, ports, source, _ = documents()
    if fault == "kind":
        source["actions"][-1]["participants"]["recipient"]["kind"] = "missing"
    elif fault == "carrier":
        ports["actions"][-1]["participants"][0]["state"] = "Actor"
    elif fault == "payload":
        lib["records"][-1]["fields"][-1]["type"] = "individual_ref"
    elif fault == "permission":
        ports["actions"][-1]["participants"][0]["write"] = False
    else:
        source["seats"][0]["offers"][-1]["for_each_participants"]["recipient"]["identity_field"] = (
            "observation"
        )
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_independent_bind_rejects_a_forged_actor_family_in_world_ir():
    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    transitions = []
    for transition in program.world_ir.transitions:
        if transition.symbol == "fund":
            selection = replace(
                transition.action.selected[0], primary_kind="missing", kinds=("missing",)
            )
            transition = replace(
                transition, action=replace(transition.action, selected=(selection,))
            )
        transitions.append(transition)
    world = replace(program.world_ir, transitions=tuple(transitions))
    with pytest.raises(C0LawError, match="Actor selection"):
        bind_world(world, replace(program.world_layout, world=world))


def object_documents():
    lib, ports, source, assets = documents()
    lib["records"].append(_record("Battery", {"charge": {"int": [0, 10]}}))
    lib["object_kinds"] = [
        {
            "symbol": "battery",
            "sort": "TEST.BATTERY@1",
            "state": "Battery",
            "version": "1",
            "max_instances": 2,
        }
    ]
    source["object_kinds"] = [{"kind": "battery", "sort": "TEST.BATTERY@1"}]
    assets["opening_objects"] = [
        {"kind": "battery", "state": {"charge": 2}},
        {"kind": "battery", "state": {"charge": 3}},
    ]
    payload = next(row for row in lib["records"] if row["name"] == "FundAttempt")
    payload["fields"].append({"name": "battery", "type": "individual_ref"})
    action = ports["actions"][-1]
    action["participants"].insert(
        0,
        {
            "name": "battery",
            "selector": "individual",
            "state": "Battery",
            "payload_field": "battery",
            "write": True,
        },
    )
    action["effects"]["actor"] = {}
    action["effects"]["battery"] = {"charge": "remaining"}
    action["value"]["read"] = ["battery.charge", "recipient.count", "recipient.awake"]
    action["value"]["write_paths"] = ["battery.charge", "recipient.count"]
    law = source["lawdefs"][-1]["body"]["value"]
    law["guard"] = "battery.charge > 0 and recipient.awake and recipient.count < 100"
    law["outputs"]["remaining"] = {"sub": [{"ref": "battery.charge"}, 1]}
    source["actions"][-1]["participants"]["battery"] = {"kind": "battery"}
    offer = source["seats"][0]["offers"][-1]
    offer["for_each_participants"]["battery"] = {"kind": "battery", "read": ["battery.charge"]}
    offer["payload"]["battery"] = {"ref": "battery_ref"}
    return lib, ports, source, assets


def test_object_resource_and_selected_actor_settle_atomically_not_other_instances():
    lib, ports, source, assets = object_documents()
    assets["opening_actors"] = [
        {"kind": "sprite", "state": {"count": 5, "awake": True}, "debt": 20}
    ]
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    session.continue_form("seat_0")
    offers = [offer for offer in session.offers("seat_0") if offer.entry == "fund"]
    assert len(offers) == 2
    target = next(item for item in session.author_actor_instances() if item.formed_by is not None)
    before_count = dict(session.author_snapshot().owners)["actor_0"].count
    result = session.submit("seat_0", offers[0].entry, dict(offers[0].payload))
    assert isinstance(result, K0Published)
    assert [item.current_state.charge for item in session.author_object_instances()] == [1, 3]
    assert session._runtime.read_actor(target.actor).view.count == 1
    assert [item.current_state.count for item in session.author_actor_instances()] == [5, 1]
    assert dict(session.author_snapshot().owners)["actor_0"].count == before_count
    assert [item.name for item in result.occurrences[0].selected_owners] == ["battery", "recipient"]


def test_current_selected_actor_guard_rejects_old_menu_without_spending_object():
    lib, ports, source, assets = object_documents()
    # The first permitted interaction makes the recipient unavailable for the next one.
    action = ports["actions"][-1]
    action["effects"]["recipient"]["awake"] = "awake"
    action["value"]["write_paths"].append("recipient.awake")
    source["lawdefs"][-1]["body"]["value"]["outputs"]["awake"] = False
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    session.continue_form("seat_0")
    (first, stale) = [offer for offer in session.offers("seat_0") if offer.entry == "fund"]
    assert isinstance(session.submit("seat_0", first.entry, dict(first.payload)), K0Published)
    session.continue_form("seat_0")
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", stale.entry, dict(stale.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_selected_actor_availability_recomputes_current_state_without_leaking_it():
    lib, ports, source, assets = object_documents()
    action = ports["actions"][-1]
    action["effects"]["recipient"]["awake"] = "awake"
    action["value"]["write_paths"].append("recipient.awake")
    source["lawdefs"][-1]["body"]["value"]["outputs"]["awake"] = False
    ports["candidate_inputs"] = [
        {
            "symbol": "recipient_awake",
            "action": "fund",
            "read": ["recipient.awake"],
            "fields": {},
        }
    ]
    source["seats"][0]["offers"][-1]["availability"] = {
        "ref": "recipient_awake",
        "when": "recipient.awake",
    }
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    session.continue_form("seat_0")
    offers = [offer for offer in session.offers("seat_0") if offer.entry == "fund"]
    before = session.author_snapshot()
    assert session.offers("seat_0") == session.offers("seat_0")
    assert session.author_snapshot() == before
    assert isinstance(session.submit("seat_0", "fund", dict(offers[0].payload)), K0Published)
    assert not any(offer.entry == "fund" for offer in session.offers("seat_0"))
    assert "recipient.awake" not in dict(session.read("seat_0").fields)


@pytest.mark.parametrize("slot", ["when", "label", "payload", "fixed"])
def test_actor_private_state_or_unresolved_selector_cannot_enter_public_offers(slot):
    lib, ports, source, _ = documents()
    offer = source["seats"][0]["offers"][-1]
    if slot == "when":
        offer["when"] = "recipient.awake"
    elif slot == "label":
        offer["label"] = [{"if": {"when": "recipient.awake", "then": "yes", "else": "no"}}]
    elif slot == "payload":
        offer["payload"]["recipient"] = {"ref": "actor.sighting.subject"}
    else:
        offer["for_each_participants"]["recipient"] = {"fixed_actor": "sprite"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
