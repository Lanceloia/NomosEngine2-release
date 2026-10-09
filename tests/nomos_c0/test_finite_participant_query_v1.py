"""Typed keyed left-semijoin preserves finite read scope and actual admission."""

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _compile, _owners
from test_output_family_v1 import Person, _ports
from test_participant_groups_v1 import grouped

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValueStateError, compile_value_program
from nomos_c0.expression_read_authority_v1 import check_expression_reads


@dataclass(frozen=True)
class Record:
    name: str
    paid: bool
    secret: int = 99


@dataclass(frozen=True)
class Ledger:
    records: tuple[Record, ...]


def query():
    return {
        "query": {
            "from": {"collection": {"ref": "ledger.records"}, "as": "record", "key": "name"},
            "join": {"participants": "selected", "as": "person", "key": "name"},
            "where": "not record.paid and person.ready and person.amount > 0",
        }
    }


def ports():
    base = _ports()
    return replace(
        base,
        roots={**base.roots, "ledger": Ledger},
        readable_paths=base.readable_paths | {"ledger.records"},
        admission_readable_paths=base.readable_paths | {"ledger.records"},
        readable_fields={
            **base.readable_fields,
            Ledger: frozenset({"records"}),
            Record: frozenset({"name", "paid"}),
        },
        admission_readable_fields={
            **base.readable_fields,
            Ledger: frozenset({"records"}),
            Record: frozenset({"name", "paid"}),
        },
        outputs={"result": tuple[Record, ...]},
        participant_groups=(("selected", ("one", "two")),),
    )


def compile_query(expression=None, selected=None):
    raw = dict(
        schema="c0.value.v1",
        bindings=[],
        guard=True,
        outputs={"result": query() if expression is None else expression},
    )
    return compile_value_program(
        json.dumps(raw),
        ports() if selected is None else selected,
        admission_outputs=frozenset({"result"}),
    )


def current(rows=(Record("b", False), Record("a", False), Record("c", False))):
    return dict(
        ledger=Ledger(rows),
        one=Person(2, name="a"),
        two=Person(5, name="b"),
        three=Person(100, name="c"),
    )


def test_query_has_typed_ir_preserves_left_order_and_excludes_unselected_members():
    program = compile_query()
    tree = program._tree["outputs"]["result"]
    assert tree.operation == "participant_query"
    assert tree.result_type == tuple[Record, ...]
    result = program.evaluate(current(), occurrence=K0OccurrenceRef(1))["result"]
    assert [row.name for row in result] == ["b", "a"]
    check_expression_reads(replace(tree, stage="admission"), ports(), frozenset(ports().roots))


def test_each_evaluation_uses_current_rows_and_current_participant_state():
    program = compile_query()
    roots = current((Record("a", True), Record("b", False)))
    assert [
        row.name for row in program.evaluate(roots, occurrence=K0OccurrenceRef(1))["result"]
    ] == ["b"]
    roots["two"] = replace(roots["two"], ready=False)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(2))["result"] == ()
    roots["ledger"] = Ledger(())
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(3))["result"] == ()


@pytest.mark.parametrize("side", ["left", "right"])
def test_duplicate_keys_are_errors_not_silent_deduplication(side):
    roots = current()
    if side == "left":
        roots["ledger"] = Ledger((Record("a", False), Record("a", True)))
    else:
        roots["two"] = replace(roots["two"], name="a")
    with pytest.raises(C0ValueStateError, match="unique"):
        compile_query().evaluate(roots, occurrence=K0OccurrenceRef(1))


@pytest.mark.parametrize("side", ["left", "right"])
def test_malformed_key_values_are_state_errors(side):
    roots = current()
    if side == "left":
        roots["ledger"] = Ledger((Record(None, False),))
    else:
        roots["one"] = replace(roots["one"], name=None)
    with pytest.raises(C0ValueStateError, match="nominal type"):
        compile_query().evaluate(roots, occurrence=K0OccurrenceRef(1))


def test_admission_query_does_not_borrow_effect_only_read_permission():
    selected = ports()
    selected = replace(
        selected, admission_readable_paths=selected.admission_readable_paths - {"two.name"}
    )
    with pytest.raises(C0LawError):
        compile_query(selected=selected)


@pytest.mark.parametrize(
    "fault",
    [
        "unselected",
        "alias",
        "key_type",
        "bad_predicate",
        "left_secret",
        "right_secret",
        "missing_port",
    ],
)
def test_invalid_types_and_unauthorized_fields_are_compile_errors(fault):
    expression = query()
    body = expression["query"]
    selected = ports()
    if fault == "unselected":
        body["join"]["participants"] = "other"
    elif fault == "alias":
        body["join"]["as"] = "record"
    elif fault == "key_type":
        body["join"]["key"] = "amount"
    elif fault == "bad_predicate":
        body["where"] = {"ref": "person.amount"}
    elif fault == "left_secret":
        body["where"] = "record.secret > 0"
    elif fault == "right_secret":
        body["where"] = "person.secret > 0"
    else:
        selected = replace(
            selected,
            readable_paths=selected.readable_paths - {"two.name"},
            admission_readable_paths=selected.admission_readable_paths - {"two.name"},
        )
    with pytest.raises(C0LawError):
        compile_query(expression, selected)


def test_real_k0_action_rechecks_query_and_keeps_actor_knowledge_separate():
    lib, selected, source, assets, _ = grouped()
    selected["participant_groups"][0]["read"].append("name")
    selected["actions"][0]["value"]["fields"]["KnownPerson"] = ["name"]
    body = lib["lawdefs"][0]["body"]["value"]
    body["bindings"] = [
        {
            "name": "eligible",
            "stage": "admission",
            "let": {
                "query": {
                    "from": {"collection": {"ref": "actor.known"}, "as": "known", "key": "name"},
                    "join": {"participants": "recipients", "as": "recipient", "key": "name"},
                    "where": {"not": {"ref": "recipient.enabled"}},
                }
            },
        }
    ]
    body["guard"] = {
        "all": [
            body["guard"],
            {
                "lt": [
                    0,
                    {
                        "count_matching": {
                            "collection": {"ref": "eligible"},
                            "as": "row",
                            "where": True,
                        }
                    },
                ]
            },
        ]
    }
    program = _compile(lib, selected, source)
    session = program.start(assets)
    offer = session.offers("maker")[0]
    knowledge = _owners(session)["maker"].known
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert _owners(session)["maker"].known == knowledge
    assert _owners(session)["a"].enabled and not _owners(session)["b"].enabled
    assets["opening"]["maker"]["known"] = [{"name": "a"}]
    session = program.start(assets)
    action = dict(program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "b"))
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before
