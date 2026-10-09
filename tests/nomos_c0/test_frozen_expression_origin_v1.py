"""Physical author locations survive checking and mechanical backend binding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace

import pytest
import yaml
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_local_computation_v1 import Sample, State, ports, program, state

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_document_v1 import (
    C0AuthorDocument,
    C0OriginFrame,
    C0SourceContext,
    parse_author_document,
    read_author_document,
)
from nomos_c0.composable_value_v1 import compile_value_program
from nomos_c0.expression_ir_v1 import C0Expression
from nomos_c0.pure_definition_v1 import check_pure_definitions
from nomos_c0.value_symbols_v1 import bind_value_program, symbolize_value_program


def _document(text, file="world.yaml", format="yaml"):
    return parse_author_document(text, file=file, format=format)


def test_yaml_coordinates_are_value_spans_not_guessed_line_searches():
    text = 'first:\n  guard: {expr: "1 < 2"}\nsecond:\n  - {guard: false}\n'
    document = _document(text)
    span = document.spans["first", "guard", "expr"]
    assert (span.line, span.column, span.end_line, span.end_column) == (2, 17, 2, 24)
    assert span.file == "world.yaml"
    assert span.digest == hashlib.sha256(text.encode()).hexdigest() == document.digest
    assert document.spans["second", 0, "guard"].line == 4
    context = document.context(aliases=(("guard", ("first", "guard")),))
    assert context.locate("guard.expr.generated[0]") is span
    assert context.locate("guarded.expr") is None
    assert document.context().locate("unknown") is None
    with pytest.raises(FrozenInstanceError):
        span.line = 99
    with pytest.raises(TypeError):
        document.spans["first", "guard"] = span
    with pytest.raises(TypeError):
        document.data["first"]["guard"] = False
    data = document.to_data()
    data["first"]["guard"] = False
    assert document.to_data()["first"]["guard"] == {"expr": "1 < 2"}


def test_json_is_strict_json_and_has_physical_value_coordinates():
    document = _document(
        '{\n  "items": [{"number": 1e2, "text": "yes"}]\n}\n', file="world.json", format="json"
    )
    assert document.to_data() == {"items": [{"number": 100.0, "text": "yes"}]}
    assert document.spans["items", 0, "number"].line == 2
    with pytest.raises(ValueError):
        _document('{"not_json": True}', format="json")


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\na: 2\n",
        "outer: {same: 1, same: 2}",
        "true: 1",
        "[1, 2]",
        "a: &value [*value]",
        "a: 2026-10-04",
        "a: .nan",
        "a: !!python/object:foo {}",
        "a: 1\n---\nb: 2",
        "",
    ],
)
def test_invalid_or_ambiguous_document_is_rejected(text):
    with pytest.raises(ValueError):
        _document(text)


def test_finite_yaml_aliases_expand_as_data_with_use_token_coordinates(monkeypatch):
    from nomos_c0 import author_document_v1 as documents

    document = _document("a: &value {item: [1, 2]}\nb: *value\nc: [*value]\n")
    assert document.to_data() == {
        "a": {"item": [1, 2]},
        "b": {"item": [1, 2]},
        "c": [{"item": [1, 2]}],
    }
    assert document.spans["b", "item", 0].line == 2
    assert (document.spans["b",].column, document.spans["b",].end_column) == (4, 10)
    assert document.spans["a", "item", 0].line == 1
    assert document.spans["c", 0, "item", 1].line == 3
    with pytest.raises(ValueError, match="alias"):
        _document("a: *missing")
    monkeypatch.setattr(documents, "_MAX_NODES", 20)
    with pytest.raises(ValueError, match="structure limit"):
        _document("a: &a [1, 2]\nb: &b [*a, *a, *a]\nc: [*b, *b]")


def test_document_limits_and_detached_construction(monkeypatch):
    from nomos_c0 import author_document_v1 as documents

    monkeypatch.setattr(documents, "_MAX_BYTES", 20)
    with pytest.raises(ValueError, match="byte limit"):
        _document("a: " + "x" * 21)
    monkeypatch.setattr(documents, "_MAX_DEPTH", 1)
    with pytest.raises(ValueError, match="structure limit"):
        _document("a: {b: {c: 1}}")
    original = _document("a: 1")
    raw = {"a": [1]}
    other = C0AuthorDocument(original.file, original.digest, raw, original.index)
    raw["a"].append(2)
    assert other.to_data() == {"a": [1]}
    with pytest.raises(ValueError):
        C0SourceContext(original.index, aliases=(("a", ()), ("a", ())))
    with pytest.raises(ValueError):
        C0SourceContext(original.index, aliases=(("a", ([],)),))


def _lib():
    return _document(
        """pure_definitions:
  - name: small
    parameters: {number: int}
    result: bool
    stage: admission
    body: 'number < 2'
  - name: nested
    parameters: {number: int}
    result: bool
    stage: admission
    body: {call: {ref: small, args: {number: {ref: number}}}}
