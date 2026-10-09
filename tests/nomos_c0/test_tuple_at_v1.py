"""Strict tuple selection retains nominal values, source read authority and lazy branches."""

import json
from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend
from test_read_object_domain_due_v1 import advance, documents, scene, submit
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.checked_value_binding_v1 import C0ValueBackend
from nomos_c0.composable_value_v1 import (
    C0ValuePorts,
    C0ValueStateError,
    compile_value_program,
    verify_pure_definition_types,
)
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.pure_definition_v1 import check_pure_definitions
from nomos_c0.replayable_die_v1 import next_seed, roll


@dataclass(frozen=True)
class Item:
    public: int
    hidden: int


@dataclass(frozen=True)
class ForeignItem:
    public: int
    hidden: int


@dataclass(frozen=True)
class State:
    items: tuple[Item, ...]
    index: int


def ref(path):
    return {"ref": path}


def at(collection=None, index=None):
    return {
        "tuple_at": {
            "collection": ref("state.items") if collection is None else collection,
            "index": ref("state.index") if index is None else index,
        }
    }


def local(value, result):
    return {"let": {"name": "chosen", "value": value, "in": result}}


def ports(*, output=int, hidden=False):
    paths = frozenset({"state.items", "state.index"})
    fields = {
        State: frozenset({"items", "index"}),
        Item: frozenset({"public", "hidden"} if hidden else {"public"}),
    }
    return C0ValuePorts(
        roots={"state": State},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={"Item": Item},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"value": output},
    )


def compile_expr(expression, *, selected=None, bindings=(), admission=False):
    return compile_value_program(
        json.dumps(
            {
                "schema": "c0.value.v1",
                "bindings": list(bindings),
                "guard": True,
                "outputs": {"value": expression},
            }
        ),
        selected or ports(),
        admission_outputs=frozenset({"value"}) if admission else frozenset(),
    )


def evaluate(program, state):
    return program.evaluate({"state": state}, occurrence=K0OccurrenceRef(1))["value"]


def test_public_field_projection_preserves_order_and_input_and_admission_stage():
    expression = local(at(), ref("chosen.public"))
    program = compile_expr(expression, admission=True)
    items = (Item(7, 77), Item(3, 33), Item(7, 77))
    for index in range(len(items)):
        state = State(items, index)
        assert program.evaluate_admission_outputs({"state": state}) == {
            "value": items[index].public
        }
        assert state.items is items


def test_whole_record_selection_keeps_the_original_nominal_instance():
    program = compile_expr(at(), selected=ports(output=Item, hidden=True))
    items = (Item(8, 88), Item(4, 44))
    assert evaluate(program, State(items, 1)) is items[1]
    with pytest.raises(C0LawError):
        compile_expr(at(), selected=ports(output=ForeignItem, hidden=True))


@pytest.mark.parametrize("shape", ["direct", "let", "binding", "field", "copy"])
def test_collection_read_does_not_authorize_hidden_record_export_or_field(shape):
    expression, bindings, output = at(), (), Item
    selected = ports(output=output)
    if shape == "let":
        expression = local(at(), ref("chosen"))
    elif shape == "binding":
        bindings = ({"name": "chosen", "let": at(), "stage": "admission"},)
        expression = ref("chosen")
    elif shape == "field":
        expression = local(at(), ref("chosen.hidden"))
        selected = ports()
    elif shape == "copy":
        expression = {"copy": {"from": at(), "changes": {"public": 10}}}
        selected = replace(selected, writable_fields={Item: frozenset({"public"})})
    with pytest.raises(C0LawError, match="read port"):
        compile_expr(expression, selected=selected, bindings=bindings)


def test_explicit_projection_may_construct_a_constant_without_reading_hidden_input():
    expression = local(
        at(), {"record": {"type": "Item", "fields": {"public": ref("chosen.public"), "hidden": 0}}}
    )
    result = evaluate(
        compile_expr(expression, selected=ports(output=Item)), State((Item(9, 99),), 0)
    )
    assert result == Item(9, 0)


