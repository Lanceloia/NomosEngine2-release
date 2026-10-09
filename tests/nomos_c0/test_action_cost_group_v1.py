"""Cost groups are finite author sugar; permission and value checks stay in Graph."""

from copy import deepcopy

import pytest

from nomos_c0.action_cost_group_v1 import expand_action_cost_groups
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET


def _form():
    return {
        "mode": "action_value_event_jump",
        "seats": [
            {
                "seat": "player",
                "tempo": {"const": 1},
                "eligible": {"const": True},
                "costs": {"Wait": {"const": 2}},
                "cost_groups": [
                    {"entries": ["Walk", "Run"], "value": {"read": "actor.travel_cost"}},
                    {"entries": ["Rest"], "value": {"const": 3}},
                ],
            }
        ],
        "end_at": None,
        "max_same_time_actions": 8,
    }


def test_expansion_preserves_inline_costs_and_absolute_group_origins():
    form = _form()
    original = deepcopy(form)
    expanded, origins = expand_action_cost_groups(form)
    assert form == original
    assert expanded == {
        **original,
        "seats": [{
            **{key: value for key, value in original["seats"][0].items() if key != "cost_groups"},
            "costs": {
                "Wait": {"const": 2},
                "Walk": {"read": "actor.travel_cost"},
                "Run": {"read": "actor.travel_cost"},
                "Rest": {"const": 3},
            },
        }],
    }
    assert origins == {
        (0, "Walk"): ("game_form", "seats", 0, "cost_groups", 0, "value"),
        (0, "Run"): ("game_form", "seats", 0, "cost_groups", 0, "value"),
        (0, "Rest"): ("game_form", "seats", 0, "cost_groups", 1, "value"),
    }


def test_expressions_are_independently_copied_across_entries_and_seats():
    form = _form()
    control = form["seats"][0]
    form["seats"].append({**control, "seat": "friend"})
    expanded, origins = expand_action_cost_groups(form)
    costs = expanded["seats"][0]["costs"]
    costs["Walk"]["read"] = "changed"
    costs["Wait"]["const"] = 9
    assert costs["Run"] == {"read": "actor.travel_cost"}
    assert expanded["seats"][1]["costs"]["Walk"] == {"read": "actor.travel_cost"}
    assert expanded["seats"][1]["costs"]["Wait"] == {"const": 2}
    assert control["cost_groups"][0]["value"] == {"read": "actor.travel_cost"}
    assert control["costs"]["Wait"] == {"const": 2}
    assert origins[1, "Run"] == ("game_form", "seats", 1, "cost_groups", 0, "value")


@pytest.mark.parametrize("form", [
    {"mode": "manual"},
    {"mode": "event_jump_stop", "seats": ["player"], "end_at": 5, "wake_at": []},
    {"mode": "action_value_event_jump", "seats": [{"costs": {"Wait": {"const": 1}}}]},
])
def test_without_groups_preserves_existing_syntax(form):
    expanded, origins = expand_action_cost_groups(form)
    assert expanded == form
    assert expanded is not form
    assert origins == {}


def test_empty_groups_keeps_explicit_costs_without_defaults():
    form = _form()
    form["seats"][0]["costs"] = {}
    form["seats"][0]["cost_groups"] = []
    expanded, origins = expand_action_cost_groups(form)
    assert expanded["seats"][0]["costs"] == {}
    assert "cost_groups" not in expanded["seats"][0]
    assert origins == {}


def test_inline_expressions_with_aliases_are_independent_when_expanding_groups():
    form = _form()
    value = {"const": 2}
    form["seats"][0]["costs"] = {"Wait": value, "Pause": value}
    expanded, _ = expand_action_cost_groups(form)
    costs = expanded["seats"][0]["costs"]
    costs["Wait"]["const"] = 9
    assert costs["Pause"] == {"const": 2}
    assert value == {"const": 2}


