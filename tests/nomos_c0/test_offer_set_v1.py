"""Explicit offer reuse preserves order, isolation, budgets and author locations."""

import json
from copy import deepcopy

import pytest
from test_multi_participant_action_v0 import _compile, _world

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import (
    C0OriginFrame,
    C0SourceContext,
    C0SourceIndex,
    parse_author_document,
)
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.offer_set_v1 import expand_offer_sets


def _offer(label, *, family=False):
    return {
        "entry_family" if family else "entry": "act",
        "label": {"const": label},
        "when": {"const": True},
        "payload": {"count": {"const": 1}},
    }


def _source():
    return {
        "offer_sets": [{"name": "shared", "offers": [_offer("A"), _offer("B")]}],
        "seats": [
            {
                "name": "first",
                "actor": "a",
                "entries": ["act"],
                "read": ["a.name"],
                "offers": [
                    _offer("before"),
                    {"use_offer_set": "shared"},
                    _offer("after"),
                    {"use_offer_set": "shared"},
                ],
            },
            {
                "name": "second",
                "actor": "b",
                "entries": ["other"],
                "read": [],
                "offers": [{"use_offer_set": "shared"}],
            },
        ],
    }


@pytest.mark.parametrize("family", [False, True])
@pytest.mark.parametrize(
    "form",
    [
        {},
        {"for_each": {"collection": {"ref": "actor.paths"}, "as": "path"}},
        {"fixed_participants": True},
        {"for_each_object": {"kind": "tool"}, "visible_when": {"const": True}},
        {"for_each_participants": {"tool": {"kind": "tool"}}, "visible_when": {"const": True}},
        {
            "for_each_participants": {"tool": {"kind": "tool"}},
            "for_each": {"collection": {"ref": "actor.paths"}, "as": "path"},
            "visible_when": {"const": True},
        },
    ],
)
@pytest.mark.parametrize(
    "metadata",
    [
        {"availability": {"ref": "local_ground", "when": {"const": True}}},
        {"operation": "move"},
        {"availability": {"ref": "local_ground", "when": {"const": True}}, "operation": "move"},
    ],
)
def test_all_source_offer_forms_preserve_availability_and_operation(family, form, metadata):
    offer = {**_offer("Move", family=family), **form, **metadata}
    source = {
        "offer_sets": [{"name": "movement", "offers": [offer]}],
        "seats": [{"offers": [{"use_offer_set": "movement"}]}],
    }
    before = deepcopy(source)
    expanded, origins = expand_offer_sets(source)
    actual = expanded["seats"][0]["offers"][0]
    assert actual == offer
    assert origins[0, 0][0] == ("offer_sets", 0, "offers", 0)
    if "availability" in actual:
        actual["availability"]["when"]["const"] = False
    assert source == before


def test_expansion_is_ordered_detached_and_does_not_share_permissions():
    source = _source()
    before = deepcopy(source)
    expanded, origins = expand_offer_sets(source)
    assert source == before
    assert "offer_sets" not in expanded
    assert [item["label"]["const"] for item in expanded["seats"][0]["offers"]] == [
        "before",
        "A",
        "B",
        "after",
        "A",
        "B",
    ]
    assert set(origins) == {(0, index) for index in range(6)} | {(1, 0), (1, 1)}
    assert expanded["seats"][1]["read"] == []
    assert expanded["seats"][1]["entries"] == ["other"]
    expanded["seats"][0]["offers"][1]["payload"]["count"]["const"] = 7
    assert expanded["seats"][0]["offers"][4]["payload"]["count"]["const"] == 1
    assert expanded["seats"][1]["offers"][0]["payload"]["count"]["const"] == 1
    expanded["seats"][0]["offers"][0]["label"]["const"] = "changed"
    expanded["seats"][0]["read"].append("a.secret")
    assert source == before


def test_family_offers_expand_before_family_binding_and_leave_additional_unchanged():
    source = {
        "offer_sets": [{"name": "family", "offers": [_offer("family", family=True)]}],
        "seats": [
            {
                "seat_family": "people",
                "names": "upper",
                "entries": ["act"],
                "read": [],
                "offers": [{"use_offer_set": "family"}],
                "additional": {"a": {"entries": ["extra"], "offers": [_offer("extra")]}},
            }
        ],
    }
    expanded, origins = expand_offer_sets(source)
    seat = expanded["seats"][0]
    assert seat["offers"] == [_offer("family", family=True)]
    assert seat["additional"] == source["seats"][0]["additional"]
    assert set(origins) == {(0, 0)}
    assert origins[0, 0][0] == ("offer_sets", 0, "offers", 0)


def test_plain_source_keeps_absolute_original_paths_without_a_context():
    source = {"seats": [{"offers": [_offer("plain")]}]}
    expanded, origins = expand_offer_sets(source)
    assert expanded == source
    assert origins == {(0, 0): (("seats", 0, "offers", 0), ())}
    assert expand_offer_sets({}) == ({}, {})


