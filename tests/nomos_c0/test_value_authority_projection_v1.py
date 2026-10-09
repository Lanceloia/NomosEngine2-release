"""Project immutable authority once per guard call, never cache world-state results."""

import json
from dataclasses import dataclass

import pytest

from nomos_c0 import composable_value_v1 as module


@dataclass(frozen=True)
class Counter:
    value: int


@pytest.mark.parametrize("binding", [False, True])
@pytest.mark.parametrize("closed_false", [False, True])
def test_each_guard_call_projects_once_and_rechecks_all_current_roots(
    monkeypatch, binding, closed_false
):
    ports = module.C0ValuePorts(
        roots={"left": Counter, "right": Counter},
        readable_paths=frozenset({"left.value", "right.value"}),
        admission_readable_paths=frozenset({"left.value", "right.value"}),
        readable_fields={Counter: frozenset({"value"})},
        admission_readable_fields={Counter: frozenset({"value"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"value": int},
    )
    value = module.compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": (
                    [{"name": "current", "stage": "admission", "let": {"ref": "left.value"}}]
                    if binding
                    else []
                ),
                "guard": (
                    False
                    if closed_false
                    else {
                        "eq": [
                            {"ref": "current" if binding else "left.value"},
                            {"ref": "right.value"},
                        ]
                    }
                ),
                "outputs": {"value": {"ref": "left.value"}},
            }
        ),
        ports,
    )
    calls = []
    original = module.C0ClosedValuePorts.annotations

    def observed(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(module.C0ClosedValuePorts, "annotations", observed)
    assert value.admits({"left": Counter(1), "right": Counter(1)}) is not closed_false
    assert len(calls) == 1
    assert not value.admits({"left": Counter(2), "right": Counter(1)})
    assert len(calls) == 2

    def unexpected_guard(*args, **kwargs):
        pytest.fail("a malformed root reached the guard")

    monkeypatch.setattr(module, "_eval", unexpected_guard)
    for roots in (
        {"left": Counter(1)},
        {"left": Counter(1), "right": object()},
        {"left": object(), "right": Counter(1)},
    ):
        with pytest.raises(module.C0ValueStateError):
            value.admits(roots)
    assert len(calls) == 5
