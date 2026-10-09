"""Optional aggregate exports retain nominal identity and field authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program


@dataclass(frozen=True)
class Evidence:
    public: str
    hidden: int


@dataclass(frozen=True)
class Receipt:
    amount: int
    evidence: Evidence


@dataclass(frozen=True)
class ForeignReceipt:
    amount: int
    evidence: Evidence


@dataclass(frozen=True)
class Entry:
    name: str
    payment: Receipt | None


@dataclass(frozen=True)
class State:
    entries: tuple[Entry, ...]


def ref(path):
    return {"ref": path}


def record(type_name, **fields):
    return {"record": {"type": type_name, "fields": fields}}


def ports(*, hidden=True):
    paths = frozenset({"state.entries"})
    fields = {
        State: frozenset({"entries"}),
        Entry: frozenset({"name", "payment"}),
        Receipt: frozenset({"amount", "evidence"}),
        Evidence: frozenset({"public", "hidden"} if hidden else {"public"}),
    }
    return C0ValuePorts(
        roots={"state": State},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={Receipt: frozenset({"amount"}), Entry: frozenset({"payment"})},
        record_types={
            "Entry": Entry,
            "Receipt": Receipt,
            "ForeignReceipt": ForeignReceipt,
            "Evidence": Evidence,
        },
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"entries": tuple[Entry, ...]},
    )


def compile_projection(payment, *, selected=None, where=True, copy_outer=False):
    entry = (
        {"copy": {"from": ref("entry"), "changes": {"payment": payment}}}
        if copy_outer
        else record("Entry", name=ref("entry.name"), payment=payment)
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {
            "entries": {
                "collect_matching": {
                    "collection": ref("state.entries"),
                    "as": "entry",
                    "where": where,
                    "value": entry,
                }
            }
        },
    }
    return compile_value_program(json.dumps(source), selected or ports())


def constructed_payment():
    return record(
        "Receipt", amount=7, evidence=record("Evidence", public={"const": "seen"}, hidden=0)
    )


@pytest.mark.parametrize("copy_outer", [False, True])
def test_nested_optional_record_constructor_is_a_real_nominal_collection_export(copy_outer):
    program = compile_projection(constructed_payment(), copy_outer=copy_outer)
    assert program.evaluate(
        {"state": State((Entry("one", None), Entry("two", None)))},
        occurrence=K0OccurrenceRef(1),
    ) == {
        "entries": (
            Entry("one", Receipt(7, Evidence("seen", 0))),
            Entry("two", Receipt(7, Evidence("seen", 0))),
        )
    }


@pytest.mark.parametrize("copy_outer", [False, True])
def test_optional_record_copy_keeps_unmodified_fields_and_requires_local_nonnull(copy_outer):
    payment = {"copy": {"from": ref("entry.payment"), "changes": {"amount": 8}}}
    program = compile_projection(
        payment, where={"not_none": ref("entry.payment")}, copy_outer=copy_outer
    )
    assert program.evaluate(
        {"state": State((Entry("unknown", None), Entry("paid", Receipt(1, Evidence("yes", 9)))))},
        occurrence=K0OccurrenceRef(1),
    ) == {"entries": (Entry("paid", Receipt(8, Evidence("yes", 9))),)}
    with pytest.raises(C0LawError, match="undeclared field"):
        compile_projection(payment, copy_outer=copy_outer)


@pytest.mark.parametrize("copy_outer", [False, True])
def test_none_is_an_unknown_optional_record_not_an_implicit_constructor(copy_outer):
    program = compile_projection(None, copy_outer=copy_outer)
    assert program.evaluate(
        {"state": State((Entry("paid", Receipt(1, Evidence("yes", 9))),))},
        occurrence=K0OccurrenceRef(1),
    ) == {"entries": (Entry("paid", None),)}


def test_optional_reference_export_retains_unknown_and_known_records():
    entries = (Entry("unknown", None), Entry("paid", Receipt(1, Evidence("yes", 9))))
    program = compile_projection(ref("entry.payment"))
    assert program.evaluate({"state": State(entries)}, occurrence=K0OccurrenceRef(1)) == {
        "entries": entries
    }


def test_guarded_optional_copy_or_none_keeps_proof_within_its_branch():
    payment = {
        "if": {
            "when": {"not_none": ref("entry.payment")},
            "then": {"copy": {"from": ref("entry.payment"), "changes": {"amount": 8}}},
            "else": None,
        }
    }
    program = compile_projection(payment)
    assert program.evaluate(
        {"state": State((Entry("unknown", None), Entry("paid", Receipt(1, Evidence("yes", 9)))))},
        occurrence=K0OccurrenceRef(1),
    ) == {"entries": (Entry("unknown", None), Entry("paid", Receipt(8, Evidence("yes", 9))))}
    payment["if"]["else"] = ref("entry.payment.evidence")
    with pytest.raises(C0LawError, match="nullable value"):
        compile_projection(payment)


@pytest.mark.parametrize("shape", ["record", "copy", "ref"])
def test_optional_record_export_cannot_launder_a_hidden_nested_field(shape):
    payment = ref("entry.payment")
    if shape == "record":
        payment = record("Receipt", amount=7, evidence=ref("entry.payment.evidence"))
    elif shape == "copy":
        payment = {"copy": {"from": payment, "changes": {"amount": 8}}}
    with pytest.raises(C0LawError, match="read port"):
        compile_projection(
            payment, selected=ports(hidden=False), where={"not_none": ref("entry.payment")}
        )


def test_explicit_reconstruction_does_not_require_unread_source_fields():
    program = compile_projection(constructed_payment(), selected=ports(hidden=False))
    assert program.evaluate(
        {"state": State((Entry("one", Receipt(1, Evidence("private", 99))),))},
        occurrence=K0OccurrenceRef(1),
    ) == {"entries": (Entry("one", Receipt(7, Evidence("seen", 0))),)}


def test_optional_record_rejects_a_structurally_identical_foreign_nominal_constructor():
    payment = record(
        "ForeignReceipt", amount=7, evidence=record("Evidence", public={"const": "seen"}, hidden=0)
    )
    with pytest.raises(C0LawError, match="wrong type"):
        compile_projection(payment)


def test_optional_record_copy_does_not_gain_write_permission():
    selected = replace(ports(), writable_fields={Entry: frozenset({"payment"})})
    payment = {"copy": {"from": ref("entry.payment"), "changes": {"amount": 8}}}
    with pytest.raises(C0LawError, match="undeclared field"):
        compile_projection(payment, selected=selected, where={"not_none": ref("entry.payment")})


def test_constructing_optional_record_does_not_prove_an_unrelated_nullable_read():
    payment = record(
        "Receipt",
        amount=ref("entry.payment.amount"),
        evidence=record("Evidence", public={"const": "seen"}, hidden=0),
    )
    with pytest.raises(C0LawError, match="nullable value"):
        compile_projection(payment)