def test_pure_call_retains_collection_source_and_caller_field_authority():
    definition = {
        "name": "public_at",
        "parameters": {"rows": {"tuple": "Item"}},
        "result": "int",
        "stage": "admission",
        "body": local(at(ref("rows"), 0), ref("chosen.public")),
    }
    definitions = check_pure_definitions([definition], {"Item": Item})
    verify_pure_definition_types(definitions, {"Item": Item})
    selected = replace(ports(), pure_definitions=definitions)
    expression = {"call": {"ref": "public_at", "args": {"rows": ref("state.items")}}}
    assert evaluate(compile_expr(expression, selected=selected), State((Item(5, 55),), 0)) == 5
    definition["body"] = local(at(ref("rows"), 0), ref("chosen.hidden"))
    definitions = check_pure_definitions([definition], {"Item": Item})
    with pytest.raises(C0LawError, match="read port"):
        compile_expr(expression, selected=replace(selected, pure_definitions=definitions))
    definition.update(
        name="from_state",
        parameters={"input": "State"},
        body=local(at(ref("input.items"), 0), ref("chosen.public")),
    )
    definitions = check_pure_definitions([definition], {"Item": Item, "State": State})
    allowed = frozenset({"state", "state.index"})
    selected = replace(
        ports(hidden=True),
        pure_definitions=definitions,
        readable_paths=allowed,
        admission_readable_paths=allowed,
    )
    with pytest.raises(C0LawError, match="read boundary"):
        compile_expr(
            {"call": {"ref": "from_state", "args": {"input": ref("state")}}}, selected=selected
        )


def test_pure_call_whole_record_export_retains_caller_read_authority():
    definitions = check_pure_definitions(
        [
            {
                "name": "item_at",
                "parameters": {"rows": {"tuple": "Item"}},
                "result": "Item",
                "stage": "admission",
                "body": at(ref("rows"), 0),
            }
        ],
        {"Item": Item},
    )
    expression = {"call": {"ref": "item_at", "args": {"rows": ref("state.items")}}}
    with pytest.raises(C0LawError, match="read port"):
        compile_expr(expression, selected=replace(ports(output=Item), pure_definitions=definitions))
    selected = replace(ports(output=Item, hidden=True), pure_definitions=definitions)
    item = Item(2, 22)
    assert evaluate(compile_expr(expression, selected=selected), State((item,), 0)) is item


def test_parameter_names_are_not_interpreted_as_expression_operations():
    definitions = check_pure_definitions(
        [
            {
                "name": "first",
                "parameters": {"ref": {"tuple": "Item"}},
                "result": "Item",
                "stage": "admission",
                "body": at(ref("ref"), 0),
            }
        ],
        {"Item": Item},
    )
    expression = {"call": {"ref": "first", "args": {"ref": ref("state.items")}}}
    selected = replace(ports(output=Item, hidden=True), pure_definitions=definitions)
    item = Item(3, 33)
    assert evaluate(compile_expr(expression, selected=selected), State((item,), 0)) is item
    with pytest.raises(C0LawError, match="read port"):
        compile_expr(expression, selected=replace(ports(output=Item), pure_definitions=definitions))


def test_admission_whole_record_export_does_not_borrow_effect_read_authority():
    selected = replace(
        ports(output=Item, hidden=True),
        admission_readable_fields={
            State: frozenset({"items", "index"}),
            Item: frozenset({"public"}),
        },
    )
    compile_expr(at(), selected=selected)
    with pytest.raises(C0LawError, match="read port"):
        compile_expr(at(), selected=selected, admission=True)


def test_nullable_item_keeps_its_type_and_branch_local_proof():
    @dataclass(frozen=True)
    class OptionalState:
        items: tuple[Item | None, ...]

    paths = frozenset({"state.items"})
    fields = {OptionalState: frozenset({"items"}), Item: frozenset({"public"})}
    selected = replace(
        ports(),
        roots={"state": OptionalState},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
    )
    expression = local(
        at(index=0),
        {"if": {"when": {"not_none": ref("chosen")}, "then": ref("chosen.public"), "else": 0}},
    )
    program = compile_expr(expression, selected=selected)
    assert evaluate(program, OptionalState((None,))) == 0
    assert evaluate(program, OptionalState((Item(6, 66),))) == 6
    with pytest.raises(C0LawError, match="nullable value"):
        compile_expr(local(at(index=0), ref("chosen.public")), selected=selected)


