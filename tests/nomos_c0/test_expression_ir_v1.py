"""Run consumes checked operations, never author containers or type inference."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.expression_ir_v1 import C0Expression, C0ValueType, _ExpressionDraft
from nomos_c0.owner_graph_v1 import compile_owner_graph


@dataclass(frozen=True)
class Item:
    key: str
    value: int


@dataclass(frozen=True)
class Inventory:
    items: tuple[Item, ...]
    wanted: str


def _program():
    ports = C0ValuePorts(
        roots={"inventory": Inventory},
        readable_paths=frozenset({"inventory.items", "inventory.wanted"}),
        admission_readable_paths=frozenset({"inventory.items", "inventory.wanted"}),
        readable_fields={
            Inventory: frozenset({"items", "wanted"}),
            Item: frozenset({"key", "value"}),
        },
        admission_readable_fields={
            Inventory: frozenset({"items", "wanted"}),
            Item: frozenset({"key", "value"}),
        },
        writable_fields={Item: frozenset({"value"})},
        record_types={"Item": Item},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={"inventory.items": "key"},
        outputs={"changed": tuple[Item, ...], "appended": tuple[Item, ...], "count": int},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [
            {"name": "floor", "const": 0},
            {
                "name": "selected",
                "collection": "inventory.items",
                "key": "key",
                "value": {"ref": "inventory.wanted"},
                "required": True,
            },
        ],
        "guard": {"le": [{"ref": "floor"}, {"ref": "selected.value"}]},
        "outputs": {
            "changed": {
                "replace_unique": {
                    "collection": {"ref": "inventory.items"},
                    "old": {"ref": "selected"},
                    "new": {
                        "copy": {
                            "from": {"ref": "selected"},
                            "changes": {
                                "value": {"add": [{"ref": "selected.value"}, {"const": 1}]},
                            },
                        }
                    },
                    "key": "key",
                }
            },
            "appended": {
                "append": [
                    {"ref": "inventory.items"},
                    {
                        "record": {
                            "type": "Item",
                            "fields": {"key": {"const": "new"}, "value": {"ref": "floor"}},
                        }
                    },
                ]
            },
            "count": {
                "count_matching": {
                    "collection": {"ref": "inventory.items"},
                    "as": "item",
                    "where": {"lt": [{"ref": "floor"}, {"ref": "item.value"}]},
                }
            },
        },
    }
    return compile_value_program(json.dumps(source), ports, admission_outputs=frozenset({"count"}))


def _nodes(value):
    if isinstance(value, C0Expression):
        yield value
        yield from _nodes(value.operand)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _nodes(item)
    elif type(value) is tuple:
        for item in value:
            yield from _nodes(item)


def _forbid_frontend(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("runtime called the expression frontend")

    for name in ("_expr_type", "_infer_expr_type", "_prepare_expression", "_compile_expression"):
        monkeypatch.setattr(values, name, forbidden)
    monkeypatch.setattr(json, "loads", forbidden)


@pytest.mark.parametrize("draft", [False, True])
def test_operation_membership_matches_mapping_without_missing_key_exceptions(monkeypatch, draft):
    node = (
        _ExpressionDraft("const", 3, "guard")
        if draft
        else C0Expression("const", 3, C0ValueType("nominal", int), "admission", "guard")
    )
    assert dict(node) == {"const": 3}
    assert node.get("const") == 3 and node.get("unknown") is None
    for key in ("unknown", None, 3, ("const",)):
        assert key not in node
        with pytest.raises(KeyError):
            node[key]
    assert "const" in node

    def forbid_lookup(*args):
        pytest.fail("operation membership used an exception-based lookup")

    monkeypatch.setattr(type(node), "__getitem__", forbid_lookup)
    assert "const" in node and "unknown" not in node


def test_nodes_carry_type_stage_and_origin_and_are_deeply_immutable():
    program = _program()
    assert program.guard_ir.expression.result_type is bool
    for node in _nodes(program.guard_ir.expression):
        assert node.stage == "admission"
        assert node.origin.startswith("guard")
    for node in _nodes(program._tree["outputs"]["changed"]):
        assert node.stage == "effect"
        assert node.origin.startswith("outputs.changed")
        assert node.result_type is not None
    assert program._tree["outputs"]["count"].stage == "admission"
    with pytest.raises(FrozenInstanceError):
        program.guard_ir.expression.origin = "rewritten"
    with pytest.raises(TypeError):
        program._tree["outputs"]["changed"]["replace_unique"]["old"] = {"const": None}


def test_lookup_collection_updates_and_admission_outputs_need_no_runtime_frontend(monkeypatch):
    program = _program()
    roots = {"inventory": Inventory((Item("old", 3),), "old")}
    _forbid_frontend(monkeypatch)
    assert program.admits(roots)
    assert program.evaluate_admission_outputs(roots) == {"count": 1}
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(7)) == {
        "changed": (Item("old", 4),),
        "appended": (Item("old", 3), Item("new", 0)),
        "count": 1,
    }
    assert roots["inventory"].items == (Item("old", 3),)
    with pytest.raises(C0ValueStateError, match="unique lookup"):
        program.admits({"inventory": Inventory((), "missing")})


def test_evaluator_rejects_raw_source_and_effect_stage_before_admission():
    program = _program()
    context = {"inventory": Inventory((Item("old", 3),), "old")}
    with pytest.raises(C0ValueStateError, match="checked expression"):
        values._eval({"const": True}, context, program._ports.roots, program._ports)
    with pytest.raises(C0ValueStateError, match="before admission"):
        values._eval(
            program._tree["outputs"]["changed"], context, program._ports.roots, program._ports
        )


def test_typed_participant_offers_and_real_k0_action_need_no_runtime_frontend(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
    lib, ports, source, assets = (
        read_author_document(root / f"multi_participant_v0.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )
    program = compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    declaration = program.seats[0].offers[0]
    assert declaration.condition.stage == "admission"
    assert declaration.condition.origin == "offers[0].when"
    assert all(type(value) is C0Expression for value in declaration.payload.values())
    with pytest.raises(TypeError):
        declaration.payload["tool"] = {"const": None}
    session = program.start(assets)
    _forbid_frontend(monkeypatch)
    offer = session.offers("maker")[0]
    outcome = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(outcome, K0Published)
    assert dict(session.author_snapshot().owners)["a"].enabled is True
    assert outcome.occurrences[0].source == dict(program.actions)[offer.entry].source_key