def test_origins_keep_inline_paths_and_each_reference_use_and_definition():
    source = _source()
    document = parse_author_document(json.dumps(source), file="offers.json", format="json")
    inherited = C0OriginFrame("source_binding", "source", "root")
    context = document.context(frames=(inherited,))
    _, origins = expand_offer_sets(source, context)
    assert origins[0, 0] == (("seats", 0, "offers", 0), (inherited,))
    assert origins[0, 3] == (("seats", 0, "offers", 2), (inherited,))
    for key, use_index, member_index in [((0, 1), 1, 0), ((0, 2), 1, 1), ((0, 4), 3, 0)]:
        path, frames = origins[key]
        use_path = ("seats", 0, "offers", use_index)
        assert path == ("offer_sets", 0, "offers", member_index)
        assert frames == (
            inherited,
            C0OriginFrame("offer_set_use", "shared", repr(use_path), document.spans[use_path]),
            C0OriginFrame("offer_set_definition", "shared", repr(path), document.spans[path]),
        )


def test_assembled_origins_use_index_paths_not_original_fragment_paths():
    source = _source()
    document = parse_author_document(json.dumps(source), file="part.json", format="json")
    use_path = ("seats", 0, "offers", 1)
    definition_path = ("offer_sets", 0, "offers", 0)
    index = C0SourceIndex(
        {use_path: document.spans[definition_path], definition_path: document.spans[use_path]},
        {use_path: definition_path, definition_path: use_path},
    )
    _, origins = expand_offer_sets(source, C0SourceContext(index))
    assert origins[0, 1][0] == definition_path
    assert origins[0, 1][1][0].span.path == definition_path
    assert origins[0, 1][1][1].span.path == use_path


@pytest.mark.parametrize(
    "declarations",
    [
        None,
        [{"name": "shared", "offers": []}],
        [{"name": "shared", "offers": {}}],
        [{"name": "bad name", "offers": [_offer("A")]}],
        [{"name": [], "offers": [_offer("A")]}],
        [{"name": "shared", "offers": [_offer("A")]}] * 2,
        [{"name": "shared", "offers": [{"use_offer_set": "shared"}]}],
        [{"name": "shared", "offers": [{"use_offer_set": "other"}]}],
        [{"name": "shared", "offers": [{"read": []}]}],
        [{"name": "shared", "offers": [None]}],
    ],
)
def test_invalid_groups_are_rejected_even_when_unused(declarations):
    with pytest.raises(C0LawError):
        expand_offer_sets({"offer_sets": declarations, "seats": []})


@pytest.mark.parametrize("field", ["read", "entries", "controller"])
def test_groups_and_group_offers_cannot_carry_seat_capabilities(field):
    source = _source()
    source["offer_sets"][0][field] = []
    with pytest.raises(C0LawError, match="unknown fields"):
        expand_offer_sets(source)
    del source["offer_sets"][0][field]
    source["offer_sets"][0]["offers"][0][field] = []
    with pytest.raises(C0LawError, match="unknown fields"):
        expand_offer_sets(source)


@pytest.mark.parametrize(
    "reference",
    [
        {"use_offer_set": "unknown"},
        {"use_offer_set": []},
        {"use_offer_set": "shared", "entry": "act"},
    ],
)
def test_unknown_or_mixed_references_are_rejected_without_mutation(reference):
    source = _source()
    source["seats"][0]["offers"] = [reference]
    before = deepcopy(source)
    with pytest.raises(C0LawError):
        expand_offer_sets(source)
    assert source == before


def test_set_count_budget_accepts_64_and_rejects_65():
    source = {
        "offer_sets": [
            {"name": f"set_{index}", "offers": [_offer(str(index))]} for index in range(64)
        ]
    }
    assert expand_offer_sets(source) == ({}, {})
    source["offer_sets"].append({"name": "one_more", "offers": [_offer("last")]})
    with pytest.raises(C0LawError, match="64"):
        expand_offer_sets(source)


def test_definition_and_expansion_use_existing_finite_offer_budget():
    limit = COMPILE_BUDGET.finite_offers
    assert limit == 256
    source = {
        "offer_sets": [{"name": "shared", "offers": [_offer(str(i)) for i in range(limit)]}],
        "seats": [{"offers": [{"use_offer_set": "shared"}]}],
    }
    expanded, origins = expand_offer_sets(source)
    assert len(expanded["seats"][0]["offers"]) == len(origins) == limit
    source["seats"][0]["offers"].append(_offer("extra"))
    with pytest.raises(C0CompileLimitError, match="offer set expansion"):
        expand_offer_sets(source)
    source["seats"][0]["offers"] = [{"use_offer_set": "shared"}] * 2
    with pytest.raises(C0CompileLimitError, match="offer set expansion"):
        expand_offer_sets(source)
    source["offer_sets"][0]["offers"].append(_offer("extra"))
    with pytest.raises(C0CompileLimitError, match="offer set definition"):
        expand_offer_sets(source)
    with pytest.raises(C0CompileLimitError):
        expand_offer_sets({"seats": [{"offers": [_offer(str(i)) for i in range(limit + 1)]}]})


def test_real_offer_still_compiles_and_does_not_inherit_other_seat_reads():
    lib, ports, source, _ = _world()
    source["offer_sets"] = [{"name": "shared", "offers": source["seats"][0]["offers"]}]
    source["seats"][0]["offers"] = [{"use_offer_set": "shared"}]
    expanded, _ = expand_offer_sets(source)
    _compile(lib, ports, expanded)
    expanded["seats"][0]["read"] = []
    with pytest.raises(C0LawError):
        _compile(lib, ports, expanded)
