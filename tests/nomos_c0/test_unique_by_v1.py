"""Unique keys are checked projections, not repeated pairwise count queries."""

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_expression_ir_v1 import Inventory, Item, _program

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import compile_value_program, verify_pure_definition_types
from nomos_c0.expression_read_authority_v1 import check_expression_reads
from nomos_c0.pure_definition_v1 import check_pure_definitions


def _predicate(keys=None, **changes):
    return {
        "unique_by": {
            "collection": "inventory.items",
            "as": "item",
            "keys": keys if keys is not None else ["item.key"],
            **changes,
        }
    }


def _compile(guard, ports=None):
    return compile_value_program(
        json.dumps(
            {"schema": "c0.value.v1", "bindings": [], "guard": guard, "outputs": {"count": 0}}
        ),
        replace(ports or _program()._ports, outputs={"count": int}, collection_keys={}),
    )


@pytest.mark.parametrize(
    "items,keys,expected",
    [
        ((), ["item.key"], True),
        ((Item("a", 1),), ["item.key"], True),
        ((Item("a", 1), Item("b", 1)), ["item.key"], True),
        ((Item("a", 1), Item("a", 2)), ["item.key"], False),
        ((Item("a", 1), Item("a", 2)), ["item.key", "item.value"], True),
        ((Item("a", 1), Item("a", 1)), ["item.key", "item.value"], False),
        ((Item("a", 1), Item("b", 2)), ["item.value > 0"], False),
    ],
)
def test_single_and_composite_keys_keep_multiplicity_without_mutating_collection(
    items, keys, expected
):
    program = _compile(_predicate(keys))
    expression = program.guard_ir.expression
    assert expression.operation == "unique_by" and expression.result_type is bool
    roots = {"inventory": Inventory(items, "a")}
    assert program.admits(roots) is expected
    assert roots["inventory"].items is items
    check_expression_reads(expression, program._ports, {"inventory": Inventory})
    with pytest.raises(C0LawError):
        check_expression_reads(expression, program._ports, {})


@pytest.mark.parametrize(
    "changes",
    [
        {"keys": []},
        {"keys": ["item.key"] * 9},
        {"keys": "item.key"},
        {"keys": ["inventory.items"]},
        {"keys": [None]},
        {"keys": ["item"]},
        {"keys": [{"if": {"when": True, "then": "item.key", "else": None}}]},
        {"collection": "inventory.wanted"},
        {"as": "inventory"},
        {"as": "_item"},
        {"keys": ["foreign.key"]},
        {"extra": True},
    ],
)
def test_malformed_keys_collections_and_scope_fail_at_compile(changes):
    declaration = _predicate()["unique_by"]
    declaration.update(changes)
    with pytest.raises(C0LawError):
        _compile({"unique_by": declaration})


def test_field_permissions_remain_required_for_each_key_and_second_pass():
    ports = _program()._ports
    denied = replace(
        ports,
        admission_readable_fields={**ports.admission_readable_fields, Item: frozenset({"key"})},
    )
    with pytest.raises(C0LawError):
        _compile(_predicate(["item.key", "item.value"]), denied)
    program = _compile(_predicate(["item.key", "item.value"]))
    denied = replace(ports, readable_fields={**ports.readable_fields, Item: frozenset({"key"})})
    with pytest.raises(C0LawError):
        check_expression_reads(program.guard_ir.expression, denied, {"inventory": Inventory})


def test_pure_definition_keeps_alias_hygiene_and_caller_authority():
    raw = [
        {
            "name": "unique_keys",
            "parameters": {"items": {"tuple": "Item"}},
            "result": "bool",
            "stage": "admission",
            "body": {"unique_by": {"collection": "items", "as": "member", "keys": ["member.key"]}},
        }
    ]
    definitions = check_pure_definitions(raw, {"Item": Item})
    verify_pure_definition_types(definitions, {"Item": Item})
    ports = replace(_program()._ports, pure_definitions=definitions)
    program = _compile(
        {"call": {"ref": "unique_keys", "args": {"items": "inventory.items"}}}, ports
    )
    assert program.admits({"inventory": Inventory((Item("a", 1), Item("b", 2)), "a")})
    assert not program.admits({"inventory": Inventory((Item("a", 1), Item("a", 2)), "a")})
    check_expression_reads(program.guard_ir.expression, ports, {"inventory": Inventory})
    raw[0]["body"]["unique_by"]["as"] = "items"
    with pytest.raises(C0LawError, match="shadows"):
        check_pure_definitions(raw, {"Item": Item})


