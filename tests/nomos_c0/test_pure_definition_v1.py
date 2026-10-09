"""Typed Lib computations preserve caller authority, lexical scope and K0 settlement."""

from __future__ import annotations

from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_local_computation_v1 import Sample, State, const, local, ports, program, ref, state

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as values
from nomos_c0.composable_value_v1 import verify_pure_definition_types
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.pure_definition_v1 import check_pure_definitions


def definition(name="compute", parameters=None, body=None, result="int", stage="admission"):
    return {
        "name": name,
        "parameters": parameters if parameters is not None else {"number": "int"},
        "result": result,
        "stage": stage,
        "body": body if body is not None else {"add": [ref("number"), const(1)]},
    }


def call(name="compute", **arguments):
    return {"call": {"ref": name, "args": arguments}}


def checked(raw):
    records = {"State": State, "Sample": Sample}
    table = check_pure_definitions(raw, records)
    verify_pure_definition_types(table, records)
    return table


def selected(raw, **changes):
    return replace(ports(), pure_definitions=checked(raw), **changes)


def test_scalar_formal_can_share_caller_root_name_without_capturing_it():
    raw = [definition(parameters={"state": "int"}, body={"add": [ref("state"), ref("state")]})]
    compiled = program(
        outputs={"value": call(state=ref("state.count"))}, selected_ports=selected(raw)
    )
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 6}


def test_nested_calls_are_closed_and_nullable_formals_require_their_own_proof():
    raw = [
        definition(
            "read_sample",
            {"sample": {"optional": "Sample"}},
            {
                "if": {
                    "when": {"not_none": ref("sample")},
                    "then": ref("sample.value"),
                    "else": const(0),
                }
            },
        ),
        definition(
            "compute", {"value": {"optional": "Sample"}}, call("read_sample", sample=ref("value"))
        ),
    ]
    compiled = program(
        outputs={"value": call(value=ref("state.sample"))}, selected_ports=selected(raw)
    )
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 0}
    assert compiled.evaluate(state(sample=Sample(8)), occurrence=K0OccurrenceRef(2)) == {"value": 8}
    raw[0]["body"] = ref("sample.value")
    with pytest.raises(C0LawError, match="nullable"):
        checked(raw)


def test_tuple_formal_counts_nominal_elements():
    raw = [
        definition(
            parameters={"items": {"tuple": "Sample"}},
            body={
                "count_matching": {
                    "collection": ref("items"),
                    "as": "item",
                    "where": {"lt": [const(2), ref("item.value")]},
                }
            },
        )
    ]
    compiled = program(
        outputs={"value": call(items=ref("state.items"))}, selected_ports=selected(raw)
    )
    current = {"state": State(0, True, None, 0, (Sample(1), Sample(3), Sample(4)))}
    assert compiled.evaluate(current, occurrence=K0OccurrenceRef(1)) == {"value": 2}


def query_definition():
    return definition(
        parameters={"items": {"tuple": "Sample"}, "other": {"tuple": "Sample"}},
        body={
            "count_matching": {
                "collection": {
                    "query": {
                        "from": {"collection": ref("items"), "as": "state", "key": "value"},
                        "join": {"collection": ref("other"), "as": "matched", "key": "value"},
                        "where": call("positive", number=ref("state.value")),
                    }
                },
                "as": "result",
                "where": True,
            }
        },
    )


def test_pure_query_alias_is_local_even_when_it_names_a_caller_root():
    raw = [
        query_definition(),
        definition("positive", body={"lt": [const(2), ref("number")]}, result="bool"),
    ]
    compiled = program(
        outputs={"value": call(items=ref("state.items"), other=ref("state.items"))},
        selected_ports=selected(raw),
    )
    current = {"state": State(0, True, None, 0, (Sample(1), Sample(3), Sample(4)))}
    assert compiled.evaluate(current, occurrence=K0OccurrenceRef(1)) == {"value": 2}


def test_pure_query_local_alias_still_requires_caller_member_read_permission():
    raw = [
        query_definition(),
        definition("positive", body={"lt": [const(2), ref("number")]}, result="bool"),
    ]
    ports = selected(raw)
    fields = dict(ports.readable_fields)
    fields[Sample] = frozenset()
    with pytest.raises(C0LawError):
        program(
            outputs={"value": call(items=ref("state.items"), other=ref("state.items"))},
            selected_ports=replace(ports, readable_fields=fields),
        )


@pytest.mark.parametrize("fault", ["left_shadow", "right_shadow", "capture", "leak", "duplicate"])
def test_pure_query_rejects_shadowing_capture_and_alias_escape(fault):
    raw = query_definition()
    body = raw["body"]["count_matching"]
    query = body["collection"]["query"]
    if fault == "left_shadow":
        query["from"]["as"] = "items"
    elif fault == "right_shadow":
        query["join"]["as"] = "other"
    elif fault == "capture":
        query["where"] = ref("external.ready")
    elif fault == "leak":
        body["where"] = ref("matched.value")
    else:
        query["join"]["as"] = query["from"]["as"]
    with pytest.raises(C0LawError):
        checked([raw, definition("positive", body=True, result="bool")])


