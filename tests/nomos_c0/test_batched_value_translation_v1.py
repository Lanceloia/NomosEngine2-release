"""A closed batch shares input trees, never per-rule authority or another layout."""

import gc
import json
import weakref
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_checked_value_binding_v1 import _neutral_lib, _value

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.checked_value_binding_v1 import C0ValueBackend
from nomos_c0.composable_value_v1 import compile_value_program
from nomos_c0.declarative_nominal_v0 import bind_nominal_records
from nomos_c0.expression_ir_v1 import C0Expression, closed_value_type
from nomos_c0.value_symbols_v1 import _ValueSymbolTranslation


def _pair():
    checked = _neutral_lib()
    body, ports = _value(checked)
    outputs = {"state.stock": "stock", "state.received": "received"}
    first = compile_value_program(json.dumps(body), ports, state_outputs=outputs)
    for name in ("secret", "roll"):
        body["outputs"].pop(name)
    state = checked.record("State")
    restricted = replace(
        ports,
        readable_paths=ports.readable_paths - {"state.secret"},
        readable_fields={**ports.readable_fields, state: ports.readable_fields[state] - {"secret"}},
        outputs={
            name: value for name, value in ports.outputs.items() if name not in ("secret", "roll")
        },
    )
    second = compile_value_program(json.dumps(body), restricted, state_outputs=outputs)
    return checked, (first, second)


def test_batch_shares_definition_bodies_but_keeps_ports_and_each_layout():
    checked, programs = _pair()
    backend = C0ValueBackend(checked.record_layout)
    captured = backend.capture_many(programs)
    assert captured == tuple(backend.capture(program) for program in programs)
    assert (
        captured[0].value.ports.pure_definitions[0].body
        is captured[1].value.ports.pure_definitions[0].body
    )
    for layout in (checked.record_layout, bind_nominal_records(checked.signatures)):
        selected = C0ValueBackend(layout)
        rebound = selected.bind_many(captured)
        row = layout.record("Row")
        state = layout.record("State")(5, 2, True, 2, (row("r", 9),), 19)
        for ir, value in zip(captured, rebound, strict=True):
            alone = selected.bind(ir)
            assert value._ports is not alone._ports
            assert value.evaluate(
                {"state": state}, occurrence=K0OccurrenceRef(7)
            ) == alone.evaluate({"state": state}, occurrence=K0OccurrenceRef(7))
        assert "state.secret" in rebound[0]._ports.readable_paths
        assert "state.secret" not in rebound[1]._ports.readable_paths
        assert rebound[0]._ports is not rebound[1]._ports
        assert (
            rebound[0]._ports.pure_definitions[0].body is rebound[1]._ports.pure_definitions[0].body
        )


def test_batch_checks_every_layout_and_rechecks_next_call(monkeypatch):
    checked, programs = _pair()
    backend = C0ValueBackend(checked.record_layout)
    layout_type = type(checked.record_layout)
    original = layout_type.check
    calls = []

    def tracked(self, signatures):
        calls.append(signatures)
        return original(self, signatures)

    monkeypatch.setattr(layout_type, "check", tracked)
    captured = backend.capture_many(programs)
    assert len(calls) == 2
    backend.bind_many(captured)
    assert len(calls) == 4
    with pytest.raises(TypeError, match="read-only"):
        checked.record("State").validate_for_k0 = lambda value: None
    backend.bind_many(captured)
    assert len(calls) == 6


def test_foreign_or_invalid_second_item_rejects_whole_batch_without_reuse():
    checked, programs = _pair()
    backend = C0ValueBackend(checked.record_layout)
    captured = backend.capture_many(programs)
    foreign, _ = _pair()
    with pytest.raises(C0LawError, match="selected signatures"):
        backend.bind_many((captured[0], replace(captured[1], signatures=foreign.signatures)))
    with pytest.raises(C0LawError, match="checked frontend"):
        backend.capture_many((programs[0], None))
    bad_ports = replace(captured[1].value.ports, readable_paths=frozenset())
    invalid = replace(captured[1], value=replace(captured[1].value, ports=bad_ports))
    with pytest.raises(C0LawError):
        backend.bind_many((captured[0], invalid))
    assert len(backend.bind_many(captured)) == 2
    for method, values in ((backend.capture_many, programs), (backend.bind_many, captured)):
        with pytest.raises(C0LawError, match="closed tuple"):
            method(iter(values))


def test_translation_retains_inputs_and_does_not_merge_equal_distinct_origins():
    translation = _ValueSymbolTranslation({}, binding=False)
    left = C0Expression("const", 1, closed_value_type(int), "admission", "left")
    right = replace(left, origin="right")
    first, second = translation.tree(left), translation.tree(right)
    assert first is not second
    assert (first.origin, second.origin) == ("left", "right")
    reference = weakref.ref(left)
    del left
    gc.collect()
    assert reference() is not None
    del translation
    gc.collect()
    assert reference() is None
