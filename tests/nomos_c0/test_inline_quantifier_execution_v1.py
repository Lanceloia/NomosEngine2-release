"""Inline quantifiers retain checked collection and lexical reduction boundaries."""

from dataclasses import replace

import pytest
from test_count_predicate_v1 import Inventory, Item, _compile
from test_invariant_execution_v1 import outcome, rewrite
from test_quantifier_collection_execution_v1 import OPERATIONS, compile_query, roots

from nomos_c0 import composable_value_v1 as values
from nomos_c0.expression_ir_v1 import C0Expression, closed_value_type
from nomos_c0.invariant_execution_v1 import compile_invariant_admission


@pytest.mark.parametrize("operation", OPERATIONS)
def test_inline_quantifier_does_not_call_wrappers_or_interpreter(operation, monkeypatch):
    compiled, _ = compile_query(operation)
    expected = compiled.admits(roots())
    execute = compile_invariant_admission(compiled)

    def forbidden(*args, **kwargs):
        pytest.fail("inline quantifier re-entered a wrapper or interpreter")

    for name in ("_eval_quantifier", "_reduce_quantifier", "_eval"):
        monkeypatch.setattr(values, name, forbidden)
    assert execute(roots()) is expected
    closure = dict(zip(execute.__code__.co_freevars, execute.__closure__, strict=True))
    assert not any(
        name.startswith(("collection_", "predicate_")) and name.rsplit("_", 1)[-1].isdigit()
        for name in closure["execute"].cell_contents.__code__.co_names
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("amounts", [(), (0,), (1,), (1, 2), (-1, 2, 0), (1, 2, "bad")])
def test_inline_quantifier_matches_results_first_error_and_visits(operation, amounts, monkeypatch):
    compiled, _ = compile_query(operation)
    execute = compile_invariant_admission(compiled)
    current = {"inventory": Inventory(tuple(Item(str(i), v) for i, v in enumerate(amounts)), "a")}
    original = Item.__getattribute__
    visits = []

    def read(item, name):
        if name == "value":
            visits.append(original(item, "key"))
        return original(item, name)

    monkeypatch.setattr(Item, "__getattribute__", read)
    expected = outcome(compiled.admits, current)
    expected_visits = list(visits)
    visits.clear()
    assert outcome(execute, current) == expected
    assert visits == expected_visits


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("returned", [True, False, 1, None])
def test_inline_quantifier_uses_exact_true(operation, returned):
    compiled, node = compile_query(operation, where="True")
    execute = compile_invariant_admission(compiled)
    current = {"inventory": Inventory((Item("a", 1),), "a")}
    with rewrite(node.operand["where"], operand=returned):
        assert outcome(execute, current) == outcome(compiled.admits, current)


def test_inline_count_keeps_distinct_row_contexts_and_environments(monkeypatch):
    compiled, _ = compile_query(
        "count_matching", where={"lt": [0, {"ceil_div": ["item.value", 1]}]}
    )
    execute = compile_invariant_admission(compiled)
    original = values._eval
    contexts, environments = [], []

    def read(node, context, env, ports):
        if node.operation == "ceil_div":
            contexts.append(context)
            environments.append(env)
        return original(node, context, env, ports)

    monkeypatch.setattr(values, "_eval", read)
    execute(roots())
    assert [context["item"].key for context in contexts] == ["a", "b"]
    assert len({id(context) for context in contexts}) == 2
    assert len({id(env) for env in environments}) == 2


def test_inline_nested_queries_keep_outer_alias_and_stop_only_inner_loop():
    compiled = _compile(
        "count(item for item in inventory.items if "
        "exists(other for other in inventory.items if other.value == item.value)) == 2"
    )
    current = roots()
    assert compile_invariant_admission(compiled)(current) is True
    assert compiled.admits(current) is True
    assert set(current) == {"inventory"}


@pytest.mark.parametrize("operation", OPERATIONS)
def test_inline_collection_bounds_and_shape_precede_reduction(operation, monkeypatch):
    compiled, _ = compile_query(operation)
    execute = compile_invariant_admission(compiled)
    monkeypatch.setattr(values, "_MAX_INT", 1)
    for collection in (roots()["inventory"].items, [Item("a", 1)], (), "bad"):
        current = {"inventory": Inventory(collection, "a")}
        assert outcome(execute, current) == outcome(compiled.admits, current)


def test_inline_item_plan_identity_change_reparses_when_reached(monkeypatch):
    compiled, node = compile_query("exists")
    execute = compile_invariant_admission(compiled)
    collection = node.operand["collection"]
    calls = []
    original = values._tuple_item

    def parse(annotation):
        calls.append(annotation)
        return original(annotation)

    monkeypatch.setattr(values, "_tuple_item", parse)
    assert execute(roots()) is True
    # The collection reference still parses its declared key's element type.
    assert calls == [tuple[Item, ...]]
    calls.clear()
    with rewrite(collection, value_type=closed_value_type(tuple[Item, ...])):
        assert execute(roots()) is True
    assert calls == [tuple[Item, ...], tuple[Item, ...]]


def test_inline_malformed_item_plan_is_deferred_until_after_collection_read(monkeypatch):
    compiled, node = compile_query("exists")
    collection = node.operand["collection"]
    events = []
    original = Inventory.__getattribute__

    def read(inventory, name):
        if name == "items":
            events.append("collection")
        return original(inventory, name)

    with rewrite(collection, value_type=closed_value_type(int)):
        execute = compile_invariant_admission(compiled)
        assert events == []
        monkeypatch.setattr(Inventory, "__getattribute__", read)
        with pytest.raises(values.C0LawError, match="homogeneous typed tuple"):
            execute(roots())
    assert events == ["collection"]


def test_inline_collection_unique_key_precedes_matching_and_uses_current_ports():
    compiled, _ = compile_query("exists", where="True")
    execute = compile_invariant_admission(compiled)
    duplicate = {"inventory": Inventory((Item("a", 1), Item("a", 2)), "a")}
    assert outcome(execute, duplicate) == outcome(compiled.admits, duplicate)
    assert isinstance(outcome(execute, duplicate), tuple)
    denied = replace(compiled._admission_ports, readable_fields={})
    with rewrite(compiled, _runtime_admission_ports=denied):
        assert outcome(execute, roots()) == outcome(compiled.admits, roots())


def test_inline_unselected_lazy_call_argument_is_not_forced():
    from nomos_c0.composable_value_v1 import verify_pure_definition_types
    from nomos_c0.pure_definition_v1 import check_pure_definitions

    definitions = check_pure_definitions(
        [
            {
                "name": "ignore",
                "parameters": {"unused": "int"},
                "result": "bool",
                "stage": "admission",
                "body": True,
            }
        ],
        {},
    )
    verify_pure_definition_types(definitions, {})
    source, _ = compile_query("exists")
    compiled = _compile(
        {
            "exists": {
                "collection": "inventory.items",
                "as": "item",
                "where": {"call": {"ref": "ignore", "args": {"unused": {"ceil_div": [1, 0]}}}},
            }
        },
        ports=replace(source._ports, pure_definitions=definitions),
    )
    assert compile_invariant_admission(compiled)(roots()) is True
    assert compiled.admits(roots()) is True


def test_inline_generation_keeps_depth_limit_and_interpreter_fallback(monkeypatch):
    guard = {"exists": {"collection": "inventory.items", "as": "item", "where": True}}
    for _ in range(8):
        guard = {"not": guard}
    compiled = _compile(guard)
    execute = compile_invariant_admission(compiled)
    calls = []
    original = values._eval

    def evaluate(node, *args):
        calls.append(node.operation)
        return original(node, *args)

    monkeypatch.setattr(values, "_eval", evaluate)
    assert execute(roots()) is True
    assert calls[0] == "not"


def legacy_emission(node, depth=0):
    """Independent node-qualification oracle for the pre-inline helper boundaries."""
    visited = [node]
    if type(node) is not C0Expression or node.stage != "admission" or depth >= 6:
        return visited
    operation, operand = node.operation, node.operand
    if operation in ("eq", "le", "lt", "all", "any"):
        children = operand
    elif operation in ("not", "is_none", "not_none"):
        children = (operand,)
    elif operation == "if":
        children = (operand["when"], operand["then"], operand["else"])
    elif operation == "clause":
        children = (operand["test"],)
    elif operation in OPERATIONS:
        # Old executor(collection) and executor(where) each invoked emit at zero.
        return visited + legacy_emission(operand["collection"]) + legacy_emission(operand["where"])
    else:
        children = ()
    for child in children:
        visited.extend(legacy_emission(child, depth + 1))
    return visited


def generated_nodes(execute):
    closure = dict(zip(execute.__code__.co_freevars, execute.__closure__, strict=True))
    return closure["execute"].cell_contents.__globals__["nodes"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("ordinary_depth", [5, 6])
def test_inline_expands_exactly_legacy_helper_local_nodes(operation, ordinary_depth):
    collection = "inventory.items"
    where = "True"
    for _ in range(ordinary_depth):
        collection = {"if": {"when": True, "then": collection, "else": "inventory.items"}}
        where = {"not": where}
    guard = {operation: {"collection": collection, "as": "item", "where": where}}
    if operation == "count_matching":
        guard = {"eq": [guard, 1]}
    for _ in range(4):
        guard = {"not": guard}
    compiled = _compile(guard)
    execute = compile_invariant_admission(compiled)
    expected = legacy_emission(compiled.guard_ir.expression)
    actual = generated_nodes(execute)
    assert len(actual) == len(expected)
    assert all(left is right for left, right in zip(actual, expected, strict=True))
    assert outcome(execute, roots()) == outcome(compiled.admits, roots())


def test_inline_helper_budget_resets_do_not_reenter_interpreter(monkeypatch):
    collection = "inventory.items"
    where = "True"
    for _ in range(5):
        collection = {"if": {"when": True, "then": collection, "else": "inventory.items"}}
        where = {"not": where}
    guard = {"exists": {"collection": collection, "as": "item", "where": where}}
    for _ in range(5):
        guard = {"not": guard}
    compiled = _compile(guard)
    execute = compile_invariant_admission(compiled)
    expected = compiled.admits(roots())

    def forbidden(*args, **kwargs):
        pytest.fail("legacy-qualified helper subtree fell back to interpreter")

    monkeypatch.setattr(values, "_eval", forbidden)
    assert execute(roots()) is expected


def test_inline_where_depth_six_still_falls_back_at_legacy_boundary(monkeypatch):
    where = True
    for _ in range(6):
        where = {"not": where}
    compiled, node = compile_query("exists", where=where)
    execute = compile_invariant_admission(compiled)
    leaf = node.operand["where"]
    for _ in range(6):
        leaf = leaf.operand
    calls = []
    original = values._eval

    def evaluate(current, *args):
        calls.append(current)
        return original(current, *args)

    monkeypatch.setattr(values, "_eval", evaluate)
    assert execute(roots()) is True
    assert len(calls) == 1 and calls[0] is leaf


def test_inline_nested_helper_resets_keep_current_outer_alias(monkeypatch):
    where = {"eq": ["other.value", "item.value"]}
    for _ in range(4):
        where = {"not": where}
    nested = {"exists": {"collection": "inventory.items", "as": "other", "where": where}}
    for _ in range(5):
        nested = {"not": nested}
    compiled = _compile(
        {
            "eq": [
                {
                    "count_matching": {
                        "collection": "inventory.items",
                        "as": "item",
                        "where": nested,
                    }
                },
                0,
            ]
        }
    )
    execute = compile_invariant_admission(compiled)
    expected = compiled.admits(roots())

    def forbidden(*args, **kwargs):
        pytest.fail("nested helper-local budget was tightened")

    monkeypatch.setattr(values, "_eval", forbidden)
    assert execute(roots()) is expected
    assert expected is True


@pytest.mark.parametrize("layers,mixed_branches", [(50, False), (25, True)])
def test_legal_deep_exists_compile_and_use_bounded_static_blocks(
    monkeypatch, layers, mixed_branches
):
    guard = True
    for index in range(layers):
        if mixed_branches:
            guard = {"any": [False, guard]}
        guard = {
            "exists": {
                "collection": {"ref": "inventory.items"},
                "as": f"row{index}",
                "where": guard,
            }
        }
    compiled = _compile(guard)
    current = {"inventory": Inventory((Item("a", 1),), "a")}
    assert compiled.admits(current) is True
    execute = compile_invariant_admission(compiled)
    calls = []
    original = values._eval

    def evaluate(node, *args):
        calls.append(node.operation)
        return original(node, *args)

    monkeypatch.setattr(values, "_eval", evaluate)
    assert execute(current) is True
    assert calls
    empty = {"inventory": Inventory((), "a")}
    assert execute(empty) is False
    assert compiled.admits(empty) is False
