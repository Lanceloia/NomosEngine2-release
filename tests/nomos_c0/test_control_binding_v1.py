"""Startup/control binds to the same world, not to a previous native layout."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from nomos_kernel._action_value_abi import _K0ActionValueDueBoundary, _K0ActionValueOpening
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0OwnerState,
)
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_nominal_signatures_v1 import assert_symbolic
from test_world_binding_v1 import (
    ROOT,
    _compile,
    _documents,
    _forbid_checks,
    _layout,
    _parcel,
    _snapshot,
    _submit,
)

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.control_binding_v1 import bind_control
from nomos_c0.program_start_v1 import _opening
from nomos_c0.value_symbols_v1 import C0SymbolicType
from nomos_c0.world_binding_v1 import bind_world


def _inputs():
    lib, ports, source = _documents("parcel_delivery_v0")
    ports["actions"][0]["value"]["read"].append("actor.name")
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    source["temporal"] = {
        "mechanism": "action_value_event_jump",
        "order": ["arrive"],
        "max_pending": 1,
        "periodic": [],
    }
    source["opening_guard"] = {"eq": [{"ref": "scene.parcel.id"}, {"const": "P-1"}]}
    alternate = deepcopy(source["actions"][1])
    alternate.update(
        name="confirm_alt", source_key="c0.parcel.alt", event_type="c0.parcel.alt.action"
    )
    source["actions"].append(alternate)
    source["seats"][1]["entries"].append("confirm_alt")
    offer = deepcopy(source["seats"][1]["offers"][0])
    offer.update(entry="confirm_alt", label="Alternate acknowledgement")
    source["seats"][1]["offers"].append(offer)
    source["game_form"] = {
        "mode": "action_value_event_jump",
        "end_at": 8,
        "max_same_time_actions": 8,
        "seats": [
            {
                "seat": "sender",
                "tempo": 1,
                "eligible": {"is_none": {"ref": "actor.sent_ref"}},
                "costs": {
                    "dispatch": {
                        "if": {
                            "when": {"eq": [{"ref": "actor.name"}, {"const": "Mira"}]},
                            "then": 4,
                            "else": 7,
                        }
                    }
                },
            },
            {
                "seat": "receiver",
                "tempo": 1,
                "eligible": {"is_none": {"ref": "actor.receipt"}},
                "costs": {"confirm": 2, "confirm_alt": 3},
            },
        ],
        "world_stops": [
            {
                "outcome": "delivered",
                "owners": ["receiver"],
                "when": {"not_none": {"ref": "receiver.receipt"}},
            }
        ],
    }
    source["appraisal_profiles"] = [
        {
            "name": "prefer_alt",
            "seat": "receiver",
            "fallback_entry": "confirm",
            "tie_order": ["confirm_alt", "confirm"],
            "rules": [
                {"entry": "confirm", "mode": "default"},
                {
                    "entry": "confirm_alt",
                    "mode": "score",
                    "value": {
                        "if": {
                            "when": {"eq": [{"ref": "payload.destination"}, {"const": "dock"}]},
                            "then": 10,
                            "else": 0,
                        }
                    },
                },
            ],
        }
    ]
    assets["action_value_openings"] = [
        {"seat": "sender", "debt": 0, "tie_priority": 0},
        {"seat": "receiver", "debt": 3, "tie_priority": 1},
    ]
    return lib, ports, source, assets


def _runtime(world, control, assets):
    costs = dict(control.action_costs)
    specs = [
        replace(
            action.build_spec(),
            action_value_owner=action.actor_owner.key,
            action_cost_projector=costs[name],
        )
        for name, action in world.actions
    ]
    laws = []
    for _, event in world.events:
        spec, law = event.build()
        specs.append(spec)
        laws.append(law)
    specs.extend(world.temporal_binding.due_specs)
    owners = tuple(item.owner for item in world.layout.owners.owners)
    profile = _K0InMemoryProfile(
        owners,
        tuple(specs),
        tuple(laws),
        max(1 + len(laws), len(world.dues)),
        len(laws),
        temporal_policy=control.temporal_policy,
        action_value_policy=control.action_value_policy,
        terminal_policy=control.terminal_policy,
    )
    return _K0InMemorySession.create(
        profile,
        tuple(
            _K0OwnerState(
                item.owner.key, _opening(item.owner.state_type, assets["opening"][item.symbol])
            )
            for item in world.layout.owners.owners
        ),
        initial_time=_K0FixedTime(assets["time"]),
        opening_action_values=tuple(
            _K0ActionValueOpening(**row) for row in assets["action_value_openings"]
        ),
    )


def test_control_is_symbolic_frozen_and_consumed_by_production_profile():
    lib, ports, source, _ = _inputs()
    program = _compile(lib, ports, source)
    ir = program.control_ir
    assert_symbolic(ir)
    assert "c0.parcel-demo.sender" not in repr(ir)
    assert ir.world is program.world_ir
    with pytest.raises(FrozenInstanceError):
        ir.mode = "manual"
    bound = bind_control(ir, bind_world(program.world_ir, program.world_layout))
    assert program.game_form == bound.game_form
    assert program.opening_guard == bound.opening
    assert program.profile.action_value_policy == bound.action_value_policy
    assert program.profile.temporal_policy == bound.temporal_policy
    for name, cost in bound.action_costs:
        action = dict(program.actions)[name]
        spec = next(item for item in program.profile.source_specs if item.key == action.source_key)
        assert spec.action_cost_projector == cost
        assert cost.basis == action._cost_basis()
    assert program.appraisal_profiles == bound.appraisals


def test_one_control_runs_cost_due_stop_and_scoring_in_two_layouts(monkeypatch):
    lib, ports, source, assets = _inputs()
    program = _compile(lib, ports, source)
    second = _layout(program)
    _forbid_checks(monkeypatch)
    final = []
    for layout in (program.world_layout, second):
        world = bind_world(program.world_ir, layout)
        control = bind_control(program.control_ir, world)
        runtime = _runtime(world, control, assets)
        assert runtime.action_opportunity().seat == "sender"
        assert isinstance(_submit(world, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
        assert runtime.action_value_history()[-1].cost == 4
        assert isinstance(runtime.continue_action_value(), _K0ActionValueDueBoundary)
        assert runtime.read_time().ordinal == 2
        assert runtime.continue_action_value().seat == "receiver"
        assert runtime.read_time().ordinal == 3
        actor = runtime.read_owner(layout.owners.owner("receiver").owner.key).view
        rule = control.appraisals[0].rules[1]
        payload = dict(world.actions)["confirm_alt"].payload_type("Niko", "P-1", "dock")
        assert rule.value.evaluate_admission_outputs({"actor": actor, "payload": payload}) == {
            "score": 10
        }
        assert runtime.terminal_state() is None
        assert isinstance(
            _submit(world, runtime, "confirm_alt", "Niko", "P-1", "dock"), K0Published
        )
        assert runtime.action_value_history()[-1].cost == 3
        assert runtime.terminal_state().outcome == "delivered"
        assert runtime.terminal_state().trigger == runtime.occurrence_history()[-1].occurrence
        assert (
            runtime.occurrence_history()[-1].source == dict(world.actions)["confirm_alt"].source_key
        )
        final.append(_snapshot(world, runtime))
    assert final[0] == final[1]


def test_same_program_two_assets_recomputes_cost_and_rejects_illegal_opening():
    lib, ports, source, assets = _inputs()
    program = _compile(lib, ports, source)
    for name, cost in (("Mira", 4), ("Ada", 7)):
        opening = deepcopy(assets)
        opening["opening"]["sender"]["name"] = name
        session = program.start(opening)
        offer = session.form_frame("sender").offers[0]
        assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
        assert session._runtime.action_value_history()[-1].cost == cost
        assert "scene.routes" not in dict(session.read("sender").fields)
    illegal = deepcopy(assets)
    illegal["opening"]["scene"]["parcel"]["id"] = "P-2"
    with pytest.raises(C0BindingError, match="opening"):
        program.start(illegal)


def test_bound_appraisal_selects_actual_source_and_world_stop_is_not_an_occurrence():
    lib, ports, source, assets = _inputs()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    program = _compile(lib, ports, source)
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    session.submit("sender", offer.entry, dict(offer.payload))
    frame = session.continue_form("sender")
    assert frame.finished and frame.outcome == "delivered"
    assert frame.time == 3
    assert session.appraisal_history()[0].proposal.chosen.entry == "confirm_alt"
    assert session._runtime.action_value_history()[-1].cost == 3
    tape = session._runtime.occurrence_history()
    assert tape[-1].source == dict(program.actions)["confirm_alt"].source_key
    assert session.form_frame("sender").outcome == "delivered"
    assert session._runtime.occurrence_history() == tape


def test_nonpositive_bound_cost_rejects_without_changing_world_or_scheduler():
    lib, ports, source, assets = _inputs()
    source["game_form"]["seats"][0]["costs"]["dispatch"] = 0
    program = _compile(lib, ports, source)
    world = bind_world(program.world_ir, _layout(program))
    control = bind_control(program.control_ir, world)
    runtime = _runtime(world, control, assets)
    before = (_snapshot(world, runtime), runtime.action_value_state(), runtime.occurrence_history())
    assert isinstance(_submit(world, runtime, "dispatch", "Mira", "P-1", "dock"), K0NotAdmitted)
    assert before == (
        _snapshot(world, runtime),
        runtime.action_value_state(),
        runtime.occurrence_history(),
    )
    assert runtime.action_value_history() == ()


@pytest.mark.parametrize("mode", ["manual", "event_jump_stop"])
def test_existing_control_modes_bind_without_action_value_projection(mode):
    lib, ports, source = _documents("parcel_delivery_v0")
    if mode == "manual":
        source["game_form"] = {"mode": "manual"}
    program = _compile(lib, ports, source)
    bound = bind_control(program.control_ir, bind_world(program.world_ir, _layout(program)))
    assert bound.action_value_policy is None and bound.action_costs == ()
    assert (bound.game_form is None) == (mode == "manual")
    if mode == "event_jump_stop":
        assert bound.game_form.seats == ("sender", "receiver")
        assert bound.game_form.end_at == 8


def test_control_rejects_a_separately_checked_equal_world():
    lib, ports, source, _ = _inputs()
    first = _compile(lib, ports, source)
    second = _compile(lib, ports, source)
    with pytest.raises(C0LawError, match="exact selected world"):
        bind_control(first.control_ir, bind_world(second.world_ir, second.world_layout))


@pytest.mark.parametrize(
    "defect",
    [
        "entry_owner",
        "cost_ports",
        "projection_root",
        "projection_permission",
        "appraisal_root",
        "appraisal_permission",
        "stop_owner",
    ],
)
def test_control_binding_rechecks_owner_ports_and_local_read_permissions(defect):
    lib, ports, source, _ = _inputs()
    program = _compile(lib, ports, source)
    ir = program.control_ir
    if defect == "entry_owner":
        ir = replace(
            ir, seats=(replace(ir.seats[0], actor="receiver"), replace(ir.seats[1], actor="sender"))
        )
    elif defect == "cost_ports":
        seat = ir.action_values[0]
        value = seat.costs[0][1]
        value = replace(
            value, value=replace(value.value, ports=replace(value.value.ports, outputs=()))
        )
        ir = replace(
            ir, action_values=(replace(seat, costs=(("dispatch", value),)), ir.action_values[1])
        )
    elif defect.startswith("projection"):
        seat = ir.action_values[0]
        value = seat.projection
        changes = (
            {"roots": (("actor", C0SymbolicType("record", "Receiver")),)}
            if defect.endswith("root")
            else {"readable_paths": value.value.ports.readable_paths | {"actor.secret"}}
        )
        value = replace(
            value, value=replace(value.value, ports=replace(value.value.ports, **changes))
        )
        ir = replace(ir, action_values=(replace(seat, projection=value), ir.action_values[1]))
    elif defect.startswith("appraisal"):
        profile = ir.appraisals[0]
        rule = profile.rules[1]
        value = rule.value
        changes = (
            {"roots": (("actor", C0SymbolicType("record", "Sender")),)}
            if defect.endswith("root")
            else {"readable_paths": value.value.ports.readable_paths | {"actor.secret"}}
        )
        value = replace(
            value, value=replace(value.value, ports=replace(value.value.ports, **changes))
        )
        ir = replace(
            ir, appraisals=(replace(profile, rules=(profile.rules[0], replace(rule, value=value))),)
        )
    else:
        ir = replace(ir, world_stops=(replace(ir.world_stops[0], owners=("sender",)),))
    with pytest.raises(C0LawError):
        bind_control(ir, bind_world(program.world_ir, program.world_layout))


@pytest.mark.parametrize(
    "field,value",
    [("end_at", True), ("end_at", -1), ("max_same_time_actions", 0), ("wake_at", (2, 1))],
)
def test_control_rejects_invalid_time_bounds(field, value):
    lib, ports, source, _ = _inputs()
    program = _compile(lib, ports, source)
    with pytest.raises(C0LawError, match="bounds"):
        replace(program.control_ir, **{field: value})


def test_frontend_still_rejects_hidden_appraisal_input():
    lib, ports, source, _ = _inputs()
    source["appraisal_profiles"][0]["rules"][1]["value"] = {"ref": "scene.parcel.id"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_defer_remains_control_history_not_a_world_occurrence():
    program, assets = _parcel()
    session = program.start(assets)
    tape = session._runtime.occurrence_history()
    session.defer_form("sender")
    assert session.form_control_history()[0].seat == "sender"
    assert session._runtime.occurrence_history() == tape
