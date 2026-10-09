"""Finite LawDef declaration and compile-time instantiation boundaries."""

from __future__ import annotations

import copy

import pytest

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.lawdef_binding_v1 import C0LawDefinitions


def _definitions() -> list[dict[str, object]]:
    return [
        {
            "name": "advance",
            "family": "action",
            "formals": {"step": "int", "enabled": "bool"},
            "body": {"value": {"outputs": [{"arg": "step"}, {"arg": "enabled"}]}},
        },
        {
            "name": "notice",
            "family": "direct_event",
            "formals": {"message": "str"},
            "body": {"law": {"outputs": [{"arg": "message"}]}},
        },
        {
            "name": "due",
            "family": "due_event",
            "formals": {},
            "body": {"law": {"outputs": [{"const": "ready"}]}},
        },
    ]


def test_three_families_have_closed_structural_instances() -> None:
    definitions = C0LawDefinitions(_definitions())
    first = definitions.instantiate(
        "action", {"ref": "advance", "args": {"step": 1, "enabled": True}}
    )
    second = definitions.instantiate(
        "action", {"ref": "advance", "args": {"step": 2, "enabled": False}}
    )
    assert first == {"value": {"outputs": [{"const": 1}, {"const": True}]}}
    assert second == {"value": {"outputs": [{"const": 2}, {"const": False}]}}
    assert definitions.instantiate(
        "direct_event", {"ref": "notice", "args": {"message": "visible"}}
    ) == {"law": {"outputs": [{"const": "visible"}]}}
    assert definitions.instantiate("due_event", {"ref": "due", "args": {}}) == {
        "law": {"outputs": [{"const": "ready"}]}
    }
    first["value"]["outputs"][0]["const"] = 99
    assert definitions.instantiate(
        "action", {"ref": "advance", "args": {"step": 1, "enabled": True}}
    )["value"]["outputs"][0] == {"const": 1}


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.append(copy.deepcopy(rows[0])),
        lambda rows: rows[0].update(family="unknown"),
        lambda rows: rows[0].update(formals={"step": "int", "enabled": "bool", "unused": "str"}),
        lambda rows: rows[0]["body"]["value"]["outputs"].append({"arg": "missing"}),
        lambda rows: rows[0]["body"]["value"]["outputs"].append({"arg": 1}),
        lambda rows: rows[0]["body"].update(extra=True),
    ],
)
def test_malformed_or_open_declarations_reject(change: object) -> None:
    rows = _definitions()
    change(rows)
    with pytest.raises(C0LawError):
        C0LawDefinitions(rows)


@pytest.mark.parametrize(
    "use",
    [
        {"ref": "notice", "args": {"step": 1, "enabled": True}},
        {"ref": "advance", "args": {"step": True, "enabled": True}},
        {"ref": "advance", "args": {"step": -1, "enabled": True}},
        {"ref": "advance", "args": {"step": 1}},
        {"ref": "advance", "args": {"step": 1, "enabled": True, "extra": 1}},
        {"ref": "advance", "args": {"step": 1, "enabled": True}, "identity": "injected"},
    ],
)
def test_foreign_or_malformed_use_rejects(use: object) -> None:
    definitions = C0LawDefinitions(_definitions())
    with pytest.raises(C0LawError):
        definitions.instantiate("action", use)


def test_recursive_template_rejects_as_law_error() -> None:
    rows = _definitions()
    recursive: list[object] = []
    recursive.append(recursive)
    rows[0]["body"]["value"]["outputs"].append(recursive)
    with pytest.raises(C0LawError, match="deeply nested"):
        C0LawDefinitions(rows)


def test_combined_library_and_source_definitions_remain_bounded() -> None:
    rows = _definitions()
    many = [
        dict(rows[0], name=f"advance_{index}")
        for index in range(COMPILE_BUDGET.law_definitions + 1)
    ]
    before = copy.deepcopy(many)
    with pytest.raises(C0CompileLimitError) as caught:
        C0LawDefinitions(many)
    error = caught.value
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "law_definitions",
        257,
        256,
        "LawDef binding",
    )
    assert many == before


@pytest.mark.parametrize("count", [64, 65, 128, 129, 256])
def test_lawdef_budget_includes_the_last_definition(count: int) -> None:
    many = [dict(_definitions()[0], name=f"advance_{index}") for index in range(count)]
    before = copy.deepcopy(many)
    definitions = C0LawDefinitions(many)
    assert definitions.instantiate(
        "action", {"ref": f"advance_{count - 1}", "args": {"step": 2, "enabled": True}}
    ) == {"value": {"outputs": [{"const": 2}, {"const": True}]}}
    assert many == before


@pytest.mark.parametrize("value", [None, {}, (), []])
def test_malformed_or_empty_lawdefs_are_not_resource_overflows(value: object) -> None:
    with pytest.raises(C0LawError, match="finite LawDefs") as caught:
        C0LawDefinitions(value)
    assert not isinstance(caught.value, C0CompileLimitError)
