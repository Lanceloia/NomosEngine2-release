"""Text count is a bounded query, never a Python generator executed at Run."""

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_expression_ir_v1 import Inventory, Item, _program

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import compile_value_program, verify_pure_definition_types
from nomos_c0.condition_source_v0 import lower_author_expression
from nomos_c0.expression_read_authority_v1 import check_expression_reads
from nomos_c0.pure_definition_v1 import check_pure_definitions


def _compile(guard, *, ports=None):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": guard,
                "outputs": {
                    "count": "count(item for item in inventory.items if item.value > 0)",
                    "changed": {"ref": "inventory.items"},
                    "appended": {"ref": "inventory.items"},
                },
            }
        ),
        ports or _program()._ports,
    )


def test_text_count_lowers_to_the_existing_query_and_preserves_source_location():
    text = "count(path for path in scene.bridge_paths if path.start == actor.site) == 1"
    tree, origins = lower_author_expression(text, path="guard.bridge")
    assert tree == {
        "eq": [
            {
                "count_matching": {
                    "collection": {"ref": "scene.bridge_paths"},
                    "as": "path",
                    "where": {"eq": [{"ref": "path.start"}, {"ref": "actor.site"}]},
                }
            },
            {"const": 1},
        ]
    }
    assert set(origins.values()) == {"guard.bridge"}


@pytest.mark.parametrize(
    "items,admitted", [([], False), ([1], True), ([1, 2], False), ([-1, 2], True)]
)
@pytest.mark.parametrize("predicate", ["count({query}) == 1", "exactly_one({query})"])
def test_checked_count_handles_empty_unique_duplicate_and_filtered_rows(items, admitted, predicate):
    program = _compile(predicate.format(query="item for item in inventory.items if item.value > 0"))
    roots = {
        "inventory": Inventory(tuple(Item(str(i), value) for i, value in enumerate(items)), "0")
    }
    assert program.admits(roots) is admitted
    result = program.evaluate(roots, occurrence=K0OccurrenceRef(1))
    if admitted:
        assert result["count"] == 1
        assert result["changed"] == roots["inventory"].items
    else:
        assert result is None


def test_nested_queries_keep_distinct_lexical_aliases():
    text = (
        "count(item for item in inventory.items if "
        "count(other for other in inventory.items if other.value == item.value) == 1) == 1"
    )
    program = _compile(text)
    assert program.admits({"inventory": Inventory((Item("a", 3),), "a")})
    assert not program.admits({"inventory": Inventory((Item("a", 3), Item("b", 3)), "a")})


@pytest.mark.parametrize(
    "text",
    [
        "count(inventory.items)",
        "count(item for item in inventory.items)",
        "count(item.value for item in inventory.items if True)",
        "count(item for item in range(3) if True)",
        "count(item for item in inventory.items if True if True)",
        "count(item for item in inventory.items for other in inventory.items if True)",
        "count(item for item in inventory.items if True, extra=True)",
        "count(item async for item in inventory.items if True)",
        "sum(item for item in inventory.items if True)",
        "count(item for item in inventory.items if item.value())",
    ],
)
def test_non_query_python_constructs_are_rejected(text):
    with pytest.raises(C0LawError):
        lower_author_expression(text)


@pytest.mark.parametrize(
    "guard",
    [
        "count(inventory for inventory in inventory.items if True) == 1",
        "count(item for item in inventory.items if item.value) == 1",
        "count(item for item in inventory.wanted if True) == 1",
        "count(item for item in inventory.items if True) == item.value",
    ],
)
def test_shadowing_wrong_types_and_alias_escape_are_rejected_by_the_same_ir_checker(guard):
    with pytest.raises(C0LawError):
        _compile(guard)


def test_text_count_does_not_grant_field_read_permission():
    ports = _program()._ports
    ports = replace(
        ports,
        admission_readable_fields={**ports.admission_readable_fields, Item: frozenset({"key"})},
    )
    with pytest.raises(C0LawError):
        _compile("count(item for item in inventory.items if item.value > 0) == 1", ports=ports)


