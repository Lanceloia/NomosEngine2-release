"""Evaluate selected real M1 preview laws and ports without compiling a world."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.composable_value_v1 import C0ValueStateError, compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.lawdef_binding_v1 import C0LawDefinitions
from nomos_c0.program_start_v1 import _opening
from nomos_c0.seat_offer_preview_v0 import C0SeatOfferPreview
from nomos_c0.seat_offers_v0 import C0SeatOffer

WORLD = Path(__file__).resolve().parents[2] / "src/nomos_examples/everflame"
ENTRIES = ("move_adventurer", "cross_ice_adventurer")


def _document(path):
    return read_author_document(WORLD / path).to_data()


@pytest.fixture(scope="module")
def authored():
    nominal = check_nominal_lib(_document("model.lib.yaml"))
    ports = _document("capabilities.ports.yaml")
    # Keep the selected authored rows intact; no Action/Event bodies or Session are built.
    selected_ports = {key: ports[key] for key in ("schema", "scene_owner", "offer_provider")}
    selected_ports.update(
        actions=[row for row in ports["actions"]
                 if row["symbol"] in {"try_direct_passage", "cross_ice"}],
        events=[],
        due_events=[],
        seat_offer_previews=[
            row for row in ports["seat_offer_previews"]
            if row["symbol"] in {"move_self_protection", "cross_success_protection"}
        ],
    )
    library = check_graph_ports(selected_ports, nominal)
    seats = _document("source/control/seats.yaml")["seats"]
    seat = next(row for row in seats if row.get("name") == "adventurer")
    laws = C0LawDefinitions(_document("source/rules/local_observation.yaml")["lawdefs"])
    assets = _document("opening.assets.yaml")
    scene = _opening(nominal.record("Scene"), assets["opening"]["scene"])
    actor = _opening(nominal.record("Person"), assets["opening"]["adventurer"])
    return nominal, library, seat, laws, assets, scene, actor


@pytest.fixture(scope="module", params=ENTRIES)
def preview_case(authored, request):
    nominal, library, seat, laws, assets, scene, actor = authored
    declaration = next(row for row in seat["offer_previews"] if row["entry"] == request.param)
    port = next(row for row in library.seat_offer_preview_ports
                if row.symbol == declaration["template"])
    body = laws.instantiate("seat_view", declaration["law"])["value"]
    value = compile_value_program(
        json.dumps(body), port.value_ports,
        admission_outputs=frozenset(port.value_ports.outputs),
    )
    torch_literal = next(row["state"] for row in assets["opening_objects"]
                         if row["kind"] == "everflame")
    torch = _opening(port.value_ports.roots[port.object_root], torch_literal)
    preview = C0SeatOfferPreview(request.param, port, value)
    candidate = next(row for row in getattr(actor, port.collection_field)
                     if getattr(row, port.candidate_origin_field) == actor.site)
    offer = C0SeatOffer(
        request.param, "Selected authored movement",
        ((port.offer_payload_key, getattr(candidate, port.candidate_key)),
         ("base_move_cost", candidate.base_move_cost)),
    )
    return preview, scene, actor, torch, candidate, offer, body, seat, nominal


def _project(case, *, actor=None, torch=None, offer=None):
    preview, scene, current_actor, current_torch, _, current_offer, *_ = case
    return preview.project(
        scene, current_actor if actor is None else actor,
        current_torch if torch is None else torch,
        current_offer if offer is None else offer,
    )


@pytest.mark.parametrize("current,maximum,expected", [
    (5, 5, 10000), (3, 5, 16667), (1, 5, 50000), (3, 10, 33334),
])
def test_cost_uses_current_speed_and_shared_authored_formula(
    preview_case, current, maximum, expected,
):
    preview, _, actor, _, _, offer, body, seat, _ = preview_case
    actor = replace(actor, current_movement_speed=current, max_movement_speed=maximum,
                    cold_loss_step=maximum // 5)
    actor.validate_for_k0()
    result = _project(preview_case, actor=actor)
    assert dict(result.preview)["action_value_cost"] == expected
    assert result.payload == offer.payload
    assert offer.preview == ()
    assert body["outputs"]["action_value_cost"] == {
        "call": {"ref": "movement.action_cost", "args": {
            "base_cost": {"ref": "candidate.base_move_cost"},
            "maximum_speed": {"ref": "actor.max_movement_speed"},
            "current_speed": {"ref": "actor.current_movement_speed"},
        }},
    }
    assert seat["presentation"]["preview_fields"][preview.entry]["action_value_cost"] == (
        "\u884c\u52a8\u503c\u6d88\u8017"
    )
    assert preview.ports.value_ports.outputs["action_value_cost"] is int
    assert "payload" not in preview.ports.value_ports.roots
    assert "candidate.base_move_cost" in preview.ports.value_ports.readable_paths


@pytest.mark.parametrize("caller_cost", [None, 0, 1, 99999, "forged-fee"])
def test_caller_payload_cost_cannot_change_local_candidate_price(preview_case, caller_cost):
    offer = preview_case[5]
    payload = dict(offer.payload)
    if caller_cost is None:
        del payload["base_move_cost"]
    else:
        payload["base_move_cost"] = caller_cost
    forged = replace(offer, payload=tuple(payload.items()))
    result = _project(preview_case, offer=forged)
    assert dict(result.preview)["action_value_cost"] == 10000
    assert result.payload == forged.payload


def test_only_unique_current_origin_candidate_sets_price(preview_case):
    preview, _, actor, _, candidate, _, *_ = preview_case
    port = preview.ports
    remote = replace(candidate, start="ritual_ring", base_move_cost=30001)
    actor = replace(actor, **{port.collection_field: (remote, candidate)})
    assert dict(_project(preview_case, actor=actor).preview)["action_value_cost"] == 10000
    actor = replace(actor, site=remote.start)
    actor.validate_for_k0()
    assert dict(_project(preview_case, actor=actor).preview)["action_value_cost"] == 30001


@pytest.mark.parametrize("kind", ["missing", "wrong_origin", "duplicate", "foreign_nominal"])
def test_invalid_candidate_leaves_offer_unknown(preview_case, kind):
    preview, _, actor, _, candidate, offer, *_ = preview_case
    collection = {
        "missing": (),
        "wrong_origin": (replace(candidate, start="ritual_ring"),),
        "duplicate": (candidate, replace(candidate, base_move_cost=20000)),
        "foreign_nominal": (candidate, object()),
    }[kind]
    actor = replace(actor, **{preview.ports.collection_field: collection})
    # The production projection catches this error and retains the unpriced offer.
    with pytest.raises(C0ValueStateError, match="Actor-local candidate"):
        _project(preview_case, actor=actor)
    assert offer.preview == ()


@pytest.mark.parametrize("current,maximum", [(0, 5), (-1, 5), (5, 0), (6, 5)])
def test_invalid_speed_has_no_fabricated_preview(preview_case, current, maximum):
    actor = replace(preview_case[2], current_movement_speed=current, max_movement_speed=maximum)
    assert _project(preview_case, actor=actor).preview == ()


@pytest.mark.parametrize("condition,expected", [
    ("opening", "unknown"), ("known_destination", "protected"),
    ("empty_torch", "exposed"), ("other_holder", "unknown"),
])
def test_existing_protection_output_is_preserved(preview_case, condition, expected):
    preview, _, actor, torch, candidate, _, _, _, nominal = preview_case
    protection_key = "self_after_move" if preview.entry == "move_adventurer" else "self_if_success"
    if condition == "known_destination":
        destination = candidate.end if preview.entry == "move_adventurer" else candidate.intended
        coverage = nominal.record("Coverage")(
            destination, (destination,), (destination,), (destination,),
        )
        actor = replace(actor, known_coverage=(coverage,))
    elif condition == "empty_torch":
        actor = replace(actor, known_everflame_charges=0)
        torch = replace(torch, charges=0)
    elif condition == "other_holder":
        torch = replace(torch, holder="huddled_one")
    actor.validate_for_k0()
    torch.validate_for_k0()
    result = dict(_project(preview_case, actor=actor, torch=torch).preview)
    assert result == {"action_value_cost": 10000, protection_key: expected}
