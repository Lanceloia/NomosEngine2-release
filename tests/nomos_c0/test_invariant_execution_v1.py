"""Generated guard execution remains derived from current checked IR and state."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError, make_dataclass

import pytest
from nomos_kernel._owner_abi import _validate_closed_host_object
from test_count_predicate_v1 import Inventory, Item, _compile
from test_local_computation_v1 import Sample, State, const, local, program, ref, state

from nomos_c0 import composable_value_v1 as values
from nomos_c0.invariant_execution_v1 import compile_invariant_admission


@contextmanager
def rewrite(value, **updates):
    originals = {name: getattr(value, name) for name in updates}
    try:
        for name, update in updates.items():
            object.__setattr__(value, name, update)
        yield
    finally:
        for name, original in originals.items():
            object.__setattr__(value, name, original)


def outcome(callback, roots):
    try:
        return callback(roots)
    except Exception as error:
        return type(error), str(error), type(error.__cause__), str(error.__cause__)


@pytest.mark.parametrize(
    "guard",
    [
        {"all": [{"not_none": ref("state.sample")}, {"lt": [ref("state.count"), const(5)]}]},
        {"any": [{"eq": [ref("state.count"), const(3)]}, {"le": [ref("state.count"), const(5)]}]},
        {"not": {"eq": [ref("state.count"), const(3)]}},
        {"if": {"when": ref("state.ready"), "then": const(True), "else": const(False)}},
        {"all": [const(False), {"eq": [{"ceil_div": [const(1), const(0)]}, const(0)]}]},
        {"any": [const(True), {"eq": [{"ceil_div": [const(1), const(0)]}, const(0)]}]},
        {"eq": [{"ceil_div": [const(1), const(0)]}, const(0)]},
    ],
)
def test_plan_matches_guard_results_errors_and_short_circuit(guard):
    compiled = program(guard=guard)
    execute = compile_invariant_admission(compiled)
    for roots in (state(), state(7), state(sample=Sample(2)), {}, {"state": object()}):
        assert outcome(execute, roots) == outcome(compiled.admits, roots)
    _validate_closed_host_object(compiled, label="program")


def test_plan_is_fixed_and_rule_edits_require_new_compilation():
    compiled = program(guard={"all": [const(True), const(True)]})
    execute = compile_invariant_admission(compiled)
    assert execute(state())
    child = compiled.guard_ir.expression.operand[1]
    with pytest.raises(FrozenInstanceError):
        child.operand = False
    changed = program(guard=const(False))
    with pytest.raises(FrozenInstanceError):
        compiled.guard_ir = changed.guard_ir
    assert not compile_invariant_admission(changed)(state())
    assert execute(state())


def test_plan_keeps_current_reference_shape_and_permission(monkeypatch):
    compiled = program(guard={"eq": [ref("state.count"), const(3)]})
    execute = compile_invariant_admission(compiled)
    assert execute(state())
    monkeypatch.setattr(State.__dataclass_fields__["secret"], "init", False)
    assert outcome(execute, state()) == outcome(compiled.admits, state())


def test_bindings_and_deep_guards_keep_existing_executor():
    compiled = program(
        bindings=[local("n", ref("state.count"))], guard={"eq": [ref("n"), const(3)]}
    )
    execute = compile_invariant_admission(compiled)
    assert execute(state()) and not execute(state(4))
    guard = const(True)
    for _ in range(25):
        guard = {"not": guard}
    deep = program(guard=guard)
    assert compile_invariant_admission(deep)(state()) == deep.admits(state())


def test_plan_root_type_does_not_accept_same_named_record():
    compiled = program(guard=const(True))
    foreign = make_dataclass("State", [("count", int)], frozen=True)
    roots = {"state": foreign(3)}
    assert outcome(compile_invariant_admission(compiled), roots) == outcome(compiled.admits, roots)


def test_supported_nodes_execute_without_recursive_interpreter(monkeypatch):
    compiled = program(guard={"all": [{"eq": [const(3), const(3)]}, {"not": const(False)}]})
    execute = compile_invariant_admission(compiled)

    def forbidden(*args):
        pytest.fail("specialized boolean node re-entered the interpreter")

    monkeypatch.setattr(values, "_eval", forbidden)
    assert execute(state())


def test_new_binding_tree_is_compiled_independently():
    compiled = program(guard=const(True))
    execute = compile_invariant_admission(compiled)
    changed = program(bindings=[local("n", ref("state.count"))], guard=const(True))
    with pytest.raises(FrozenInstanceError):
        compiled._tree = changed._tree
    assert outcome(compile_invariant_admission(changed), state()) == outcome(
        changed.admits, state()
    )
    assert execute(state())


@pytest.mark.parametrize("operation", ["none_matching", "exists", "exactly_one", "count_matching"])
@pytest.mark.parametrize("amounts", [(), (0,), (1,), (1, 2), (-1, 2, 0)])
def test_planned_quantifiers_match_empty_filtered_and_multiple_rows(operation, amounts):
    query = {operation: {"collection": "inventory.items", "as": "item", "where": "item.value > 0"}}
    compiled = _compile({"eq": [query, {"const": 1}]} if operation == "count_matching" else query)
    roots = {
        "inventory": Inventory(tuple(Item(str(i), value) for i, value in enumerate(amounts)), "0")
    }
    assert outcome(compile_invariant_admission(compiled), roots) == outcome(compiled.admits, roots)


@pytest.mark.parametrize("operation", ["none_matching", "exists", "exactly_one", "count_matching"])
def test_planned_quantifier_short_circuit_and_recompiled_predicate(operation, monkeypatch):
    query = {operation: {"collection": "inventory.items", "as": "item", "where": "item.value > 0"}}
    compiled = _compile({"eq": [query, {"const": 1}]} if operation == "count_matching" else query)
    node = compiled.guard_ir.expression
    if operation == "count_matching":
        node = node.operand[0]
    execute = compile_invariant_admission(compiled)
    roots = {"inventory": Inventory((Item("0", 1), Item("1", 2), Item("bad", "bad")), "0")}
    seen = []
    original = Item.__getattribute__

    def read(item, name):
        if name == "value":
            seen.append(original(item, "key"))
        return original(item, name)

    monkeypatch.setattr(Item, "__getattribute__", read)
    expected = outcome(compiled.admits, roots)
    visits = list(seen)
    seen.clear()
    assert outcome(execute, roots) == expected
    assert seen == visits
    changed = _compile("exists(item for item in inventory.items if False)")
    with pytest.raises(TypeError):
        node.operand["where"] = changed.guard_ir.expression.operand["where"]
    assert not compile_invariant_admission(changed)(roots)
    assert outcome(execute, roots) == expected


@pytest.mark.parametrize("operation", ["none_matching", "exists", "exactly_one", "count_matching"])
def test_quantifier_preserves_current_collection_type_checks(operation):
    query = {operation: {"collection": "inventory.items", "as": "item", "where": "True"}}
    compiled = _compile({"eq": [query, {"const": 1}]} if operation == "count_matching" else query)
    execute = compile_invariant_admission(compiled)
    for collection in ([Item("0", 1)], (Item("0", 1),), "bad"):
        roots = {"inventory": Inventory(collection, "0")}
        assert outcome(execute, roots) == outcome(compiled.admits, roots)


def test_nested_planned_queries_do_not_leak_aliases():
    compiled = _compile(
        "exactly_one(item for item in inventory.items if "
        "exists(other for other in inventory.items if other.value == item.value))"
    )
    execute = compile_invariant_admission(compiled)
    roots = {"inventory": Inventory((Item("0", 1),), "0")}
    assert execute(roots)
    assert set(roots) == {"inventory"}