""",
        "calculation.lib.yaml",
    )


def _compiled(document, definitions=(), path=()):
    raw = document.to_data()
    for part in path:
        raw = raw[part]
    context = document.context(aliases=(("", path),))
    selected = replace(ports(), pure_definitions=definitions, source_context=context)
    return compile_value_program(json.dumps(raw), selected)


def _value_text(guard):
    return yaml.safe_dump(
        {
            "schema": "c0.value.v1",
            "bindings": [],
            "guard": guard,
            "outputs": {"value": {"ref": "state.count"}},
        },
        sort_keys=False,
    )


def test_two_calls_keep_the_same_definition_and_distinct_call_sites():
    lib = _lib()
    definitions = check_pure_definitions(
        lib.to_data()["pure_definitions"], {}, source_context=lib.context()
    )
    call = {"call": {"ref": "small", "args": {"number": {"ref": "state.count"}}}}
    document = _document(_value_text({"all": [call, json.loads(json.dumps(call))]}))
    compiled = _compiled(document, definitions)
    first, second = compiled.guard_ir.expression["all"]
    first_trace = first["call"]["body"].provenance
    second_trace = second["call"]["body"].provenance
    assert [frame.kind for frame in first_trace] == [
        "pure_call",
        "pure_definition",
        "expression",
    ]
    assert first_trace[0].span.path == ("guard", "all", 0)
    assert second_trace[0].span.path == ("guard", "all", 1)
    assert first_trace[1:] == second_trace[1:]
    assert first_trace[-1].span.path == ("pure_definitions", 0, "body")
    assert first_trace[-1].span.file == "calculation.lib.yaml"
    assert compiled._ports.source_context is None
    assert all(item.source_context is None for item in compiled._ports.pure_definitions)
    assert first["call"]["definition"].source_context is None
    (failure,) = compiled.false_guard_clauses(state(3))
    assert failure.provenance == first_trace
    assert compiled.false_guard_clauses(state(1)) == ()


def test_nested_calls_and_argument_expressions_do_not_lose_outer_provenance():
    lib = _lib()
    definitions = check_pure_definitions(
        lib.to_data()["pure_definitions"], {}, source_context=lib.context()
    )
    document = _document(
        _value_text({"call": {"ref": "nested", "args": {"number": {"ref": "state.count"}}}})
    )
    compiled = _compiled(document, definitions)
    (failure,) = compiled.false_guard_clauses(state(3))
    assert [frame.kind for frame in failure.provenance] == [
        "pure_call",
        "pure_definition",
        "pure_call",
        "pure_definition",
        "expression",
    ]
    assert [frame.name for frame in failure.provenance[:-1]] == [
        "nested",
        "nested",
        "small",
        "small",
    ]
    assert failure.provenance[0].span.file == "world.yaml"
    assert failure.provenance[2].span.path == ("pure_definitions", 1, "body")
    argument = compiled.guard_ir.expression["call"]["args"]["number"]
    assert len(argument.provenance) == 1
    assert argument.provenance[0].span.path == ("guard", "call", "args", "number")


def test_selected_branch_names_and_named_clause_source_can_have_precise_aliases():
    document = _document(
        _value_text(
            {
                "if": {
                    "when": {"ref": "state.ready"},
                    "then": {"require": [{"small": "state.count < 2"}]},
                    "else": False,
                }
            }
        )
    )
    context = document.context(
        aliases=(
            ("", ()),
            ("guard.if.then.require.small", ("guard", "if", "then", "require", 0, "small")),
        )
    )
    compiled = compile_value_program(
        json.dumps(document.to_data()), replace(ports(), source_context=context)
    )
    (failure,) = compiled.false_guard_clauses(state(3))
    assert failure.names == ("small",)
    assert failure.path == "guard.if.then.require.small"
    assert failure.branches == ("guard.if.then",)
    assert failure.provenance[-1].span.path[-3:] == ("require", 0, "small")
    assert compiled.false_guard_clauses(state(1)) == ()
    (other,) = compiled.false_guard_clauses(state(3, ready=False))
    assert other.provenance[-1].span.path == ("guard", "if", "else")
    assert "then" not in other.path


def test_generated_effect_check_points_to_the_effect_not_the_generated_guard():
    raw = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "outputs": {},
        "effects": [{"spend": {"debit": "state.count", "amount": 2, "floor": 0}}],
    }
    document = _document(yaml.safe_dump(raw, sort_keys=False))
    context = document.context(aliases=(("", ()), ("effects.spend", ("effects", 0, "spend"))))
    compiled = compile_value_program(
        json.dumps(document.to_data()),
        replace(ports(), source_context=context),
        state_outputs={"state.count": "value"},
    )
    (failure,) = compiled.false_guard_clauses(state(1))
    assert failure.path == "effects.spend.sufficient"
    assert failure.provenance[-1].span.path == ("effects", 0, "spend")
    assert compiled.evaluate(state(3), occurrence=K0OccurrenceRef(1)) == {"value": 1}


def test_frozen_locations_survive_file_edits_and_two_backend_layouts(tmp_path, monkeypatch):
    from dataclasses import make_dataclass

    path = tmp_path / "selected.yaml"
    path.write_text(_value_text("state.count < 2"), encoding="utf-8")
    compiled = _compiled(read_author_document(path))
    (expected,) = compiled.false_guard_clauses(state(3))
    symbolic = symbolize_value_program(compiled, {"State": State, "Sample": Sample})
    OtherSample = make_dataclass("OtherSample", [("value", int)], frozen=True)
    OtherState = make_dataclass(
        "OtherState",
        [
            ("count", int),
            ("ready", bool),
            ("sample", OtherSample | None),
            ("secret", int),
            ("items", tuple[OtherSample, ...], ()),
        ],
        frozen=True,
    )
    rebound = bind_value_program(symbolic, {"State": OtherState, "Sample": OtherSample})
    path.write_text("not: the compiled source anymore\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("Run consulted author input or frontend")

    monkeypatch.setattr(type(path), "read_text", forbidden)
    monkeypatch.setattr(values, "_compile_expression", forbidden)
    monkeypatch.setattr(values, "_infer_expr_type", forbidden)
    assert compiled.false_guard_clauses(state(3)) == (expected,)
    assert rebound.false_guard_clauses({"state": OtherState(3, True, None, 19)}) == (expected,)
    assert rebound.evaluate(
        {"state": OtherState(1, True, None, 19)}, occurrence=K0OccurrenceRef(1)
    ) == {"value": 1}
    assert (
        expected.provenance[-1].span.digest
        == compiled.guard_ir.expression.provenance[-1].span.digest
    )
    assert compiled._ports.source_context is rebound._ports.source_context is None


def test_without_document_context_logical_origins_remain_but_coordinates_are_not_invented():
    compiled = program(guard="state.count < 2")
    (failure,) = compiled.false_guard_clauses(state())
    assert failure.path == "guard"
    assert failure.provenance == ()


@pytest.mark.parametrize("located", ["call", "definition"])
def test_partial_source_evidence_leaves_missing_side_unlocated(located):
    lib = _lib()
    definitions = check_pure_definitions(
        lib.to_data()["pure_definitions"],
        {},
        source_context=lib.context() if located == "definition" else None,
    )
    document = _document(
        _value_text({"call": {"ref": "small", "args": {"number": {"ref": "state.count"}}}})
    )
    selected = replace(
        ports(),
        pure_definitions=definitions,
        source_context=document.context() if located == "call" else None,
    )
    compiled = compile_value_program(json.dumps(document.to_data()), selected)
    (failure,) = compiled.false_guard_clauses(state(3))
    caller, definition, predicate = failure.provenance
    assert (caller.span is not None) == (located == "call")
    assert (definition.span is not None) == (located == "definition")
    assert (predicate.span is not None) == (located == "definition")


def test_alternative_failures_have_their_own_spans_not_a_single_invented_cause():
    document = _document(_value_text({"any": ["state.count < 1", "state.count > 9"]}))
    compiled = _compiled(document)
    failures = compiled.false_guard_clauses(state(3))
    assert [failure.provenance[-1].span.path for failure in failures] == [
        ("guard", "any", 0),
        ("guard", "any", 1),
    ]
    assert compiled.false_guard_clauses(state(0)) == ()


def test_real_k0_publishes_and_rejects_with_metadata_but_no_index_in_runtime():
    from authored_counter_v1 import _actor, _inputs

    from nomos_c0.owner_graph_v1 import compile_owner_graph

    library, source, assets = _inputs(1, 1)
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"] = {"all": [value["guard"], "actor.count < 1"]}
    document = _document(yaml.safe_dump(source, sort_keys=False))
    compiled = compile_owner_graph(library, document)
    session = compiled.start(assets)
    offer = session.offers("seat_0")[0]
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    assert _actor(session, 0).count == 1
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    action = dict(compiled.actions)[offer.entry]
    (failure,) = action.value.false_guard_clauses(
        action._roots(
            dict(before.owners)["scene"],
            _actor(session, 0),
            action.payload_type("person_0", "person_0"),
        )
    )
    assert failure.provenance[-1].span.path == ("lawdefs", 0, "body", "value", "guard", "all", 1)
    assert action.value._ports.source_context is None


def test_runtime_expression_tree_contains_spans_but_no_compile_context():
    lib = _lib()
    definitions = check_pure_definitions(
        lib.to_data()["pure_definitions"], {}, source_context=lib.context()
    )
    compiled = _compiled(
        _document(
            _value_text({"call": {"ref": "small", "args": {"number": {"ref": "state.count"}}}})
        ),
        definitions,
    )

    def visit(value):
        assert type(value) is not C0SourceContext
        if type(value) is C0Expression:
            assert all(type(frame) is C0OriginFrame for frame in value.provenance)
            visit(value.operand)
        elif isinstance(value, Mapping):
            for item in value.values():
                visit(item)
        elif type(value) is tuple:
            for item in value:
                visit(item)

    visit(compiled.guard_ir.expression)


def test_all_four_formation_adapters_strip_compile_maps_and_keep_real_source_frames():
    from test_world_binding_v1 import ROOT, _documents

    from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
    from nomos_c0.declarative_nominal_v0 import check_nominal_lib
    from nomos_c0.owner_graph_v1 import compile_owner_graph

    lib, port_data, source = _documents("parcel_delivery_v0")
    graph = check_graph_ports(port_data, check_nominal_lib(lib))
    document = _document(json.dumps(source), format="json")
    compiled = compile_owner_graph(graph, document)
    for _, transition in (*compiled.actions, *compiled.events, *compiled.due_laws):
        assert transition.ports.value_ports.source_context is None
        span = transition.value.guard_ir.expression.provenance[-1].span
        assert span.path[0] == "lawdefs"
        assert span.digest == document.digest
    session = compiled.start((ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("sender")
    assert session.time == 2
    offer = session.form_frame("receiver").offers[0]
    assert isinstance(session.submit("receiver", offer.entry, dict(offer.payload)), K0Published)
    assert len(session.author_snapshot().occurrences) == 6
