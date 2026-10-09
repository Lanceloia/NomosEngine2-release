"""Quantifier plans read current collection metadata and preserve reduction order."""

from dataclasses import FrozenInstanceError, dataclass, replace

import pytest
from test_count_predicate_v1 import Inventory, Item, _compile
from test_invariant_execution_v1 import outcome, rewrite

from nomos_c0 import composable_value_v1 as values
from nomos_c0.expression_ir_v1 import closed_value_type
from nomos_c0.invariant_execution_v1 import compile_invariant_admission

OPERATIONS = ("none_matching", "exists", "exactly_one", "count_matching")


def compile_query(operation, where="item.value > 0"):
    query = {operation: {"collection": "inventory.items", "as": "item", "where": where}}
    compiled = _compile({"eq": [query, {"const": 1}]} if operation == "count_matching" else query)
    node = compiled.guard_ir.expression
    return compiled, node.operand[0] if operation == "count_matching" else node


def roots():
    return {"inventory": Inventory((Item("a", 1), Item("b", 2)), "a")}


@pytest.mark.parametrize("operation", OPERATIONS)
def test_unchanged_collection_and_predicate_bypass_dispatch(operation, monkeypatch):
    compiled, _ = compile_query(operation)
    execute = compile_invariant_admission(compiled)
    expected = compiled.admits(roots())

    def forbidden(*args):
        pytest.fail("planned collection/predicate re-entered operation dispatch")

    monkeypatch.setattr(values, "_eval", forbidden)
    assert execute(roots()) is expected


@pytest.mark.parametrize("operation", OPERATIONS)
def test_collection_edit_requires_new_compilation(operation):
    compiled, node = compile_query(operation)
    execute = compile_invariant_admission(compiled)
    changed, replacement = compile_query(operation)
    with pytest.raises(TypeError):
        node.operand["collection"] = replacement.operand["collection"]
    reference = node.operand["collection"]
    with pytest.raises(FrozenInstanceError):
        reference.operand = "inventory.wanted"
    assert outcome(execute, roots()) == outcome(compiled.admits, roots())
    assert changed.admits(roots()) == compiled.admits(roots())


@pytest.mark.parametrize("mutation", ["alias", "where", "type", "key", "permission", "operation"])
def test_public_metadata_mutation_during_read_is_rejected(monkeypatch, mutation):
    interpreted, first = compile_query("none_matching")
    planned, second = compile_query("none_matching")
    replacement = _compile("exists(other for other in inventory.items if False)")
    original = Inventory.__getattribute__
    events = []

    def read(inventory, name):
        result = original(inventory, name)
        if name == "items":
            node, ports = active
            events.append("collection")
            with pytest.raises((TypeError, FrozenInstanceError)):
                if mutation == "alias":
                    node.operand["as"] = "other"
                elif mutation == "where":
                    node.operand["where"] = replacement.guard_ir.expression.operand["where"]
                elif mutation == "type":
                    node.operand["collection"].value_type = closed_value_type(int)
                elif mutation == "key":
                    ports.collection_keys = {"inventory.items": "missing"}
                elif mutation == "permission":
                    ports.readable_fields = {}
                else:
                    node.operation = "exists"
        return result

    monkeypatch.setattr(Inventory, "__getattribute__", read)
    results = []
    traces = []
    active = [None, None]
    for compiled, node, use_plan in ((interpreted, first, False), (planned, second, True)):
        active[:] = node, compiled._admission_ports
        callback = compile_invariant_admission(compiled) if use_plan else compiled.admits
        results.append(outcome(callback, roots()))
        traces.append(list(events))
        events.clear()
    assert results[0] == results[1]
    assert traces == [["collection"], ["collection"]]
    assert results[0] is False


@pytest.mark.parametrize("operation", OPERATIONS)
def test_bounded_collection_check_still_precedes_reduction(operation, monkeypatch):
    compiled, _ = compile_query(operation)
    execute = compile_invariant_admission(compiled)
    monkeypatch.setattr(values, "_MAX_INT", 1)
    assert outcome(execute, roots()) == outcome(compiled.admits, roots())
    if operation == "none_matching":
        assert execute(roots()) is False
    else:
        assert isinstance(outcome(execute, roots()), tuple)


def test_collection_plan_rechecks_current_field_grants_and_shape(monkeypatch):
    compiled, _ = compile_query("exists")
    execute = compile_invariant_admission(compiled)
    assert execute(roots())
    denied = replace(compiled._admission_ports, readable_fields={})
    with rewrite(compiled, _runtime_admission_ports=denied):
        assert outcome(execute, roots()) == outcome(compiled.admits, roots())
    monkeypatch.setattr(Inventory.__dataclass_fields__["wanted"], "init", False)
    assert outcome(execute, roots()) == outcome(compiled.admits, roots())


@pytest.mark.parametrize("mutation", ["stage", "operation", "operand"])
def test_collection_metadata_is_fixed_after_compilation(mutation):
    compiled, node = compile_query("exists")
    execute = compile_invariant_admission(compiled)
    reference = node.operand["collection"]
    changes = {
        "stage": {"stage": "effect"},
        "operation": {"operation": "unknown"},
        "operand": {"operand": "inventory.wanted", "reference_path": ("inventory", "wanted")},
    }
    for name, value in changes[mutation].items():
        with pytest.raises(FrozenInstanceError):
            setattr(reference, name, value)
    assert execute(roots())


