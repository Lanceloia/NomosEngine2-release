"""Whole checked Programs, not test-built Profiles, bind and run independently."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from types import SimpleNamespace

import pytest
from nomos_kernel._settlement_outcome_abi import (
    K0NotAdmitted,
    K0Published,
    K0SettlementDefect,
    _K0TemporalPublished,
)
from test_control_binding_v1 import _inputs as _controlled
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend
from test_object_action_formation_v1 import _author_world
from test_visibility_binding_v1 import _block_frontend
from test_visibility_binding_v1 import _parcel as _visible
from test_world_binding_v1 import ROOT, _compile, _documents, _layout, _parcel

from nomos_c0 import event_formation_v2, graph_frontend_v1, program_binding_v1
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.program_ir_v1 import C0ProgramIR


def _checked(lib, ports, source):
    return check_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def _alternate(ir, layout):
    return _layout(SimpleNamespace(world_ir=ir.world, world_layout=layout))


def _block(monkeypatch):
    _block_frontend(monkeypatch)
    for name in (
        "check_owner_graph",
        "_check_graph_declarations",
        "_source",
        "compile_value_program",
    ):
        monkeypatch.setattr(graph_frontend_v1, name, forbid_frontend)
    monkeypatch.setattr(event_formation_v2, "check_event_formations", forbid_frontend)


def _offer(session, seat, entry):
    return next(item for item in session.offers(seat) if item.entry == entry)


def _submit(session, seat, entry):
    offer = _offer(session, seat, entry)
    return session.submit(seat, entry, dict(offer.payload))


def test_frontend_returns_complete_symbolic_program_before_any_profile_assembly(monkeypatch):
    lib, ports, source, _ = _controlled()
    monkeypatch.setattr(program_binding_v1, "_K0InMemoryProfile", forbid_frontend)
    monkeypatch.setattr(program_binding_v1, "bind_program", forbid_frontend)
    ir, layout = _checked(lib, ports, source)
    assert type(ir) is C0ProgramIR
    assert ir.control.world is ir.world is ir.visibility.world
    assert_symbolic(replace(ir, event_formations=None))
    assert_symbolic(ir.event_formations.event_sorts)
    assert_symbolic(ir.event_formations.canonical_projection())
    assert all(item.owner.key.value not in repr(ir) for item in layout.owners.owners)
    with pytest.raises(FrozenInstanceError):
        ir.control = None


def test_production_compile_uses_one_program_backend_and_its_actual_artifacts(monkeypatch):
    lib, ports, source, _ = _controlled()
    calls = []
    original = program_binding_v1.bind_program

    def capture(ir, layout):
        result = original(ir, layout)
        calls.append((ir, layout, result))
        return result

    monkeypatch.setattr(program_binding_v1, "bind_program", capture)
    result = _compile(lib, ports, source)
    assert len(calls) == 1
    ir, layout, actual = calls[0]
    assert result is actual and result.program_ir is ir and result.world_layout is layout
    assert result.profile.owners == tuple(item.owner for item in result.owners)
    assert result.world_ir is ir.world and result.control_ir is ir.control
    assert result.visibility_ir is ir.visibility
    for name, action in result.actions:
        spec = next(item for item in result.profile.source_specs if item.key == action.source_key)
        assert spec.rule.program is action
        assert spec.action_cost_projector.basis == action._cost_basis()
    assert result.formation_plan.semantic_program is ir.event_formations


def test_backend_binds_partitions_against_exactly_one_world(monkeypatch):
    ir, layout = _checked(*_controlled()[:3])
    worlds = []
    original_world = program_binding_v1.bind_world

    def world(*args):
        bound = original_world(*args)
        worlds.append(bound)
        return bound

    monkeypatch.setattr(program_binding_v1, "bind_world", world)
    for name in ("bind_control", "bind_visibility"):
        original = getattr(program_binding_v1, name)

        def partition(ir, actual, original=original):
            assert worlds == [actual]
            return original(ir, actual)

        monkeypatch.setattr(program_binding_v1, name, partition)
    program = bind_program(ir, layout)
    assert len(worlds) == 1 and program.actions is worlds[0].actions


def test_whole_program_two_layouts_two_assets_cost_due_read_offer_and_exact_sources(monkeypatch):
    lib, ports, source, assets = _controlled()
    ir, layout = _checked(lib, ports, source)
    alternate = _alternate(ir, layout)
    lib.clear()
    ports.clear()
    source.clear()
    _block(monkeypatch)
    outcomes = []
    for selected in (layout, alternate):
        program = bind_program(ir, selected)
        assert program.program_ir is ir
        assert all(
            a.payload_type is selected.owners.record_layout.record(t.action.payload)
            for (name, a), t in (
                ((name, a), next(t for t in ir.world.transitions if t.symbol == name))
                for name, a in program.actions
            )
        )
        for actor_name, cost in (("Mira", 4), ("Ada", 7)):
            opening = deepcopy(assets)
            opening["opening"]["sender"]["name"] = actor_name
            session = program.start(opening)
            before = session.author_snapshot()
            assert session.read("sender") == session.read("sender")
            assert session.offers("sender") == session.offers("sender")
            assert session.author_snapshot() == before
            assert "scene.routes" not in dict(session.read("sender").fields)
            assert "receiver.notice" not in dict(session.read("sender").fields)
            assert isinstance(_submit(session, "sender", "dispatch"), K0Published)
            assert session._runtime.action_value_history()[-1].cost == cost
            assert session.continue_form("receiver").time == 3
            arrived = session._runtime.occurrence_history()[-1]
            assert arrived.source == dict(program.due_laws)["arrive"].ports.source_key
            formed = session.formation_trace()
            assert formed[-1].occurrence == arrived.occurrence
            assert formed[-1].predecessor == session._runtime.occurrence_history()[0].occurrence
            assert formed[-1].scheduled_at == 2
            assert isinstance(_submit(session, "receiver", "confirm_alt"), K0Published)
            assert session._runtime.action_value_history()[-1].cost == 3
            assert session.form_frame("sender").outcome == "delivered"
            tape = session._runtime.occurrence_history()
            assert tape[-1].source == dict(program.actions)["confirm_alt"].source_key
            with pytest.raises(C0BindingError, match="finished"):
                session.continue_form("sender")
            assert session._runtime.occurrence_history() == tape
            outcomes.append(
                (
                    actor_name,
                    cost,
                    tuple(
                        (name, asdict(state)) for name, state in session.author_snapshot().owners
                    ),
                    tuple((r.family, r.occurrence) for r in tape),
                )
            )
    assert outcomes[:2] == outcomes[2:]
    assert layout.owners.record_layout.record(
        "Sender"
    ) is not alternate.owners.record_layout.record("Sender")


def test_same_program_object_formation_schedule_and_control_keep_one_actual_basis(monkeypatch):
    lib, ports, source, assets = _author_world()
    ir, layout = _checked(lib, ports, source)
    alternate = _alternate(ir, layout)
    _block(monkeypatch)
    results = []
    for selected in (layout, alternate):
        program = bind_program(ir, selected)
        session = program.start(assets)
        assert program.object_plan.ports[0].family == "tool"
        published = _submit(session, "sender", "dispatch")
        assert isinstance(published, K0Published)
        objects = session.author_object_instances()
        assert len(objects) == 2 and objects[0].formed_by is None
        assert objects[1].formed_by == published.occurrences[0].occurrence
        assert objects[0].owner != objects[1].owner
        assert session._runtime._pending_due[0].key.formation == objects[1].formed_by
        session.defer_form("sender")
        session.defer_form("receiver")
        assert session.continue_form("receiver").time == 2
        assert session.formation_trace()[-1].predecessor == objects[1].formed_by
        results.append(tuple(asdict(item.current_state) for item in objects))
    assert results[0] == results[1]


def test_whole_program_generic_law_targets_opening_and_new_subsort_objects(monkeypatch):
    lib, ports, source = _documents("object_target_v1")
    assets = read_author_document(ROOT / "object_target_v1.assets.yaml").to_data()
    ir, layout = _checked(lib, ports, source)
    alternate = _alternate(ir, layout)
    _block(monkeypatch)
    for selected in (layout, alternate):
        program = bind_program(ir, selected)
        session = program.start(assets)
        assert isinstance(_submit(session, "actor", "make"), K0Published)
        objects = session.author_object_instances()
        assert {item.individual.family for item in objects} == {"tool", "fine_tool"}
        for item in objects:
            if not item.current_state.visible:
                assert not any(
                    o.entry == "inspect" and dict(o.payload)["target"] == item.individual
                    for o in session.offers("actor")
                )
                assert session._runtime.read_individual(item.individual).view.ready
                continue
            offer = next(
                o
                for o in session.offers("actor")
                if o.entry == "inspect" and dict(o.payload)["target"] == item.individual
            )
            result = session.submit("actor", "inspect", dict(offer.payload))
            assert isinstance(result, K0Published)
            actual = result.occurrences[0]
            assert actual.source == dict(program.actions)["inspect"].source_key
            assert actual.selected_owners[0].owner == item.owner
            assert not session._runtime.read_individual(item.individual).view.ready
        assert not any(o.entry == "inspect" for o in session.offers("actor"))


def test_wrong_event_claim_is_rejected_before_any_backend_profile(monkeypatch):
    lib, ports, source, _ = _controlled()
    source["ontology"]["formations"][0]["trigger"] = "confirm"
    monkeypatch.setattr(program_binding_v1, "bind_program", forbid_frontend)
    monkeypatch.setattr(program_binding_v1, "_K0InMemoryProfile", forbid_frontend)
    with pytest.raises(C0LawError, match="world formation"):
        _compile(lib, ports, source)


def test_rebound_autonomous_control_stops_without_extra_advance(monkeypatch):
    lib, ports, source, assets = _controlled()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    ir, layout = _checked(lib, ports, source)
    alternate = _alternate(ir, layout)
    _block(monkeypatch)
    for selected in (layout, alternate):
        program = bind_program(ir, selected)
        session = program.start(assets)
        assert isinstance(_submit(session, "sender", "dispatch"), K0Published)
        frame = session.continue_form("sender")
        assert frame.finished and frame.outcome == "delivered" and frame.time == 3
        assert session.appraisal_history()[0].proposal.chosen.entry == "confirm_alt"
        assert (
            session._runtime.occurrence_history()[-1].source
            == dict(program.actions)["confirm_alt"].source_key
        )


@pytest.mark.parametrize("mode", ["manual", "event_jump_stop"])
def test_rebound_existing_control_modes_keep_defer_separate_from_world_occurrences(mode):
    lib, ports, source, assets = _visible()
    if mode == "event_jump_stop":
        source["game_form"] = {
            "mode": mode,
            "seats": ["sender", "receiver"],
            "end_at": 8,
            "wake_at": [],
        }
    ir, layout = _checked(lib, ports, source)
    session = bind_program(ir, _alternate(ir, layout)).start(assets)
    if mode == "event_jump_stop":
        before = session._runtime.occurrence_history()
        session.defer_form("sender")
        assert session.form_control_history()[-1].choice == "defer"
        assert session._runtime.occurrence_history() == before
    else:
        assert isinstance(_submit(session, "sender", "dispatch"), K0Published)
        assert session.program.game_form is None


def test_same_checked_world_runs_with_two_authored_control_forms(monkeypatch):
    lib, ports, source = _documents("parcel_delivery_v0")
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    timed_ir, layout = _checked(lib, ports, source)
    source["game_form"] = {"mode": "manual"}
    manual_ir, _ = _checked(lib, ports, source)
    assert manual_ir.world == timed_ir.world
    manual_ir = replace(
        manual_ir,
        world=timed_ir.world,
        control=replace(manual_ir.control, world=timed_ir.world),
        visibility=replace(manual_ir.visibility, world=timed_ir.world),
    )
    _block(monkeypatch)
    manual = bind_program(manual_ir, layout).start(assets)
    timed = bind_program(timed_ir, layout).start(assets)
    assert manual.program.world_ir is timed.program.world_ir
    first = _submit(manual, "sender", "dispatch")
    assert first == _submit(timed, "sender", "dispatch")
    before = timed._runtime.occurrence_history()
    timed.defer_form("sender")
    assert timed.form_control_history()[-1].choice == "defer"
    assert timed._runtime.occurrence_history() == before
    current = timed.continue_form("receiver")
    assert current.time == 0 and current.ready_seats == ("receiver",)
    timed.defer_form("receiver")
    assert timed._runtime.occurrence_history() == before
    advanced = manual.advance("receiver", 3)
    assert isinstance(advanced, _K0TemporalPublished)
    assert advanced.interval.t1.ordinal == 2
    assert timed.continue_form("receiver").time == 2
    assert manual.author_snapshot() == replace(timed.author_snapshot(), form_choices=())
    assert manual._runtime.occurrence_history() == timed._runtime.occurrence_history()
    assert _submit(manual, "receiver", "confirm") == _submit(timed, "receiver", "confirm")
    assert manual.program.game_form is None
    assert not manual.form_control_history()


@pytest.mark.parametrize("fault", ["world", "visibility_world", "entries", "presentation"])
def test_program_rejects_mismatched_partitions_before_backend_assembly(fault, monkeypatch):
    lib, ports, source, _ = _controlled()
    ir, _ = _checked(lib, ports, source)
    monkeypatch.setattr(program_binding_v1, "_K0InMemoryProfile", forbid_frontend)
    if fault == "world":
        with pytest.raises(C0LawError, match="share one checked world"):
            replace(ir, world=replace(ir.world))
    elif fault == "visibility_world":
        with pytest.raises(C0LawError, match="share one checked world"):
            replace(ir, visibility=replace(ir.visibility, world=replace(ir.world)))
    elif fault == "entries":
        seat = ir.control.seats[-1]
        control = replace(
            ir.control, seats=ir.control.seats[:-1] + (replace(seat, entries=("confirm",)),)
        )
        with pytest.raises(C0LawError, match="disagree on seats or entries"):
            replace(ir, control=control)
    else:
        seat = ir.visibility.seats[0]
        from nomos_c0.visibility_ir_v1 import C0SeatPresentation

        presentation = C0SeatPresentation(
            "Sender",
            tuple((path, path) for path in seat.read_paths),
            "OK",
            "No",
            "Empty",
            finish_on_action=(("dispatch", "foreign", "Done"),),
        )
        visibility = replace(
            ir.visibility,
            seats=(replace(seat, presentation=presentation),) + ir.visibility.seats[1:],
        )
        with pytest.raises(C0LawError, match="undeclared world stop"):
            replace(ir, visibility=visibility)


def test_bound_program_rejects_foreign_layout_and_invalid_opening():
    lib, ports, source, assets = _controlled()
    ir, layout = _checked(lib, ports, source)
    other, other_layout = _checked(lib, ports, source)
    with pytest.raises(C0LawError, match="selected checked world"):
        bind_program(ir, other_layout)
    program = bind_program(ir, layout)
    invalid = deepcopy(assets)
    invalid["opening"]["scene"]["parcel"]["id"] = "P-2"
    with pytest.raises(C0BindingError, match="opening"):
        program.start(invalid)
    assert other.world is not ir.world


def test_rebound_program_finite_rejection_keeps_world_cost_and_occurrence_history():
    lib, ports, source, assets = _controlled()
    source["game_form"]["seats"][0]["costs"]["dispatch"] = 0
    ir, layout = _checked(lib, ports, source)
    session = bind_program(ir, _alternate(ir, layout)).start(assets)
    before = session.author_snapshot(), session._runtime.action_value_state()
    assert isinstance(_submit(session, "sender", "dispatch"), K0NotAdmitted)
    assert (session.author_snapshot(), session._runtime.action_value_state()) == before
    assert session._runtime.action_value_history() == ()


def test_rebound_program_due_failure_remains_atomic_and_fatal():
    original, assets = _parcel(false_law="event.arrive")
    program = bind_program(original.program_ir, _layout(original))
    session = program.start(assets)
    assert isinstance(_submit(session, "sender", "dispatch"), K0Published)
    session.defer_form("sender")
    session.defer_form("receiver")
    before = session.author_snapshot(), session._runtime._pending_due
    with pytest.raises(K0SettlementDefect):
        session.continue_form("receiver")
    assert (session.author_snapshot(), session._runtime._pending_due) == before
    with pytest.raises(K0SettlementDefect):
        session.continue_form("receiver")