@pytest.mark.parametrize("groups", [
    None, {}, (), "groups",
    [{"entries": [], "value": {"const": 1}}],
    [{"entries": ("Walk",), "value": {"const": 1}}],
    [{"entries": "Walk", "value": {"const": 1}}],
    [{"entries": ["Walk", "Walk"], "value": {"const": 1}}],
    [{"entries": ["Wait"], "value": {"const": 1}}],
    [{"entries": ["Walk"], "value": {"const": 1}},
     {"entries": ["Walk"], "value": {"const": 2}}],
    [{"entries": ["Walk"]}],
    [{"value": {"const": 1}}],
    [{"entries": ["Walk"], "value": {"const": 1}, "default": True}],
    [None],
])
def test_rejects_malformed_groups_and_cost_collisions_without_mutation(groups):
    form = _form()
    form["seats"][0]["cost_groups"] = groups
    before = deepcopy(form)
    with pytest.raises(C0LawError):
        expand_action_cost_groups(form)
    assert form == before


@pytest.mark.parametrize("entry", [None, 1, True, "", "_Walk", "walk.run", "class", "x" * 65])
def test_requires_explicit_public_action_names(entry):
    form = _form()
    form["seats"][0]["cost_groups"][0]["entries"] = [entry]
    with pytest.raises(C0LawError, match="public identifier"):
        expand_action_cost_groups(form)


@pytest.mark.parametrize("costs", [None, [], "costs"])
def test_groups_do_not_replace_required_inline_costs_mapping(costs):
    form = _form()
    form["seats"][0]["costs"] = costs
    with pytest.raises(C0LawError, match="explicit costs mapping"):
        expand_action_cost_groups(form)


def test_groups_require_costs_field_even_when_empty():
    form = _form()
    del form["seats"][0]["costs"]
    form["seats"][0]["cost_groups"] = []
    with pytest.raises(C0LawError, match="explicit costs mapping"):
        expand_action_cost_groups(form)


@pytest.mark.parametrize("mode", ["manual", "event_jump_stop", "unknown", None])
def test_other_modes_explicitly_reject_even_empty_groups(mode):
    form = _form()
    form["mode"] = mode
    form["seats"][0]["cost_groups"] = []
    with pytest.raises(C0LawError, match="requires action_value_event_jump"):
        expand_action_cost_groups(form)


@pytest.mark.parametrize("mode", ["manual", "event_jump_stop", "action_value_event_jump"])
def test_rejects_groups_at_gameform_level(mode):
    with pytest.raises(C0LawError, match="control seat"):
        expand_action_cost_groups({"mode": mode, "cost_groups": []})


@pytest.mark.parametrize("count", [64, 65])
def test_group_count_bound(count):
    form = _form()
    form["seats"][0]["cost_groups"] = [
        {"entries": [f"Action{i}"], "value": {"const": 1}} for i in range(count)
    ]
    if count > 64:
        with pytest.raises(C0LawError, match="at most 64"):
            expand_action_cost_groups(form)
    else:
        expanded, origins = expand_action_cost_groups(form)
        assert len(origins) == count
        assert len(expanded["seats"][0]["costs"]) == count + 1


@pytest.mark.parametrize("extra", [0, 1])
def test_entry_count_uses_existing_action_budget(extra):
    form = _form()
    count = COMPILE_BUDGET.actions + extra
    form["seats"][0]["cost_groups"] = [{
        "entries": [f"Action{i}" for i in range(count)], "value": {"const": 1},
    }]
    if extra:
        with pytest.raises(C0LawError, match=f"1..{COMPILE_BUDGET.actions}"):
            expand_action_cost_groups(form)
    else:
        _, origins = expand_action_cost_groups(form)
        assert len(origins) == COMPILE_BUDGET.actions


@pytest.mark.parametrize("value", [{"const": 0}, {"const": -1}, {"read": "target.private"}, None])
def test_leaves_expression_validity_coverage_and_read_authority_to_graph(value):
    form = _form()
    form["seats"][0]["cost_groups"] = [{"entries": ["Undeclared"], "value": value}]
    expanded, _ = expand_action_cost_groups(form)
    assert expanded["seats"][0]["costs"] == {"Wait": {"const": 2}, "Undeclared": value}