def test_reduction_keeps_immutable_predicate_but_reads_each_current_row(monkeypatch):
    original = Item.__getattribute__
    replacement = _compile("exists(item for item in inventory.items if False)")
    false_where = replacement.guard_ir.expression.operand["where"]
    results = []
    traces = []
    for use_plan in (False, True):
        compiled, node = compile_query("count_matching")
        seen = []

        def read(item, name):
            result = original(item, name)
            if name == "value":
                seen.append(original(item, "key"))
                with pytest.raises(TypeError):
                    node.operand["where"] = false_where
            return result

        callback = compile_invariant_admission(compiled) if use_plan else compiled.admits
        monkeypatch.setattr(Item, "__getattribute__", read)
        results.append(callback(roots()))
        traces.append(seen)
    assert results == [False, False]
    assert traces == [["a", "b"], ["a", "b"]]


def generator_reduction(operation, declaration, collection, context, env, ports, predicate):
    # Independent reference for the replaced reducer's evaluation order.
    name = declaration["as"]
    item_type = values._tuple_item(declaration["collection"].result_type)
    matching = (
        predicate(declaration["where"], {**context, name: item}, {**env, name: item_type}, ports)
        is True
        for item in collection
    )
    if operation == "none_matching":
        return not any(matching)
    if operation == "exists":
        return any(matching)
    if operation == "exactly_one":
        found = False
        for matched in matching:
            if matched:
                if found:
                    return False
                found = True
        return found
    return sum(matching)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("rows", [(), (True,), (1, None), (True, "error"), (True, True, "error")])
def test_direct_reduction_matches_generator_truth_short_circuit_and_failure_order(operation, rows):
    compiled, node = compile_query(operation)
    traces = []
    results = []
    for reducer in (generator_reduction, values._reduce_quantifier):
        seen = []
        contexts = []
        environments = []

        def predicate(where, context, env, ports):
            item = context["item"]
            seen.append(item)
            contexts.append(context)
            environments.append(env)
            if item == "error":
                raise ValueError("reached bad row")
            return item

        def run(_):
            return reducer(
                operation, node.operand, rows, {}, {}, compiled._admission_ports, predicate
            )

        results.append(outcome(run, {}))
        traces.append(seen)
        assert len({id(value) for value in contexts}) == len(contexts)
        assert len({id(value) for value in environments}) == len(environments)
    assert results[0] == results[1]
    assert traces[0] == traces[1]


def test_quantifier_item_plan_avoids_repeated_type_parsing(monkeypatch):
    compiled, _ = compile_query("exists")
    execute = compile_invariant_admission(compiled)
    original = values._tuple_item
    calls = []

    def parse(annotation):
        calls.append(annotation)
        return original(annotation)

    monkeypatch.setattr(values, "_tuple_item", parse)
    with rewrite(
        compiled,
        _runtime_admission_ports=replace(compiled._admission_ports, collection_keys={}),
    ):
        assert execute(roots())
        # Isolate item preparation from the independent read-time key contract.
        assert not calls
        assert compiled.admits(roots())
        assert calls == [tuple[Item, ...]]


def test_quantifier_item_plan_observes_type_changes_after_collection_read(monkeypatch):
    compiled, node = compile_query("exists")
    execute = compile_invariant_admission(compiled)
    reference = node.operand["collection"]
    original = Inventory.__getattribute__

    def read(inventory, name):
        result = original(inventory, name)
        if name == "items":
            object.__setattr__(reference, "value_type", closed_value_type(int))
        return result

    monkeypatch.setattr(Inventory, "__getattribute__", read)
    with rewrite(reference, value_type=reference.value_type):
        planned = outcome(execute, roots())
    with rewrite(reference, value_type=reference.value_type):
        interpreted = outcome(compiled.admits, roots())
    assert planned == interpreted
    assert isinstance(planned, tuple)


def test_nested_quantifier_item_plans_keep_alias_environments():
    guard = (
        "exists(item for item in inventory.items if "
        "exists(other for other in inventory.items if other.key == item.key))"
    )
    compiled = _compile(guard)
    execute = compile_invariant_admission(compiled)
    assert execute(roots()) == compiled.admits(roots()) is True
    empty = {"inventory": Inventory((), "a")}
    assert execute(empty) == compiled.admits(empty) is False


def test_nested_quantifier_plans_use_distinct_element_types():
    from test_local_computation_v1 import const, ports, program

    @dataclass(frozen=True)
    class Table:
        rows: tuple[Item, ...]
        labels: tuple[str, ...]

    paths = frozenset({"table.rows", "table.labels"})
    grants = {Table: frozenset({"rows", "labels"}), Item: frozenset({"key"})}
    declared = replace(
        ports(),
        roots={"table": Table},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=grants,
        admission_readable_fields=grants,
    )
    compiled = program(
        guard=(
            "exists(row for row in table.rows if "
            "exists(label for label in table.labels if label == row.key))"
        ),
        outputs={"value": const(0)},
        selected_ports=declared,
    )
    execute = compile_invariant_admission(compiled)
    for labels in (("a",), ("absent",), ()):
        actual = {"table": Table((Item("a", 1),), labels)}
        assert execute(actual) == compiled.admits(actual) == (labels == ("a",))