@pytest.mark.parametrize(
    "change",
    [
        "capture",
        "implicit_occurrence",
        "parameter_occurrence",
        "recursive",
        "unknown",
        "wrong_result",
        "wrong_body",
        "shadow",
        "bad_stage",
    ],
)
def test_invalid_or_unused_lib_definition_is_compile_error(change):
    raw = [definition()]
    if change == "capture":
        raw[0]["body"] = ref("state.count")
    elif change == "implicit_occurrence":
        raw[0].update(body=ref("occurrence"), result="occurrence_ref", stage="effect")
    elif change == "parameter_occurrence":
        raw[0]["parameters"] = {"occurrence": "int"}
    elif change == "recursive":
        raw[0]["body"] = call(number=ref("number"))
    elif change == "unknown":
        raw[0]["body"] = call("missing", number=ref("number"))
    elif change == "wrong_result":
        raw[0]["result"] = "bool"
    elif change == "wrong_body":
        raw[0]["body"] = {"add": [ref("number"), const(True)]}
    elif change == "shadow":
        raw[0]["body"] = {"let": {"name": "number", "value": const(1), "in": ref("number")}}
    else:
        raw[0]["stage"] = "world"
    with pytest.raises(C0LawError):
        checked(raw)


@pytest.mark.parametrize(
    "arguments", [{}, {"number": const(True)}, {"number": const(1), "extra": const(2)}]
)
def test_call_checks_exact_signature(arguments):
    with pytest.raises(C0LawError):
        program(outputs={"value": call(**arguments)}, selected_ports=selected([definition()]))


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("inside", [False, True])
def test_record_arguments_and_returns_cannot_launder_exact_read_permissions(nested, inside):
    raw = [definition("identity", {"value": "State"}, ref("value"), "State")]
    if inside:
        raw.append(definition("compute", {"value": "State"}, ref("value.secret")))
    else:
        raw.append(
            definition("compute", {"value": "State"}, call("identity", value=ref("value")), "State")
        )
    if nested:
        raw.append(
            definition(
                "wrapper",
                {"value": "State"},
                call(value=ref("value")),
                "int" if inside else "State",
            )
        )
    target = "wrapper" if nested else "compute"
    declared = selected(raw)
    declared = replace(
        declared,
        readable_paths=(declared.readable_paths | {"state"}) - {"state.secret"},
        admission_readable_paths=declared.admission_readable_paths | {"state"},
        admission_readable_fields=declared.readable_fields,
    )
    with pytest.raises(C0LawError, match="boundary"):
        if inside:
            program(
                guard={"eq": [call(target, value=ref("state")), const(19)]}, selected_ports=declared
            )
        else:
            program(
                [local("alias", call(target, value=ref("state")))],
                {"eq": [ref("alias.secret"), const(19)]},
                selected_ports=declared,
            )


def test_parameters_are_lazy_once_per_call_but_not_cached_across_queries(monkeypatch):
    raw = [
        definition(
            parameters={"used": "int", "unused": "int"}, body={"add": [ref("used"), ref("used")]}
        )
    ]
    compiled = program(
        outputs={
            "value": call(
                used={"add": [ref("state.count"), const(1)]},
                unused={"ceil_div": [const(1), const(0)]},
            )
        },
        selected_ports=selected(raw),
    )
    original, observed = values._eval, []

    def counted(node, *args):
        if node.origin == "outputs.value.call.args.used":
            observed.append(node)
        return original(node, *args)

    monkeypatch.setattr(values, "_eval", counted)
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 8}
    assert len(observed) == 1
    assert compiled.evaluate(state(6), occurrence=K0OccurrenceRef(2)) == {"value": 14}
    assert len(observed) == 2


def test_effect_die_has_explicit_inputs_and_cannot_flow_back_to_admission():
    raw = [
        definition(
            parameters={"seed": "int"},
            body={"die_roll": {"seed": ref("seed"), "sides": const(6)}},
            stage="effect",
        )
    ]
    compiled = program(outputs={"value": call(seed=const(3))}, selected_ports=selected(raw))
    result = compiled.evaluate(state(), occurrence=K0OccurrenceRef(1))["value"]
    assert 1 <= result <= 6
    with pytest.raises(C0LawError, match="admission"):
        program(guard={"eq": [call(seed=const(3)), const(1)]}, selected_ports=selected(raw))
    raw.append(definition("wrapper", {"seed": "int"}, call(seed=ref("seed"))))
    with pytest.raises(C0LawError, match="admission"):
        checked(raw)


def test_occurrence_is_available_only_as_an_explicit_argument():
    raw = [
        definition(
            parameters={"stamp": "occurrence_ref"}, body=ref("stamp"), result="occurrence_ref"
        )
    ]
    compiled = program(
        outputs={"value": call(stamp=ref("occurrence"))},
        selected_ports=selected(raw, outputs={"value": K0OccurrenceRef}),
    )
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(7)) == {
        "value": K0OccurrenceRef(7)
    }
    with pytest.raises(C0LawError):
        program([local("early", call(stamp=ref("occurrence")))], selected_ports=selected(raw))