@pytest.mark.parametrize("operation", ["exists", "exactly_one"])
@pytest.mark.parametrize("items", [[], [1], [1, 2], [-1, 1]])
def test_declared_predicate_is_preserved_as_typed_boolean_ir(operation, items):
    predicate = {
        operation: {"collection": "inventory.items", "as": "item", "where": "item.value > 0"}
    }
    program = _compile(predicate)
    expression = program.guard_ir.expression
    assert expression.operation == operation
    assert expression.result_type is bool and expression.stage == "admission"
    assert (
        lower_author_expression(predicate)[0]
        == lower_author_expression(
            f"{operation}(item for item in inventory.items if item.value > 0)"
        )[0]
    )
    roots = {
        "inventory": Inventory(tuple(Item(str(i), value) for i, value in enumerate(items)), "0")
    }
    count = sum(value > 0 for value in items)
    assert program.admits(roots) is (count > 0 if operation == "exists" else count == 1)
    check_expression_reads(expression, program._ports, {"inventory": Inventory})
    with pytest.raises(C0LawError):
        check_expression_reads(expression, program._ports, {})


@pytest.mark.parametrize(
    "operation,visited",
    [("exists", ["0"]), ("none_matching", ["0"]), ("exactly_one", ["0", "1"])],
)
def test_predicate_stops_when_truth_is_decided_without_evaluating_the_remaining_rows(
    monkeypatch, operation, visited
):
    program = _compile(
        {operation: {"collection": "inventory.items", "as": "item", "where": "item.value > 0"}}
    )
    read = []
    original = values._eval

    def observed(node, context, *args, **kwargs):
        if node.operation == "ref" and node.operand == "item.value":
            read.append(context["item"].key)
        return original(node, context, *args, **kwargs)

    monkeypatch.setattr(values, "_eval", observed)
    roots = {"inventory": Inventory((Item("0", 1), Item("1", 2), Item("2", 3)), "0")}
    assert program.admits(roots) is (operation == "exists")
    assert read == visited


@pytest.mark.parametrize("operation", ["exists", "exactly_one"])
def test_semantic_predicate_keeps_type_scope_and_field_authority_checks(operation):
    for collection, alias, where in [
        ("inventory.items", "inventory", "True"),
        ("inventory.items", "item", "item.value"),
        ("inventory.wanted", "item", "True"),
    ]:
        with pytest.raises(C0LawError):
            _compile({operation: {"collection": collection, "as": alias, "where": where}})
    ports = _program()._ports
    ports = replace(
        ports,
        admission_readable_fields={**ports.admission_readable_fields, Item: frozenset({"key"})},
    )
    with pytest.raises(C0LawError):
        _compile(
            {operation: {"collection": "inventory.items", "as": "item", "where": "item.value > 0"}},
            ports=ports,
        )


@pytest.mark.parametrize("operation", ["exists", "exactly_one"])
def test_lib_predicate_is_closed_and_preserves_caller_read_authority(operation):
    raw = [
        {
            "name": "selected",
            "parameters": {"items": {"tuple": "Item"}},
            "result": "bool",
            "stage": "admission",
            "body": {operation: {"collection": "items", "as": "item", "where": "item.value > 0"}},
        }
    ]
    definitions = check_pure_definitions(raw, {"Item": Item})
    verify_pure_definition_types(definitions, {"Item": Item})
    ports = replace(_program()._ports, pure_definitions=definitions)
    guard = {"call": {"ref": "selected", "args": {"items": {"ref": "inventory.items"}}}}
    program = _compile(guard, ports=ports)
    assert program.admits({"inventory": Inventory((Item("a", 1),), "a")})
    check_expression_reads(program.guard_ir.expression, ports, {"inventory": Inventory})
    ports = replace(
        ports,
        admission_readable_fields={**ports.admission_readable_fields, Item: frozenset({"key"})},
    )
    with pytest.raises(C0LawError):
        _compile(guard, ports=ports)
    raw[0]["body"][operation]["as"] = "items"
    with pytest.raises(C0LawError, match="shadows"):
        check_pure_definitions(raw, {"Item": Item})


@pytest.mark.parametrize("operation", ["exists", "exactly_one"])
def test_output_family_alias_cannot_be_shadowed_by_predicate(operation):
    from test_output_family_v1 import _compile as compile_family
    from test_output_family_v1 import _source as family_source

    source = family_source({operation: {"collection": "one.name", "as": "person", "where": True}})
    with pytest.raises(C0LawError, match="alias.*shadowed"):
        compile_family(source)
