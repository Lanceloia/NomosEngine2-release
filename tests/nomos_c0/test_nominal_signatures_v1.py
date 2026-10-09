"""One checked nominal declaration can generate distinct equivalent record layouts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError

from nomos_c0 import composable_value_v1 as values
from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import (
    C0NominalRecordLayout,
    bind_nominal_records,
    check_nominal_lib,
)
from nomos_c0.value_symbols_v1 import bind_value_program, symbolize_value_program


def source():
    return {
        "schema": "c0.nominal_lib.v1",
        "records": [
            {
                "name": "Item",
                "fields": [
                    {"name": "name", "type": {"str": [1, 8]}},
                    {"name": "amount", "type": {"int": [0, 5]}},
                    {"name": "origin", "type": {"optional": "occurrence_ref"}},
                ],
                "invariant": {"call": {"ref": "bounded", "args": {"item": {"ref": "state"}}}},
            },
            {
                "name": "Box",
                "fields": [
                    {"name": "item", "type": "Item"},
                    {"name": "items", "type": {"tuple": {"item": "Item", "max": 2}}},
                ],
                "invariant": None,
            },
            {
                "name": "Other",
                "fields": [
                    {"name": "name", "type": {"str": [1, 8]}},
                    {"name": "amount", "type": {"int": [0, 5]}},
                    {"name": "origin", "type": {"optional": "occurrence_ref"}},
                ],
                "invariant": None,
            },
        ],
        "owners": [
            {
                "symbol": "box",
                "key": "c0.symbols.box",
                "version": "v1",
                "state": "Box",
                "identity_field": None,
                "seat_read": ["item", "items"],
                "write": "replace_one",
            }
        ],
        "pure_definitions": [
            {
                "name": "bounded",
                "parameters": {"item": "Item"},
                "result": "bool",
                "stage": "admission",
                "body": {"le": [{"ref": "item.amount"}, {"const": 4}]},
            }
        ],
    }


def assert_symbolic(value):
    if type(value) in (str, int, bool, type(None)):
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            assert_symbolic(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            assert_symbolic(key)
            assert_symbolic(item)
    elif type(value) in (tuple, frozenset):
        for item in value:
            assert_symbolic(item)
    else:
        pytest.fail(f"semantic signature retained a backend object: {value!r}")


def forbid_frontend(*args, **kwargs):
    pytest.fail("Bind or Run re-entered the frontend")


def test_signature_is_immutable_and_contains_no_carrier_key_or_callback():
    checked = check_nominal_lib(source())
    assert_symbolic(checked.signatures)
    item = checked.signatures.record("Item")
    assert item.fields[1].value.maximum == 5
    assert item.invariant.ports.roots[0][1].symbol == "Item"
    with pytest.raises(FrozenInstanceError):
        item.symbol = "Other"
    with pytest.raises(TypeError):
        item.invariant.tree["guard"] = None


def test_signature_is_independent_of_owner_key_but_not_record_meaning():
    original = source()
    edited = source()
    edited["owners"][0]["key"] = "c0.symbols.newbox"
    first = check_nominal_lib(original)
    second = check_nominal_lib(edited)
    assert first.signatures == second.signatures
    assert first.owners[0].owner.key != second.owners[0].owner.key
    edited["records"][0]["fields"][1]["type"] = {"int": [0, 3]}
    assert first.signatures != check_nominal_lib(edited).signatures


def test_same_signature_binds_distinct_carriers_and_pure_invariant_without_frontend(monkeypatch):
    checked = check_nominal_lib(source())
    monkeypatch.setattr(nominal, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(nominal, "check_pure_definitions", forbid_frontend)
    monkeypatch.setattr(nominal, "verify_pure_definition_types", forbid_frontend)
    second = bind_nominal_records(checked.signatures)
    for layout in (checked.record_layout, second):
        layout.check(checked.signatures)
        item = layout.record("Item")("x", 4, K0OccurrenceRef(2))
        item.validate_for_k0()
        layout.record("Box")(item, (item,)).validate_for_k0()
        assert layout.pure_definitions[0].parameters == (("item", layout.record("Item")),)
        assert layout.record("Item").__nomos_invariant__._ports.roots["state"] is type(item)
    assert second.record("Item") is not checked.record("Item")
    with pytest.raises(K0ProfileError, match="nominal"):
        second.record("Box")(checked.record("Item")("x", 1, None), ()).validate_for_k0()


@pytest.mark.parametrize("invalid", ["range", "invariant", "string", "tuple", "wrong_nominal"])
def test_generated_validator_has_same_rejection_in_two_layouts(invalid):
    checked = check_nominal_lib(source())
    for layout in (checked.record_layout, bind_nominal_records(checked.signatures)):
        item = layout.record("Item")
        if invalid == "range":
            bad = item("x", 6, None)
        elif invalid == "invariant":
            bad = item("x", 5, None)
        elif invalid == "string":
            bad = item("", 1, None)
        elif invalid == "tuple":
            bad = layout.record("Box")(item("x", 1, None), (item("x", 1, None),) * 3)
        else:
            bad = layout.record("Box")(layout.record("Other")("x", 1, None), ())
        with pytest.raises(K0ProfileError):
            bad.validate_for_k0()


@pytest.mark.parametrize("change", ["validator", "invariant", "fields", "annotation"])
def test_layout_rejects_replaced_or_weakened_generated_contract(change):
    checked = check_nominal_lib(source())
    carrier = checked.record("Item")
    with pytest.raises(TypeError, match="read-only"):
        if change == "validator":
            carrier.validate_for_k0 = lambda value: None
        elif change == "invariant":
            carrier.__nomos_invariant__ = None
        elif change == "fields":
            carrier.__nomos_fields__ = ()
        else:
            carrier.__annotations__["amount"] = str
    checked.record_layout.check(checked.signatures)


def test_layout_does_not_qualify_native_same_shape_or_different_nominal_signature():
    checked = check_nominal_lib(source())
    foreign = check_nominal_lib(source()).signatures
    with pytest.raises(C0LawError, match="selected signatures"):
        checked.record_layout.check(foreign)
    with pytest.raises(C0LawError, match="generated"):
        C0NominalRecordLayout()
    with pytest.raises(C0LawError, match="generated"):
        replace(checked.record_layout, records=(("Item", checked.record("Other")),))


def test_production_port_consumer_rechecks_generated_layout_before_using_records():
    checked = check_nominal_lib(source())
    with pytest.raises(TypeError, match="read-only"):
        checked.record("Item").validate_for_k0 = lambda value: None
    checked.check_record_layout()
    fresh = check_nominal_lib(source())
    substituted = replace(fresh, records=(("Item", fresh.record("Other")),))
    with pytest.raises(C0LawError, match="substituted"):
        check_graph_ports({}, substituted)


def test_one_checked_value_rebinds_record_copy_and_reads_in_two_layouts(monkeypatch):
    checked = check_nominal_lib(source())
    item = checked.record("Item")
    selected = C0ValuePorts(
        roots={"state": item},
        readable_paths=frozenset({"state", "state.name", "state.amount", "state.origin"}),
        admission_readable_paths=frozenset({"state.amount"}),
        readable_fields={item: frozenset({"name", "amount", "origin"})},
        admission_readable_fields={item: frozenset({"amount"})},
        writable_fields={item: frozenset({"name", "amount", "origin"})},
        record_types={"Item": item},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"copied": item, "made": item},
    )
    body = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"lt": [{"ref": "state.amount"}, {"const": 4}]},
        "outputs": {
            "copied": {
                "copy": {
                    "from": {"ref": "state"},
                    "changes": {
                        "amount": {"add": [{"ref": "state.amount"}, {"const": 1}]},
                        "origin": {"ref": "occurrence"},
                    },
                }
            },
            "made": {
                "record": {
                    "type": "Item",
                    "fields": {
                        "name": {"const": "new"},
                        "amount": {"const": 1},
                        "origin": {"ref": "occurrence"},
                    },
                }
            },
        },
    }
    value = symbolize_value_program(
        compile_value_program(json.dumps(body), selected), dict(checked.records)
    )
    assert_symbolic(value)
    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)
    for layout in (checked.record_layout, bind_nominal_records(checked.signatures)):
        bound = bind_value_program(value, dict(layout.records))
        result = bound.evaluate(
            {"state": layout.record("Item")("x", 3, None)}, occurrence=K0OccurrenceRef(7)
        )
        assert type(result["copied"]) is type(result["made"]) is layout.record("Item")
        assert result["copied"].amount == 4
        assert result["copied"].origin == result["made"].origin == K0OccurrenceRef(7)
        result["copied"].validate_for_k0()
        assert (
            bound.evaluate(
                {"state": layout.record("Item")("x", 4, None)}, occurrence=K0OccurrenceRef(8)
            )
            is None
        )


def test_production_owners_and_private_codec_use_signature_generated_records():
    checked = check_nominal_lib(source())
    item = checked.record("Item")("x", 2, K0OccurrenceRef(3))
    box = checked.record("Box")(item, (item,))
    owner = checked.owner("box").owner
    assert owner.state_type is checked.record_layout.record("Box")
    assert owner.decode_state(owner.encode_state(box)) == box
    assert owner.preserved_occurrences(box) == (K0OccurrenceRef(3), K0OccurrenceRef(3))


def test_symbol_binding_rejects_missing_record_and_unknown_type():
    checked = check_nominal_lib(source())
    program = checked.signatures.record("Item").invariant
    with pytest.raises(C0LawError, match="no backend binding"):
        bind_value_program(program, {})
    malformed = replace(
        program, binding_types=(replace(program.ports.roots[0][1], symbol="Missing"),)
    )
    with pytest.raises(C0LawError, match="no backend binding"):
        bind_value_program(malformed, dict(checked.records))
