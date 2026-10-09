"""Finite projections preserve order, nominal types, lexical scope and K0 writes."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, make_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0 import C0LawError
from nomos_c0.composable_value_v1 import (
    C0ValuePorts,
    C0ValueStateError,
    compile_value_program,
    verify_pure_definition_types,
)
from nomos_c0.nominal_fields_v1 import _leaf_type
from nomos_c0.output_family_v1 import expand_output_families
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.pure_definition_v1 import check_pure_definitions


@dataclass(frozen=True)
class Item:
    group: str
    amount: int | None
    secret: int = 99


@dataclass(frozen=True)
class Ledger:
    items: tuple[Item, ...]
    group: str


def ref(name):
    return {"ref": name}


def collect(collection=None, *, alias="item", where=None, value=None):
    return {
        "collect_matching": {
            "collection": ref("state.items") if collection is None else collection,
            "as": alias,
            "where": {"not_none": ref(f"{alias}.amount")} if where is None else where,
            "value": ref(f"{alias}.amount") if value is None else value,
        }
    }


def ports():
    paths = frozenset({"state.items", "state.group"})
    visible = {Ledger: frozenset({"items", "group"}), Item: frozenset({"group", "amount"})}
    return C0ValuePorts(
        roots={"state": Ledger},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=visible,
        admission_readable_fields=visible,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"values": tuple[int, ...]},
    )


def program(expression=None, *, selected=None, admission=False):
    document = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {"values": collect() if expression is None else expression},
    }
    return compile_value_program(
        json.dumps(document),
        ports() if selected is None else selected,
        admission_outputs=frozenset({"values"}) if admission else frozenset(),
    )


@pytest.mark.parametrize(
    "reference",
    [K0OccurrenceRef(3), _K0ActorRef("local", 1, "person"), _K0IndividualRef("local", 1, "tool")],
)
def test_record_projection_preserves_opaque_refs_but_not_hidden_fields_or_ref_internals(reference):
    item_type = make_dataclass(
        "ReferencedItem",
        [("label", str), ("reference", type(reference)), ("secret", str)],
        frozen=True,
    )
    ledger_type = make_dataclass("ReferenceLedger", [("items", tuple[item_type, ...])], frozen=True)
    selected = replace(
        ports(),
        roots={"state": ledger_type},
        readable_paths=frozenset({"state.items"}),
        admission_readable_paths=frozenset({"state.items"}),
        readable_fields={
            ledger_type: frozenset({"items"}),
            item_type: frozenset({"label", "reference", "secret"}),
        },
        admission_readable_fields={
            ledger_type: frozenset({"items"}),
            item_type: frozenset({"label", "reference", "secret"}),
        },
        outputs={"values": tuple[item_type, ...]},
    )
    expression = collect(where=True, value=ref("item"))
    assert _leaf_type(item_type, "reference") is type(reference)
    assert _leaf_type(item_type, "reference.value") is None
    assert _leaf_type(item_type, "reference.ordinal") is None
    assert _leaf_type(item_type, "reference.family") is None
    compiled = program(expression, selected=selected, admission=True)
    item = item_type("known", reference, "owned")
    actual = compiled.evaluate_admission_outputs({"state": ledger_type((item,))})["values"]
    assert actual == (item,) and actual[0].reference is reference
    hidden = replace(
        selected,
        readable_fields={
            ledger_type: frozenset({"items"}),
            item_type: frozenset({"label", "reference"}),
        },
    )
    with pytest.raises(C0LawError, match="read port"):
        program(expression, selected=hidden)
    field = "value" if type(reference) is K0OccurrenceRef else "ordinal"
    with pytest.raises(C0LawError):
        program(
            collect(where=True, value=ref(f"item.reference.{field}")),
            selected=replace(selected, outputs={"values": tuple[int, ...]}),
        )
    with pytest.raises(C0LawError):
        program(
            collect(where=True, value={"record": {"type": "Handle", "fields": {}}}),
            selected=replace(selected, record_types={"Handle": type(reference)}),
        )


def test_projection_retains_order_duplicates_empty_result_and_does_not_mutate_input():
    compiled = program(admission=True)
    state = Ledger((Item("a", 4), Item("b", None), Item("a", 2), Item("a", 4)), "a")
    assert compiled.evaluate_admission_outputs({"state": state}) == {"values": (4, 2, 4)}
    assert state.items[1].amount is None
    assert compiled.evaluate({"state": Ledger((), "a")}, occurrence=K0OccurrenceRef(3)) == {
        "values": ()
    }
    expression = compiled._tree["outputs"]["values"]
    assert expression.result_type == tuple[int, ...]
    assert expression["collect_matching"]["value"].origin.endswith(".collect_matching.value")


def test_compiled_projection_runs_without_author_lowering_or_type_inference(monkeypatch):
    from nomos_c0 import composable_value_v1 as values

    compiled = program()

    def forbidden(*args, **kwargs):
        raise AssertionError("runtime called the author frontend")

    for name in ("_expr_type", "_prepare_expression", "_compile_expression"):
        monkeypatch.setattr(values, name, forbidden)
    assert compiled.evaluate(
        {"state": Ledger((Item("a", 8),), "a")}, occurrence=K0OccurrenceRef(1)
    ) == {"values": (8,)}


def test_projected_value_runs_only_for_matches_and_nullable_proof_stays_local():
    expression = collect(
        where={"all": [{"not_none": ref("item.amount")}, "item.amount > 0"]},
        value={"ceil_div": [10, ref("item.amount")]},
    )
    compiled = program(expression)
    state = Ledger((Item("a", None), Item("a", 0), Item("a", 5)), "a")
    assert compiled.evaluate({"state": state}, occurrence=K0OccurrenceRef(1)) == {"values": (2,)}
    with pytest.raises(C0LawError, match="nominal type"):
        program(collect(where=True))
    with pytest.raises(C0LawError, match="root"):
        program({"append": [collect(), ref("item.amount")]})


@pytest.mark.parametrize(
    "expression",
    [
        collect(alias="state"),
        collect(alias="occurrence"),
        collect(alias="item.amount"),
        collect(collection=ref("state.group")),
        collect(where=1),
        collect(value=ref("item.secret")),
        collect(value="item.group"),
    ],
)
def test_mistyped_projection_shadow_or_undeclared_field_is_compile_error(expression):
    with pytest.raises(C0LawError):
        program(expression)


@pytest.mark.parametrize("field", ["value", "as"])
def test_projection_requires_exact_fields(field):
    expression = collect()
    del expression["collect_matching"][field]
    with pytest.raises(C0LawError, match="fields"):
        program(expression)


def test_runtime_rejects_list_and_foreign_nominal_item_even_if_no_item_would_match():
    compiled = program()
    for items in ([Item("a", 1)], (1,)):
        with pytest.raises(C0ValueStateError):
            compiled.evaluate({"state": Ledger(items, "a")}, occurrence=K0OccurrenceRef(1))


@pytest.mark.parametrize("shape", ["direct", "let", "call", "copy", "nested_tuple", "replacement"])
def test_whole_aggregate_cannot_launder_unread_fields(shape):
    selected = replace(
        ports(),
        outputs={"values": tuple[Item, ...]},
        record_types={"Item": Item},
        writable_fields={Item: frozenset({"amount", "group", "secret"})},
    )
    value = ref("item")
    if shape == "let":
        value = {"let": {"name": "alias", "value": value, "in": ref("alias")}}
    elif shape == "copy":
        value = {"copy": {"from": value, "changes": {"amount": 1}}}
    elif shape == "call":
        raw = [
            {
                "name": "identity",
                "parameters": {"input": "Item"},
                "result": "Item",
                "stage": "admission",
                "body": ref("input"),
            }
        ]
        definitions = check_pure_definitions(raw, {"Item": Item})
        verify_pure_definition_types(definitions, {"Item": Item})
        selected = replace(selected, pure_definitions=definitions)
        value = {"call": {"ref": "identity", "args": {"input": value}}}
    elif shape == "nested_tuple":
        selected = replace(selected, outputs={"values": tuple[tuple[Item, ...], ...]})
        value = ref("state.items")
    elif shape == "replacement":
        selected = replace(
            selected,
            outputs={"values": tuple[tuple[Item, ...], ...]},
            collection_keys={"state.items": "group"},
        )
        value = {
            "replace_unique": {
                "collection": ref("state.items"),
                "old": ref("item"),
                "new": {"copy": {"from": ref("item"), "changes": {"amount": 1}}},
                "key": "group",
            }
        }
    with pytest.raises(C0LawError, match="read port"):
        program(collect(where=True, value=value), selected=selected)


def test_explicit_record_projection_does_not_require_reading_an_unselected_source_field():
    selected = replace(
        ports(),
        outputs={"values": tuple[Item, ...]},
        record_types={"Item": Item},
        writable_fields={Item: frozenset({"amount", "group", "secret"})},
    )
    value = {
        "record": {
            "type": "Item",
            "fields": {"group": ref("item.group"), "amount": ref("item.amount"), "secret": 0},
        }
    }
    compiled = program(collect(where=True, value=value), selected=selected)
    assert compiled.evaluate(
        {"state": Ledger((Item("a", None),), "a")}, occurrence=K0OccurrenceRef(1)
    ) == {"values": (Item("a", None, 0),)}
    visible = {**selected.readable_fields, Item: frozenset({"group", "amount", "secret"})}
    selected = replace(selected, readable_fields=visible, admission_readable_fields=visible)
    compiled = program(collect(where=True, value=ref("item")), selected=selected)
    assert compiled.evaluate(
        {"state": Ledger((Item("a", None),), "a")}, occurrence=K0OccurrenceRef(1)
    ) == {"values": (Item("a", None, 99),)}


def test_stage_rules_apply_to_projection_predicate_and_selected_value():
    expression = collect(value={"die_roll": {"seed": ref("item.amount"), "sides": 6}})
    program(expression)
    with pytest.raises(C0LawError, match="before Action admission"):
        program(expression, admission=True)
    with pytest.raises(C0LawError, match="before Action admission"):
        program(
            collect(where={"eq": [{"die_roll": {"seed": 1, "sides": 6}}, 1]}, value=1),
            admission=True,
        )


def test_closed_pure_projection_retains_caller_field_authority_and_captures_nothing():
    definition = {
        "name": "select",
        "parameters": {"rows": {"tuple": "Item"}},
        "result": {"tuple": "int"},
        "stage": "admission",
        "body": collect(ref("rows")),
    }
    definitions = check_pure_definitions([definition], {"Item": Item})
    verify_pure_definition_types(definitions, {"Item": Item})
    compiled = program(
        {"call": {"ref": "select", "args": {"rows": ref("state.items")}}},
        selected=replace(ports(), pure_definitions=definitions),
        admission=True,
    )
    assert compiled.evaluate_admission_outputs({"state": Ledger((Item("a", 7),), "a")}) == {
        "values": (7,)
    }
    definition["body"] = collect(ref("rows"), where=True, value=ref("item.secret"))
    definitions = check_pure_definitions([definition], {"Item": Item})
    verify_pure_definition_types(definitions, {"Item": Item})
    with pytest.raises(C0LawError, match="read port"):
        program(
            {"call": {"ref": "select", "args": {"rows": ref("state.items")}}},
            selected=replace(ports(), pure_definitions=definitions),
        )
    definition["body"] = collect(ref("rows"), value=ref("state.group"))
    with pytest.raises(C0LawError, match="captures"):
        check_pure_definitions([definition], {"Item": Item})


def test_output_family_substitutes_outer_root_but_cannot_capture_projection_alias():
    declaration = {
        "name": "selected",
        "owners": ["state"],
        "as": "owner",
        "fields": {
            "items": collect(
                ref("owner.items"),
                where={"all": ["item.group == owner.group", {"not_none": ref("item.amount")}]},
            )
        },
    }
    outputs, _ = expand_output_families(
        [declaration],
        roots={"state": Ledger},
        binding_names=set(),
        state_outputs={"state.items": "values"},
        explicit_outputs={},
    )
    compiled = program(outputs["values"])
    assert compiled.evaluate(
        {"state": Ledger((Item("a", 3), Item("b", 2)), "a")}, occurrence=K0OccurrenceRef(1)
    ) == {"values": (3,)}
    declaration["fields"]["items"] = collect(ref("owner.items"), alias="owner")
    with pytest.raises(C0LawError, match="shadowed"):
        expand_output_families(
            [declaration],
            roots={"state": Ledger},
            binding_names=set(),
            state_outputs={"state.items": "values"},
            explicit_outputs={},
        )


def _runtime_documents(maximum=3):
    from authored_counter_v1 import counter_documents

    lib, ports_document, source, assets = counter_documents()
    lib["records"][0]["fields"].append(
        {"name": "items", "type": {"tuple": {"item": {"int": [0, 10]}, "max": 3}}}
    )
    lib["records"][1]["fields"].append(
        {"name": "seen", "type": {"tuple": {"item": {"int": [0, 10]}, "max": maximum}}}
    )
    assets["opening"]["scene"]["items"] = [3, 1, 2]
    assets["opening"]["actor_0"]["seen"] = []
    action = ports_document["actions"][0]
    action["effects"]["actor"]["seen"] = "seen"
    action["value"]["read"].append("scene.items")
    action["value"]["write_paths"].append("actor.seen")
    value = source["lawdefs"][0]["body"]["value"]
    value["outputs"]["seen"] = collect(ref("scene.items"), where="item > 1", value=ref("item"))
    return lib, ports_document, source, assets


def test_real_action_projects_current_tuple_rechecks_guard_and_owner_bound_rolls_back():
    from authored_counter_v1 import _actor, build

    documents = _runtime_documents()
    lib, ports_document, source, assets = documents
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"] = "payload.target == actor.name and actor.count == 0"
    session = compile_owner_graph(build(lib, ports_document), source).start(assets)
    offer = session.offers("seat_0")[0]
    result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert _actor(session, 0).seen == (3, 2)
    assert _actor(session, 0).count == 1
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before

    lib, ports_document, source, assets = deepcopy(_runtime_documents(maximum=1))
    session = compile_owner_graph(build(lib, ports_document), source).start(assets)
    offer = session.offers("seat_0")[0]
    before = session._runtime.occurrence_history()
    with pytest.raises(K0SettlementDefect):
        session.submit("seat_0", offer.entry, dict(offer.payload))
    assert _actor(session, 0).seen == () and _actor(session, 0).count == 0
    assert session._runtime.occurrence_history() == before