def test_no_alias_escape_or_output_family_shadow():
    from test_output_family_v1 import _compile as compile_family
    from test_output_family_v1 import _source as family_source

    with pytest.raises(C0LawError):
        _compile({"all": [_predicate(), "item.key == 'a'"]})
    with pytest.raises(C0LawError, match="shadow"):
        compile_family(
            family_source(
                {"unique_by": {"collection": "one.name", "as": "person", "keys": ["person"]}}
            )
        )


def test_key_evaluation_is_linear_and_stops_at_first_duplicate(monkeypatch):
    original = values._eval
    visits = []

    def observed(node, context, *args, **kwargs):
        if node.operation == "ref" and node.operand == "item.key":
            visits.append(context["item"].key)
        return original(node, context, *args, **kwargs)

    monkeypatch.setattr(values, "_eval", observed)
    program = _compile(_predicate())
    items = tuple(Item(str(index), index) for index in range(32))
    assert program.admits({"inventory": Inventory(items, "0")})
    assert len(visits) == 32
    visits.clear()
    assert not program.admits({"inventory": Inventory((items[0], items[0], *items[1:]), "0")})
    assert visits == ["0", "0"]
    visits.clear()
    legacy = _compile(
        {
            "none_matching": {
                "collection": "inventory.items",
                "as": "other",
                "where": {
                    "not": {
                        "exactly_one": {
                            "collection": "inventory.items",
                            "as": "item",
                            "where": "item.key == other.key",
                        }
                    }
                },
            }
        }
    )
    assert legacy.admits({"inventory": Inventory(items, "0")})
    assert len(visits) == 32 * 32


def test_unvisited_malformed_tail_is_not_evaluated_but_visited_wrong_key_is_rejected():
    program = _compile(_predicate())
    roots = {"inventory": Inventory((Item("a", 1), Item("a", 2), Item(None, 3)), "a")}
    assert not program.admits(roots)
    with pytest.raises(values.C0ValueStateError, match="foreign key"):
        program.admits({"inventory": Inventory((Item(None, 3),), "a")})
    with pytest.raises(values.C0ValueStateError, match="foreign element"):
        program.admits({"inventory": Inventory((object(),), "a")})


def test_effect_stage_and_nominal_occurrence_keys_use_the_same_checked_operation():
    ports = replace(_program()._ports, outputs={"result": bool}, collection_keys={})
    program = compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"result": _predicate([{"ref": "occurrence"}])},
            }
        ),
        ports,
    )
    result = program.evaluate(
        {"inventory": Inventory((Item("a", 1),), "a")}, occurrence=K0OccurrenceRef(7)
    )
    assert result == {"result": True}
    result = program.evaluate(
        {"inventory": Inventory((Item("a", 1), Item("b", 2)), "a")}, occurrence=K0OccurrenceRef(7)
    )
    assert result == {"result": False}
    assert program._tree["outputs"]["result"].operation == "unique_by"
    assert program._tree["outputs"]["result"].stage == "effect"


def test_declared_collection_key_remains_a_stronger_independent_contract():
    ports = _program()._ports
    program = compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": _predicate(["item.value"]),
                "outputs": {"count": 0},
            }
        ),
        replace(ports, outputs={"count": int}),
    )
    with pytest.raises(values.C0ValueStateError, match="declared collection key"):
        program.admits({"inventory": Inventory((Item("a", 1), Item("a", 2)), "a")})
