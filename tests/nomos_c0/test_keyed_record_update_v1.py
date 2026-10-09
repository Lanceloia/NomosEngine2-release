"""Keyed field updates preserve unselected records and checked write authority."""

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueStateError, compile_value_program
from nomos_c0.expression_read_authority_v1 import check_expression_reads


@dataclass(frozen=True)
class Row:
    name: str
    paid: bool
    origin: K0OccurrenceRef
    receipt: K0OccurrenceRef | None
    extra: str


@dataclass(frozen=True)
class Ledger:
    rows: tuple[Row, ...]
    batch: tuple[Row, ...]


def ports():
    paths = frozenset({"ledger.rows", "ledger.batch"})
    fields = {
        Ledger: frozenset({"rows", "batch"}),
        Row: frozenset({"name", "paid", "origin", "receipt", "extra"}),
    }
    return C0ValuePorts(
        roots={"ledger": Ledger},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={Row: frozenset({"paid", "receipt"})},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"result": tuple[Row, ...]},
    )


def update():
    return {
        "update_matching": {
            "collection": {"ref": "ledger.rows"},
            "matching": {"ref": "ledger.batch"},
            "key": "name",
            "as": "row",
            "set": {"paid": True, "receipt": {"ref": "occurrence"}},
        }
    }


def compile_update(expression=None, selected=None):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": [],
                "guard": True,
                "outputs": {"result": update() if expression is None else expression},
            }
        ),
        ports() if selected is None else selected,
    )


def rows():
    return (
        Row("a", True, K0OccurrenceRef(1), K0OccurrenceRef(2), "old"),
        Row("b", False, K0OccurrenceRef(3), None, "keep"),
        Row("c", False, K0OccurrenceRef(4), None, "untouched"),
    )


def evaluate(program, ledger):
    return program.evaluate({"ledger": ledger}, occurrence=K0OccurrenceRef(5))["result"]


def test_update_changes_only_selected_fields_and_keeps_order_and_old_sources():
    program = compile_update()
    tree = program._tree["outputs"]["result"]
    assert tree.operation == "update_matching" and tree.result_type == tuple[Row, ...]
    original = rows()
    result = evaluate(program, Ledger(original, (original[1],)))
    assert result == (
        original[0],
        replace(original[1], paid=True, receipt=K0OccurrenceRef(5)),
        original[2],
    )
    assert result[0] is original[0] and result[2] is original[2]
    assert result[1].origin == original[1].origin and result[1].extra == "keep"
    assert evaluate(program, Ledger(original, ())) == original
    assert evaluate(program, Ledger((), ())) == ()


@pytest.mark.parametrize(
    "bad", ["duplicate_base", "duplicate_batch", "missing", "stale", "key_type"]
)
def test_bad_current_batch_is_not_silently_ignored(bad):
    original = rows()
    ledger = Ledger(original, (original[1],))
    if bad == "duplicate_base":
        ledger = replace(ledger, rows=original + (original[0],))
    elif bad == "duplicate_batch":
        ledger = replace(ledger, batch=ledger.batch * 2)
    elif bad == "missing":
        ledger = replace(ledger, batch=(replace(original[1], name="foreign"),))
    elif bad == "stale":
        ledger = replace(ledger, batch=(replace(original[1], origin=K0OccurrenceRef(99)),))
    else:
        ledger = replace(ledger, rows=(replace(original[0], name=None),), batch=())
    with pytest.raises(C0ValueStateError):
        evaluate(compile_update(), ledger)


@pytest.mark.parametrize(
    "bad",
    ["key_write", "readonly", "wrong_type", "empty", "alias", "key_read", "batch_read", "extra"],
)
def test_compile_rejects_bad_field_or_read_write_permissions(bad):
    expression, selected = update(), ports()
    body = expression["update_matching"]
    if bad == "key_write":
        selected = replace(selected, writable_fields={Row: frozenset({"name"})})
        body["set"] = {"name": {"const": "other"}}
    elif bad == "readonly":
        body["set"] = {"origin": {"ref": "occurrence"}}
    elif bad == "wrong_type":
        body["set"] = {"paid": 1}
    elif bad == "empty":
        body["set"] = {}
    elif bad == "alias":
        body["as"] = "ledger"
    elif bad == "key_read":
        selected = replace(
            selected,
            readable_fields={
                **selected.readable_fields,
                Row: selected.readable_fields[Row] - {"name"},
            },
        )
    elif bad == "batch_read":
        selected = replace(selected, readable_paths=frozenset({"ledger.rows"}))
    else:
        body["unexpected"] = True
    with pytest.raises(C0LawError):
        compile_update(expression, selected)


def test_set_reads_original_row_for_every_field_not_an_intermediate_copy():
    expression = update()
    expression["update_matching"]["set"] = {
        "paid": {"not": {"ref": "row.paid"}},
        "receipt": {
            "if": {"when": {"ref": "row.paid"}, "then": {"ref": "occurrence"}, "else": None}
        },
    }
    original = rows()
    result = evaluate(compile_update(expression), Ledger(original, original))
    assert not result[0].paid and result[0].receipt == K0OccurrenceRef(5)
    assert result[1].paid and result[1].receipt is None


def test_read_checker_recognizes_alias_but_does_not_make_effect_available_before_admission():
    tree = compile_update()._tree["outputs"]["result"]
    with pytest.raises(C0LawError, match="before admission"):
        check_expression_reads(tree, ports(), frozenset({"ledger"}))


def test_declared_record_constructor_authorizes_fields_without_new_owner_write_paths():
    selected = replace(ports(), writable_fields={}, record_types={"Row": Row})
    original = rows()
    result = evaluate(compile_update(selected=selected), Ledger(original, (original[1],)))
    assert result[1] == replace(original[1], paid=True, receipt=K0OccurrenceRef(5))
    for field in ("name", "undeclared"):
        expression = update()
        expression["update_matching"]["set"] = {field: {"const": "other"}}
        with pytest.raises(C0LawError):
            compile_update(expression, selected)


def test_admission_read_check_preserves_collection_and_field_authority():
    expression = update()
    expression["update_matching"]["set"] = {"paid": {"not": {"ref": "row.paid"}}}
    raw = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {"result": expression},
    }
    program = compile_value_program(
        json.dumps(raw), ports(), admission_outputs=frozenset({"result"})
    )
    tree = program._tree["outputs"]["result"]
    check_expression_reads(tree, ports(), frozenset({"ledger"}))
    with pytest.raises(C0LawError, match="authority"):
        check_expression_reads(tree, ports(), frozenset())
    denied = replace(ports(), admission_readable_paths=frozenset({"ledger.rows"}))
    with pytest.raises(C0LawError):
        compile_value_program(json.dumps(raw), denied, admission_outputs=frozenset({"result"}))