@pytest.mark.parametrize("field", ["collection", "index", "extra"])
def test_compile_requires_exact_tuple_at_operands(field):
    expression = at()
    if field == "extra":
        expression["tuple_at"][field] = 0
    else:
        del expression["tuple_at"][field]
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        compile_expr(expression, selected=ports(output=Item, hidden=True))


@pytest.mark.parametrize(
    "index",
    [True, {"const": "0"}, {"const": None}, {"if": {"when": True, "then": 0, "else": None}}],
)
def test_compile_rejects_non_exact_integer_index(index):
    with pytest.raises(C0LawError, match="exact integer"):
        compile_expr(local(at(index=index), ref("chosen.public")))


@pytest.mark.parametrize("annotation", [int, tuple[int, str], tuple[()]])
def test_compile_requires_homogeneous_variadic_tuple(annotation):
    carrier = dataclass(frozen=True)(
        type("OtherState", (), {"__annotations__": {"items": annotation}})
    )
    selected = replace(
        ports(),
        roots={"state": carrier},
        readable_paths=frozenset({"state.items"}),
        admission_readable_paths=frozenset({"state.items"}),
        readable_fields={carrier: frozenset({"items"})},
        admission_readable_fields={carrier: frozenset({"items"})},
    )
    with pytest.raises(C0LawError, match="homogeneous typed tuple"):
        compile_expr(at(index=0), selected=selected)


@pytest.mark.parametrize(
    "items,index",
    [
        ((), 0),
        ((Item(1, 11),), -1),
        ((Item(1, 11),), 1),
        ((Item(1, 11),), True),
        ((Item(1, 11),), "0"),
        ([Item(1, 11)], 0),
        ((ForeignItem(1, 11),), 0),
        ((Item(1, 11), ForeignItem(2, 22)), 0),
    ],
)
def test_runtime_malformed_or_out_of_range_inputs_raise_existing_state_error(items, index):
    program = compile_expr(local(at(), ref("chosen.public")))
    with pytest.raises(C0ValueStateError) as failure:
        evaluate(program, State(items, index))
    assert type(failure.value) is C0ValueStateError


def test_runtime_rejects_tuple_and_integer_subclasses():
    class TupleSubclass(tuple):
        pass

    class IntSubclass(int):
        pass

    program = compile_expr(local(at(), ref("chosen.public")))
    for state in (State(TupleSubclass((Item(1, 11),)), 0), State((Item(1, 11),), IntSubclass(0))):
        with pytest.raises(C0ValueStateError):
            evaluate(program, state)


def test_lazy_if_does_not_evaluate_an_empty_or_negative_selection():
    for index in ({"sub": [0, 1]}, 0):
        expression = {
            "if": {"when": False, "then": local(at(index=index), ref("chosen.public")), "else": 12}
        }
        assert evaluate(compile_expr(expression), State((), 0)) == 12


def test_symbolic_bind_preserves_nominal_item_and_runs_without_frontend(monkeypatch):
    from test_nominal_signatures_v1 import source

    from nomos_c0 import composable_value_v1 as values

    lib = source()
    checked = check_nominal_lib(lib)
    box, item = checked.record("Box"), checked.record("Item")
    paths = frozenset({"state.items"})
    fields = {box: frozenset({"items"}), item: frozenset({"name", "amount", "origin"})}
    selected = replace(
        ports(),
        roots={"state": box},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        outputs={"value": item},
        record_types={},
    )
    program = compile_expr(at(index=1), selected=selected)
    ir = C0ValueBackend(checked.record_layout).capture(program)
    assert_symbolic(ir)
    layouts = (checked.record_layout, bind_nominal_records(checked.signatures))
    monkeypatch.setattr(values, "_prepare_expression", forbid_frontend)
    monkeypatch.setattr(values, "_infer_expr_type", forbid_frontend)
    monkeypatch.setattr(values, "lower_author_expression", forbid_frontend)
    for layout in layouts:
        rebound = C0ValueBackend(layout).bind(ir)
        row = layout.record("Item")
        first, second = row("a", 1, None), row("b", 2, K0OccurrenceRef(7))
        state = layout.record("Box")(first, (first, second))
        assert evaluate(rebound, state) is second


