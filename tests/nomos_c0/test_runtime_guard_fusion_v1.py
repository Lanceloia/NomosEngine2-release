"""Fused checked references preserve actual reads, failures and lexical scope."""

from dataclasses import make_dataclass, replace

import pytest
from test_count_predicate_v1 import Inventory, Item, _compile
from test_invariant_execution_v1 import outcome
from test_local_computation_v1 import Sample, State, const, ports, program, ref, state

from nomos_c0 import composable_value_v1 as values
from nomos_c0.invariant_execution_v1 import compile_invariant_admission


def test_supported_reference_block_has_no_forwarding_calls(monkeypatch):
    compiled = program(
        guard={
            "all": [
                {"eq": [ref("state.count"), const(3)]},
                {"not_none": ref("state.sample")},
                {"eq": [ref("state.sample.value"), const(2)]},
            ]
        }
    )
    execute = compile_invariant_admission(compiled)

    def forbidden(*args, **kwargs):
        pytest.fail("generated reference block used a forwarding helper")

    monkeypatch.setattr(values, "_eval_reference", forbidden)
    monkeypatch.setattr(values, "_read_reference", forbidden)
    monkeypatch.setattr(values, "_field_type", forbidden)
    assert execute(state(sample=Sample(2)))
    assert not execute(state(4, sample=Sample(2)))


@pytest.mark.parametrize("roots", [state(), {}, {"state": object()}, state(sample=Sample(2))])
def test_nullable_and_malformed_current_values_match_general_executor(roots):
    compiled = program(
        guard={
            "all": [
                {"not_none": ref("state.sample")},
                {"eq": [ref("state.sample.value"), const(2)]},
            ]
        }
    )
    assert outcome(compile_invariant_admission(compiled), roots) == outcome(compiled.admits, roots)


def test_repeated_reference_keeps_each_current_getter_and_short_circuit(monkeypatch):
    compiled = program(
        guard={
            "all": [
                {"eq": [ref("state.count"), const(3)]},
                {"eq": [ref("state.count"), const(3)]},
            ]
        }
    )
    execute = compile_invariant_admission(compiled)
    original = State.__getattribute__
    seen = []

    def read(value, name):
        if name == "count":
            seen.append(name)
        return original(value, name)

    monkeypatch.setattr(State, "__getattribute__", read)
    assert execute(state())
    assert seen == ["count", "count"]
    seen.clear()
    assert not execute(state(4))
    assert seen == ["count"]


def test_native_layout_still_checked_after_binding(monkeypatch):
    compiled = program(guard={"eq": [ref("state.count"), const(3)]})
    execute = compile_invariant_admission(compiled)
    assert execute(state())
    monkeypatch.setattr(State.__dataclass_fields__["secret"], "init", False)
    assert outcome(execute, state()) == outcome(compiled.admits, state())


def test_tuple_projection_keeps_actual_index_and_shape_checks():
    pair = tuple[int, str]
    holder = make_dataclass("PairHolder", [("pair", pair)], frozen=True)
    paths = frozenset({"holder.pair", "holder.pair.left"})
    grants = {holder: frozenset({"pair"})}
    declared = replace(
        ports(),
        roots={"holder": holder},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=grants,
        admission_readable_fields=grants,
        tuple_fields={pair: {"left": 0}},
        admission_tuple_fields={pair: {"left": 0}},
    )
    compiled = program(
        guard={"eq": [ref("holder.pair.left"), const(3)]},
        outputs={"value": const(0)},
        selected_ports=declared,
    )
    execute = compile_invariant_admission(compiled)
    for current in ((3, "a"), (4, "a"), (), (True, "a"), [3, "a"]):
        roots = {"holder": holder(current)}
        assert outcome(execute, roots) == outcome(compiled.admits, roots)


def test_generated_reference_queries_permission_after_native_getter(monkeypatch):
    compiled = program(guard={"eq": [ref("state.count"), const(3)]})
    execute = compile_invariant_admission(compiled)
    roots = state()
    declared = compiled._admission_ports
    original = declared.readable_fields
    calls = []

    def read_count(actual):
        calls.append(actual)
        object.__setattr__(declared, "readable_fields", {})
        return 3

    monkeypatch.setattr(State, "count", property(read_count), raising=False)
    try:
        expected = outcome(compiled.admits, roots)
        object.__setattr__(declared, "readable_fields", original)
        assert outcome(execute, roots) == expected
        assert len(calls) == 2 and isinstance(expected, tuple)
    finally:
        object.__setattr__(declared, "readable_fields", original)


def test_collection_reference_rechecks_duplicate_keys_and_current_rows():
    compiled = _compile("exists(item for item in inventory.items if item.value > 0)")
    execute = compile_invariant_admission(compiled)
    for items in ((Item("a", 1),), (Item("a", 1), Item("a", 2)), (Item("a", 0),)):
        roots = {"inventory": Inventory(items, "a")}
        assert outcome(execute, roots) == outcome(compiled.admits, roots)


def test_fused_field_check_keeps_missing_type_and_permission_failures(monkeypatch):
    compiled = program(guard={"eq": [ref("state.count"), const(3)]})
    execute = compile_invariant_admission(compiled)
    original = values._resolved_fields
    monkeypatch.setattr(
        values, "_resolved_fields", lambda carrier: {} if carrier is State else original(carrier)
    )
    assert outcome(execute, state()) == outcome(compiled.admits, state())


def test_tuple_projection_rechecks_permission_after_current_indexing():
    pair = tuple[int, str]
    holder = make_dataclass("LivePairHolder", [("pair", pair)], frozen=True)
    paths = frozenset({"holder.pair", "holder.pair.left"})
    declared = replace(
        ports(),
        roots={"holder": holder},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields={holder: frozenset({"pair"})},
        admission_readable_fields={holder: frozenset({"pair"})},
        tuple_fields={pair: {"left": 0}},
        admission_tuple_fields={pair: {"left": 0}},
    )
    compiled = program(
        guard={"eq": [ref("holder.pair.left"), const(3)]},
        outputs={"value": const(0)},
        selected_ports=declared,
    )
    execute = compile_invariant_admission(compiled)
    runtime_ports = compiled._admission_ports
    original = runtime_ports.tuple_fields

    class LiveTuple:
        def __getitem__(self, index):
            object.__setattr__(runtime_ports, "tuple_fields", {})
            return 3

    roots = {"holder": holder(LiveTuple())}
    try:
        expected = outcome(compiled.admits, roots)
        object.__setattr__(runtime_ports, "tuple_fields", original)
        assert outcome(execute, roots) == expected
        assert isinstance(expected, tuple) and expected[0] is values.C0LawError
    finally:
        object.__setattr__(runtime_ports, "tuple_fields", original)


def test_nested_alias_references_are_fused_without_leaking_context(monkeypatch):
    compiled = _compile(
        "exactly_one(item for item in inventory.items if "
        "exists(other for other in inventory.items if other.value == item.value))"
    )
    execute = compile_invariant_admission(compiled)
    roots = {"inventory": Inventory((Item("a", 1),), "a")}
    original = values._read_reference

    def read(parts, *args):
        if parts in (("item", "value"), ("other", "value")):
            pytest.fail("lexical alias used a forwarding helper")
        return original(parts, *args)

    monkeypatch.setattr(values, "_read_reference", read)
    assert execute(roots)
    assert set(roots) == {"inventory"}