def test_definition_guard_origin_and_repeated_calls_have_separate_clause_scopes():
    raw = [
        definition(
            parameters={"number": "int"}, body={"require": [{"small": "number < 2"}]}, result="bool"
        )
    ]
    condition = call(number=ref("state.count"))
    compiled = program(guard={"all": [condition, condition]}, selected_ports=selected(raw))
    (failure,) = compiled.false_guard_clauses(state())
    assert failure.names == ("small",)
    assert failure.path == "pure_definitions.compute.body.require.small"
    assert len(compiled.guard_ir.clauses) == 2


def test_run_never_calls_definition_checker_or_expression_frontend(monkeypatch):
    compiled = program(
        outputs={"value": call(number=ref("state.count"))}, selected_ports=selected([definition()])
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Run entered Compile")

    for name in (
        "_compile_expression",
        "_infer_expr_type",
        "_prepare_expression",
        "verify_pure_definition_types",
    ):
        monkeypatch.setattr(values, name, forbidden)
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 4}


def test_lib_record_table_precedes_cross_record_function_and_invariant_checks():
    from test_declarative_nominal_v0 import _source

    source = _source()
    source["pure_definitions"] = [
        definition(
            parameters={"parcel": "Parcel", "routes": {"tuple": "Route"}},
            body={
                "all": [
                    {"eq": [ref("parcel.status"), const("home")]},
                    {
                        "eq": [
                            {
                                "count_matching": {
                                    "collection": ref("routes"),
                                    "as": "route",
                                    "where": {"le": [ref("route.travel"), const(2)]},
                                }
                            },
                            const(1),
                        ]
                    },
                ]
            },
            result="bool",
        )
    ]
    scene = next(row for row in source["records"] if row["name"] == "Scene")
    scene["invariant"] = call(parcel=ref("state.parcel"), routes=ref("state.routes"))
    nominal = check_nominal_lib(source)
    parcel = nominal.record("Parcel")("p", "dock", "home", None, None)
    route = nominal.record("Route")("dock", 2)
    nominal.record("Scene")(parcel, (route,), "none").validate_for_k0()
    with pytest.raises(K0ProfileError, match="invariant"):
        nominal.record("Scene")(parcel, (), "none").validate_for_k0()


def _counter(definitions):
    from authored_counter_v1 import build, counter_documents

    lib, declared, source, assets = counter_documents(definitions=definitions)
    value = source["lawdefs"][0]["body"]["value"]
    value["outputs"]["count"] = call(number={"add": [ref("actor.count"), {"arg": "step"}]})
    return compile_owner_graph(build(lib, declared), source).start(assets)


def test_one_definition_edit_changes_real_k0_output_without_changing_source_or_opening():
    from authored_counter_v1 import _actor

    first = _counter([definition(body=ref("number"))])
    second = _counter([definition(body={"add": [ref("number"), const(4)]})])
    for session, expected in ((first, 1), (second, 5)):
        offer = session.offers("seat_0")[0]
        assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
        assert _actor(session, 0).count == expected
    assert (
        first._runtime.occurrence_history()[0].source
        == second._runtime.occurrence_history()[0].source
    )


def test_pure_body_failure_rolls_back_real_k0_and_keeps_fatal_boundary():
    from authored_counter_v1 import _actor

    session = _counter([definition(body={"ceil_div": [ref("number"), const(0)]})])
    offer = session.offers("seat_0")[0]
    before = session._runtime.occurrence_history()
    with pytest.raises(K0SettlementDefect):
        session.submit("seat_0", offer.entry, dict(offer.payload))
    assert _actor(session, 0).count == 0
    assert session._runtime.occurrence_history() == before
    with pytest.raises(K0SettlementDefect):
        session.submit("seat_0", offer.entry, dict(offer.payload))


def test_pure_guard_rechecks_current_state_and_finite_rejection_is_zero_write():
    from authored_counter_v1 import _actor, build, counter_documents

    lib, declared, source, assets = counter_documents(
        definitions=[
            definition(
                parameters={"number": "int"}, body={"lt": [ref("number"), const(1)]}, result="bool"
            )
        ]
    )
    source["lawdefs"][0]["body"]["value"]["guard"] = call(number=ref("actor.count"))
    session = compile_owner_graph(build(lib, declared), source).start(assets)
    offer = session.offers("seat_0")[0]
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    assert _actor(session, 0).count == 1


def test_call_graph_and_expanded_body_have_finite_compile_limits():
    raw = [definition("leaf", {}, const(1))]
    for index in range(14):
        previous = raw[-1]["name"]
        raw.append(definition(f"node_{index}", {}, {"add": [call(previous), call(previous)]}))
    with pytest.raises(C0LawError, match="node limit"):
        checked(raw)
    raw = [definition(f"chain_{index}", {}, call(f"chain_{index + 1}")) for index in range(16)]
    raw.append(definition("chain_16", {}, const(1)))
    with pytest.raises(C0LawError, match="too deep"):
        checked(raw)
