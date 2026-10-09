"""Runtime metadata work stays local without caching states or permission proofs."""

from copy import copy
from dataclasses import InitVar, dataclass, field, fields, replace
from typing import ClassVar

import pytest
from nomos_kernel import K0OccurrenceRef
from test_local_computation_v1 import Sample, State, const, ports, program, state

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.expression_ir_v1 import C0Expression, closed_value_type


@pytest.mark.parametrize(
    "operation,results,expected,visited",
    [
        ("all", (), True, 0),
        ("any", (), False, 0),
        ("all", (True, False, "unreachable"), False, 2),
        ("any", (False, True, "unreachable"), True, 2),
        ("all", (1, "unreachable"), False, 1),
        ("any", (1, True), True, 2),
        ("all", (True, True), True, 2),
        ("any", (False, False), False, 2),
    ],
)
def test_boolean_loops_keep_identity_order_and_short_circuit(
    monkeypatch, operation, results, expected, visited
):
    original = values._eval
    children = tuple(
        C0Expression("const", index, closed_value_type(bool), "admission", str(index))
        for index in range(len(results))
    )
    root = C0Expression(operation, children, closed_value_type(bool), "admission", "guard")
    calls = []

    def evaluate_child(node, context, env, declared):
        index = node.operand
        calls.append(index)
        result = results[index]
        if result == "unreachable":
            pytest.fail("short-circuited child was evaluated")
        return result

    monkeypatch.setattr(values, "_eval", evaluate_child)
    assert original(root, {}, {}, ports()) is expected
    assert calls == list(range(visited))


@pytest.mark.parametrize("operation,prefix", [("all", True), ("any", False)])
def test_boolean_loops_preserve_first_selected_error(monkeypatch, operation, prefix):
    original = values._eval
    children = tuple(
        C0Expression("const", index, closed_value_type(bool), "admission", str(index))
        for index in range(3)
    )
    root = C0Expression(operation, children, closed_value_type(bool), "admission", "guard")
    calls = []

    def evaluate_child(node, context, env, declared):
        calls.append(node.operand)
        if node.operand == 1:
            raise values.C0ValueStateError("first selected failure")
        return prefix

    monkeypatch.setattr(values, "_eval", evaluate_child)
    with pytest.raises(values.C0ValueStateError, match="first selected failure"):
        original(root, {}, {}, ports())
    assert calls == [0, 1]


def test_each_reference_step_checks_current_record_shape_once(monkeypatch):
    calls = []
    original = values._frozen_record

    def checked(carrier):
        calls.append(carrier)
        return original(carrier)

    monkeypatch.setattr(values, "_frozen_record", checked)
    declared = ports()
    for amount in (2, 7):
        assert (
            values._read_ref(
                "state.sample.value", state(sample=Sample(amount)), {"state": State}, declared
            )
            == amount
        )
    assert calls == [State, Sample, State, Sample]


def test_reference_permission_is_rechecked_for_the_selected_ports():
    declared = ports()
    current = state(sample=Sample(2))
    assert values._read_ref("state.sample.value", current, declared.roots, declared) == 2
    denied = replace(declared, readable_fields={State: declared.readable_fields[State]})
    with pytest.raises(C0LawError, match="read port"):
        values._read_ref("state.sample.value", current, denied.roots, denied)
    with pytest.raises(values.C0ValueStateError, match="nullable"):
        values._read_ref("state.sample.value", state(), declared.roots, declared)


def test_record_shape_is_not_cached_across_evaluations(monkeypatch):
    compiled = program(outputs={"value": {"ref": "state.count"}})
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 3}
    monkeypatch.setattr(State.__dataclass_fields__["count"], "init", False)
    with pytest.raises(values.C0ValueStateError, match="malformed"):
        compiled.evaluate(state(), occurrence=K0OccurrenceRef(2))


