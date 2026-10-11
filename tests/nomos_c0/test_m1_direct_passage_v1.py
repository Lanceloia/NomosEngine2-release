"""Real authored passage law: an obstruction is a published, sourced outcome."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel import K0EventTypeKey, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryProfile,
    _K0InMemorySession,
)
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from nomos_kernel._state_image_abi import _K0OwnerState

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.composable_action_v1 import compile_composable_action
from nomos_c0.composable_value_v1 import compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.lawdef_binding_v1 import C0LawDefinitions
from nomos_c0.program_start_v1 import _opening

WORLD = Path(__file__).resolve().parents[2] / "src/nomos_examples/everflame"


def document(path):
    return read_author_document(WORLD / path).to_data()


@pytest.fixture(scope="module")
def authored():
    nominal = check_nominal_lib(document("model.lib.yaml"))
    raw = document("capabilities.ports.yaml")
    ports = {key: raw[key] for key in ("schema", "scene_owner", "offer_provider")}
    ports.update(
        actions=[row for row in raw["actions"] if row["symbol"] == "try_direct_passage"],
        events=[],
        due_events=[],
    )
    library = check_graph_ports(ports, nominal)
    binding = next(
        row
        for row in document("source/bindings/capabilities.yaml")["actions"]
        if row.get("name") == "move_adventurer"
    )
    template = library.actions[0]
    assert binding["template"] == template.symbol
    selected = replace(
        template.ports,
        source_key=K0SourceSpecKey(binding["source_key"]),
        event_type=K0EventTypeKey(binding["event_type"]),
    )
    value = C0LawDefinitions(document("source/rules/direct_passage.yaml")["lawdefs"])
    body = {
        "schema": "c0.action.value.v1",
        "source_key": binding["source_key"],
        "event_type": binding["event_type"],
        **value.instantiate("action", binding["law"]),
    }
    program = compile_composable_action(json.dumps(body), selected)
    assets = document("opening.assets.yaml")["opening"]
    actor = _opening(nominal.record("Person"), assets["adventurer"])
    scene = _opening(nominal.record("Scene"), assets["scene"])
    # A short single-law runtime, not a scripted full adventure.
    path = next(
        row for row in scene.paths if row.start == "ritual_ring" and row.end == "ritual_threshold"
    )
    actor = replace(actor, site=path.start, known_paths=(path,))
    return nominal, selected, program, scene, actor, path


def settle(case, *, scene=None, current_actor=None, **payload_changes):
    nominal, ports, program, initial_scene, initial_actor, path = case
    scene = initial_scene if scene is None else scene
    actor = initial_actor if current_actor is None else current_actor
    owners = tuple(sorted((ports.scene_owner, ports.actor_owner), key=lambda owner: owner.key))
    runtime = _K0InMemorySession.create(
        _K0InMemoryProfile(owners, (program.build_spec(),), (), 1, 0),
        tuple(
            _K0OwnerState(owner.key, scene if owner.key == ports.scene_owner.key else actor)
            for owner in owners
        ),
    )
    values = dict(actor=actor.name, destination=path.end, base_move_cost=path.base_move_cost)
    values.update(payload_changes)
    attempt = _K0InMemoryActionAttempt(program.source_key, nominal.record("MoveAttempt")(**values))
    result = runtime.settle(attempt)
    return (
        result,
        runtime.read_owner(ports.scene_owner.key).view,
        runtime.read_owner(ports.actor_owner.key).view,
    )


@pytest.mark.parametrize("frozen", [True, False])
def test_attempt_publishes_real_success_or_obstruction(authored, frozen):
    _, _, program, scene, actor, path = authored
    scene = replace(scene, floors=tuple(replace(floor, frozen=frozen) for floor in scene.floors))
    result, after_scene, after = settle(authored, scene=scene)
    assert isinstance(result, K0Published)
    assert len(result.occurrences) == 1
    action = result.occurrences[0].occurrence
    assert result.occurrences[0].source == program.source_key
    outcome = after.conversations.movement_attempt
    assert outcome.action == action == after.last_action_ref
    assert outcome.start == path.start and outcome.destination == path.end
    assert outcome.outcome == ("blocked" if frozen else "arrived")
    assert outcome.landing == after.site == (path.start if frozen else path.end)
    if frozen:
        assert after_scene.actor_motion == scene.actor_motion
        assert after.known_residents == actor.known_residents
        assert after.sighting_ref == actor.sighting_ref
    else:
        assert after_scene.actor_motion.action == action
        assert after_scene.actor_motion.end == path.end


@pytest.mark.parametrize(
    "kind",
    ["unknown_path", "wrong_target", "wrong_cost", "wrong_actor", "frozen", "dead", "exhausted"],
)
def test_illegal_attempt_still_rejects_without_world_write(authored, kind):
    actor = authored[4]
    changes = {}
    if kind == "unknown_path":
        actor = replace(actor, known_paths=())
    elif kind == "wrong_target":
        changes["destination"] = "palace_exit"
    elif kind == "wrong_cost":
        changes["base_move_cost"] = 1
    elif kind == "wrong_actor":
        changes["actor"] = "huddled_one"
    elif kind == "frozen":
        actor = replace(actor, cold_state="frozen", current_movement_speed=0)
    elif kind == "dead":
        actor = replace(actor, vital=replace(actor.vital, life="dead", endurance=0))
    elif kind == "exhausted":
        actor = replace(actor, vital=replace(actor.vital, life="incapacitated", endurance=0))
    result, scene, after = settle(authored, current_actor=actor, **changes)
    assert isinstance(result, K0NotAdmitted)
    assert scene == authored[3] and after == actor


def test_opening_has_no_fake_attempt_and_player_reads_only_own_result(authored):
    nominal, *_ = authored
    assert authored[4].conversations.movement_attempt is None
    seat = next(
        row
        for row in document("source/control/seats.yaml")["seats"]
        if row.get("name") == "adventurer"
    )
    assert "adventurer.conversations.movement_attempt" in seat["read"]
    assert set(seat["read"]) <= set(seat["presentation"]["fields"])
    assert "conversations.movement_attempt" in nominal.owner("adventurer").seat_readable_paths
    assert "scene.floors" not in seat["read"]


@pytest.mark.parametrize("frozen", [False, True])
def test_success_and_obstruction_use_the_same_authored_cost(authored, frozen):
    nominal, ports, _, scene, actor, path = authored
    seat = next(
        row
        for row in document("source/control/session.yaml")["game_form"]["seats"]
        if row["seat"] == "adventurer"
    )
    cost = next(row["value"] for row in seat["cost_groups"] if "move_adventurer" in row["entries"])
    value = compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"cost": cost},
            }
        ),
        replace(ports.value_ports, outputs={"cost": int}),
        admission_outputs=frozenset({"cost"}),
    )
    scene = replace(scene, floors=tuple(replace(floor, frozen=frozen) for floor in scene.floors))
    payload = nominal.record("MoveAttempt")(actor.name, path.end, path.base_move_cost)
    assert value.evaluate_admission_outputs(
        {"scene": scene, "actor": actor, "payload": payload}
    ) == {"cost": 10000}
