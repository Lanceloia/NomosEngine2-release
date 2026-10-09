"""Pure update aliases bind only inside field values and preserve caller authority."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_keyed_record_update_v1 import Ledger, Row, compile_update, ports, rows

from nomos_c0 import C0LawError
from nomos_c0.composable_value_v1 import verify_pure_definition_types
from nomos_c0.pure_definition_v1 import check_pure_definitions


def _definition():
    return {
        "name": "pay",
        "parameters": {
            "items": {"tuple": "Row"},
            "selected": {"tuple": "Row"},
            "stamp": "occurrence_ref",
        },
        "result": {"tuple": "Row"},
        "stage": "effect",
        "body": {
            "update_matching": {
                "collection": {"ref": "items"},
                "matching": {"ref": "selected"},
                "key": "name",
                "as": "row",
                "set": {"paid": {"not": {"ref": "row.paid"}}, "receipt": {"ref": "stamp"}},
            }
        },
    }


def _checked(raw):
    records = {"Row": Row, "Ledger": Ledger}
    result = check_pure_definitions([raw], records)
    verify_pure_definition_types(result, records)
    return result


def _compile(raw, selected_ports=None):
    return compile_update(
        {
            "call": {
                "ref": "pay",
                "args": {
                    "items": {"ref": "ledger.rows"},
                    "selected": {"ref": "ledger.batch"},
                    "stamp": {"ref": "occurrence"},
                },
            }
        },
        replace(
            ports() if selected_ports is None else selected_ports, pure_definitions=_checked(raw)
        ),
    )


def test_pure_keyed_update_local_row_is_not_an_external_capture():
    compiled = _compile(_definition())
    original = rows()
    result = compiled.evaluate(
        {"ledger": Ledger(original, (original[1],))}, occurrence=K0OccurrenceRef(7)
    )["result"]
    assert result == (
        original[0],
        replace(original[1], paid=True, receipt=K0OccurrenceRef(7)),
        original[2],
    )


@pytest.mark.parametrize("fault", ["shadow", "collection_escape", "outside_capture"])
def test_pure_keyed_update_rejects_capture_and_alias_escape(fault):
    raw = deepcopy(_definition())
    body = raw["body"]["update_matching"]
    if fault == "shadow":
        body["as"] = "items"
    elif fault == "collection_escape":
        body["collection"] = {"ref": "row"}
    else:
        body["set"]["paid"] = {"ref": "outside.paid"}
    with pytest.raises(C0LawError, match="shadow|undeclared"):
        _checked(raw)


def test_pure_keyed_update_cannot_acquire_caller_field_write_authority():
    with pytest.raises(C0LawError, match="unauthorized fields"):
        _compile(_definition(), replace(ports(), writable_fields={Row: frozenset({"receipt"})}))
