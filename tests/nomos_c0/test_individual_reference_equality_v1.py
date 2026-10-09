"""Opaque individual identity comparison never grants state or field access."""

import json
from dataclasses import dataclass

import pytest
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program


@dataclass(frozen=True)
class References:
    known: _K0IndividualRef | None
    selected: _K0IndividualRef


def _check(expression):
    ports = C0ValuePorts(
        roots={"state": References},
        readable_paths=frozenset({"state.known", "state.selected"}),
        admission_readable_paths=frozenset({"state.known", "state.selected"}),
        readable_fields={References: frozenset({"known", "selected"})},
        admission_readable_fields={References: frozenset({"known", "selected"})},
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"same": bool},
    )
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"same": expression},
            }
        ),
        ports,
        admission_outputs=frozenset({"same"}),
    )


@pytest.mark.parametrize(
    "scope,ordinal,family,same",
    [
        ("scope", 1, "tool", True),
        ("other", 1, "tool", False),
        ("scope", 2, "tool", False),
        ("scope", 1, "other", False),
    ],
)
def test_identity_equality_uses_full_reference_not_only_ordinal(scope, ordinal, family, same):
    program = _check({"eq": [{"ref": "state.known"}, {"ref": "state.selected"}]})
    state = References(
        _K0IndividualRef("scope", 1, "tool"), _K0IndividualRef(scope, ordinal, family)
    )
    assert program.evaluate_admission_outputs({"state": state}) == {"same": same}
    assert program.evaluate_admission_outputs({"state": References(None, state.selected)}) == {
        "same": False
    }


def test_reference_does_not_grant_field_access_or_record_equality():
    with pytest.raises(C0LawError):
        _check({"eq": [{"ref": "state.known.ordinal"}, {"const": 1}]})
    with pytest.raises(C0LawError):
        _check({"eq": [{"ref": "state"}, {"ref": "state"}]})
