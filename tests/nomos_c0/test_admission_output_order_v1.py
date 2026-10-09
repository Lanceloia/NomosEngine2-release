"""Admission subsets retain source order, including the first range failure."""

import json
from dataclasses import dataclass

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0.composable_value_v1 import (
    C0ValuePorts,
    C0ValueRangeError,
    compile_value_program,
)


@dataclass(frozen=True)
class Record:
    number: int


def _compile(outputs, selected):
    fields = {Record: frozenset({"number"})}
    paths = frozenset({"record.number"})
    ports = C0ValuePorts(
        roots={"record": Record},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={name: int for name in outputs},
    )
    return compile_value_program(
        json.dumps({"schema": "c0.value.v1", "bindings": [], "guard": True, "outputs": outputs}),
        ports,
        admission_outputs=frozenset(selected),
    )


def test_admission_and_complete_evaluation_fail_at_the_same_declared_first_output():
    names = tuple(f"out{index}" for index in range(8))
    first = next(name for name in names if name != next(iter(frozenset(names))))
    order = (first,) + tuple(name for name in names if name != first)
    program = _compile(
        {name: {"sub": [0, 1]} if name == first else {"ceil_div": [1, 0]} for name in order},
        names,
    )
    roots = {"record": Record(0)}
    with pytest.raises(C0ValueRangeError, match="subtraction"):
        program.evaluate_admission_outputs(roots)
    with pytest.raises(C0ValueRangeError, match="subtraction"):
        program.evaluate(roots, occurrence=K0OccurrenceRef(1))


@pytest.mark.parametrize("selected", [(), ("last", "first")])
def test_admission_subset_preserves_order_without_evaluating_unselected_outputs(selected):
    program = _compile({"first": 2, "unused": {"ceil_div": [1, 0]}, "last": 3}, selected)
    result = program.evaluate_admission_outputs({"record": Record(0)})
    assert tuple(result) == (() if not selected else ("first", "last"))
    assert result == ({} if not selected else {"first": 2, "last": 3})
