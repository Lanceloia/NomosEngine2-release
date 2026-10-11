"""Selected real escort Laws and a small K0 graph, never a full M1 replay."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.appraisal_definition_v1 import C0AppraisalDefinitions
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.direct_actor_event_v1 import C0EventTrigger
from nomos_c0.finite_appraisal_v1 import check_finite_appraisal_shape
from nomos_c0.owner_graph_v1 import compile_owner_graph

WORLD = Path(__file__).resolve().parents[2] / "src/nomos_examples/everflame"
RESIDENTS = (
    "ritual_resident", "huddled_one", "huddled_two", "wall_resident",
    "prison_resident_one", "prison_resident_two",
)
NPCS = (*RESIDENTS, "emma")
PUBLIC = (
    "adventurer.conversations.latest_escort_reply",
    "adventurer.conversations.heard_escort_replies",
)
HERE = "ballroom_chandelier_reach"


def _document(path):
    return read_author_document(WORLD / path).to_data()


def _row(rows, key, value):
    return next(row for row in rows if row.get(key) == value)


def _seat(seats, owner):
    direct = next((row for row in seats if row.get("name") == owner), None)
    if direct is not None:
        return deepcopy(direct)
    family = next(row for row in seats if owner in row.get("names", {}))
    result = deepcopy(family)
    result["read"] = [path.replace("actor.", owner + ".", 1) for path in result["read"]]
    for offer in result["offers"]:
        if "entry_family" in offer:
            offer["entry"] = offer.pop("entry_family") + "_" + owner
    return result


def _profile(lib, policies, owner, *, hidden=False):
    name = ("remain_hidden_" if hidden else "toward_exit_") + owner
    if owner == "emma":
        name = "local_emma"
    direct = next((row for row in policies if row.get("name") == name), None)
    if direct is None:
        family = next(row for row in policies if row.get("profiles", {}).get(owner) == name)
        direct = {
            "name": name, "seat": owner, "definition": family["definition"],
            "entries": {slot: entry + "_" + owner for slot, entry in family["entries"].items()},
        }
    else:
        direct = deepcopy(direct)
    if "definition" in direct:
        direct, _ = C0AppraisalDefinitions(lib["appraisal_definitions"]).bind(direct)
    reply, wait = "escort_reply_" + owner, "wait_" + owner
    if owner == "emma":
        wait = "queen_wait_emma"
    # Select the real reply and fallback rules; other world capabilities are not compiled.
    return {
        "name": name, "seat": owner, "fallback_entry": wait,
        "tie_order": [entry for entry in direct["tie_order"] if entry in (reply, wait)],
        "rules": [row for row in direct["rules"] if row["entry"] in (reply, wait)],
    }


@pytest.fixture(scope="module")
def authored():
    lib = _document("model.lib.yaml")
    lib["owners"] = [row for row in lib["owners"]
                     if row["symbol"] in ("scene", "adventurer", *NPCS)]
    nominal = check_nominal_lib(lib)
    raw_ports = _document("capabilities.ports.yaml")
    ports = {key: raw_ports[key] for key in ("schema", "scene_owner", "offer_provider")}
    ports.update(
        actions=[row for row in raw_ports["actions"] if row["symbol"] in {
            "offer_escort", "escort_reply", "queen_escort_reply", "wait", "queen_wait",
        }],
        events=[row for row in raw_ports["events"] if row["symbol"] in {
            "escort_heard", "queen_escort_heard", "escort_reply_heard",
        }],
        candidate_inputs=[row for row in raw_ports["candidate_inputs"]
                          if row["symbol"] in {
                              "escort_reply_audience", "queen_escort_reply_audience",
                          }],
        due_events=[],
    )
    bindings = _document("source/bindings/capabilities.yaml")
    rules = []
    for path in ("escort_and_reward", "escort_reply", "shared_actions"):
        rules.extend(_document("source/rules/" + path + ".yaml")["lawdefs"])
    rules = [row for row in rules if row["name"] in {
        "action.offer_escort", "action.escort_reply", "action.queen_escort_reply",
        "event.escort_heard", "event.queen_escort_heard", "event.escort_reply_heard",
        "action.wait", "action.queen_wait",
    }]
    original_seats = _document("source/control/seats.yaml")["seats"]
    policies = _document("source/control/policies.yaml")["appraisal_profiles"]
    player = _seat(original_seats, "adventurer")
    player["entries"] = ["offer_escort_adventurer", "wait_adventurer"]
    player["offers"] = [row for row in player["offers"]
                        if row.get("entry") == "offer_escort_adventurer"]
    player["offers"].append({"entry": "wait_adventurer", "label": "Wait",
                             "when": {"const": True}, "payload": {}})
    # Only the player-local hearing projection is needed in this short graph.
    player["read"] = ["adventurer.name", "adventurer.site", "adventurer.vital.life",
                      "adventurer.cold_state", "adventurer.known_residents", *PUBLIC]
    player = {key: player[key] for key in ("name", "actor", "entries", "read", "offers")}
    seats, profiles = [player], []
    form_seats = [{"seat": "adventurer", "tempo": 100,
                   "eligible": "actor.vital.life == 'alive' and actor.cold_state != 'frozen'",
                   "costs": {"offer_escort_adventurer": 10000, "wait_adventurer": 10000}}]
    controls = _document("source/control/session.yaml")["game_form"]["seats"]
    for owner in NPCS:
        seat = _seat(original_seats, owner)
        wait = "queen_wait_emma" if owner == "emma" else "wait_" + owner
        reply = "escort_reply_" + owner
        seats.append({
            "name": owner, "actor": owner, "entries": [reply, wait], "read": seat["read"],
            "offers": [row for row in seat["offers"] if row.get("entry") == reply]
            + [{"entry": wait, "label": "Wait", "when": {"const": True}, "payload": {}}],
        })
        profiles.append(_profile(lib, policies, owner))
        control = _row(controls, "seat", owner)
        reply_cost = next(row["value"] for row in control["cost_groups"]
                          if reply in row["entries"])
        form_seats.append({
            "seat": owner, "tempo": control["tempo"], "eligible": control["eligible"],
            "costs": {reply: reply_cost, wait: 10000},
        })
    profiles.append(_profile(lib, policies, "huddled_one", hidden=True))
    source = {
        "schema": "c0.owner_graph.v6", "owners": ["scene", "adventurer", *NPCS],
        "actor_domains": [
            {"name": "residents", "actor_state": "Person", "owners": list(RESIDENTS)},
            {"name": "people", "actor_state": "Person", "owners": ["adventurer", *RESIDENTS]},
        ],
        "offer_provider": {"name": "finite_value", "version": "1"},
        "lawdefs": rules,
        "actions": [
            _row(bindings["actions"], "name", "offer_escort_adventurer"),
            _row(bindings["actions"], "family", "escort_reply"),
            _row(bindings["actions"], "family", "wait"),
            _row(bindings["actions"], "name", "escort_reply_emma"),
            _row(bindings["actions"], "name", "queen_wait_emma"),
        ],
        "events": [
            _row(bindings["events"], "family", "escort_heard"),
            _row(bindings["events"], "name", "queen_escort_heard"),
            _row(bindings["events"], "family", "escort_reply_heard"),
        ],
        "seats": seats, "appraisal_profiles": profiles,
        "due_events": [],
        "temporal": {"mechanism": "action_value_event_jump", "order": [],
                     "max_pending": 0, "periodic": []},
        "game_form": {"mode": "action_value_event_jump", "end_at": None,
                      "max_same_time_actions": 64, "seats": form_seats},
    }
    program = compile_owner_graph(check_graph_ports(ports, nominal), source)
    opening = _document("opening.assets.yaml")["opening"]
    assets = {
        "schema": "c0.owner_graph.assets.v1", "time": 0,
        "opening": {owner: deepcopy(opening[owner]) for owner in source["owners"]},
        "action_value_openings": [
            {"seat": owner, "debt": 0, "tie_priority": index}
            for index, owner in enumerate(("adventurer", *NPCS))
        ],
        "controllers": [{"seat": "adventurer", "mode": "human_prompt"}]
        + [{"seat": profile["seat"], "mode": "finite_appraisal", "profile": profile["name"]}
           for profile in profiles[:-1]],
    }
    for owner in ("adventurer", *NPCS):
        assets["opening"][owner].update(site=HERE, cold_state="mobile", current_movement_speed=5)
    return program, assets, nominal, source, lib, policies


def _snapshot(session):
    return dict(session.author_snapshot().owners)


def _invite(session):
    offer = next(row for row in session.offers("adventurer")
                 if row.entry == "offer_escort_adventurer")
    result = session.submit("adventurer", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    return result.occurrences[0].occurrence


def _pending_state(authored, owner="huddled_one"):
    program, assets, *_ = authored
    session = program.start(assets)
    invitation = _invite(session)
    state = _snapshot(session)
    action = dict(program.actions)["escort_reply_" + owner]
    return action, state, invitation


@pytest.mark.parametrize("owner", NPCS)
def test_selected_real_reply_law_keeps_distinct_witnesses_and_current_status(authored, owner):
    action, state, invitation = _pending_state(authored, owner)
    actor = state[owner]
    payload = action.payload_type(owner, "adventurer", "ready_now")
    outputs = action.value.evaluate(
        {"scene": state["scene"], "actor": actor, "recipient": state["adventurer"],
         "payload": payload}, occurrence=K0OccurrenceRef(100),
    )
    reply = outputs["escort_reply"] if owner == "emma" else outputs["conversations"].escort_reply
    assert reply.speaker == owner and reply.recipient == "adventurer"
    assert reply.status == "ready_now" and reply.site == HERE
    assert reply.invitation == invitation and reply.invitation_hearing == actor.escort_heard_ref
    assert len({reply.invitation, reply.invitation_hearing, reply.action}) == 3
    assert outputs["reply_log"].entries == (reply,)
    assert state["adventurer"].conversations.heard_escort_replies == ()
    assert not hasattr(reply, "commitment")
    if owner != "emma":
        assert outputs["conversations"].prison == actor.conversations.prison
        assert outputs["conversations"].tower == actor.conversations.tower
        assert outputs["conversations"].visible_motions == actor.conversations.visible_motions


@pytest.mark.parametrize("owner", ("huddled_one", "emma"))
@pytest.mark.parametrize("fault", ("not_heard", "frozen", "dead", "absent", "repeated"))
def test_reply_law_rejects_without_actual_local_hearing_or_ability(authored, owner, fault):
    action, state, invitation = _pending_state(authored, owner)
    actor, recipient = state[owner], state["adventurer"]
    if fault == "not_heard":
        actor = replace(actor, escort_heard_ref=None)
    elif fault == "frozen":
        actor = replace(actor, cold_state="frozen", current_movement_speed=0)
    elif fault == "dead":
        actor = replace(actor, vital=replace(actor.vital, life="dead", endurance=0,
                                            death_ref=K0OccurrenceRef(90)))
    elif fault == "absent":
        actor = replace(actor, site="ritual_ring")
    elif owner == "emma":
        actor = replace(actor, escort_replied_invitations=(invitation,))
    else:
        actor = replace(actor, conversations=replace(
            actor.conversations, escort_replied_invitations=(invitation,),
        ))
    assert action.value.evaluate(
        {"scene": state["scene"], "actor": actor, "recipient": recipient,
         "payload": action.payload_type(owner, "adventurer", "ready_now")},
        occurrence=K0OccurrenceRef(100),
    ) is None


@pytest.mark.parametrize("owner", ("huddled_one", "emma"))
def test_current_inability_or_confinement_can_be_reported_but_not_readiness(authored, owner):
    action, state, _ = _pending_state(authored, owner)
    actor = (replace(state[owner], current_movement_speed=0) if owner == "emma"
             else replace(state[owner], site="treasure_ice"))
    actor.validate_for_k0()
    roots = {"scene": state["scene"], "actor": actor,
             "recipient": replace(state["adventurer"], site=actor.site)}
    for status in ("ready_now", "unable_now", "not_ready_now"):
        result = action.value.evaluate(
            {**roots, "payload": action.payload_type(owner, "adventurer", status)},
            occurrence=K0OccurrenceRef(100),
        )
        assert (result is not None) == (status == "unable_now")


def test_short_k0_autonomous_replies_reach_only_actual_player_hearing(authored):
    program, assets, *_ = authored
    session = program.start(assets)
    invitation = _invite(session)
    assert _snapshot(session)["adventurer"].conversations.heard_escort_replies == ()
    frame = session.continue_form("adventurer")
    assert not frame.offer_faults
    heard = dict(session.read("adventurer").fields)[PUBLIC[1]]
    assert {record.reply.speaker for record in heard} == set(NPCS)
    assert len(heard) == len(NPCS)
    history = {row.occurrence: row for row in session.author_snapshot().occurrences}
    for record in heard:
        reply = record.reply
        assert reply.invitation == invitation and reply.status == "ready_now"
        assert history[reply.action].source == dict(program.actions)[
            "escort_reply_" + reply.speaker
        ].source_key
        assert history[record.hearing].formation_basis.predecessor == reply.action
        assert len({invitation, reply.invitation_hearing, reply.action, record.hearing}) == 4
    assert dict(session.read("adventurer").fields)[PUBLIC[0]] == heard[-1]
    assert all("escort_reply_log" not in name and "escort_replied_invitations" not in name
               for name, _ in session.read("adventurer").fields)
    assert all(record.proposal.chosen.entry.startswith("escort_reply_")
               for record in session.appraisal_history()[:len(NPCS)])
    assert not any(offer.entry == "escort_reply_huddled_one"
                   for offer in session.offers("huddled_one"))
    assert isinstance(session.submit("adventurer", "wait_adventurer", {}), K0Published)
    session.continue_form("adventurer")
    assert _snapshot(session)["adventurer"].conversations.heard_escort_replies == heard


@pytest.mark.parametrize("fault", ("absent", "frozen", "not_attending"))
def test_short_k0_invitation_cannot_create_hearing_or_reply_for_unavailable_npc(authored, fault):
    program, original, *_ = authored
    assets = deepcopy(original)
    npc = assets["opening"]["emma"]
    if fault == "absent":
        npc["site"] = "tower_top"
    elif fault == "frozen":
        npc.update(cold_state="frozen", current_movement_speed=0)
    else:
        npc["attending"] = False
    session = program.start(assets)
    _invite(session)
    session.continue_form("adventurer")
    npc = _snapshot(session)["emma"]
    assert npc.escort_heard_ref is None and npc.escort_reply is None
    heard = _snapshot(session)["adventurer"].conversations.heard_escort_replies
    assert len(heard) == len(RESIDENTS)
    assert all(record.reply.speaker != "emma" for record in heard)


def test_existing_hidden_tendency_is_not_replaced_with_escort_acceptance(authored):
    program, original, *_ = authored
    assets = deepcopy(original)
    _row(assets["controllers"], "seat", "huddled_one")["profile"] = "remain_hidden_huddled_one"
    session = program.start(assets)
    _invite(session)
    session.continue_form("adventurer")
    heard = _snapshot(session)["adventurer"].conversations.heard_escort_replies
    reply = next(record.reply for record in heard if record.reply.speaker == "huddled_one")
    assert reply.status == "not_ready_now"


@pytest.mark.parametrize("fault", ("absent", "frozen", "dead", "foreign_action", "repeated"))
def test_actual_player_hearing_law_rechecks_locality_trigger_and_no_repeat(authored, fault):
    program, assets, *_ = authored
    session = program.start(assets)
    _invite(session)
    session.continue_form("adventurer")
    state = _snapshot(session)
    actor = state["adventurer"]
    reply = state["scene"].escort_reply_log.entries[0]
    trigger = reply.action
    if fault != "repeated":
        actor = replace(actor, conversations=replace(
            actor.conversations, heard_escort_replies=(), latest_escort_reply=None,
        ))
    if fault == "absent":
        actor = replace(actor, site="ritual_ring")
    elif fault == "frozen":
        actor = replace(actor, cold_state="frozen", current_movement_speed=0)
    elif fault == "dead":
        actor = replace(actor, vital=replace(actor.vital, life="dead", endurance=0,
                                            death_ref=K0OccurrenceRef(90)))
    elif fault == "foreign_action":
        trigger = K0OccurrenceRef(500)
    event = next(event for _, event in program.events
                 if event.ports.value_ports.outputs.get("conversations") is not None)
    assert event.value.evaluate(
        {"scene": state["scene"], "actor": actor, "trigger": C0EventTrigger(trigger)},
        occurrence=K0OccurrenceRef(600),
    ) is None


def test_author_schema_costs_control_and_profile_coverage_remain_bounded(authored):
    _, _, _, source, lib, policies = authored
    assert len(_row(lib["records"], "name", "Person")["fields"]) == 64
    assert len(_row(lib["records"], "name", "Scene")["fields"]) <= 64
    for seat in source["game_form"]["seats"][1:]:
        assert seat["costs"]["escort_reply_" + seat["seat"]] == 1000
    definitions = C0AppraisalDefinitions(lib["appraisal_definitions"])
    for profile in policies:
        if "definition" in profile and profile.get("seat") in NPCS:
            bound, _ = definitions.bind(profile)
            check_finite_appraisal_shape(bound, seat=bound["seat"],
                                         entries=tuple(profile["entries"].values()))
    player_seat = _seat(_document("source/control/seats.yaml")["seats"], "adventurer")
    assert set(PUBLIC) <= set(player_seat["read"])
    assert not any(path.startswith(tuple(owner + "." for owner in NPCS))
                   for path in player_seat["read"] if "escort_reply" in path)
