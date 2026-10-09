"""Lexical computations reuse checked values without widening stage or authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect
from nomos_kernel._owner_abi import _validate_closed_host_object
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as values
from nomos_c0.composable_value_v1 import C0ValuePorts, C0ValueRangeError, compile_value_program
from nomos_c0.owner_graph_v1 import compile_owner_graph


@dataclass(frozen=True)
class Sample:
    value: int


@dataclass(frozen=True)
class State:
    count: int
    ready: bool
    sample: Sample | None
    secret: int
    items: tuple[Sample, ...] = ()


def ref(name):
    return {"ref": name}


def const(value):
    return {"const": value}


def local(name, expression, stage="admission"):
    return {"name": name, "let": expression, "stage": stage}


def scoped(name, value, body):
    return {"let": {"name": name, "value": value, "in": body}}


def ports(outputs=None):
    admission = frozenset(
        {"state.count", "state.ready", "state.sample", "state.sample.value", "state.items"}
    )
    return C0ValuePorts(
        roots={"state": State},
        readable_paths=admission | {"state.secret"},
        admission_readable_paths=admission,
        readable_fields={
            State: frozenset({"count", "ready", "sample", "secret", "items"}),
            Sample: frozenset({"value"}),
        },
        admission_readable_fields={
            State: frozenset({"count", "ready", "sample", "items"}),
            Sample: frozenset({"value"}),
        },
        writable_fields={State: frozenset({"count"}), Sample: frozenset({"value"})},
        record_types={"Sample": Sample},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs=outputs or {"value": int},
    )


def program(
    bindings=(), guard=None, outputs=None, *, selected_ports=None, admission_outputs=frozenset()
):
    source = {
        "schema": "c0.value.v1",
        "bindings": list(bindings),
        "guard": guard if guard is not None else const(True),
        "outputs": outputs or {"value": ref("state.count")},
    }
    return compile_value_program(
        json.dumps(source), selected_ports or ports(), admission_outputs=admission_outputs
    )


def state(count=3, ready=True, sample=None):
    return {"state": State(count, ready, sample, 19)}


def test_computation_is_cached_only_inside_one_evaluation(monkeypatch):
    compiled = program(
        [local("next_count", {"add": [ref("state.count"), const(1)]})],
        {"le": [const(1), ref("next_count")]},
        {"value": {"add": [ref("next_count"), ref("next_count")]}},
        admission_outputs=frozenset({"value"}),
    )
    calls = []
    original = values._eval

    def counted(node, *args):
        if node.origin == "bindings[0].let":
            calls.append(node)
        return original(node, *args)

    monkeypatch.setattr(values, "_eval", counted)
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 8}
    assert len(calls) == 1
    assert compiled.evaluate_admission_outputs(state(7)) == {"value": 16}
    assert len(calls) == 2
    assert compiled.admits(state())
    assert len(calls) == 3


def test_compiled_admission_ports_are_reused_but_current_values_are_not(monkeypatch):
    declared = ports()
    compiled = program(
        guard={"le": [ref("state.count"), const(4)]},
        selected_ports=declared,
        admission_outputs=frozenset({"value"}),
    )
    assert compiled._admission_ports.readable_paths == declared.admission_readable_paths
    assert compiled._ports is compiled._ports
    assert compiled._admission_ports is compiled._admission_ports
    assert "state.secret" not in compiled._admission_ports.readable_paths
    declared.roots.clear()
    declared.admission_readable_fields.clear()

    def forbid_replace(*args, **kwargs):
        pytest.fail("runtime rebuilt constant admission ports")

    monkeypatch.setattr(values, "replace", forbid_replace)
    assert compiled.admits(state(3))
    assert compiled.evaluate_admission_outputs(state(4)) == {"value": 4}
    assert not compiled.admits(state(5))
    assert compiled.evaluate_admission_outputs(state(5)) is None
    with pytest.raises(values.C0ValueStateError):
        compiled.admits({"state": Sample(3)})


def test_reused_generic_ports_remain_closed_immutable_and_read_current_bindings(monkeypatch):
    pair = tuple[int | str, int]
    declared = replace(
        ports({"value": tuple[Sample, ...]}),
        tuple_fields={pair: {"left": 0}},
        admission_tuple_fields={pair: {"left": 0}},
    )
    compiled = program(
        [local("current", ref("state.count"))],
        guard={"le": [ref("current"), const(4)]},
        outputs={"value": ref("state.items")},
        selected_ports=declared,
        admission_outputs=frozenset({"value"}),
    )
    _validate_closed_host_object(compiled, "compiled value")
    assert compiled._ports.outputs == {"value": tuple[Sample, ...]}
    assert compiled._ports.tuple_fields == {pair: {"left": 0}}
    reordered = tuple[str | int, int]
    assert compiled._ports.tuple_fields[reordered] == {"left": 0}
    assert {reordered: {"left": 0}} == compiled._ports.tuple_fields
    assert compiled._ports.tuple_fields == {reordered: {"left": 0}}
    with pytest.raises(TypeError):
        compiled._ports.outputs["value"] = int
    with pytest.raises(TypeError):
        compiled._admission_ports.tuple_fields[pair]["left"] = 1
    declared.tuple_fields[pair]["left"] = 1
    declared.admission_tuple_fields.clear()
    assert compiled._admission_ports.tuple_fields[pair]["left"] == 0

    def forbid_replace(*args, **kwargs):
        pytest.fail("runtime rebuilt constant ports for a bound computation")

    monkeypatch.setattr(values, "replace", forbid_replace)
    assert compiled.evaluate_admission_outputs(state(3)) == {"value": ()}
    assert compiled.evaluate_admission_outputs(
        {"state": State(4, True, None, 19, (Sample(8),))}
    ) == {"value": (Sample(8),)}
    assert compiled.evaluate_admission_outputs(state(5)) is None


def test_unused_computation_and_unselected_branch_do_not_run():
    bad = {"ceil_div": [const(1), const(0)]}
    compiled = program([local("unused", bad)])
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 3}
    selected = program(
        [local("bad", bad)],
        outputs={
            "value": {
                "if": {"when": ref("state.ready"), "then": ref("state.count"), "else": ref("bad")}
            }
        },
    )
    assert selected.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 3}
    with pytest.raises(C0ValueRangeError):
        selected.evaluate(state(ready=False), occurrence=K0OccurrenceRef(2))


def test_existing_required_lookup_is_not_made_lazy():
    compiled = program(
        [
            {
                "name": "item",
                "collection": "state.items",
                "as": "candidate",
                "where": const(True),
                "required": True,
            }
        ]
    )
    assert compiled.admits(state()) is False
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) is None


def test_scoped_let_is_lexical_and_preserves_selected_branch_nullable_proof():
    expression = {
        "if": {
            "when": {"not_none": ref("state.sample")},
            "then": scoped(
                "amount", ref("state.sample.value"), {"add": [ref("amount"), ref("amount")]}
            ),
            "else": const(0),
        }
    }
    compiled = program(outputs={"value": expression})
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 0}
    assert compiled.evaluate(state(sample=Sample(4)), occurrence=K0OccurrenceRef(2)) == {"value": 8}
    with pytest.raises(C0LawError, match="root"):
        program(
            outputs={"value": {"add": [scoped("amount", const(1), ref("amount")), ref("amount")]}}
        )


def test_nonselected_branch_still_requires_static_read_authority():
    with pytest.raises(C0LawError, match="boundary"):
        program(
            guard={
                "if": {
                    "when": const(True),
                    "then": const(True),
                    "else": scoped(
                        "hidden", ref("state.secret"), {"eq": [ref("hidden"), const(0)]}
                    ),
                }
            }
        )


@pytest.mark.parametrize(
    "bindings",
    [
        [local("self", ref("self"))],
        [local("first", ref("second")), local("second", const(1))],
        [local("state", const(1))],
        [local("occurrence", const(1))],
        [local("same", const(1)), local("same", const(2))],
        [local("x", const(1), "unknown")],
        [local("later", const(1), "effect"), local("early", const(1))],
        [local(f"value_{index}", const(index)) for index in range(65)],
    ],
)
def test_bad_declaration_graph_is_compile_error(bindings):
    with pytest.raises(C0LawError):
        program(bindings)


def test_effect_computation_uses_actual_occurrence_and_full_checked_ports():
    compiled = program(
        [
            local("hidden", ref("state.secret"), "effect"),
            local("stamp", ref("occurrence"), "effect"),
        ],
        ref("state.ready"),
        {"value": ref("hidden"), "stamp": ref("stamp")},
        selected_ports=ports({"value": int, "stamp": K0OccurrenceRef}),
    )
    assert compiled.admits(state())
    assert compiled.evaluate(state(ready=False), occurrence=K0OccurrenceRef(1)) is None
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(7)) == {
        "value": 19,
        "stamp": K0OccurrenceRef(7),
    }


@pytest.mark.parametrize("use", ["guard", "indirect_guard", "lookup", "debit", "admission_output"])
def test_effect_alias_cannot_flow_back_into_admission(use):
    bindings = [local("hidden", ref("state.secret"), "effect")]
    source = {
        "schema": "c0.value.v1",
        "bindings": bindings,
        "guard": const(True),
        "outputs": {"value": ref("state.count")},
    }
    kwargs = {}
    if use == "guard":
        source["guard"] = {"eq": [ref("hidden"), const(1)]}
    elif use == "indirect_guard":
        bindings[:0] = [local("earlier", ref("middle")), local("middle", ref("hidden"))]
        source["guard"] = {"eq": [ref("earlier"), const(1)]}
    elif use == "lookup":
        bindings.insert(
            0,
            {
                "name": "item",
                "collection": "state.items",
                "as": "candidate",
                "where": {"eq": [ref("hidden"), const(1)]},
                "required": False,
            },
        )
    elif use == "debit":
        source["outputs"] = {}
        source["effects"] = [
            {"spend": {"debit": "state.count", "amount": ref("hidden"), "floor": 0}}
        ]
        kwargs["state_outputs"] = {"state.count": "value"}
    else:
        source["outputs"]["value"] = ref("hidden")
        kwargs["admission_outputs"] = frozenset({"value"})
    with pytest.raises(C0LawError, match="root"):
        compile_value_program(json.dumps(source), ports(), **kwargs)


def test_effect_local_can_use_guard_proof_but_admission_local_cannot():
    guard = {"not_none": ref("state.sample")}
    with pytest.raises(C0LawError, match="nullable"):
        program([local("amount", ref("state.sample.value"))], guard, {"value": ref("amount")})
    compiled = program(
        [local("amount", ref("state.sample.value"), "effect")], guard, {"value": ref("amount")}
    )
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) is None
    assert compiled.evaluate(state(sample=Sample(4)), occurrence=K0OccurrenceRef(2)) == {"value": 4}


@pytest.mark.parametrize(
    "expression",
    [
        ref("state"),
        {"if": {"when": ref("state.ready"), "then": ref("state"), "else": ref("state")}},
        {"copy": {"from": ref("state"), "changes": {"count": const(5)}}},
        scoped("inner", ref("state"), ref("inner")),
    ],
)
def test_alias_member_access_does_not_expand_exact_root_paths(expression):
    declared = ports()
    declared = replace(
        declared,
        readable_paths=declared.readable_paths | {"state"},
        admission_readable_paths=declared.admission_readable_paths | {"state"},
        admission_readable_fields=declared.readable_fields,
    )
    # Even with another granted field of this nominal carrier, state.secret is not granted here.
    declared = replace(declared, readable_paths=declared.readable_paths - {"state.secret"})
    with pytest.raises(C0LawError, match="boundary"):
        program(
            [local("alias", expression)],
            {"eq": [ref("alias.secret"), const(19)]},
            selected_ports=declared,
        )


def test_local_record_alias_can_be_guarded_without_losing_its_nominal_type():
    compiled = program(
        [local("selected", ref("state.sample"))],
        {"not_none": ref("selected")},
        {"value": ref("selected.value")},
    )
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) is None
    assert compiled.evaluate(state(sample=Sample(6)), occurrence=K0OccurrenceRef(2)) == {"value": 6}


def test_real_k0_rechecks_current_local_computation_and_retains_rejection_atomicity():
    from authored_counter_v1 import _actor, _inputs

    library, source, assets = _inputs(1, 1)
    value = source["lawdefs"][0]["body"]["value"]
    value["bindings"] = [local("next_count", {"add": [ref("actor.count"), {"arg": "step"}]})]
    value["guard"] = {"all": [value["guard"], {"le": [ref("next_count"), const(1)]}]}
    value["outputs"]["count"] = ref("next_count")
    session = compile_owner_graph(library, source).start(assets)
    offer = session.offers("seat_0")[0]
    first = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(first, K0Published)
    assert _actor(session, 0).count == 1
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


@pytest.mark.parametrize("admitted", [False, True])
def test_effect_computation_fault_uses_real_k0_atomic_and_fatal_boundary(admitted):
    from authored_counter_v1 import _actor, _inputs

    library, source, assets = _inputs(1, 1)
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"] = const(admitted)
    value["bindings"] = [local("broken", {"ceil_div": [{"arg": "step"}, const(0)]}, "effect")]
    value["outputs"]["count"] = ref("broken")
    session = compile_owner_graph(library, source).start(assets)
    offer = session.offers("seat_0")[0]
    before = session._runtime.occurrence_history()
    if admitted:
        with pytest.raises(K0SettlementDefect):
            session.submit("seat_0", offer.entry, dict(offer.payload))
        with pytest.raises(K0SettlementDefect):
            session.submit("seat_0", offer.entry, dict(offer.payload))
    else:
        assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert _actor(session, 0).count == 0
    assert session._runtime.occurrence_history() == before


def test_run_needs_no_frontend_or_type_inference(monkeypatch):
    compiled = program(
        [local("amount", scoped("inner", ref("state.count"), {"add": [ref("inner"), const(1)]}))],
        outputs={"value": ref("amount")},
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Run called the frontend")

    for name in ("_expr_type", "_infer_expr_type", "_prepare_expression", "_compile_expression"):
        monkeypatch.setattr(values, name, forbidden)
    assert compiled.evaluate(state(), occurrence=K0OccurrenceRef(1)) == {"value": 4}


def test_scoped_guard_keeps_named_diagnostic_location():
    compiled = program(
        guard=scoped("amount", ref("state.count"), {"require": [{"small_enough": "amount < 2"}]})
    )
    (failure,) = compiled.false_guard_clauses(state())
    assert failure.names == ("small_enough",)
    assert failure.path == "guard.let.in.require.small_enough"
    assert compiled.guard_ir.clauses[0].path == failure.path


def test_shadow_names_and_nonnull_proofs_do_not_escape_scoped_guard():
    with pytest.raises(C0LawError, match="shadows"):
        program(guard=scoped("state", const(1), const(True)))
    with pytest.raises(C0LawError, match="nullable"):
        program(
            guard=scoped("choice", ref("state.sample"), {"not_none": ref("choice")}),
            outputs={"value": ref("state.sample.value")},
        )


@pytest.mark.parametrize("member", ["missing", "value.missing"])
@pytest.mark.parametrize("scoped_alias", [False, True])
def test_unknown_member_of_constructed_alias_is_controlled_compile_error(member, scoped_alias):
    constructed = {"record": {"type": "Sample", "fields": {"value": const(1)}}}
    condition = {"eq": [ref(f"alias.{member}"), const(1)]}
    with pytest.raises(C0LawError, match="field"):
        if scoped_alias:
            program(guard=scoped("alias", constructed, condition))
        else:
            program([local("alias", constructed)], condition)
