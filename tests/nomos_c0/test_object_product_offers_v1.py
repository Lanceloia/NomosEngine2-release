"""Authored role products preserve identity, projection authority and transfer atomicity."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_multi_participant_action_v0 import _compile
from test_nominal_signatures_v1 import assert_symbolic
from test_world_binding_v1 import _layout

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.value_symbols_v1 import C0SymbolicExpression
from nomos_c0.visibility_binding_v1 import bind_visibility
from nomos_c0.world_binding_v1 import bind_world

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _world():
    return tuple(
        read_author_document(ROOT / f"container_transfer_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )


def _states(session):
    return {item.current_state.label: item for item in session.author_object_instances()}


@pytest.mark.parametrize("target", ["Cup A", "Cup B"])
def test_one_authored_law_transfers_between_two_selected_same_kind_owners(target):
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    offers = session.offers("operator")
    assert [offer.label for offer in offers] == [
        "Pour from Bottle into Cup A",
        "Pour from Bottle into Cup B",
    ]
    chosen = next(offer for offer in offers if offer.label.endswith(target))
    before = _states(session)
    assert before["Bottle"].individual.family == before[target].individual.family == "container"
    assert dict(chosen.payload) == {
        "origin": before["Bottle"].individual,
        "destination": before[target].individual,
    }
    outcome = session.submit("operator", chosen.entry, dict(chosen.payload))
    assert isinstance(outcome, K0Published)
    after = _states(session)
    assert after["Bottle"].current_state.units == 1 and after[target].current_state.units == 1
    assert sum(item.current_state.units for item in after.values()) == 2
    assert (
        after["Cup B" if target == "Cup A" else "Cup A"]
        == before["Cup B" if target == "Cup A" else "Cup A"]
    )
    assert after["Hidden vessel"] == before["Hidden vessel"]
    record = outcome.occurrences[0]
    assert record.source == dict(session.program.actions)["transfer"].source_key
    assert {item.name: item.selector for item in record.selected_owners} == dict(chosen.payload)
    assert (
        after[target].current_state.changed
        == after["Bottle"].current_state.changed
        == record.occurrence
    )
    before_reject = session.author_snapshot(), session.author_object_instances()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("operator", chosen.entry, dict(chosen.payload))
    assert (session.author_snapshot(), session.author_object_instances()) == before_reject
    action = dict(session.program.actions)["transfer"]
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key, action.payload_type(actor="operator", **dict(chosen.payload))
            )
        ),
        K0NotAdmitted,
    )
    assert (session.author_snapshot(), session.author_object_instances()) == before_reject


def test_a_third_cup_changes_runtime_options_without_a_new_law_entry_or_source():
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    assets["opening_objects"].append(
        {
            "kind": "container",
            "state": {
                "label": "Cup C",
                "holder": "operator",
                "visible": True,
                "units": 0,
                "capacity": 1,
                "changed": None,
            },
        }
    )
    session = program.start(assets)
    assert len(program.actions) == len(source["actions"]) == len(lib["lawdefs"]) == 1
    assert [offer.label for offer in session.offers("operator")] == [
        "Pour from Bottle into Cup A",
        "Pour from Bottle into Cup B",
        "Pour from Bottle into Cup C",
    ]
    chosen = session.offers("operator")[-1]
    assert isinstance(session.submit("operator", chosen.entry, dict(chosen.payload)), K0Published)
    assert _states(session)["Cup C"].current_state.units == 1


def test_roles_may_also_select_different_explicit_kinds_with_the_same_carrier():
    lib, ports, source, assets = _world()
    lib["object_kinds"].append(
        {
            "symbol": "cup",
            "sort": "EXAMPLE.CUP@1",
            "state": "Container",
            "version": "1",
            "max_instances": 8,
        }
    )
    source["object_kinds"].append({"kind": "cup", "sort": "EXAMPLE.CUP@1"})
    source["actions"][0]["participants"]["destination"] = {"kind": "cup"}
    source["seats"][0]["offers"][0]["for_each_participants"]["destination"]["kind"] = "cup"
    for item in assets["opening_objects"][1:]:
        item["kind"] = "cup"
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("operator")[0]
    values = dict(offer.payload)
    assert values["origin"].family == "container" and values["destination"].family == "cup"
    assert isinstance(session.submit("operator", offer.entry, values), K0Published)
    assert _states(session)["Cup A"].current_state.units == 1


def test_editing_only_the_shared_law_changes_k0_admission_not_the_offered_bindings():
    lib, ports, source, assets = _world()
    original = _compile(lib, ports, source).start(assets)
    original_offer = original.offers("operator")[0]
    assert isinstance(
        original.submit("operator", original_offer.entry, dict(original_offer.payload)), K0Published
    )
    lib["lawdefs"][0]["body"]["value"]["guard"]["require"].append({"reserve": "origin.units > 2"})
    changed = _compile(lib, ports, source).start(assets)
    changed_offer = changed.offers("operator")[0]
    assert changed_offer.label == original_offer.label
    assert (
        dict(changed.program.actions)["transfer"].source_key
        == dict(original.program.actions)["transfer"].source_key
    )
    before = changed.author_snapshot(), changed.author_object_instances()
    assert isinstance(
        changed.submit("operator", changed_offer.entry, dict(changed_offer.payload)), K0NotAdmitted
    )
    assert (changed.author_snapshot(), changed.author_object_instances()) == before


def test_a_broken_destination_invariant_rolls_back_both_selected_owners_and_history():
    lib, ports, source, assets = _world()
    assets["opening_objects"][1]["state"]["units"] = 1
    lib["lawdefs"][0]["body"]["value"]["guard"]["require"][-1] = {"quantity": "origin.units > 0"}
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["transfer"]
    states = _states(session)
    before = session.author_snapshot(), session.author_object_instances()
    with pytest.raises(K0SettlementDefect):
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key,
                action.payload_type(
                    actor="operator",
                    origin=states["Bottle"].individual,
                    destination=states["Cup A"].individual,
                ),
            )
        )
    assert (session.author_snapshot(), session.author_object_instances()) == before


@pytest.mark.parametrize("fault", ["foreign", "same", "hidden", "full", "empty", "unpermitted"])
def test_k0_rechecks_each_current_role_and_rejects_without_partial_write(fault):
    lib, ports, source, assets = _world()
    if fault == "full":
        assets["opening_objects"][1]["state"]["units"] = 1
    if fault == "empty":
        assets["opening_objects"][0]["state"]["units"] = 0
    if fault == "unpermitted":
        assets["opening_objects"][1]["state"]["holder"] = "someone_else"
    program = _compile(lib, ports, source)
    session = program.start(assets)
    states = _states(session)
    origin, destination = states["Bottle"].individual, states["Cup A"].individual
    if fault == "foreign":
        destination = _states(program.start(assets))["Cup A"].individual
    if fault == "same":
        destination = origin
    if fault == "hidden":
        destination = states["Hidden vessel"].individual
    action = dict(program.actions)["transfer"]
    before = session.author_snapshot(), session.author_object_instances()
    outcome = session._runtime.settle(
        _K0InMemoryActionAttempt(
            action.source_key,
            action.payload_type(actor="operator", origin=origin, destination=destination),
        )
    )
    assert isinstance(outcome, K0NotAdmitted)
    assert (session.author_snapshot(), session.author_object_instances()) == before


@pytest.mark.parametrize(
    "fault",
    ["hidden_label", "cross_read", "swapped_ref", "missing_role", "old_label", "ambiguous_ref"],
)
def test_compile_checks_role_local_reads_labels_and_exact_payload_bindings(fault):
    lib, ports, source, _ = _world()
    offer = source["seats"][0]["offers"][0]
    if fault == "hidden_label":
        offer["for_each_participants"]["destination"]["read"].remove("destination.label")
    elif fault == "cross_read":
        offer["for_each_participants"]["origin"]["read"].append("destination.capacity")
    elif fault == "swapped_ref":
        offer["payload"]["destination"] = {"ref": "origin_ref"}
    elif fault == "missing_role":
        del offer["for_each_participants"]["destination"]
    elif fault == "old_label":
        offer["label"] = {"prefix": "Pour ", "object": {"ref": "origin.label"}}
    else:
        offer["payload"]["origin"] = {"ref": "object_ref"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_checked_product_ir_rebinds_in_two_layouts_without_frontend(monkeypatch):
    from test_visibility_binding_v1 import _block_frontend

    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    assert_symbolic(program.visibility_ir)
    _block_frontend(monkeypatch)
    outcomes = []
    for layout in (program.world_layout, alternate):
        session = bind_program(program.program_ir, layout).start(assets)
        offer = session.offers("operator")[1]
        assert isinstance(session.submit("operator", offer.entry, dict(offer.payload)), K0Published)
        outcomes.append({name: item.current_state.units for name, item in _states(session).items()})
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("fault", ["read", "domain", "ref", "role", "label", "budget"])
def test_ir_bind_cannot_swap_or_expand_role_authority(fault):
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    offer = seat.offers[0]
    values = dict(offer.parameters)
    roles = values["objects"]
    if fault == "read":
        values["objects"] = (
            replace(roles[0], read_paths=roles[0].read_paths + ("destination.changed",)),
            *roles[1:],
        )
    elif fault == "domain":
        values["objects"] = (replace(roles[0], kinds=("undeclared",)), *roles[1:])
    elif fault == "ref":
        values["payload"] = {
            **values["payload"],
            "destination": replace(values["payload"]["destination"], operand="origin_ref"),
        }
    elif fault == "role":
        values["objects"] = tuple(reversed(roles))
    elif fault == "label":
        values["labels"] = (values["condition"],)
    else:
        values["max_candidates"] += 1
    changed = replace(offer, parameters=tuple((key, values[key]) for key, _ in offer.parameters))
    forged = replace(ir, seats=(replace(seat, offers=(changed,)),))
    with pytest.raises(C0LawError):
        bind_visibility(forged, bind_world(program.world_ir, program.world_layout))


def _swap_read(value, before, after):
    if type(value) is C0SymbolicExpression:
        return replace(
            value,
            operand=after
            if value.operation == "ref" and value.operand == before
            else _swap_read(value.operand, before, after),
        )
    if isinstance(value, Mapping):
        return {key: _swap_read(child, before, after) for key, child in value.items()}
    if type(value) is tuple:
        return tuple(_swap_read(child, before, after) for child in value)
    return value


@pytest.mark.parametrize("location", ["condition", "visible_when", "labels", "payload"])
def test_ir_bind_rejects_an_expression_borrowing_another_roles_field(location, monkeypatch):
    from test_visibility_binding_v1 import _block_frontend

    lib, ports, source, assets = _world()
    if location == "payload":
        next(row for row in lib["records"] if row["name"] == "TransferAttempt")["fields"].append(
            {"name": "quantity_hint", "type": {"int": [0, 8]}}
        )
        source["seats"][0]["offers"][0]["payload"]["quantity_hint"] = {"ref": "origin.units"}
    program = _compile(lib, ports, source)
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    offer = seat.offers[0]
    values = dict(offer.parameters)
    assert "origin.capacity" not in offer.ports.readable_paths
    assert "destination.capacity" in offer.ports.readable_paths
    forged_condition = _swap_read(values["condition"], "origin.units", "origin.capacity")
    if location == "labels":
        values[location] = (
            replace(
                values["labels"][0],
                operation="if",
                operand={
                    "when": forged_condition,
                    "then": values["labels"][0],
                    "else": values["labels"][0],
                },
            ),
            *values["labels"][1:],
        )
    elif location == "payload":
        values[location] = _swap_read(values[location], "origin.units", "origin.capacity")
    else:
        values[location] = forged_condition
    changed = replace(offer, parameters=tuple((key, values[key]) for key, _ in offer.parameters))
    visibility = replace(ir, seats=(replace(seat, offers=(changed,)),))
    forged = replace(program.program_ir, visibility=visibility)
    assets["opening_objects"][0]["state"]["units"] = 0
    _block_frontend(monkeypatch)
    with pytest.raises(C0LawError, match="exact read authority"):
        bind_program(forged, program.world_layout)
    # The genuine checked graph still rebinds without entering the author frontend.
    genuine = bind_program(program.program_ir, program.world_layout).start(assets)
    assert genuine.offers("operator") == ()


def test_ir_read_check_preserves_lexical_let_and_closed_pure_call(monkeypatch):
    from test_visibility_binding_v1 import _block_frontend

    lib, ports, source, assets = _world()
    lib["pure_definitions"] = [
        {
            "name": "positive",
            "parameters": {"units": "int"},
            "result": "bool",
            "stage": "admission",
            "body": "units > 0",
        }
    ]
    offer = source["seats"][0]["offers"][0]
    offer["when"] = {
        "let": {
            "name": "remaining",
            "value": {"ref": "origin.units"},
            "in": {
                "all": [
                    {"call": {"ref": "positive", "args": {"units": {"ref": "remaining"}}}},
                    {"not": {"eq": [{"ref": "origin_ref"}, {"ref": "destination_ref"}]}},
                    {"lt": [{"ref": "destination.units"}, {"ref": "destination.capacity"}]},
                ]
            },
        }
    }
    program = _compile(lib, ports, source)
    _block_frontend(monkeypatch)
    session = bind_program(program.program_ir, program.world_layout).start(assets)
    assert [item.label for item in session.offers("operator")] == [
        "Pour from Bottle into Cup A",
        "Pour from Bottle into Cup B",
    ]
    chosen = session.offers("operator")[0]
    assert isinstance(session.submit("operator", chosen.entry, dict(chosen.payload)), K0Published)


@pytest.mark.parametrize("budget", ["work", "output"])
def test_candidate_bounds_report_a_fault_instead_of_truncating_or_publishing(budget):
    lib, ports, source, assets = _world()
    ports["offer_provider"]["limit"] = 4
    if budget == "work":
        lib["object_kinds"][0]["max_instances"] = 8
        assets["opening_objects"] += [dict(assets["opening_objects"][3]) for _ in range(4)]
    else:
        for item in assets["opening_objects"]:
            item["state"].update(visible=True, units=1, capacity=8)
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot(), session.author_object_instances()
    assert session.offers("operator") == ()
    assert len(session.offer_faults("operator")) == 1
    assert (session.author_snapshot(), session.author_object_instances()) == before
