"""Reference execution rechecks current grants, shape and keys after value reads."""

from dataclasses import FrozenInstanceError, replace

import pytest
from test_count_predicate_v1 import Inventory, Item, _compile
from test_invariant_execution_v1 import outcome, rewrite
from test_local_computation_v1 import Sample, State, const, ports, program, ref, state

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.expression_ir_v1 import closed_value_type
from nomos_c0.invariant_execution_v1 import compile_invariant_admission


def test_nominal_reference_only_unwraps_actual_optional_annotation(monkeypatch):
    calls = []
    original = values._nonnull

    def unwrap(annotation):
        calls.append(annotation)
        return original(annotation)

    monkeypatch.setattr(values, "_nonnull", unwrap)
    declared = ports()
    assert values._read_reference(("state", "count"), state(), declared.roots, declared) == 3
    assert not calls
    assert (
        values._read_reference(
            ("state", "sample", "value"), state(sample=Sample(2)), declared.roots, declared
        )
        == 2
    )
    assert calls == [Sample | None]
    with pytest.raises(values.C0ValueStateError, match="nullable"):
        values._read_reference(("state", "sample", "value"), state(), declared.roots, declared)


def test_field_grant_default_does_not_allocate_or_hide_present_invalid_value(monkeypatch):
    declared = ports()
    assert values._field_type(State, "count", declared) is int

    def allocate(*args):
        pytest.fail("field lookup constructed a new empty grant set")

    monkeypatch.setattr(values, "frozenset", allocate, raising=False)
    assert values._field_type(State, "count", declared) is int
    with pytest.raises(C0LawError, match="read port"):
        values._field_type(State, "count", replace(declared, readable_fields={}))
    with pytest.raises(TypeError):
        values._field_type(State, "count", replace(declared, readable_fields={State: None}))


def test_reference_grant_is_queried_after_getter(monkeypatch):
    declared = ports()
    roots = state()
    order = []

    def get_count(actual):
        order.append("get")
        object.__setattr__(declared, "readable_fields", {State: frozenset()})
        return 3

    monkeypatch.setattr(State, "count", property(get_count), raising=False)
    with pytest.raises(C0LawError, match="read port"):
        values._read_reference(("state", "count"), roots, declared.roots, declared)
    assert order == ["get"]


def test_plan_reference_bypasses_dispatch_but_reads_each_new_value(monkeypatch):
    compiled = program(guard=ref("state.ready"))
    execute = compile_invariant_admission(compiled)

    def interpreted(*args):
        pytest.fail("unchanged planned reference re-entered operation dispatch")

    monkeypatch.setattr(values, "_eval", interpreted)
    assert execute(state(ready=True))
    assert not execute(state(ready=False))


@pytest.mark.parametrize("mutation", ["key", "type"])
def test_reference_metadata_is_queried_after_read_in_both_executors(monkeypatch, mutation):
    compiled = _compile("exists(item for item in inventory.items if item.value > 0)")
    reference = compiled.guard_ir.expression.operand["collection"]
    original = values._read_reference
    roots = {"inventory": Inventory((Item("same", 1), Item("same", 2)), "same")}
    declared = compiled._admission_ports

    def read(parts, context, env, ports):
        result = original(parts, context, env, ports)
        if parts == ("inventory", "items"):
            if mutation == "key":
                object.__setattr__(ports, "collection_keys", {"inventory.items": "key"})
            else:
                object.__setattr__(reference, "value_type", closed_value_type(int))
        return result

    monkeypatch.setattr(values, "_read_reference", read)
    with rewrite(declared, collection_keys={} if mutation == "key" else declared.collection_keys):
        with rewrite(reference, value_type=reference.value_type):
            interpreted = outcome(
                lambda actual: values._eval(reference, actual, declared.roots, declared), roots
            )
    with rewrite(declared, collection_keys={} if mutation == "key" else declared.collection_keys):
        with rewrite(reference, value_type=reference.value_type):
            planned = outcome(
                lambda actual: values._eval_reference(reference, actual, declared.roots, declared),
                roots,
            )
    assert planned == interpreted
    assert isinstance(planned, tuple)


def test_plan_reference_rechecks_permissions_shape_and_changed_path(monkeypatch):
    compiled = program(guard={"eq": [ref("state.count"), const(3)]})
    execute = compile_invariant_admission(compiled)
    node = compiled.guard_ir.expression.operand[0]
    assert execute(state())
    denied = replace(compiled._admission_ports, readable_fields={})
    with rewrite(compiled, _runtime_admission_ports=denied):
        assert outcome(execute, state()) == outcome(compiled.admits, state())
    with pytest.raises(FrozenInstanceError):
        node.reference_path = ("state", "secret")
    changed = program(guard={"eq": [ref("state.count"), const(4)]})
    assert not compile_invariant_admission(changed)(state())
    assert execute(state())
    monkeypatch.setattr(State.__dataclass_fields__["secret"], "init", False)
    assert outcome(execute, state()) == outcome(compiled.admits, state())
