"""Resource effects couple admission and state outputs across neutral records."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program


@dataclass(frozen=True)
class Supply:
    stock: int
    mirrored: int
    cost: int = 1
    minimum: int = 0
    secret: int = 99
    permitted: bool = True
    known: int | None = None
    maybe_cost: int | None = None


def _ports():
    names = frozenset({"stock", "mirrored", "cost", "minimum", "permitted", "known", "maybe_cost"})
    paths = frozenset(f"supply.{name}" for name in names)
    return C0ValuePorts(
        roots={"supply": Supply},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields={Supply: names},
        admission_readable_fields={Supply: names},
        writable_fields={Supply: frozenset({"stock", "mirrored", "permitted", "known"})},
        writable_paths=frozenset(
            {"supply.stock", "supply.mirrored", "supply.permitted", "supply.known"}
        ),
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"stock": int, "mirrored": int, "action": K0OccurrenceRef},
    )


def _source():
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"require": [{"allowed": "supply.permitted"}]},
        "effects": [
            {
                "spend": {
                    "debit": "supply.stock",
                    "amount": "supply.cost",
                    "floor": "supply.minimum",
                    "mirror": ["supply.mirrored"],
                }
            }
        ],
        "outputs": {"action": {"ref": "occurrence"}},
    }


def _compile(source=None, ports=None, mapping=None):
    return compile_value_program(
        json.dumps(_source() if source is None else source, sort_keys=True),
        _ports() if ports is None else ports,
        state_outputs={"supply.stock": "stock", "supply.mirrored": "mirrored"}
        if mapping is None
        else mapping,
    )


@pytest.mark.parametrize(
    "balance,cost,floor,remaining",
    [(1, 1, 0, 0), (5, 2, 1, 3), (5, 4, 1, 1), ((1 << 63) - 1, 1, 0, (1 << 63) - 2)],
)
def test_debit_and_explicit_mirror_share_current_input(balance, cost, floor, remaining):
    program = _compile()
    roots = {"supply": Supply(balance, 999, cost, floor)}
    assert program.admits(roots)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(7)) == {
        "stock": remaining,
        "mirrored": remaining,
        "action": K0OccurrenceRef(7),
    }
    assert roots["supply"].stock == balance


@pytest.mark.parametrize(
    "balance,cost,floor,label",
    [
        (0, 1, 0, "sufficient"),
        (5, 0, 0, "positive_amount"),
        (5, -1, 0, "positive_amount"),
        (5, 1, -1, "nonnegative_floor"),
        (0, 1, 1, "above_floor"),
        (-1, 1, 0, "above_floor"),
        ((1 << 63), 1, 0, "bounded_balance"),
        (5, (1 << 63), 0, "sufficient"),
        (5, 1, (1 << 63), "above_floor"),
    ],
)
def test_invalid_or_insufficient_resource_refuses_before_subtraction(balance, cost, floor, label):
    program = _compile()
    roots = {"supply": Supply(balance, 99, cost, floor)}
    assert not program.admits(roots)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(7)) is None
    (failure,) = program.false_guard_clauses(roots)
    assert failure.path == f"effects.spend.{label}"


def test_original_guard_still_short_circuits_resource_checks_and_preserves_names():
    program = _compile()
    (failure,) = program.false_guard_clauses({"supply": Supply(-1, 999, permitted=False)})
    assert failure.names == ("allowed",)
    assert failure.path == "guard.require.allowed"


def test_effect_ir_points_to_the_one_immutable_runtime_tree():
    program = _compile()
    effect = program.effects[0]
    assert effect.checks is program.guard_ir.expression["all"][1]["all"][0]
    assert dict(effect.results)["stock"] is program._tree["outputs"]["stock"]
    assert effect.writes == (("supply.stock", "stock"), ("supply.mirrored", "mirrored"))
    assert "effects" not in program._tree
    with pytest.raises(TypeError):
        effect.checks["all"] = ()
    with pytest.raises(TypeError):
        dict(effect.results)["stock"]["sub"] = ()


def test_pure_view_cannot_author_state_debits():
    with pytest.raises(C0LawError, match="state write graph"):
        compile_value_program(json.dumps(_source()), _ports())


def test_all_effects_read_one_pre_state_instead_of_the_previous_effect_result():
    source = _source()
    del source["effects"][0]["spend"]["mirror"]
    source["effects"].append(
        {"other": {"debit": "supply.mirrored", "amount": "supply.stock", "floor": 0}}
    )
    result = _compile(source).evaluate({"supply": Supply(3, 10)}, occurrence=K0OccurrenceRef(1))
    assert result["stock"] == 2
    assert result["mirrored"] == 7


def test_known_optional_integer_is_an_explicit_write_not_a_required_read():
    source = _source()
    source["effects"][0]["spend"]["mirror"] = ["supply.known"]
    ports = replace(
        _ports(), admission_readable_paths=_ports().admission_readable_paths - {"supply.known"}
    )
    program = _compile(source, ports, {"supply.stock": "stock", "supply.known": "mirrored"})
    result = program.evaluate({"supply": Supply(3, 999, known=None)}, occurrence=K0OccurrenceRef(1))
    assert result["mirrored"] == 2


def test_optional_cost_needs_the_original_guards_nonnull_proof():
    source = _source()
    source["effects"][0]["spend"]["amount"] = "supply.maybe_cost"
    with pytest.raises(C0LawError, match="admission integers"):
        _compile(source)
    source["guard"]["require"].append({"cost_known": "supply.maybe_cost is not None"})
    program = _compile(source)
    assert not program.admits({"supply": Supply(3, 99)})
    result = program.evaluate(
        {"supply": Supply(3, 99, maybe_cost=2)}, occurrence=K0OccurrenceRef(1)
    )
    assert result["stock"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"debit": "supply.secret"},
        {"debit": {"ref": "supply.stock"}},
        {"amount": True},
        {"amount": "supply.secret"},
        {"amount": {"ref": "occurrence"}},
        {"amount": {"die_roll": {"seed": 1, "sides": 6}}},
        {"floor": False},
        {"mirror": ["supply.secret"]},
        {"mirror": ["supply.stock"]},
        {"mirror": ["supply.mirrored", "supply.mirrored"]},
        {"unknown": 1},
    ],
)
def test_effects_cannot_bypass_stage_type_permission_or_overlap_checks(change):
    source = _source()
    source["effects"][0]["spend"].update(change)
    with pytest.raises(C0LawError):
        _compile(source)


@pytest.mark.parametrize("declarations", [[], {}, None, [{"a": {}, "b": {}}], [{"_bad": {}}]])
def test_malformed_effect_declarations_are_rejected(declarations):
    source = _source()
    source["effects"] = declarations
    with pytest.raises(C0LawError):
        _compile(source)


def test_repeated_names_and_effect_writes_are_not_ordered_state_mutations():
    for same_name in (False, True):
        source = _source()
        body = deepcopy(source["effects"][0]["spend"])
        source["effects"].append({"spend" if same_name else "spend_again": body})
        with pytest.raises(C0LawError, match="repeated|overlaps"):
            _compile(source)


def test_explicit_output_cannot_override_an_effect_result():
    source = _source()
    source["outputs"]["stock"] = 99
    with pytest.raises(C0LawError, match="overlaps"):
        _compile(source)


@pytest.mark.parametrize(
    "mapping",
    [
        {"supply.stock": []},
        {"supply.stock": "unknown"},
        {"supply.cost": "stock"},
        {"supply.stock": "stock", "supply.mirrored": "stock"},
        {"supply.stock.nested": "stock"},
        {"unknown.stock": "stock"},
    ],
)
def test_checked_output_graph_rejects_foreign_or_aliased_endpoints(mapping):
    with pytest.raises(C0LawError, match="write graph"):
        _compile(mapping=mapping)


def test_effect_reads_must_be_granted_before_admission():
    ports = _ports()
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(
            ports=replace(
                ports,
                admission_readable_paths=ports.admission_readable_paths - {"supply.stock"},
            )
        )


def test_readable_bool_state_cannot_be_treated_as_an_integer_resource():
    source = _source()
    source["effects"][0]["spend"]["debit"] = "supply.permitted"
    ports = replace(_ports(), outputs={"stock": bool, "mirrored": int, "action": K0OccurrenceRef})
    with pytest.raises(C0LawError, match="admission integers"):
        _compile(source, ports, {"supply.permitted": "stock", "supply.mirrored": "mirrored"})