def test_shape_scan_filters_pseudo_fields_like_dataclasses_fields(monkeypatch):
    @dataclass(frozen=True)
    class WithPseudoFields:
        value: int
        class_value: ClassVar[int] = field(default=1, init=False)
        opening: InitVar[int] = field(default=2, init=False)

    assert tuple(item.name for item in fields(WithPseudoFields)) == ("value",)
    assert values._frozen_record(WithPseudoFields)
    monkeypatch.setattr(WithPseudoFields.__dataclass_fields__["value"], "init", False)
    assert not values._frozen_record(WithPseudoFields)


def test_shape_scan_rechecks_nonselected_fields_and_replaced_metadata(monkeypatch):
    compiled = program(outputs={"value": {"ref": "state.count"}})
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 3}
    with monkeypatch.context() as patch:
        patch.setattr(State.__dataclass_fields__["secret"], "init", False)
        with pytest.raises(values.C0ValueStateError, match="malformed"):
            compiled.evaluate(state(), occurrence=K0OccurrenceRef(2))
    assert compiled.evaluate(state(5), occurrence=K0OccurrenceRef(3)) == {"value": 5}
    with monkeypatch.context() as patch:
        replaced = dict(State.__dataclass_fields__)
        replaced["count"] = copy(State.__dataclass_fields__["count"])
        patch.setattr(State, "__dataclass_fields__", replaced)
        patch.setattr(replaced["count"], "init", False)
        with pytest.raises(values.C0ValueStateError, match="malformed"):
            compiled.evaluate(state(), occurrence=K0OccurrenceRef(4))


@pytest.mark.parametrize(
    "annotation,valid,invalid",
    [
        (int, 1, True),
        (bool, True, 1),
        (type(None), None, False),
        (Sample, Sample(3), State(3, True, None, 1)),
        (int | None, None, True),
        (tuple[int, ...], (1, 2), (1, True)),
        (tuple[int, str], (1, "x"), (1, 2)),
        (tuple[()], (), (1,)),
    ],
)
def test_fast_nominal_match_preserves_exact_and_compound_types(annotation, valid, invalid):
    assert values._value_matches(valid, annotation)
    assert not values._value_matches(invalid, annotation)


def test_direct_operation_dispatch_retains_short_circuit(monkeypatch):
    compiled = program(
        guard={"eq": [const(1), const(1)]},
        outputs={
            "value": {
                "if": {
                    "when": {"eq": [const(True), const(False)]},
                    "then": {"ceil_div": [const(1), const(0)]},
                    "else": const(7),
                }
            }
        },
    )

    def forbid_membership(*args):
        pytest.fail("operation dispatch inspected the Mapping facade")

    monkeypatch.setattr(values.C0Expression, "__contains__", forbid_membership)
    monkeypatch.setattr(values.C0Expression, "__getitem__", forbid_membership)
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 7}


@pytest.mark.parametrize("amount,sample", [(1, None), (4, Sample(2)), (7, Sample(8))])
def test_binding_free_guard_matches_full_context_without_mutating_roots(amount, sample):
    compiled = program(
        guard={
            "all": [
                {"le": [{"ref": "state.count"}, const(4)]},
                {
                    "any": [
                        {"is_none": {"ref": "state.sample"}},
                        {
                            "all": [
                                {"not_none": {"ref": "state.sample"}},
                                {"eq": [{"ref": "state.sample.value"}, const(2)]},
                            ]
                        },
                    ]
                },
            ]
        },
    )
    roots = state(amount, sample=sample)
    before = dict(roots)
    assert compiled.admits(roots) == (compiled._admitted_context(roots) is not None)
    assert roots == before and roots["state"] is before["state"]
    assert compiled.admits(state(9, sample=sample)) is False
    with pytest.raises(values.C0ValueStateError, match="wrong owner roots"):
        compiled.admits({})
    with pytest.raises(values.C0ValueStateError, match="foreign nominal root"):
        compiled.admits({"state": Sample(1)})
