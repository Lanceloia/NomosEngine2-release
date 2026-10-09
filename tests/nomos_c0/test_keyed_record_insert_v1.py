"""New records append by key; existing records and their sources are retained."""

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_keyed_record_update_v1 import Ledger, Row, rows
from test_keyed_record_update_v1 import ports as record_ports
from test_output_family_v1 import Person, _ports

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValueStateError, compile_value_program
from nomos_c0.expression_read_authority_v1 import check_expression_reads


def ports():
    records, people = record_ports(), _ports()
    paths = frozenset(path for path in people.readable_paths if not path.startswith("three."))
    return replace(
        records,
        roots={**records.roots, "one": Person, "two": Person},
        readable_paths=records.readable_paths | paths,
        admission_readable_paths=records.admission_readable_paths | paths,
        readable_fields={**records.readable_fields, **people.readable_fields},
        admission_readable_fields={**records.admission_readable_fields, **people.readable_fields},
        record_types={"Row": Row},
        participant_groups=(("selected", ("one", "two")),),
    )


def collection():
    return {
        "collect_participants": {
            "group": "selected",
            "as": "person",
            "where": {"ref": "person.ready"},
            "value": {
                "record": {
                    "type": "Row",
                    "fields": {
                        "name": {"ref": "person.name"},
                        "paid": False,
                        "origin": {"ref": "occurrence"},
                        "receipt": None,
                        "extra": {"const": "new"},
                    },
                }
            },
        }
    }


def insertion(candidates=None):
    return {
        "insert_missing": {
            "collection": {"ref": "ledger.rows"},
            "key": "name",
            "candidates": {"ref": "ledger.batch"} if candidates is None else candidates,
        }
    }


def compile_insert(expression=None, selected=None, admission=False):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"result": insertion() if expression is None else expression},
            }
        ),
        ports() if selected is None else selected,
        admission_outputs=frozenset({"result"}) if admission else frozenset(),
    )


def current(ledger):
    return {"ledger": ledger, "one": Person(2, name="a"), "two": Person(5, name="b")}


def evaluate(program, roots):
    return program.evaluate(roots, occurrence=K0OccurrenceRef(9))["result"]


def test_insert_preserves_existing_paid_record_and_appends_only_new_keys_in_input_order():
    original = rows()
    candidates = (
        replace(original[0], paid=False, receipt=None, origin=K0OccurrenceRef(8)),
        original[2],
    )
    ledger = Ledger(original[:2], candidates)
    program = compile_insert()
    assert program._tree["outputs"]["result"].operation == "insert_missing"
    result = evaluate(program, current(ledger))
    assert result == original and result[0] is original[0] and result[1] is original[1]
    assert evaluate(program, current(Ledger(original, candidates))) == original
    assert evaluate(program, current(Ledger(original, ()))) == original
    assert evaluate(program, current(Ledger((), candidates))) == candidates


def test_participant_generation_is_checked_native_ir_not_an_authored_accumulator():
    original = rows()[1]
    program = compile_insert(insertion(collection()))
    tree = program._tree["outputs"]["result"]
    assert tree.operand["candidates"].operation == "participant_collect"
    roots = current(Ledger((original,), ()))
    result = evaluate(program, roots)
    assert result[0] is original
    assert result[1] == Row("a", False, K0OccurrenceRef(9), None, "new")
    roots["one"] = replace(roots["one"], ready=False)
    assert evaluate(program, roots) == (original,)
    assert "three" not in program._ports.roots


def test_generation_uses_predicate_proof_and_skips_absent_value():
    expression = insertion(collection())
    generate = expression["insert_missing"]["candidates"]["collect_participants"]
    generate["where"] = {"not_none": {"ref": "person.maybe"}}
    generate["value"]["record"]["fields"]["extra"] = {
        "if": {
            "when": {"lt": [0, {"ref": "person.maybe"}]},
            "then": {"const": "positive"},
            "else": {"const": "nonpositive"},
        }
    }
    roots = current(Ledger((), ()))
    roots["two"] = replace(roots["two"], maybe=1)
    result = evaluate(compile_insert(expression), roots)
    assert result == (Row("b", False, K0OccurrenceRef(9), None, "positive"),)


@pytest.mark.parametrize("side", ["base", "candidates"])
def test_duplicates_reject_even_when_existing_keys_would_be_kept(side):
    original = rows()[0]
    ledger = Ledger((original,), (original,))
    ledger = (
        replace(ledger, rows=ledger.rows * 2)
        if side == "base"
        else replace(ledger, batch=ledger.batch * 2)
    )
    with pytest.raises(C0ValueStateError, match="unique"):
        evaluate(compile_insert(), current(ledger))


@pytest.mark.parametrize("side", ["base", "candidates"])
def test_runtime_bad_key_type_is_not_hidden_by_existing_key_policy(side):
    original = rows()[0]
    ledger = Ledger((original,), (original,))
    malformed = (replace(original, name=None),)
    ledger = replace(ledger, rows=malformed) if side == "base" else replace(ledger, batch=malformed)
    with pytest.raises(C0ValueStateError, match="key type"):
        evaluate(compile_insert(), current(ledger))


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_group",
        "alias",
        "unread_member",
        "constructor",
        "where_type",
        "key",
        "batch_read",
        "row_type",
        "extra_field",
    ],
)
def test_compile_checks_group_type_constructor_and_read_permissions(fault):
    expression, selected = insertion(collection()), ports()
    generate = expression["insert_missing"]["candidates"]["collect_participants"]
    if fault == "unknown_group":
        generate["group"] = "unselected"
    elif fault == "alias":
        generate["as"] = "one"
    elif fault == "unread_member":
        selected = replace(selected, readable_paths=selected.readable_paths - {"two.name"})
    elif fault == "constructor":
        selected = replace(selected, record_types={})
    elif fault == "where_type":
        generate["where"] = {"ref": "person.amount"}
    elif fault == "key":
        expression["insert_missing"]["key"] = "missing"
    elif fault == "batch_read":
        expression = insertion()
        selected = replace(selected, readable_paths=selected.readable_paths - {"ledger.batch"})
    elif fault == "row_type":
        generate["value"] = {"ref": "person.name"}
    else:
        expression["insert_missing"]["ignore_duplicates"] = True
    with pytest.raises(C0LawError):
        compile_insert(expression, selected)


def test_admission_can_use_existing_rows_but_cannot_borrow_ungranted_paths():
    program = compile_insert(admission=True)
    tree = program._tree["outputs"]["result"]
    check_expression_reads(tree, ports(), frozenset(ports().roots))
    selected = replace(
        ports(), admission_readable_paths=ports().admission_readable_paths - {"ledger.batch"}
    )
    with pytest.raises(C0LawError):
        compile_insert(selected=selected, admission=True)
    with pytest.raises(C0LawError):
        compile_insert(insertion(collection()), admission=True)