def choice_documents(opening):
    lib, ports_doc, source, assets = documents(opening=opening)
    lib["records"][0]["fields"] += [
        {"name": "chosen", "type": {"optional": "individual_ref"}},
        {"name": "seed", "type": {"int": [0, (1 << 63) - 1]}},
    ]
    assets["opening"]["scene"].update(chosen=None, seed=17)
    value = ports_doc["due_events"][0]["value"]
    value["read"].append("scene.seed")
    value["write_paths"] += ["scene.chosen", "scene.seed"]
    value["outputs"].update(chosen="scene.chosen", seed="scene.seed")
    body = source["lawdefs"][1]["body"]["law"]
    body["bindings"] = [
        {
            "name": "pool",
            "stage": "admission",
            "let": {
                "collect_matching": {
                    "collection": ref("items.members"),
                    "as": "member",
                    "where": True,
                    "value": ref("member.individual"),
                }
            },
        },
        {
            "name": "n",
            "stage": "admission",
            "let": {"count_matching": {"collection": ref("pool"), "as": "entry", "where": True}},
        },
    ]
    body["outputs"].update(
        chosen={
            "if": {
                "when": {"eq": [ref("n"), 0]},
                "then": None,
                "else": {
                    "if": {
                        "when": {"eq": [ref("n"), 1]},
                        "then": at(ref("pool"), 0),
                        "else": at(
                            ref("pool"),
                            {
                                "sub": [
                                    {"die_roll": {"seed": ref("scene.seed"), "sides": ref("n")}},
                                    1,
                                ]
                            },
                        ),
                    }
                },
            }
        },
        seed={
            "if": {
                "when": {"lt": [1, ref("n")]},
                "then": {"die_next_seed": ref("scene.seed")},
                "else": ref("scene.seed"),
            }
        },
    )
    if opening < 2:
        source["game_form"]["seats"][0]["eligible"] = False
    return lib, ports_doc, source, assets


@pytest.mark.parametrize("opening", [0, 1, 5])
def test_actual_due_selects_original_refs_and_empty_or_singleton_never_draws_d1(
    opening, monkeypatch
):
    from nomos_c0 import composable_value_v1 as values

    lib, ports_doc, source, assets = choice_documents(opening)
    program = _compile(lib, ports_doc, source)
    if opening < 2:
        monkeypatch.setattr(values, "_die_roll", forbid_frontend)
        monkeypatch.setattr(values, "_die_next_seed", forbid_frontend)
    for selected in (program, bind_program(program.program_ir, _layout(program))):
        session = selected.start(deepcopy(assets))
        if opening > 1:
            submit(session, "count_0")
        objects = session.author_object_instances()
        actual = tuple(row.individual for row in objects if row.individual.family == "artifact")
        session.continue_form("seat_0")
        expected = (
            None if not actual else actual[0 if len(actual) == 1 else roll(17, len(actual)) - 1]
        )
        assert scene(session).chosen == expected
        assert scene(session).seed == (next_seed(17) if len(actual) > 1 else 17)
        assert session.author_object_instances() == objects
        event = session._runtime.occurrence_history()[-1]
        assert tuple(ref for _, ref in event.participants.objects) == actual


def test_invalid_due_selection_rolls_back_objects_scene_time_and_history():
    lib, ports_doc, source, assets = choice_documents(5)
    source["lawdefs"][1]["body"]["law"]["outputs"]["chosen"] = at(ref("pool"), ref("n"))
    session = _compile(lib, ports_doc, source).start(assets)
    submit(session, "count_0")
    before = (
        session.author_snapshot(),
        session.author_object_instances(),
        session._runtime._time,
        session._runtime.action_value_state(),
    )
    with pytest.raises(K0SettlementDefect):
        advance(session)
    assert (
        session.author_snapshot(),
        session.author_object_instances(),
        session._runtime._time,
        session._runtime.action_value_state(),
    ) == before
    assert session._runtime._fatal
