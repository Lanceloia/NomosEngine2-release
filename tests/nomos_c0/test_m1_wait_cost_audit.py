"""The diagnostic native oracle keeps the value boundary, not a fake Session."""

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from tools.c0_audit_m1_wait import checked_native_wait, expression_comparison, is_wait


@dataclass(frozen=True)
class Actor:
    name: str


@dataclass(frozen=True)
class Payload:
    actor: str


def compiled_wait():
    paths = frozenset({"actor.name", "payload.actor"})
    fields = {Actor: frozenset({"name"}), Payload: frozenset({"actor"})}
    ports = C0ValuePorts(
        roots={"actor": Actor, "payload": Payload},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"action": K0OccurrenceRef, "last_action_ref": K0OccurrenceRef},
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"eq": [{"ref": "actor.name"}, {"ref": "payload.actor"}]},
        "outputs": {"action": {"ref": "occurrence"}, "last_action_ref": {"ref": "occurrence"}},
    }
    return compile_value_program(json.dumps(source), ports)


@pytest.mark.parametrize("target", ["adventurer", "other"])
def test_native_and_compiled_match_true_and_false_guards(target):
    program = compiled_wait()
    roots = {"actor": Actor("adventurer"), "payload": Payload(target)}
    occurrence = K0OccurrenceRef(5)
    assert is_wait(program)
    assert checked_native_wait(program, roots, occurrence=occurrence) == program.evaluate(
        roots, occurrence=occurrence
    )


@pytest.mark.parametrize(
    "roots,occurrence",
    [
        ({"actor": Actor("a"), "payload": Payload("a")}, None),
        ({"actor": Actor("a"), "payload": Payload("a")}, 1),
        ({"actor": Payload("a"), "payload": Payload("a")}, K0OccurrenceRef(1)),
        ({"actor": Actor("a")}, K0OccurrenceRef(1)),
    ],
)
def test_native_preserves_malformed_root_and_occurrence_rejection(roots, occurrence):
    program = compiled_wait()
    for evaluator in (
        program.evaluate,
        lambda roots, **kwargs: checked_native_wait(program, roots, **kwargs),
    ):
        with pytest.raises(C0ValueStateError):
            evaluator(roots, occurrence=occurrence)


def test_false_guard_does_not_need_future_occurrence():
    program = compiled_wait()
    roots = {"actor": Actor("a"), "payload": Payload("b")}
    assert program.evaluate(roots) is checked_native_wait(program, roots) is None


def test_native_rechecks_output_type_contract():
    program = compiled_wait()
    roots = {"actor": Actor("a"), "payload": Payload("a")}
    # This diagnostic mutation is not an author or production binding path.
    object.__setattr__(
        program,
        "_runtime_ports",
        replace(program._ports, outputs={"action": str, "last_action_ref": str}),
    )
    for evaluator in (
        program.evaluate,
        lambda roots, **kwargs: checked_native_wait(program, roots, **kwargs),
    ):
        with pytest.raises(C0ValueStateError):
            evaluator(roots, occurrence=K0OccurrenceRef(1))


def test_measurement_is_expression_only_and_rejects_other_laws():
    program = compiled_wait()
    roots = {"actor": Actor("a"), "payload": Payload("a")}
    report = expression_comparison(program, roots, K0OccurrenceRef(1), 2)
    assert "no Session equivalence" in report["boundary"]
    assert all(len(samples) == 4 for samples in report["seconds_per_evaluation"].values())
    object.__setattr__(program, "_tree", {"bindings": (), "outputs": {}})
    with pytest.raises(ValueError, match="exact authored wait"):
        expression_comparison(program, roots, K0OccurrenceRef(1), 2)
