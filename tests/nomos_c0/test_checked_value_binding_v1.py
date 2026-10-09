"""World value IR keeps nominal authority and uses the original evaluator after Bind."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend

from nomos_c0 import composable_value_v1 as values
from nomos_c0 import graph_frontend_v1 as graph_module
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.checked_value_binding_v1 import C0ValueBackend, _WorldValueBuilder
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.examples.parcel_delivery_v0 import ROOT
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _parcel(false_law=None):
    checked = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text())
    graph = check_graph_ports((ROOT / "parcel_delivery_v0.ports.json").read_text(), checked)
    source = json.loads((ROOT / "parcel_delivery_v0.source.json").read_text())
    if false_law is not None:
        law = next(item for item in source["lawdefs"] if item["name"] == false_law)
        value = law["body"]["value" if law["family"] == "action" else "law"]
        value["guard"] = {"all": [value["guard"], False]}
    return checked, graph, compile_owner_graph(graph, source)


def test_production_world_values_cover_actions_causal_events_and_due_without_backend_objects():
    checked, _, program = _parcel()
    expected = (
        {("submit", name): value.value for name, value in program.actions}
        | {("after_occurrence", name): value.value for name, value in program.events}
        | {("due", name): value.value for name, value in program.due_laws}
    )
    assert len(expected) == len(program.world_values) == 6
    backend = C0ValueBackend(checked.record_layout)
    for item in program.world_values:
        assert_symbolic(item)
        assert item.body.signatures is checked.signatures
        actual = expected[item.formation, item.symbol]
        rebound = backend.bind(item.body)
        assert actual._tree == rebound._tree
        assert actual._ports == rebound._ports
        assert actual._ports is not rebound._ports
        assert rebound._ports is rebound._ports
        assert rebound._admission_ports is rebound._admission_ports
        assert actual.guard_ir == rebound.guard_ir
    notice = next(item for item in program.world_values if item.symbol == "notice")
    assert dict(notice.body.value.ports.roots)["trigger"].kind == "intrinsic"
    due = next(item for item in program.world_values if item.symbol == "arrive")
    assert dict(due.body.value.ports.roots)["due"].symbol == "due"
    assert dict(due.body.value.ports.roots)["time"].symbol == "time"


def test_bound_world_values_reach_real_k0_with_exact_refs_and_no_runtime_frontend(monkeypatch):
    _, _, program = _parcel()
    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)
    monkeypatch.setattr(graph_module, "compile_value_program", forbid_frontend)
    assets = json.loads((ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    before = session._runtime.occurrence_history()
    departure = next(item for item in before if item.source.value == "c0.parcel.depart")
    notice = next(item for item in before if item.source.value == "c0.parcel.notice")
    actor = next(item.owner for item in program.owners if item.symbol == "receiver")
    receiver = session._runtime.read_owner(actor.key).view
    assert receiver.notice.departure == departure.occurrence
    assert receiver.notice.notification == notice.occurrence
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("sender")
    assert session.time == 2
    arrival = next(
        item
        for item in session._runtime.occurrence_history()
        if item.source.value == "c0.parcel.arrive.due"
    )
    offer = session.form_frame("receiver").offers[0]
    assert isinstance(session.submit("receiver", offer.entry, dict(offer.payload)), K0Published)
    receiver = session._runtime.read_owner(actor.key).view
    assert receiver.receipt.arrival == arrival.occurrence
    assert receiver.receipt.action == session._runtime.occurrence_history()[-1].occurrence


@pytest.mark.parametrize("formation", ["submit", "after_occurrence", "due"])
def test_production_rebinding_preserves_distinct_formation_failure_and_rollback(formation):
    law = {
        "submit": "action.dispatch",
        "after_occurrence": "event.depart",
        "due": "event.arrive",
    }[formation]
    _, _, program = _parcel(law)
    session = program.start(json.loads((ROOT / "parcel_delivery_v0.a.assets.json").read_text()))
    offer = session.form_frame("sender").offers[0]
    before = session.author_snapshot()
    result = session.submit("sender", offer.entry, dict(offer.payload))
    if formation == "submit":
        assert isinstance(result, K0NotAdmitted)
        assert session.author_snapshot() == before
        return
    assert isinstance(result, K0Published)
    if formation == "after_occurrence":
        assert [item.source.value for item in session._runtime.occurrence_history()] == [
            "c0.parcel.dispatch"
        ]
        states = dict(session.author_snapshot().owners)
        assert states["scene"].parcel.status == "home"
        assert states["receiver"].notice is None
        return
    session.defer_form("sender")
    session.defer_form("receiver")
    before = session.author_snapshot()
    pending = session._runtime._pending_due
    with pytest.raises(K0SettlementDefect):
        session.continue_form("sender")
    after = session.author_snapshot()
    assert (after.owners, after.occurrences, after.time) == (
        before.owners,
        before.occurrences,
        before.time,
    )
    assert session._runtime._pending_due == pending
    with pytest.raises(K0SettlementDefect):
        session.continue_form("sender")


def _neutral_lib():
    row_fields = [
        {"name": "key", "type": {"str": [1, 8]}},
        {"name": "score", "type": {"int": [0, 99]}},
    ]
    state_fields = [
        {"name": "stock", "type": {"int": [0, 99]}},
        {"name": "received", "type": {"int": [0, 99]}},
        {"name": "active", "type": "bool"},
        {"name": "maybe_cost", "type": {"optional": {"int": [0, 99]}}},
        {"name": "items", "type": {"tuple": {"item": "Row", "max": 3}}},
        {"name": "secret", "type": {"int": [0, 99]}},
    ]
    return check_nominal_lib(
        {
            "schema": "c0.nominal_lib.v1",
            "records": [
                {"name": "Row", "fields": row_fields, "invariant": None},
                {"name": "State", "fields": state_fields, "invariant": None},
            ],
            "owners": [
                {
                    "symbol": "state",
                    "key": "c0.values.state",
                    "version": "v1",
                    "state": "State",
                    "identity_field": None,
                    "seat_read": [],
                    "write": "replace_one",
                }
            ],
            "pure_definitions": [
                {
                    "name": "positive",
                    "parameters": {"items": {"tuple": "Row"}},
                    "result": "int",
                    "stage": "admission",
                    "body": {
                        "count_matching": {
                            "collection": {"ref": "items"},
                            "as": "row",
                            "where": {"lt": [0, {"ref": "row.score"}]},
                        }
                    },
                }
            ],
        }
    )


def _value(checked):
    state, row = checked.record("State"), checked.record("Row")
    names = frozenset({"stock", "received", "active", "maybe_cost", "items", "secret"})
    public = names - {"secret"}
    ports = C0ValuePorts(
        roots={"state": state},
        readable_paths=frozenset(f"state.{name}" for name in names),
        admission_readable_paths=frozenset(f"state.{name}" for name in public),
        readable_fields={state: names, row: frozenset({"key", "score"})},
        admission_readable_fields={state: public, row: frozenset({"key", "score"})},
        writable_fields={state: frozenset({"stock", "received"}), row: frozenset({"key", "score"})},
        writable_paths=frozenset({"state.stock", "state.received"}),
        record_types={"Row": row},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={"state.items": "key"},
        outputs={
            "stock": int,
            "received": int,
            "chosen_score": int,
            "positive": int,
            "secret": int,
            "stamp": K0OccurrenceRef,
            "made": row,
            "roll": int,
        },
        pure_definitions=checked.pure_definitions,
    )
    body = {
        "schema": "c0.value.v1",
        "bindings": [
            {
                "name": "chosen",
                "collection": "state.items",
                "key": "key",
                "value": {"const": "r"},
                "required": False,
            },
            {
                "name": "cost",
                "stage": "admission",
                "let": {
                    "if": {
                        "when": "state.maybe_cost is not None",
                        "then": "state.maybe_cost",
                        "else": 0,
                    }
                },
            },
            {"name": "stamp", "stage": "effect", "let": {"ref": "occurrence"}},
        ],
        "guard": True,
        "effects": [
            {
                "move": {
                    "transfer": {"from": "state.stock", "to": "state.received"},
                    "amount": "state.maybe_cost",
                    "floor": 0,
                    "capacity": 20,
                    "when": "state.active and state.maybe_cost is not None",
                }
            }
        ],
        "outputs": {
            "chosen_score": {
                "if": {"when": "chosen is not None", "then": "chosen.score", "else": 0}
            },
            "positive": {"call": {"ref": "positive", "args": {"items": {"ref": "state.items"}}}},
            "secret": {"ref": "state.secret"},
            "stamp": {"ref": "stamp"},
            "made": {
                "record": {
                    "type": "Row",
                    "fields": {"key": {"const": "made"}, "score": {"ref": "cost"}},
                }
            },
            "roll": {"die_roll": {"seed": {"ref": "state.secret"}, "sides": 6}},
        },
    }
    return body, ports


@pytest.mark.parametrize("active", [False, True])
def test_one_symbolic_value_keeps_lookup_let_pure_effects_and_dice_in_two_layouts(
    monkeypatch, active
):
    checked = _neutral_lib()
    body, ports = _value(checked)
    compiled = compile_value_program(
        json.dumps(body),
        ports,
        state_outputs={"state.stock": "stock", "state.received": "received"},
    )
    ir = C0ValueBackend(checked.record_layout).capture(compiled)
    assert_symbolic(ir)
    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)
    results = []
    for layout in (checked.record_layout, bind_nominal_records(checked.signatures)):
        row = layout.record("Row")
        state = layout.record("State")(
            5, 2, active, 2 if active else None, (row("r", 9), row("z", 1)), 19
        )
        value = C0ValueBackend(layout).bind(ir)
        result = value.evaluate({"state": state}, occurrence=K0OccurrenceRef(7))
        assert result["stamp"] == K0OccurrenceRef(7)
        assert result["chosen_score"] == 9
        assert result["positive"] == 2
        assert result["secret"] == 19
        assert type(result["made"]) is row
        assert result["made"].score == (2 if active else 0)
        assert (result["stock"], result["received"]) == ((3, 4) if active else (5, 2))
        results.append({name: output for name, output in result.items() if name != "made"})
        assert value.effects[0].checks is value.guard_ir.expression["all"][1]["all"][0]
        assert dict(value.effects[0].results)["stock"] is value._tree["outputs"]["stock"]
    assert results[0] == results[1]


def test_binding_keeps_conditional_short_circuit_and_false_guard_origin():
    checked = _neutral_lib()
    body, ports = _value(checked)
    body["effects"][0]["move"].update(amount={"ceil_div": [1, 0]}, when=False)
    original = compile_value_program(
        json.dumps(body),
        ports,
        state_outputs={"state.stock": "stock", "state.received": "received"},
    )
    value = C0ValueBackend(checked.record_layout).bind(
        C0ValueBackend(checked.record_layout).capture(original)
    )
    assert (
        value.evaluate(
            {"state": checked.record("State")(0, 0, False, None, (), 1)},
            occurrence=K0OccurrenceRef(7),
        )["stock"]
        == 0
    )
    body, ports = _value(checked)
    original = compile_value_program(
        json.dumps(body),
        ports,
        state_outputs={"state.stock": "stock", "state.received": "received"},
    )
    value = C0ValueBackend(checked.record_layout).bind(
        C0ValueBackend(checked.record_layout).capture(original)
    )
    roots = {"state": checked.record("State")(0, 2, True, 2, (), 1)}
    assert value.false_guard_clauses(roots) == original.false_guard_clauses(roots)
    assert value.false_guard_clauses(roots)[0].path == "effects.move.sufficient"


@pytest.mark.parametrize(
    "guard",
    [
        "state.secret == 1",
        {"not_none": {"ref": "occurrence"}},
        {"eq": [{"die_roll": {"seed": 1, "sides": 6}}, 1]},
    ],
)
def test_world_symbolization_does_not_enlarge_admission_stage_or_authority(guard):
    checked = _neutral_lib()
    body, ports = _value(checked)
    body["guard"] = guard
    with pytest.raises(C0LawError):
        compile_value_program(
            json.dumps(body),
            ports,
            state_outputs={"state.stock": "stock", "state.received": "received"},
        )


def test_backend_rejects_foreign_signature_weakened_layout_and_native_self_report():
    checked, _, program = _parcel()
    ir = program.world_values[0].body
    with pytest.raises(C0LawError, match="selected signatures"):
        C0ValueBackend(
            bind_nominal_records(
                check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text()).signatures
            )
        ).bind(ir)
    with pytest.raises(C0LawError, match="generated nominal layout"):
        C0ValueBackend(object())
    with pytest.raises(TypeError, match="read-only"):
        checked.record("Parcel").validate_for_k0 = lambda value: None
    C0ValueBackend(checked.record_layout).bind(ir)


def test_backend_rejects_unknown_intrinsic_and_undeclared_native_record():
    checked, _, program = _parcel()
    item = next(item for item in program.world_values if item.symbol == "notice")
    ports = item.body.value.ports
    roots = tuple(
        (name, replace(t, symbol="foreign") if name == "trigger" else t) for name, t in ports.roots
    )
    malformed = replace(
        item.body, value=replace(item.body.value, ports=replace(ports, roots=roots))
    )
    with pytest.raises(C0LawError, match="no backend binding"):
        C0ValueBackend(checked.record_layout).bind(malformed)
    foreign = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text())
    with pytest.raises(C0LawError, match="no nominal declaration"):
        C0ValueBackend(foreign.record_layout).capture(dict(program.actions)["dispatch"].value)


def test_bound_value_rejects_original_layout_root_in_new_carrier_layout():
    checked, _, program = _parcel()
    ir = program.world_values[0].body
    second = C0ValueBackend(bind_nominal_records(checked.signatures)).bind(ir)
    roots = {
        "scene": checked.record("Scene")(
            checked.record("Parcel")("P", "dock", "home", None, None), (), "none"
        ),
        "actor": checked.record("Sender")("Mira", None),
        "payload": checked.record("Attempt")("Mira", "P", "dock"),
    }
    with pytest.raises(C0ValueStateError, match="foreign nominal root"):
        second.admits(roots)


def test_builder_rejects_duplicate_formation_and_missing_backend():
    checked, _, program = _parcel()
    builder = _WorldValueBuilder(C0ValueBackend(checked.record_layout))
    action = dict(program.actions)["dispatch"]
    builder.transition("dispatch", action)
    with pytest.raises(C0LawError, match="identities alias"):
        builder.transition("dispatch", action)
    with pytest.raises(C0LawError, match="unsupported backend"):
        _WorldValueBuilder(None)


def test_generated_range_and_invariant_validation_still_run_after_rebinding():
    checked, _, program = _parcel()
    layout = bind_nominal_records(checked.signatures)
    dispatch = C0ValueBackend(layout).bind(program.world_values[0].body)
    with pytest.raises(K0ProfileError):
        layout.record("Route")("dock", 0).validate_for_k0()
    roots = {
        "scene": layout.record("Scene")(
            layout.record("Parcel")("P", "dock", "home", None, None),
            (layout.record("Route")("dock", 2),),
            "none",
        ),
        "actor": layout.record("Sender")("Mira", None),
        "payload": layout.record("Attempt")("Mira", "P", "dock"),
    }
    assert dispatch.evaluate_admission_outputs(roots) == {"delay": 2}
    assert dispatch.evaluate(roots, occurrence=K0OccurrenceRef(9))["sent_ref"] == K0OccurrenceRef(9)
