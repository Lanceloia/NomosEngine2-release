"""Compilation owns metadata; edits require a new compilation, not hot reload."""

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType
from typing import get_type_hints

import pytest
from nomos_kernel import K0OccurrenceRef
from test_local_computation_v1 import ports, program, state

from nomos_c0.composable_value_v1 import C0ClosedValuePorts, C0ValueProgram
from nomos_c0.expression_ir_v1 import C0Expression, closed_value_type
from nomos_c0.guard_ir_v0 import C0GuardIR
from nomos_c0.pure_definition_v1 import C0PureDefinition


def test_checked_expression_detaches_proxy_and_nested_tuple_storage():
    editable = {"parts": ({"name": [1, 2]},)}
    node = C0Expression(
        "const", MappingProxyType(editable), closed_value_type(int), "admission", "probe"
    )
    editable["parts"][0]["name"].append(3)
    editable["parts"][0]["extra"] = True
    assert node.operand["parts"][0]["name"] == (1, 2)
    assert "extra" not in node.operand["parts"][0]
    with pytest.raises(TypeError):
        node.operand["parts"][0]["name"] = ()
    with pytest.raises(FrozenInstanceError):
        node.operation = "ref"


def test_closed_ports_own_tuple_projections_keys_and_grants():
    projection = {"left": 0}
    granted = {"value"}
    keys = {"state.items": "value"}
    declared = replace(
        ports(),
        tuple_fields={tuple[int, str]: MappingProxyType(projection)},
        admission_tuple_fields={tuple[int, str]: projection},
        collection_keys=keys,
        readable_fields={int: granted},
    )
    captured = C0ClosedValuePorts.capture(declared).annotations()
    projection["left"] = 1
    granted.clear()
    keys.clear()
    assert captured.tuple_fields[tuple[int, str]]["left"] == 0
    assert captured.admission_tuple_fields[tuple[int, str]]["left"] == 0
    assert captured.readable_fields[int] == frozenset({"value"})
    assert captured.collection_keys["state.items"] == "value"
    with pytest.raises(TypeError):
        captured.tuple_fields[tuple[int, str]]["left"] = 1


def test_program_constructor_detaches_tree_without_cloning_checked_nodes():
    compiled = program()
    outputs = dict(compiled._tree["outputs"])
    editable = {**compiled._tree, "outputs": outputs, "bindings": []}
    captured = C0ValueProgram(
        compiled.guard_ir,
        MappingProxyType(editable),
        compiled._ports,
        set(),
        (),
    )
    outputs.clear()
    editable["bindings"].append({"name": "injected", "const": 999})
    assert captured._tree["outputs"]["value"] is compiled._tree["outputs"]["value"]
    assert captured._tree["bindings"] == ()
    assert captured.evaluate(state(7), occurrence=K0OccurrenceRef(1)) == {"value": 7}


def test_pure_body_and_guard_diagnostics_do_not_borrow_editable_maps():
    body = {"const": 1}
    paths = {"guard": "author.guard"}
    definition = C0PureDefinition("one", (), closed_value_type(int), "admission", body, paths)
    compiled = program()
    guard = C0GuardIR(compiled.guard_ir.expression, (), paths)
    body["const"] = 2
    paths.clear()
    assert definition.body["const"] == 1
    assert definition.source_paths["guard"] == "author.guard"
    assert guard.source_paths["guard"] == "author.guard"


def test_new_rule_is_a_new_program_and_current_state_still_changes_results():
    original = program(guard={"le": [{"ref": "state.count"}, {"const": 4}]})
    edited = program(guard={"le": [{"ref": "state.count"}, {"const": 8}]})
    assert not original.admits(state(7))
    assert edited.admits(state(7))
    assert original.admits(state(3))
    assert not original.admits(state(7))


@pytest.mark.parametrize("part", ["callback", "descriptor", "annotation", "field", "parameters"])
def test_generated_record_metadata_is_read_only_and_dataclass_protocol_survives(part):
    from test_declarative_nominal_v0 import _source

    from nomos_c0.declarative_nominal_v0 import check_nominal_lib

    lib = check_nominal_lib(_source())
    carrier = lib.record("Route")
    value = carrier("dock", 2)
    before = get_type_hints(carrier)
    with pytest.raises(TypeError, match="read-only"):
        if part == "callback":
            carrier.validate_for_k0 = lambda value: None
        elif part == "descriptor":
            carrier.travel = property(lambda value: 100)
        elif part == "annotation":
            carrier.__annotations__["travel"] = str
        elif part == "field":
            carrier.__dataclass_fields__["travel"].init = False
        else:
            carrier.__dataclass_params__.frozen = False
    assert get_type_hints(carrier) == before
    assert replace(value, travel=3).travel == 3
    value.validate_for_k0()
    lib.check_record_layout()
