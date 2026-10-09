"""Bound metadata is reusable; current values and permissions are not cached."""

from dataclasses import FrozenInstanceError, make_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_control_binding_v1 import _inputs
from test_local_computation_v1 import Sample, State, ports, program, state
from test_world_binding_v1 import _compile

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.expression_ir_v1 import C0Expression, closed_value_type


@pytest.mark.parametrize(
    "annotation", [int, int | None, tuple[int, ...], tuple[int, str], tuple[()], Sample]
)
def test_closed_annotation_metadata_is_reused_and_replace_rebinds(annotation):
    checked = closed_value_type(annotation)
    assert checked.annotation == annotation
    assert checked.annotation is checked.annotation
    changed = replace(checked, kind="nominal", carrier=str, arguments=())
    assert changed.annotation is str and checked.annotation == annotation


def test_checked_ref_evaluation_uses_bound_segments_but_reads_new_values(monkeypatch):
    compiled = program(outputs={"value": {"ref": "state.count"}})
    node = compiled._tree["outputs"]["value"]
    assert node.reference_path == ("state", "count")

    def unplanned(*args):
        pytest.fail("checked ref fell back to parsing a string path")

    monkeypatch.setattr(values, "_read_ref", unplanned)
    for amount in (2, 7):
        assert compiled.evaluate(state(amount), occurrence=K0OccurrenceRef(amount)) == {
            "value": amount
        }
    changed = replace(node, operand="state.secret")
    assert changed.reference_path == ("state", "secret")
    with pytest.raises(FrozenInstanceError):
        node.reference_path = ("state", "secret")


def test_bound_segments_keep_nullable_shape_and_selected_read_grants(monkeypatch):
    declared = ports()
    parts = ("state", "sample", "value")
    roots = state(sample=Sample(2))
    assert values._read_reference(parts, roots, declared.roots, declared) == 2
    denied = replace(declared, readable_fields={State: declared.readable_fields[State]})
    with pytest.raises(C0LawError, match="read port"):
        values._read_reference(parts, roots, denied.roots, denied)
    with pytest.raises(values.C0ValueStateError, match="nullable"):
        values._read_reference(parts, state(), declared.roots, declared)
    monkeypatch.setattr(Sample.__dataclass_fields__["value"], "init", False)
    with pytest.raises((C0LawError, KeyError)):
        values._read_reference(parts, roots, declared.roots, declared)


@pytest.fixture(scope="module")
def bound():
    lib, declarations, source, assets = _inputs()
    return _compile(lib, declarations, source), assets


def test_program_indexes_are_exact_immutable_and_partial_replacement_is_rejected(bound):
    compiled, _ = bound
    assert tuple(compiled._actions_by_name.items()) == compiled.actions
    assert tuple(compiled._owners_by_symbol.values()) == compiled.owners
    assert tuple(compiled._seats_by_symbol.values()) == compiled.seats
    assert tuple(compiled._appraisals_by_name.values()) == compiled.appraisal_profiles
    for seat in compiled.seats:
        assert dict(compiled._candidate_checks_by_seat[seat.symbol]) == dict(seat.candidate_checks)
    with pytest.raises(TypeError):
        compiled._actions_by_name["foreign"] = compiled.actions[0][1]
    with pytest.raises(TypeError):
        compiled._candidate_checks_by_seat[compiled.seats[0].symbol][100] = None
    with pytest.raises(C0BindingError, match="complete checked Bind"):
        replace(compiled, actions=compiled.actions[:1])
    assert len(compiled._actions_by_name) == len(compiled.actions)


@pytest.mark.parametrize("field", ["actions", "owners", "seats"])
def test_program_indexes_do_not_silently_hide_duplicate_declarations(bound, field):
    compiled, _ = bound
    rows = getattr(compiled, field)
    with pytest.raises(C0BindingError, match="complete checked Bind"):
        replace(compiled, **{field: (*rows, rows[0])})


def test_expression_rebinding_does_not_retain_foreign_access_metadata():
    node = C0Expression("ref", "item.key", closed_value_type(str), "admission", "output")
    rebound = replace(node, operand="payload.name", value_type=closed_value_type(int))
    assert node.reference_path == ("item", "key")
    assert rebound.reference_path == ("payload", "name") and rebound.result_type is int


def test_compound_metadata_does_not_alias_same_named_nominal_carriers():
    left = make_dataclass("Item", [("value", int)], frozen=True)
    right = make_dataclass("Item", [("value", int)], frozen=True)
    assert closed_value_type(left | None).annotation != closed_value_type(right | None).annotation


def test_new_bind_rebuilds_indexes_without_mutating_existing_program(bound):
    compiled, _ = bound
    lib, declarations, source, _ = _inputs()
    changed = _compile(lib, declarations, source)
    assert changed is not compiled
    assert changed.profile is not compiled.profile
    assert changed._actions_by_name is not compiled._actions_by_name
    assert tuple(changed._actions_by_name) == tuple(compiled._actions_by_name)
    assert tuple(changed._appraisals_by_name.values()) == changed.appraisal_profiles
    assert tuple(compiled._appraisals_by_name.values()) == compiled.appraisal_profiles
