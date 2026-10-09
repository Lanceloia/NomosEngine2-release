"""Checked neutral opening Objects and real shared subsequent Action settlement."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemorySession
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.composable_value_v1 import C0ValueStateError, _eval
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.replayable_die_v1 import next_seed, roll
from nomos_c0.value_symbols_v1 import C0SymbolicExpression

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _tone():
    result = {"const": "blue"}
    for value, color in reversed(((1, "red"), (2, "green"), (3, "clear"))):
        result = {
            "if": {
                "when": {"eq": [{"ref": "choice"}, {"const": value}]},
                "then": {"const": color},
                "else": result,
            }
        }
    return result


def _world(seed=42):
    lib, ports, source, assets = (
        read_author_document(ROOT / f"object_target_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )
    tool = next(item for item in lib["records"] if item["name"] == "Tool")
    tool["fields"].extend(
        [
            {"name": "tone", "type": {"enum": ["red", "green", "clear", "blue"]}},
            {"name": "sides", "type": {"int": [2, 1000]}},
            {"name": "holder", "type": {"str": [1, 64]}},
            {"name": "site", "type": {"str": [1, 64]}},
        ]
    )
    # Keep only the shared target Action; no formation or new world rule is involved.
    ports["actions"] = [item for item in ports["actions"] if item["symbol"] == "inspect"]
    source["actions"] = [item for item in source["actions"] if item["name"] == "inspect"]
    source["seats"][0]["entries"] = ["inspect"]
    source["seats"][0]["offers"] = [source["seats"][0]["offers"][1]]
    source["lawdefs"] = []
    ports["opening_constructions"] = [
        {
            "symbol": "prepare_tool",
            "kind": "tool",
            "read": ["sides"],
            "fields": ["tone", "ready"],
            "construct": [],
        }
    ]
    source["opening_constructions"] = [
        {
            "kind": "tool",
            "using": "prepare_tool",
            "seed": "opening_tools",
            "bindings": [{"name": "choice", "draw": {"ref": "sides"}}],
            "outputs": {"tone": _tone(), "ready": {"const": True}},
        }
    ]
    assets["opening_seeds"] = {"opening_tools": seed}
    assets["opening_objects"] = [
        {
            "kind": "tool",
            "state": {
                "label": "same",
                "visible": True,
                "sides": 4,
                "holder": holder,
                "site": site,
            },
        }
        for holder, site in (("Mira", "bench"), ("Otto", "shelf"))
    ]
    return lib, ports, source, assets


def _compile(lib, ports, source):
    checked = check_nominal_lib(lib)
    return compile_owner_graph(check_graph_ports(ports, checked), source)


def _receipt(seed=42):
    lib, ports, source, assets = _world(seed)
    session = _compile(lib, ports, source).start(assets)
    return session.author_opening_construction()


def _chain(receipt):
    return tuple(
        (slot.slot, slot.kind, slot.input_seed, slot.output_seed, slot.draws, slot.state)
        for slot in receipt.slots
    )


def test_same_kind_objects_get_complete_opening_then_shared_real_action_per_owner():
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    original = deepcopy(assets)
    session = program.start(assets)
    receipt = session.author_opening_construction()
    objects = session.author_object_instances()
    assert len(objects) == 2
    assert objects[0].owner != objects[1].owner
    assert objects[0].individual != objects[1].individual
    assert all(item.formed_by is None for item in objects)
    assert session._runtime.occurrence_history() == ()
    assert [(item.current_state.holder, item.current_state.site) for item in objects] == [
        ("Mira", "bench"),
        ("Otto", "shelf"),
    ]
    assert [item.current_state.label for item in objects] == ["same", "same"]
    assert [item.current_state.tone for item in objects] == ["clear", "red"]
    assert tuple(slot.slot for slot in receipt.slots) == (0, 1)
    assert tuple(slot.individual for slot in receipt.slots) == tuple(
        item.individual for item in objects
    )
    assert tuple(slot.owner for slot in receipt.slots) == tuple(item.owner for item in objects)
    assert all(
        slot.state == obj.current_state for slot, obj in zip(receipt.slots, objects, strict=True)
    )
    for index, obj in enumerate(objects):
        offer = next(
            item
            for item in session.offers("actor")
            if dict(item.payload)["target"] == obj.individual
        )
        assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)
        current = session.author_object_instances()
        assert [item.current_state.ready for item in current] == (
            [False, True] if index == 0 else [False, False]
        )
        assert tuple(item.owner for item in current) == tuple(item.owner for item in objects)
    assert len(session._runtime.occurrence_history()) == 2
    assert session.author_opening_construction() is receipt
    assert all(slot.state.ready for slot in receipt.slots)
    assert assets == original


def test_seed_replay_and_different_seed_and_actual_rule_edit():
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    first, second = (program.start(assets).author_opening_construction() for _ in range(2))
    assert _chain(first) == _chain(second)
    assert first.slots[0].individual != second.slots[0].individual
    assert first.slots[0].draws[0].result == roll(42, 4)
    assert first.slots[1].input_seed == next_seed(42)
    assert first.final_seeds == (("opening_tools", next_seed(next_seed(42))),)
    assets["opening_seeds"]["opening_tools"] = 43
    changed = program.start(assets).author_opening_construction()
    assert [slot.state.tone for slot in changed.slots] == ["green", "red"]
    assert first.input_json != changed.input_json
    source["opening_constructions"][0]["outputs"]["tone"] = {"const": "blue"}
    edited = _compile(lib, ports, source).start(assets).author_opening_construction()
    assert all(slot.state.tone == "blue" for slot in edited.slots)
    assert edited.source_digest != first.source_digest
    assert edited.slots[0].rule_digest != first.slots[0].rule_digest


def test_readback_and_menu_never_consume_seed_or_expose_receipt():
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    receipt = session.author_opening_construction()
    for _ in range(5):
        assert session.author_opening_construction() is receipt
        assert len(session.offers("actor")) == 2
        assert session._runtime.occurrence_history() == ()
        assert "opening_tools" not in repr(session.read("actor"))
    with pytest.raises(FrozenInstanceError):
        receipt.algorithm = "fake"
    with pytest.raises(TypeError):
        receipt.plans[0].outputs[0][1].operand["fake"] = 0


def test_compile_is_immutable_symbolic_and_start_does_not_reparse(monkeypatch):
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    plan = program.program_ir.opening_constructions[0]
    assert type(plan.outputs[0][1]) is C0SymbolicExpression
    assert plan.outputs[0][1].stage == "construction"
    assert not hasattr(plan, "assets")
    source["opening_constructions"][0]["outputs"]["tone"] = {"const": "foreign"}

    def forbidden(*args, **kwargs):
        raise AssertionError("Run must not recompile construction AST")

    import nomos_c0.composable_value_v1 as values

    monkeypatch.setattr(values, "_compile_expression", forbidden)
    rebound = bind_program(program.program_ir, program.world_layout)
    assert _chain(rebound.start(assets).author_opening_construction()) == _chain(
        program.start(assets).author_opening_construction()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_type",
        "undeclared_output",
        "duplicate_selection",
        "undeclared_read",
        "occurrence",
        "individual",
        "live_actor",
        "nested_die",
        "hidden_seed_advance",
        "wrong_sides_type",
        "shadow_seed",
        "unknown_port",
        "wrong_kind",
        "effect_call",
        "hidden_die_call",
    ],
)
def test_compile_rejects_bad_types_fields_refs_and_phase_crossing(fault):
    lib, ports, source, _ = _world()
    rule = source["opening_constructions"][0]
    if fault == "wrong_type":
        rule["outputs"]["ready"] = {"const": 1}
    elif fault == "undeclared_output":
        rule["outputs"]["holder"] = {"const": "Other"}
    elif fault == "duplicate_selection":
        source["opening_constructions"].append(deepcopy(rule))
    elif fault == "undeclared_read":
        rule["outputs"]["tone"] = {"ref": "label"}
    elif fault in {"occurrence", "individual", "live_actor"}:
        rule["outputs"]["tone"] = {"ref": {"live_actor": "actor.name"}.get(fault, fault)}
    elif fault == "nested_die":
        rule["outputs"]["ready"] = {
            "eq": [
                {"die_roll": {"seed": {"ref": "seed"}, "sides": {"const": 4}}},
                {"const": 1},
            ]
        }
    elif fault == "hidden_seed_advance":
        rule["bindings"].append({"name": "advanced", "value": {"die_next_seed": {"ref": "seed"}}})
    elif fault == "wrong_sides_type":
        rule["bindings"][0]["draw"] = {"const": True}
    elif fault == "shadow_seed":
        rule["bindings"][0]["name"] = "seed"
    elif fault == "unknown_port":
        rule["using"] = "missing"
    elif fault == "wrong_kind":
        rule["kind"] = "fine_tool"
    else:
        lib["pure_definitions"] = [
            {
                "name": "bad",
                "parameters": {},
                "result": "int",
                "stage": "effect" if fault == "effect_call" else "admission",
                "body": {"die_roll": {"seed": {"const": 42}, "sides": {"const": 4}}},
            }
        ]
        rule["bindings"] = [{"name": "choice", "value": {"call": {"ref": "bad", "args": {}}}}]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("fault", ["unknown_field", "duplicate_field", "ref_input", "ref_output"])
def test_ports_reject_field_and_reference_permissions(fault):
    lib, ports, source, _ = _world()
    port = ports["opening_constructions"][0]
    if fault == "unknown_field":
        port["fields"].append("not_a_field")
    elif fault == "duplicate_field":
        port["fields"].append("ready")
    else:
        tool = next(item for item in lib["records"] if item["name"] == "Tool")
        tool["fields"].append({"name": "identity", "type": {"optional": "individual_ref"}})
        port["read" if fault == "ref_input" else "fields"].append("identity")
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    [
        "second_draw",
        "second_nominal",
        "second_invariant",
        "literal_conflict",
        "missing_literal",
        "capacity",
        "seed_bool",
        "seed_missing",
        "seed_extra",
        "ref_literal",
        "fake_receipt",
        "fake_generated",
    ],
)
def test_failed_construction_never_calls_create_or_changes_inputs(monkeypatch, fault):
    lib, ports, source, assets = _world()
    if fault == "second_draw":
        assets["opening_objects"][1]["state"]["sides"] = 1
    elif fault == "second_nominal":
        assets["opening_objects"][1]["state"]["holder"] = "x" * 65
    elif fault == "second_invariant":
        tool = next(item for item in lib["records"] if item["name"] == "Tool")
        tool["invariant"] = {"eq": [{"ref": "state.sides"}, {"const": 4}]}
        assets["opening_objects"][1]["state"]["sides"] = 5
    elif fault == "literal_conflict":
        assets["opening_objects"][1]["state"]["ready"] = True
    elif fault == "missing_literal":
        del assets["opening_objects"][1]["state"]["sides"]
    elif fault == "capacity":
        assets["opening_objects"] *= 2
    elif fault == "seed_bool":
        assets["opening_seeds"]["opening_tools"] = True
    elif fault == "seed_missing":
        del assets["opening_seeds"]
    elif fault == "seed_extra":
        assets["opening_seeds"]["other"] = 7
    elif fault == "ref_literal":
        assets["opening_objects"][1]["state"]["sides"] = {"ref": "individual"}
    elif fault == "fake_generated":
        assets["opening_objects"][1]["generated"] = {"ready": True}
    else:
        assets["construction_receipt"] = {"valid": True}
    program = _compile(lib, ports, source)
    before = deepcopy(assets)
    calls = []
    real_create = _K0InMemorySession.create

    def create(*args, **kwargs):
        calls.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(_K0InMemorySession, "create", create)
    with pytest.raises(C0BindingError):
        program.start(assets)
    assert calls == []
    assert assets == before
    valid = _world()[3]
    session = program.start(valid)
    assert calls == [1]
    assert session.author_opening_construction().slots[0].input_seed == 42


def test_construction_evaluation_cannot_borrow_occurrence_marker():
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    plan = program.opening_constructions[0]
    with pytest.raises(C0ValueStateError, match="construction"):
        _eval(
            plan.bindings[0][2],
            {"sides": 4, "seed": 42, "occurrence": True},
            {"sides": int, "seed": int},
            plan.ports,
        )


def test_no_construction_is_literal_start_and_rejects_seed_or_expression():
    lib, ports, source, assets = _world()
    del source["opening_constructions"]
    del assets["opening_seeds"]
    for raw in assets["opening_objects"]:
        raw["state"].update(tone="blue", ready=True)
    program = _compile(lib, ports, source)
    assert program.program_ir.opening_constructions == ()
    assert program.start(assets).author_opening_construction() is None
    assets["opening_seeds"] = {"opening_tools": 42}
    with pytest.raises(C0BindingError):
        program.start(assets)
    del assets["opening_seeds"]
    assets["opening_objects"][0]["state"]["tone"] = _tone()
    with pytest.raises(C0BindingError):
        program.start(assets)


def test_lib_pure_rule_change_affects_opening_and_rule_evidence():
    lib, ports, source, assets = _world()
    lib["pure_definitions"] = [
        {
            "name": "tone_for_draw",
            "parameters": {"choice": "int"},
            "result": "str",
            "stage": "admission",
            "body": _tone(),
        }
    ]
    source["opening_constructions"][0]["outputs"]["tone"] = {
        "call": {"ref": "tone_for_draw", "args": {"choice": {"ref": "choice"}}},
    }
    first = _compile(lib, ports, source).start(assets).author_opening_construction()
    lib["pure_definitions"][0]["body"] = {"const": "green"}
    second = _compile(lib, ports, source).start(assets).author_opening_construction()
    assert first.slots[0].state.tone == "clear"
    assert second.slots[0].state.tone == "green"
    assert first.slots[0].rule_digest != second.slots[0].rule_digest


@pytest.mark.parametrize("separate_seed", [False, True])
def test_source_kind_order_and_assets_slot_order_are_explicit(separate_seed):
    lib, ports, source, assets = _world()
    port = deepcopy(ports["opening_constructions"][0])
    port.update(symbol="prepare_fine", kind="fine_tool")
    ports["opening_constructions"].append(port)
    rule = deepcopy(source["opening_constructions"][0])
    rule.update(kind="fine_tool", using="prepare_fine")
    if separate_seed:
        rule["seed"] = "fine_stream"
        assets["opening_seeds"]["fine_stream"] = 43
    source["opening_constructions"].insert(0, rule)
    fine = deepcopy(assets["opening_objects"][0])
    fine["kind"] = "fine_tool"
    assets["opening_objects"].insert(1, fine)
    session = _compile(lib, ports, source).start(assets)
    receipt = session.author_opening_construction()
    assert tuple(slot.slot for slot in receipt.slots) == (1, 0, 2)
    assert tuple(slot.individual for slot in receipt.slots) == tuple(
        session.author_object_instances()[index].individual for index in (1, 0, 2)
    )
    assert receipt.slots[0].input_seed == (43 if separate_seed else 42)
    assert receipt.slots[1].input_seed == (42 if separate_seed else next_seed(42))
    assert receipt.slots[2].input_seed == next_seed(receipt.slots[1].input_seed)


def test_unselected_kind_and_unchanged_runtime_seed_stay_literal():
    lib, ports, source, assets = _world()
    actor = next(item for item in lib["records"] if item["name"] == "Actor")
    actor["fields"].append({"name": "runtime_seed", "type": {"int": [0, 1000]}})
    assets["opening"]["actor"]["runtime_seed"] = 12
    fine = deepcopy(assets["opening_objects"][0])
    fine["kind"] = "fine_tool"
    fine["state"].update(tone="blue", ready=False)
    assets["opening_objects"].insert(1, fine)
    session = _compile(lib, ports, source).start(assets)
    assert tuple(slot.slot for slot in session.author_opening_construction().slots) == (0, 2)
    assert session.author_object_instances()[1].current_state.tone == "blue"
    assert session.author_object_instances()[1].current_state.ready is False
    assert assets["opening"]["actor"]["runtime_seed"] == 12
    actor_owner = next(item.owner for item in session.program.owners if item.symbol == "actor")
    assert session._runtime.read_owner(actor_owner.key).view.runtime_seed == 12


def test_nominal_constructor_output_is_compiled_and_checked_before_create(monkeypatch):
    lib, ports, source, assets = _world()
    lib["records"].append(
        {
            "name": "ToneInfo",
            "fields": [{"name": "face", "type": {"int": [1, 4]}}],
            "invariant": None,
        }
    )
    tool = next(item for item in lib["records"] if item["name"] == "Tool")
    tool["fields"].append({"name": "info", "type": "ToneInfo"})
    ports["opening_constructions"][0]["fields"].append("info")
    ports["opening_constructions"][0]["construct"].append("ToneInfo")
    rule = source["opening_constructions"][0]
    rule["outputs"]["info"] = {
        "record": {"type": "ToneInfo", "fields": {"face": {"ref": "choice"}}}
    }
    program = _compile(lib, ports, source)
    session = program.start(assets)
    assert [item.current_state.info.face for item in session.author_object_instances()] == [3, 1]
    rule["outputs"]["info"]["record"]["fields"]["face"] = {"const": 5}
    bad_program = _compile(lib, ports, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid nested nominal data must fail before K0 create")

    monkeypatch.setattr(_K0InMemorySession, "create", forbidden)
    with pytest.raises(C0BindingError):
        bad_program.start(assets)


def test_empty_opening_is_finite_and_does_not_draw():
    lib, ports, source, assets = _world()
    assets["opening_objects"] = []
    session = _compile(lib, ports, source).start(assets)
    receipt = session.author_opening_construction()
    assert receipt.slots == ()
    assert receipt.seeds == receipt.final_seeds == (("opening_tools", 42),)
    assert session.author_object_instances() == ()


def test_multiple_draws_chain_across_bindings_and_slots_without_extra_consumption():
    lib, ports, source, assets = _world()
    rule = source["opening_constructions"][0]
    rule["bindings"].extend(
        [
            {"name": "derived_sides", "value": {"add": [{"ref": "choice"}, {"const": 1}]}},
            {"name": "followup", "draw": {"ref": "derived_sides"}},
        ]
    )
    rule["outputs"]["ready"] = {"eq": [{"ref": "followup"}, {"const": 1}]}
    program = _compile(lib, ports, source)
    session = program.start(assets)
    receipt = session.author_opening_construction()
    current = 42
    for slot in receipt.slots:
        assert slot.input_seed == current
        first, second = slot.draws
        assert (first.binding, first.input_seed, first.sides, first.result) == (
            "choice",
            current,
            4,
            roll(current, 4),
        )
        current = next_seed(current)
        assert first.output_seed == current
        assert (second.binding, second.input_seed, second.sides, second.result) == (
            "followup",
            current,
            first.result + 1,
            roll(current, first.result + 1),
        )
        current = next_seed(current)
        assert second.output_seed == slot.output_seed == current
        assert slot.state.ready == (second.result == 1)
    assert receipt.final_seeds == (("opening_tools", current),)
    assert _chain(program.start(assets).author_opening_construction()) == _chain(receipt)
    assert assets["opening_seeds"] == {"opening_tools": 42}


def test_failure_after_prior_draws_discards_local_stream_before_create(monkeypatch):
    lib, ports, source, assets = _world()
    rule = source["opening_constructions"][0]
    # First slot completes; second slot draws once, then its next die has zero sides.
    rule["bindings"].append(
        {"name": "followup", "draw": {"sub": [{"ref": "choice"}, {"const": 1}]}}
    )
    program = _compile(lib, ports, source)
    before = deepcopy(assets)

    def forbidden(*args, **kwargs):
        raise AssertionError("failed local stream must not reach K0 create")

    monkeypatch.setattr(_K0InMemorySession, "create", forbidden)
    with pytest.raises(C0BindingError):
        program.start(assets)
    assert assets == before


def test_json_duplicate_output_is_rejected_before_compile():
    lib, ports, source, _ = _world()
    text = json.dumps(source).replace(
        '"ready": {"const": true}',
        '"ready": {"const": true}, "ready": {"const": false}',
        1,
    )
    with pytest.raises(C0LawError):
        _compile(lib, ports, text)


def test_nonliteral_source_is_rejected_as_a_law_error():
    lib, ports, source, _ = _world()
    source["opening_constructions"][0]["outputs"]["tone"] = {"const": object()}
    with pytest.raises(C0LawError, match="finite JSON"):
        _compile(lib, ports, source)


def test_invalid_ir_cannot_change_phase_or_duplicate_output_at_bind():
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    plan = program.program_ir.opening_constructions[0]
    with pytest.raises(C0LawError):
        replace(plan, outputs=plan.outputs + plan.outputs[:1])
    with pytest.raises(C0LawError):
        replace(
            plan, outputs=(("tone", replace(plan.outputs[0][1], stage="effect")), plan.outputs[1])
        )


@pytest.mark.parametrize(
    "fault",
    [
        "unrecorded_draw",
        "missing_draw",
        "output_draw",
        "wrong_seed",
        "wrong_annotation",
        "unbound_ref",
        "nested_phase",
    ],
)
def test_bind_rejects_inconsistent_symbolic_construction_ir(fault):
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    plan = program.program_ir.opening_constructions[0]
    draw = plan.bindings[0]
    expression = draw.expression
    with pytest.raises(C0LawError):
        if fault == "unrecorded_draw":
            plan = replace(plan, bindings=(replace(draw, draw=False),))
        elif fault == "missing_draw":
            plan = replace(
                plan,
                bindings=(
                    replace(draw, expression=replace(expression, operation="const", operand=4)),
                ),
            )
        elif fault == "output_draw":
            ready = replace(
                plan.outputs[1][1],
                operation="eq",
                operand=(expression, replace(expression, operation="const", operand=1)),
            )
            plan = replace(plan, outputs=(plan.outputs[0], ("ready", ready)))
        else:
            operands = dict(expression.operand)
            if fault == "wrong_seed":
                operands["seed"] = replace(operands["seed"], operation="const", operand=42)
            elif fault == "wrong_annotation":
                operands["sides"] = replace(
                    operands["sides"], value_type=plan.outputs[1][1].value_type
                )
            elif fault == "unbound_ref":
                operands["sides"] = replace(operands["sides"], operand="holder")
            else:
                operands["sides"] = replace(operands["sides"], stage="effect")
            plan = replace(
                plan,
                bindings=(
                    replace(
                        draw, expression=replace(expression, operand=MappingProxyType(operands))
                    ),
                ),
            )
        ir = replace(program.program_ir, opening_constructions=(plan,))
        bind_program(ir, program.world_layout)
