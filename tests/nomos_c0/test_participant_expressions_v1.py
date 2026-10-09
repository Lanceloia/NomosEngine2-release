"""Selected participant predicates and ordered folds retain exact read authority."""

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published
from test_multi_participant_action_v0 import _compile, _owners
from test_output_family_v1 import Person, _ports
from test_participant_groups_v1 import grouped

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import compile_value_program


def compile_expression(expression, result_type=int, ports=None):
    ports = replace(
        _ports() if ports is None else ports,
        outputs={"result": result_type},
        participant_groups=(("selected", ("one", "two")),),
    )
    source = dict(schema="c0.value.v1", bindings=[], guard=True, outputs={"result": expression})
    return compile_value_program(json.dumps(source), ports)


def roots(one=2, two=5):
    return {"one": Person(one), "two": Person(two), "three": Person(100)}


@pytest.mark.parametrize(
    "operation,expected", [("any_participant", True), ("all_participants", False)]
)
def test_predicate_uses_only_selected_members(operation, expected):
    expression = {operation: dict(group="selected", **{"as": "person"}, where="person.amount > 3")}
    program = compile_expression(expression, bool)
    assert program.evaluate(roots(), occurrence=K0OccurrenceRef(1)) == {"result": expected}


def test_fold_is_ordered_and_does_not_capture_existing_local_names():
    expression = {
        "let": {
            "name": "participantFold0",
            "value": {"const": 0},
            "in": {
                "fold_participants": dict(
                    group="selected",
                    **{"as": "person"},
                    accumulator="total",
                    initial={"ref": "participantFold0"},
                    value={"add": [{"mul": [{"ref": "total"}, 10]}, {"ref": "person.amount"}]},
                ),
            },
        }
    }
    program = compile_expression(expression)
    assert program.evaluate(roots(), occurrence=K0OccurrenceRef(1)) == {"result": 25}


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "root_alias",
        "local_alias",
        "wrong_type",
        "unread",
        "admission_only",
        "nested_alias",
    ],
)
def test_invalid_or_unauthorized_predicates_are_compile_errors(fault):
    ports = _ports()
    declaration = dict(group="selected", **{"as": "person"}, where="person.amount > 3")
    expression = {"any_participant": declaration}
    if fault == "unknown":
        declaration["group"] = "unselected"
    elif fault == "root_alias":
        declaration["as"] = "one"
    elif fault == "local_alias":
        declaration["where"] = {"let": {"name": "person", "value": 1, "in": True}}
    elif fault == "wrong_type":
        declaration["where"] = {"ref": "person.amount"}
    elif fault == "unread":
        declaration["where"] = "person.secret > 0"
    elif fault == "admission_only":
        declaration["where"] = "person.name == 'x'"
        ports = replace(ports, readable_paths=ports.admission_readable_paths)
    elif fault == "nested_alias":
        declaration["where"] = {
            "any_participant": dict(group="selected", **{"as": "person"}, where=True)
        }
    with pytest.raises(C0LawError):
        compile_expression(expression, bool, ports)


def test_generated_predicate_reaches_real_k0_action():
    lib, ports, source, assets, _ = grouped()
    body = lib["lawdefs"][0]["body"]["value"]
    body["guard"] = {
        "all": [
            body["guard"],
            {
                "not": {
                    "any_participant": {
                        "group": "recipients",
                        "as": "recipient",
                        "where": {"ref": "recipient.enabled"},
                    }
                }
            },
        ]
    }
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert _owners(session)["a"].enabled and not _owners(session)["b"].enabled


def test_same_state_type_does_not_bypass_member_specific_read_permission():
    ports = replace(_ports(), readable_paths=_ports().readable_paths - {"two.amount"})
    ports = replace(ports, admission_readable_paths=ports.admission_readable_paths - {"two.amount"})
    with pytest.raises(C0LawError):
        compile_expression(
            {
                "any_participant": {
                    "group": "selected",
                    "as": "person",
                    "where": "person.amount > 0",
                }
            },
            bool,
            ports,
        )


def test_constants_are_not_rewritten_and_admission_keeps_its_own_read_boundary():
    expression = {
        "any_participant": {
            "group": "selected",
            "as": "person",
            "where": "person.name == 'person.amount'",
        }
    }
    program = compile_expression(expression, bool)
    assert program.evaluate(roots(), occurrence=K0OccurrenceRef(1)) == {"result": True}
    ports = replace(
        _ports(), outputs={"result": int}, participant_groups=(("selected", ("one", "two")),)
    )
    source = dict(schema="c0.value.v1", bindings=[], guard=expression, outputs={"result": 1})
    with pytest.raises(C0LawError):
        compile_value_program(json.dumps(source), ports)


def test_fold_cannot_read_an_unauthorized_field():
    expression = {
        "fold_participants": {
            "group": "selected",
            "as": "person",
            "accumulator": "total",
            "initial": 0,
            "value": {"add": [{"ref": "total"}, {"ref": "person.secret"}]},
        }
    }
    with pytest.raises(C0LawError):
        compile_expression(expression)
