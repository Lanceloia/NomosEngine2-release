"""Named guards preserve typed admission and expose checked source locations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as values
from nomos_c0 import condition_source_v0 as source_module
from nomos_c0.composable_value_v1 import C0ValuePorts, compile_value_program
from nomos_c0.condition_source_v0 import lower_author_expression


@dataclass(frozen=True)
class Notice:
    site: str


@dataclass(frozen=True)
class Reader:
    save: bool
    notice: Notice | None
    secret: str = "hidden"


@dataclass(frozen=True)
class ClauseRecord:
    clause: bool


def _require(name, test):
    return {"require": [{name: test}]}


def _ports():
    fields = {Reader: frozenset({"save", "notice"}), Notice: frozenset({"site"})}
    paths = frozenset({"actor.save", "actor.notice", "actor.notice.site"})
    return C0ValuePorts(
        roots={"actor": Reader},
        readable_paths=paths,
        admission_readable_paths=paths,
        readable_fields=fields,
        admission_readable_fields=fields,
        writable_fields={},
        record_types={},
        tuple_fields={},
        admission_tuple_fields={},
        collection_keys={},
        outputs={"ok": bool},
    )


def _source(guard):
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": guard,
        "outputs": {"ok": {"const": True}},
    }


def _compile(guard, ports=None):
    return compile_value_program(json.dumps(_source(guard)), _ports() if ports is None else ports)


def test_names_and_branch_paths_locate_only_the_selected_false_clause():
    guard = _require(
        "choice",
        {
            "if": {
                "when": {"ref": "actor.save"},
                "then": _require("ready", {"not_none": {"ref": "actor.notice"}}),
                "else": _require("ready", {"const": True}),
            }
        },
    )
    program = _compile(guard)
    assert [item.names for item in program.guard_ir.clauses] == [
        ("choice",),
        ("choice", "ready"),
        ("choice", "ready"),
    ]
    (failure,) = program.false_guard_clauses({"actor": Reader(True, None)})
    assert failure.names == ("choice", "ready")
    assert failure.branches == ("guard.require.choice.if.then",)
    assert failure.path == "guard.require.choice.if.then.require.ready"
    assert failure.expression == '{"not_none":{"ref":"actor.notice"}}'
    assert program.guard_ir.clauses[1].branches == failure.branches
    assert program.admits({"actor": Reader(False, None)})
    assert program.false_guard_clauses({"actor": Reader(False, None)}) == ()


@pytest.mark.parametrize("op", ["all", "any"])
def test_boolean_indexes_do_not_allow_duplicate_names_in_one_scope(op):
    with pytest.raises(C0LawError, match="repeats in the same scope"):
        _compile({op: [_require("same", {"const": False}), _require("same", {"const": True})]})


def test_nested_named_scopes_can_reuse_a_name_without_aliasing():
    program = _compile(
        {
            "any": [
                _require("left", _require("ready", {"const": False})),
                _require("right", _require("ready", {"const": False})),
            ]
        }
    )
    failures = program.false_guard_clauses({"actor": Reader(True, None)})
    assert [failure.names for failure in failures] == [("left", "ready"), ("right", "ready")]
    assert len({failure.path for failure in failures}) == 2


def test_all_reports_first_failure_without_evaluating_later_nullable_read():
    program = _compile(
        {
            "all": [
                _require("noticed", {"not_none": {"ref": "actor.notice"}}),
                _require("here", {"eq": [{"ref": "actor.notice.site"}, {"const": "here"}]}),
            ]
        }
    )
    (failure,) = program.false_guard_clauses({"actor": Reader(True, None)})
    assert failure.names == ("noticed",)
    assert program.admits({"actor": Reader(True, Notice("here"))})


def test_named_conjunction_preserves_nonnull_proof_for_later_guard_and_output():
    guard = {
        "all": [
            _require(
                "basis",
                {
                    "all": [
                        _require("noticed", {"not_none": {"ref": "actor.notice"}}),
                        {"const": True},
                    ]
                },
            ),
            _require("here", {"eq": [{"ref": "actor.notice.site"}, {"const": "here"}]}),
        ]
    }
    source = _source(guard)
    source["outputs"] = {"site": {"ref": "actor.notice.site"}}
    program = compile_value_program(json.dumps(source), replace(_ports(), outputs={"site": str}))
    result = program.evaluate(
        {"actor": Reader(True, Notice("here"))}, occurrence=K0OccurrenceRef(1)
    )
    assert result == {"site": "here"}


@pytest.mark.parametrize(
    "guard",
    [
        {"any": [_require("noticed", {"not_none": {"ref": "actor.notice"}}), {"const": True}]},
        {
            "if": {
                "when": {"ref": "actor.save"},
                "then": _require("noticed", {"not_none": {"ref": "actor.notice"}}),
                "else": {"const": True},
            }
        },
    ],
)
def test_any_and_selected_branch_do_not_prove_nonnull_for_the_whole_guard(guard):
    source = _source(guard)
    source["outputs"] = {"site": {"ref": "actor.notice.site"}}
    with pytest.raises(C0LawError):
        compile_value_program(json.dumps(source), replace(_ports(), outputs={"site": str}))


def test_if_condition_proves_nonnull_only_in_then_branch():
    program = _compile(
        {
            "if": {
                "when": _require("noticed", {"not_none": {"ref": "actor.notice"}}),
                "then": _require("here", {"eq": [{"ref": "actor.notice.site"}, {"const": "here"}]}),
                "else": {"const": True},
            }
        }
    )
    assert program.admits({"actor": Reader(True, None)})
    (failure,) = program.false_guard_clauses({"actor": Reader(True, Notice("there"))})
    assert failure.names == ("here",) and failure.branches == ("guard.if.then",)


@pytest.mark.parametrize("name", ["", "with space", "a.b", "_private", "\u6761\u4ef6", 4])
def test_malformed_names_are_rejected(name):
    with pytest.raises(C0LawError, match="clause name"):
        _compile(_require(name, {"const": True}))


@pytest.mark.parametrize(
    "test",
    [
        {"const": 1},
        {"ref": "actor.secret"},
        {"ref": "occurrence"},
        {"eq": [{"die_roll": {"seed": {"const": 1}, "sides": {"const": 6}}}, {"const": 1}]},
    ],
)
def test_names_cannot_hide_mistyped_or_ungranted_admission_operations(test):
    with pytest.raises(C0LawError):
        _compile(_require("allowed", test))


def test_clause_names_are_not_bindings_and_do_not_authorize_ref():
    with pytest.raises(C0LawError):
        _compile({"all": [_require("ready", {"const": True}), {"ref": "ready"}]})
    with pytest.raises(C0LawError, match="internal IR"):
        _compile({"clause": {"name": "ready", "test": {"const": True}, "reads": ["actor.secret"]}})


def test_immutable_ir_is_the_only_guard_and_never_reparses_source(monkeypatch):
    source = _source(_require("noticed", "actor.notice is not None"))
    program = compile_value_program(json.dumps(source), _ports())
    assert "guard" not in program._tree
    source["guard"]["require"][0]["noticed"] = {"const": True}
    with pytest.raises(TypeError):
        program.guard_ir.expression["all"][0]["clause"]["test"] = {"const": True}
    with pytest.raises(TypeError):
        program.guard_ir.source_paths["guard"] = "false location"

    def no_reparse(*_args, **_kwargs):
        raise AssertionError("runtime reparsed author JSON")

    monkeypatch.setattr(values.json, "loads", no_reparse)
    monkeypatch.setattr(source_module, "_predicate", no_reparse)
    assert not program.admits({"actor": Reader(True, None)})
    (failure,) = program.false_guard_clauses({"actor": Reader(True, None)})
    assert failure.names == ("noticed",)


def test_named_wrappers_do_not_bypass_expression_depth_limit():
    guard = {"const": True}
    for index in range(66):
        guard = _require(f"level_{index}", guard)
    with pytest.raises(C0LawError, match="too deep"):
        _compile(guard)


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("actor.save", {"ref": "actor.save"}),
        ("True", {"const": True}),
        ("actor.notice is not None", {"not_none": {"ref": "actor.notice"}}),
        ("actor.notice is None", {"is_none": {"ref": "actor.notice"}}),
        ("not actor.save", {"not": {"ref": "actor.save"}}),
        ("actor.save == True", {"eq": [{"ref": "actor.save"}, {"const": True}]}),
        ("actor.save != False", {"not": {"eq": [{"ref": "actor.save"}, {"const": False}]}}),
        ("2 > 1", {"lt": [{"const": 1}, {"const": 2}]}),
        ("2 >= 1", {"le": [{"const": 1}, {"const": 2}]}),
        (
            "1 < 2 <= 3",
            {
                "all": [
                    {"lt": [{"const": 1}, {"const": 2}]},
                    {"le": [{"const": 2}, {"const": 3}]},
                ]
            },
        ),
    ],
)
def test_text_and_structured_inputs_have_the_same_checked_behavior(text, expression):
    compact = _compile(text)
    structured = _compile(expression)
    assert compact.guard_ir.expression.result_type is bool
    assert structured.guard_ir.expression.result_type is bool
    assert compact.guard_ir.expression.stage == structured.guard_ir.expression.stage == "admission"
    for save in (False, True):
        for notice in (None, Notice("here")):
            roots = {"actor": Reader(save, notice)}
            assert compact.admits(roots) == structured.admits(roots)
            assert compact.evaluate(roots, occurrence=K0OccurrenceRef(1)) == structured.evaluate(
                roots, occurrence=K0OccurrenceRef(1)
            )


def test_text_short_circuit_is_checked_and_false_subpredicate_maps_to_author_string():
    program = _compile(
        {
            "require": [
                {
                    "here": "actor.notice is not None and actor.notice.site == 'here'",
                }
            ]
        }
    )
    for notice in (None, Notice("there")):
        (failure,) = program.false_guard_clauses({"actor": Reader(True, notice)})
        assert failure.path == "guard.require.here"
        assert failure.names == ("here",)
    assert program.admits({"actor": Reader(True, Notice("here"))})
    with pytest.raises(C0LawError, match="nullable"):
        _compile("actor.notice is None or actor.notice.site == 'here'")


@pytest.mark.parametrize(
    "text",
    [
        "fn()",
        "__import__('os')",
        "actor.save[0]",
        "lambda: True",
        "[item for item in items]",
        "f'{actor.secret}'",
        "actor.save := True",
        "2 ** 3",
        "1 / 2",
        "1 + 2",
        "actor.notice is actor.notice",
        "actor.notice in []",
        "0.5 < 1",
        "-1 < 0",
        "actor.save ==",
    ],
)
def test_predicate_text_cannot_execute_python_or_add_unimplemented_operations(text):
    with pytest.raises(C0LawError):
        _compile(text)


@pytest.mark.parametrize("text", ["actor.secret == 'hidden'", "occurrence == None", "1 == True"])
def test_text_does_not_bypass_ports_stages_or_strict_scalar_types(text):
    with pytest.raises(C0LawError):
        _compile(text)


def test_unselected_text_branch_is_still_checked_for_read_permission():
    with pytest.raises(C0LawError, match="read boundary"):
        _compile({"if": {"when": "True", "then": "True", "else": "actor.secret == 'hidden'"}})


def test_require_preserves_declared_order_and_does_not_create_binding():
    program = _compile({"require": [{"z_first": False}, {"a_second": False}]})
    assert [clause.names for clause in program.guard_ir.clauses] == [("z_first",), ("a_second",)]
    (failure,) = program.false_guard_clauses({"actor": Reader(True, None)})
    assert failure.names == ("z_first",)
    with pytest.raises(C0LawError, match="declared root"):
        _compile({"require": [{"ready": "True"}, {"reuse": "ready"}]})
    with pytest.raises(C0LawError, match="nonempty"):
        _compile({"require": []})


def test_ordered_require_survives_canonical_json_key_sorting():
    source = _source(
        {
            "require": [
                {"z_noticed": "actor.notice is not None"},
                {"a_here": "actor.notice.site == 'here'"},
            ]
        }
    )
    program = compile_value_program(json.dumps(source, sort_keys=True), _ports())
    assert [item.names for item in program.guard_ir.clauses] == [("z_noticed",), ("a_here",)]
    assert program.admits({"actor": Reader(True, Notice("here"))})
    (failure,) = program.false_guard_clauses({"actor": Reader(True, None)})
    assert failure.names == ("z_noticed",)


@pytest.mark.parametrize(
    "conditions",
    [
        {"first": True},
        [{"first": True, "second": True}],
        [True],
        [],
    ],
)
def test_require_has_one_ordered_author_contract_without_map_fallback(conditions):
    with pytest.raises(C0LawError):
        _compile({"require": conditions})


def test_duplicate_json_condition_key_is_rejected_before_lowering():
    source = json.dumps(_source(True)).replace(
        '"guard": true', '"guard": {"require": [{"same":true,"same":false}]}'
    )
    with pytest.raises(C0LawError):
        compile_value_program(source, _ports())


def test_record_field_named_clause_is_not_mistaken_for_internal_operation():
    source = _source(True)
    source["outputs"] = {"item": {"record": {"type": "ClauseRecord", "fields": {"clause": True}}}}
    ports = replace(
        _ports(), outputs={"item": ClauseRecord}, record_types={"ClauseRecord": ClauseRecord}
    )
    program = compile_value_program(json.dumps(source), ports)
    assert program.evaluate({"actor": Reader(True, None)}, occurrence=K0OccurrenceRef(1)) == {
        "item": ClauseRecord(True),
    }


def test_internal_clause_is_rejected_in_author_guard_and_outputs():
    internal = {"clause": {"name": "old", "test": {"const": True}}}
    with pytest.raises(C0LawError, match="internal IR"):
        _compile(internal)
    source = _source(True)
    source["outputs"]["ok"] = internal
    with pytest.raises(C0LawError, match="internal IR"):
        compile_value_program(json.dumps(source), _ports())


def test_predicate_text_size_is_bounded():
    with pytest.raises(C0LawError, match="too large"):
        _compile("True" + " " * 4096)


@pytest.mark.parametrize("text", ["1 and True", "'hello' or False", "actor.notice"])
def test_text_does_not_use_python_truthiness(text):
    with pytest.raises(C0LawError):
        _compile(text)


def test_text_or_reports_all_failed_alternatives_at_the_author_location():
    program = _compile({"require": [{"ready": "actor.save or False"}]})
    failures = program.false_guard_clauses({"actor": Reader(False, None)})
    assert len(failures) == 2
    assert {failure.path for failure in failures} == {"guard.require.ready"}
    assert {failure.names for failure in failures} == {("ready",)}
    assert program.false_guard_clauses({"actor": Reader(True, None)}) == ()


def test_compile_preserves_const_strings_and_quantifier_local_names():
    value, locations = lower_author_expression(
        {
            "count_matching": {
                "collection": {"ref": "actor.items"},
                "as": "item",
                "where": "item.name == 'torch' and item.site == actor.site",
            }
        }
    )
    assert value["count_matching"]["as"] == "item"
    assert value["count_matching"]["where"]["all"][0]["eq"][1] == {"const": "torch"}
    assert locations["guard.count_matching.where.all[0]"] == "guard.count_matching.where"
