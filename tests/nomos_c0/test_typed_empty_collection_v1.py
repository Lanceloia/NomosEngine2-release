"""Typed zero-element values do not invent records or read an absent owner field."""

import json
from dataclasses import dataclass, make_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValuePorts, _compile_expression, compile_value_program
from nomos_c0.condition_source_v0 import lower_author_expression
from nomos_c0.expression_ir_v1 import closed_value_type
from nomos_c0.expression_read_authority_v1 import check_expression_reads


@dataclass(frozen=True)
class Token:
    name: str


@dataclass(frozen=True)
class Knowledge:
    tokens: tuple[Token, ...]


@dataclass(frozen=True)
class Reader:
    knowledge: Knowledge | None


def ports(output=tuple[Token, ...], *, readable=True):
    paths = frozenset({"owner.knowledge", "owner.knowledge.tokens"}) if readable else frozenset()
    fields = {Reader: frozenset({"knowledge"}), Knowledge: frozenset({"tokens"})}
    return C0ValuePorts(
        roots={"owner": Reader},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"selected": output},
    )


def compile_expression(expression, output=tuple[Token, ...], *, readable=True, value_ports=None):
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {"selected": expression},
    }
    return compile_value_program(
        json.dumps(source), value_ports or ports(output, readable=readable)
    )


def test_nominal_empty_value_needs_no_current_data_or_record_construction():
    program = compile_expression({"empty_like": "owner.knowledge.tokens"})
    owner = Reader(None)
    assert dict(program.evaluate({"owner": owner}, occurrence=K0OccurrenceRef(1))) == {
        "selected": ()
    }
    assert owner.knowledge is None


@pytest.mark.parametrize("known", [False, True])
def test_optional_knowledge_has_a_typed_empty_branch_not_a_private_fallback(known):
    expression = {
        "if": {
            "when": "owner.knowledge is not None",
            "then": {"ref": "owner.knowledge.tokens"},
            "else": {"empty_like": "owner.knowledge.tokens"},
        }
    }
    program = compile_expression(expression)
    tokens = (Token("real"),)
    reader = Reader(Knowledge(tokens) if known else None)
    assert dict(program.evaluate({"owner": reader}, occurrence=K0OccurrenceRef(1)))["selected"] == (
        tokens if known else ()
    )
    with pytest.raises(C0LawError, match="read boundary"):
        compile_expression(expression, readable=False)


@pytest.mark.parametrize(
    "name,carrier",
    [
        ("bool", bool),
        ("int", int),
        ("str", str),
        ("occurrence_ref", K0OccurrenceRef),
        ("individual_ref", _K0IndividualRef),
        ("actor_ref", _K0ActorRef),
    ],
)
def test_scalar_and_identity_collections_are_empty_without_allocating_identity(name, carrier):
    owner_type = make_dataclass("CollectionOwner", [("items", tuple[carrier, ...])], frozen=True)
    fields = {owner_type: frozenset({"items"})}
    value_ports = replace(
        ports(tuple[carrier, ...]),
        roots={"owner": owner_type},
        readable_paths=frozenset({"owner.items"}),
        admission_readable_paths=frozenset({"owner.items"}),
        readable_fields=fields,
        admission_readable_fields=fields,
    )
    program = compile_expression({"empty_like": "owner.items"}, value_ports=value_ports)
    assert (
        dict(program.evaluate({"owner": owner_type(())}, occurrence=K0OccurrenceRef(1)))["selected"]
        == ()
    )


@pytest.mark.parametrize("path", [{}, 1, "unbound.items", "owner.knowledge.unknown"])
def test_empty_constructor_rejects_undeclared_input_and_malformed_shape(path):
    with pytest.raises(C0LawError):
        compile_expression({"empty_like": path})


def test_empty_does_not_satisfy_an_unrelated_output_type_or_enable_untyped_lists():
    with pytest.raises(C0LawError):
        compile_expression({"empty_like": "owner.knowledge.tokens"}, tuple[str, ...])
    with pytest.raises(C0LawError):
        compile_expression({"empty_like": "owner.knowledge.tokens"}, readable=False)
    with pytest.raises(C0LawError, match="homogeneous"):
        compile_expression({"empty_like": "owner.knowledge"})
    with pytest.raises(C0LawError):
        compile_expression([])
    expression, locations = lower_author_expression({"empty_like": "owner.knowledge.tokens"})
    assert expression == {"empty_like": "owner.knowledge.tokens"}
    assert locations


def test_admission_cannot_query_an_effect_only_collection_type():
    expression = {"empty_like": "owner.knowledge.tokens"}
    value_ports = replace(ports(), admission_readable_paths=frozenset())
    program = compile_expression(expression, value_ports=value_ports)
    assert (
        dict(program.evaluate({"owner": Reader(None)}, occurrence=K0OccurrenceRef(1)))["selected"]
        == ()
    )
    source = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {
            "eq": [0, {"count_matching": {"collection": expression, "as": "token", "where": True}}]
        },
        "outputs": {"selected": expression},
    }
    with pytest.raises(C0LawError, match="read boundary"):
        compile_value_program(json.dumps(source), value_ports)


def test_independent_visibility_check_rejects_forged_empty_input_or_type():
    expression = _compile_expression(
        {"empty_like": "owner.knowledge.tokens"},
        {"owner": Reader},
        ports(),
        set(),
        origin="test.empty",
    )
    check_expression_reads(expression, ports(), frozenset({"owner"}))
    for forged in (
        replace(expression, operand="hidden.items"),
        replace(expression, operand="owner.knowledge.missing"),
        replace(expression, value_type=closed_value_type(tuple[str, ...])),
    ):
        with pytest.raises(C0LawError):
            check_expression_reads(forged, ports(), frozenset({"owner"}))
    partial = replace(ports(), readable_paths=frozenset({"owner.knowledge"}))
    with pytest.raises(C0LawError, match="exact read authority"):
        check_expression_reads(expression, partial, frozenset({"owner"}))
