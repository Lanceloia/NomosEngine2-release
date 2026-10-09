"""Explicit availability signals filter candidates without widening seat authority."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _fixed_scalar_world
from test_nominal_signatures_v1 import assert_symbolic
from test_visibility_binding_v1 import _block_frontend, _inputs, _parcel
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program


def _authored():
    lib, ports, source, assets = _parcel(ranged=True)
    seat = source["seats"][0]
    seat["read"] = [path for path in seat["read"] if not path.startswith("scene.")]
    seat["presentation"]["fields"] = {name: name for name in seat["read"]}
    offer = seat["offers"][0]
    offer["when"] = {"const": True}
    offer["payload"]["item_id"] = {"const": "P-1"}
    ports["candidate_inputs"] = [
        {
            "symbol": "local_route_available",
            "action": "dispatch",
            "read": ["scene.parcel.status", "scene.parcel.destination", "payload.destination"],
            "fields": {},
        }
    ]
    offer["availability"] = {
        "ref": "local_route_available",
        "when": {
            "all": [
                {"eq": [{"ref": "scene.parcel.status"}, {"const": "home"}]},
                {"eq": [{"ref": "scene.parcel.destination"}, {"ref": "payload.destination"}]},
            ]
        },
    }
    return lib, ports, source, assets


def test_same_program_current_signal_changes_candidates_without_scene_read_or_write(monkeypatch):
    lib, ports, source, assets = _authored()
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    assert_symbolic(program.visibility_ir)
    _block_frontend(monkeypatch)
    for layout in (program.world_layout, alternate):
        rebound = bind_program(program.program_ir, layout)
        for destination in ("dock", "gate"):
            opening = deepcopy(assets)
            opening["opening"]["scene"]["parcel"]["destination"] = destination
            session = rebound.start(opening)
            before = session.author_snapshot()
            assert not any(path.startswith("scene.") for path, _ in session.read("sender").fields)
            offers = session.offers("sender")
            assert tuple(dict(offer.payload)["destination"] for offer in offers) == (destination,)
            assert session.offers("sender") == offers
            assert session.author_snapshot() == before
            if destination == "dock":
                offer = offers[0]
                assert isinstance(
                    session.submit("sender", offer.entry, dict(offer.payload)), K0Published
                )
                assert not session.offers("sender")


def test_availability_does_not_replace_actual_k0_admission():
    lib, ports, source, assets = _authored()
    law = next(row for row in source["lawdefs"] if row["name"] == "action.dispatch")
    value = law["body"]["value"]
    value["guard"] = {"all": [value["guard"], False]}
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("sender")[0]
    before = session.author_snapshot()
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


@pytest.mark.parametrize(
    "fault", ["unknown", "wrong_action", "read", "fields", "write", "dice", "type"]
)
def test_input_requires_exact_action_authority_and_a_pure_boolean(fault):
    lib, ports, source, _ = _authored()
    port = ports["candidate_inputs"][0]
    availability = source["seats"][0]["offers"][0]["availability"]
    if fault == "unknown":
        availability["ref"] = "not_declared"
    elif fault == "wrong_action":
        port["action"] = "confirm"
    elif fault == "read":
        port["read"].append("scene.signal")
    elif fault == "fields":
        port["fields"] = {"Parcel": ["arrival_ref"]}
    elif fault == "write":
        port["write_paths"] = ["actor.sent_ref"]
    elif fault == "dice":
        availability["when"] = {
            "eq": [{"die_roll": {"seed": {"const": 1}, "sides": 6}}, {"const": 1}]
        }
    else:
        availability["when"] = {"const": "yes"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("slot", ["when", "payload", "label"])
def test_privileged_input_does_not_launder_into_public_candidate_fields(slot):
    lib, ports, source, _ = _authored()
    offer = source["seats"][0]["offers"][0]
    if slot == "when":
        offer["when"] = {"eq": [{"ref": "scene.parcel.status"}, {"const": "home"}]}
    elif slot == "payload":
        offer["payload"]["item_id"] = {"ref": "scene.parcel.status"}
    else:
        offer["label"]["value"] = {"ref": "scene.parcel.status"}
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(lib, ports, source)


def test_fixed_participant_filter_receives_the_complete_typed_candidate():
    lib, ports, source, assets = _fixed_scalar_world()
    ports["candidate_inputs"] = [
        {"symbol": "permission", "action": "enable", "read": ["payload.allowed"], "fields": {}}
    ]
    source["seats"][0]["offers"][0]["availability"] = {
        "ref": "permission",
        "when": {"ref": "payload.allowed"},
    }
    program = _compile(lib, ports, source)
    session = bind_program(program.program_ir, _layout(program)).start(assets)
    offer = session.offers("maker")[0]
    assert dict(offer.payload) == {"allowed": True}
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)


def test_bind_rejects_a_narrowed_grant_with_a_retained_private_expression():
    lib, ports, source, _ = _authored()
    program = _compile(lib, ports, source)
    visibility = program.visibility_ir
    seat = visibility.seats[0]
    check = seat.candidate_checks[0]
    value = check.body.value
    narrowed = replace(
        value.ports,
        readable_paths=value.ports.readable_paths - {"scene.parcel.destination"},
        admission_readable_paths=value.ports.admission_readable_paths
        - {"scene.parcel.destination"},
    )
    altered = replace(check, body=replace(check.body, value=replace(value, ports=narrowed)))
    seats = (replace(seat, candidate_checks=(altered,)), *visibility.seats[1:])
    ir = replace(program.program_ir, visibility=replace(visibility, seats=seats))
    with pytest.raises(C0LawError, match="exact read authority"):
        bind_program(ir, program.world_layout)


@pytest.mark.parametrize("local_collection", [False, True])
def test_bind_rechecks_collection_element_fields_without_reentering_frontend(
    monkeypatch, local_collection
):
    lib, ports, source, assets = _authored()
    port = ports["candidate_inputs"][0]
    port["read"] = ["scene.routes"]
    port["fields"] = {"Route": ["travel"]}
    condition = {
        "lt": [
            {"const": 0},
            {
                "count_matching": {
                    "collection": {"ref": "routes" if local_collection else "scene.routes"},
                    "as": "route",
                    "where": {"le": [{"ref": "route.travel"}, {"const": 10}]},
                }
            },
        ]
    }
    if local_collection:
        condition = {"let": {"name": "routes", "value": {"ref": "scene.routes"}, "in": condition}}
    source["seats"][0]["offers"][0]["availability"]["when"] = condition
    program = _compile(lib, ports, source)
    layouts = program.world_layout, _layout(program)
    _block_frontend(monkeypatch)
    for layout in layouts:
        session = bind_program(program.program_ir, layout).start(assets)
        before = session.author_snapshot()
        assert session.offers("sender")
        assert session.author_snapshot() == before

    visibility = program.visibility_ir
    seat = visibility.seats[0]
    check = seat.candidate_checks[0]
    value = check.body.value

    def without_travel(declarations):
        return tuple(
            (carrier, names - {"travel"} if carrier.symbol == "Route" else names)
            for carrier, names in declarations
        )

    narrowed = replace(
        value.ports,
        readable_fields=without_travel(value.ports.readable_fields),
        admission_readable_fields=without_travel(value.ports.admission_readable_fields),
    )
    altered = replace(check, body=replace(check.body, value=replace(value, ports=narrowed)))
    seats = (replace(seat, candidate_checks=(altered,)), *visibility.seats[1:])
    ir = replace(program.program_ir, visibility=replace(visibility, seats=seats))
    for layout in layouts:
        with pytest.raises(C0LawError, match="record field is not a declared read port"):
            bind_program(ir, layout)


@pytest.mark.parametrize("kind", ["fixed", "range", "object", "participant", "fixed_participant"])
def test_filter_preserves_each_existing_candidate_shape_and_actual_action(kind):
    lib, ports, source, assets = _inputs(kind)
    seat = source["seats"][0]
    key = {
        "object": "for_each_object",
        "participant": "for_each_participants",
        "fixed_participant": "fixed_participants",
    }.get(kind)
    offer = next(row for row in seat["offers"] if key is None or key in row)
    entry = offer["entry"]
    template = next(row["template"] for row in source["actions"] if row["name"] == entry)
    action = next(row for row in ports["actions"] if row["symbol"] == template)
    path = next(
        path
        for path in action["value"]["read"]
        if path.startswith(("scene.", "actor.", "payload."))
    )
    ports["candidate_inputs"] = [
        {"symbol": "selected_signal", "action": template, "read": [path], "fields": {}}
    ]
    offer["availability"] = {"ref": "selected_signal", "when": {"const": False}}
    program = _compile(lib, ports, source)
    session = program.start(assets)
    assert not any(row.entry == entry for row in session.offers(seat["name"]))
    offer["availability"]["when"] = {"const": True}
    program = _compile(lib, ports, source)
    session = bind_program(program.program_ir, _layout(program)).start(assets)
    selected = next(row for row in session.offers(seat["name"]) if row.entry == entry)
    assert isinstance(session.submit(seat["name"], entry, dict(selected.payload)), K0Published)


def test_filter_arithmetic_fault_is_not_a_legal_false_or_world_write():
    lib, ports, source, assets = _authored()
    source["seats"][0]["offers"][0]["availability"]["when"] = {
        "eq": [{"ceil_div": [{"const": 1}, {"const": 0}]}, {"const": 1}]
    }
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    assert not session.offers("sender")
    faults = session.offer_faults("sender")
    assert len(faults) == 1 and faults[0].entry == "dispatch"
    assert session.author_snapshot() == before
