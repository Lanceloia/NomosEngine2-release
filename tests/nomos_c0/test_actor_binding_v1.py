"""Actor-family expansion is a C0 contract, not a world-specific text macro."""

from __future__ import annotations

from copy import deepcopy

import pytest

from nomos_c0.actor_binding_v1 import expand_actor_bindings
from nomos_c0.author_contract_v1 import C0LawError


class Actor:
    pass


class Scene:
    pass


OWNERS = {
    "scene": (Scene, None),
    "a": (Actor, "name"),
    "b": (Actor, "name"),
    "c": (Actor, "name"),
    "new_npc": (Actor, "name"),
}


def _source() -> dict[str, object]:
    return {
        "actor_domains": [
            {"name": "participants", "actor_state": "Actor", "owners": ["a", "b", "c"]}
        ],
        "actions": [
            {
                "family": "attack",
                "template": "attack",
                "domain": "participants",
                "source_prefix": "sample.attack",
                "law": {"ref": "action.attack", "args": {}},
            }
        ],
        "events": [
            {
                "family": "resolve_attack",
                "template": "resolve",
                "for_action_family": "attack",
                "source_prefix": "sample.resolve-attack",
                "law": {"ref": "event.resolve", "args": {}},
            }
        ],
    }


def _expand(source: dict[str, object]) -> dict[str, object]:
    return expand_actor_bindings(source, OWNERS, {"attack": "a"}, frozenset({"resolve"}))


def test_closed_domain_generates_distinct_action_and_exact_causal_events() -> None:
    source = _source()
    before = deepcopy(source)
    expanded = _expand(source)
    assert source == before
    assert [item["name"] for item in expanded["actions"]] == [
        "attack_a",
        "attack_b",
        "attack_c",
    ]
    assert [item["source_key"] for item in expanded["actions"]] == [
        "sample.attack-a",
        "sample.attack-b",
        "sample.attack-c",
    ]
    assert [item["trigger_action"] for item in expanded["events"]] == [
        "attack_a",
        "attack_b",
        "attack_c",
    ]
    assert [item["causal_key"] for item in expanded["events"]] == [
        "sample.resolve-attack-a.causes",
        "sample.resolve-attack-b.causes",
        "sample.resolve-attack-c.causes",
    ]
    assert all("new_npc" not in item["name"] for item in expanded["actions"])


def test_object_target_family_preserves_one_binding_without_shared_mutation() -> None:
    source = _source()
    source["actions"][0]["target"] = {"kind": "portable"}
    expanded = _expand(source)
    assert [action["target"] for action in expanded["actions"]] == [
        {"kind": "portable"},
        {"kind": "portable"},
        {"kind": "portable"},
    ]
    expanded["actions"][0]["target"]["kind"] = "changed"
    assert source["actions"][0]["target"] == {"kind": "portable"}
    assert expanded["actions"][1]["target"] == {"kind": "portable"}


def test_target_family_cannot_add_a_second_participant_contract() -> None:
    source = _source()
    source["actions"][0].update(target={"kind": "portable"}, participants={})
    with pytest.raises(C0LawError, match="mix target and participants"):
        _expand(source)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda row: row["actor_domains"][0]["owners"].append("a"), "repeated owners"),
        (lambda row: row["actor_domains"][0]["owners"].append("scene"), "nominal state"),
        (lambda row: row["actor_domains"][0]["owners"].append("missing"), "foreign"),
        (lambda row: row["actions"][0].update(template="missing"), "foreign domain or template"),
        (lambda row: row["events"][0].update(for_action_family="missing"), "Action family"),
    ],
)
def test_malformed_or_foreign_binding_fails_before_compilation(change, message) -> None:
    source = _source()
    change(source)
    with pytest.raises(C0LawError, match=message):
        _expand(source)


def test_generated_identity_cannot_alias_a_singleton() -> None:
    source = _source()
    source["actions"].append(
        {
            "name": "attack_b",
            "template": "attack",
            "actor": "b",
            "source_key": "other.attack-b",
            "event_type": "other.attack-b.action",
            "law": {"ref": "action.attack", "args": {}},
        }
    )
    with pytest.raises(C0LawError, match="Action identities alias"):
        _expand(source)


def test_event_family_cannot_infer_a_private_actor_recipient() -> None:
    with pytest.raises(C0LawError, match="direct Scene template"):
        expand_actor_bindings(
            _source(),
            OWNERS,
            {"attack": "a"},
            frozenset(),
        )


def test_event_type_and_causal_identity_aliases_reject_before_lowering() -> None:
    source = _source()
    source["events"].append(
        {
            "name": "other",
            "source_key": "other.source",
            "event_type": "sample.resolve-attack-a.event",
            "causal_key": "other.causes",
        }
    )
    with pytest.raises(C0LawError, match="Event type identities alias"):
        _expand(source)
    source["events"][-1]["event_type"] = "other.event"
    source["events"][-1]["causal_key"] = "sample.resolve-attack-a.causes"
    with pytest.raises(C0LawError, match="causal Law identities alias"):
        _expand(source)


def test_scheduled_family_waits_for_an_explicit_due_binding_contract() -> None:
    source = _source()
    with pytest.raises(C0LawError, match="due binding contract"):
        expand_actor_bindings(
            source,
            OWNERS,
            {"attack": "a"},
            frozenset({"resolve"}),
            frozenset({"attack"}),
        )


def test_seat_family_uses_one_offer_declaration_for_each_closed_actor() -> None:
    source = _source()
    source["seats"] = [
        {
            "seat_family": "participants",
            "names": {"a": "A", "b": "B", "c": "C"},
            "entries": ["attack"],
            "read": ["scene.phase", "actor.name", "actor.own_role"],
            "offers": [
                {
                    "entry_family": "attack",
                    "label": "Attack B",
                    "when": {"eq": [{"ref": "scene.phase"}, {"const": "night"}]},
                    "payload": {"target": {"ref": "scene.b_id"}},
                }
            ],
        }
    ]
    expanded = _expand(source)
    assert [seat["name"] for seat in expanded["seats"]] == ["A", "B", "C"]
    assert [seat["entries"] for seat in expanded["seats"]] == [
        ["attack_a"],
        ["attack_b"],
        ["attack_c"],
    ]
    assert expanded["seats"][1]["read"] == ["scene.phase", "b.name", "b.own_role"]
    assert expanded["seats"][2]["offers"][0]["entry"] == "attack_c"
    assert source["seats"][0]["offers"][0]["entry_family"] == "attack"


def test_seat_family_cannot_offer_a_foreign_or_unbound_capability() -> None:
    source = _source()
    source["seats"] = [
        {
            "seat_family": "participants",
            "names": {"a": "A", "b": "B", "c": "C"},
            "entries": ["missing"],
            "read": ["actor.name"],
            "offers": [],
        }
    ]
    with pytest.raises(C0LawError, match="invalid domain, entry"):
        _expand(source)
    source["seats"][0]["entries"] = ["attack"]
    source["seats"][0]["offers"] = [
        {"entry_family": "missing", "label": "foreign", "when": True, "payload": {}}
    ]
    with pytest.raises(C0LawError, match="bound Action family"):
        _expand(source)
    source["seats"][0]["entries"] = ["attack", ["attack"]]
    with pytest.raises(C0LawError, match="invalid domain, entry"):
        _expand(source)


def test_opening_actor_guard_binds_only_the_closed_domain() -> None:
    source = _source()
    source["opening_guard"] = {"eq": [{"ref": "scene.round"}, {"const": 1}]}
    source["opening_actor_guards"] = [
        {
            "domain": "participants",
            "when": {"eq": [{"ref": "actor.name"}, {"const": "present"}]},
        }
    ]
    expanded = _expand(source)
    assert expanded["opening_guard"]["all"] == [
        {"eq": [{"ref": "scene.round"}, {"const": 1}]},
        {"eq": [{"ref": "a.name"}, {"const": "present"}]},
        {"eq": [{"ref": "b.name"}, {"const": "present"}]},
        {"eq": [{"ref": "c.name"}, {"const": "present"}]},
    ]
    assert "opening_actor_guards" not in expanded
    assert source["opening_actor_guards"][0]["when"]["eq"][0] == {"ref": "actor.name"}
    source["opening_actor_guards"][0]["domain"] = "foreign"
    with pytest.raises(C0LawError, match="closed domain"):
        _expand(source)


def test_one_event_family_binds_multiple_action_families_with_distinct_sources() -> None:
    source = _source()
    second = deepcopy(source["actions"][0])
    second.update(family="inspect", source_prefix="sample.inspect")
    source["actions"].append(second)
    event = source["events"][0]
    event.pop("for_action_family")
    event["for_action_families"] = ["attack", "inspect"]
    expanded = _expand(source)
    assert [item["trigger_action"] for item in expanded["events"]] == [
        "attack_a",
        "attack_b",
        "attack_c",
        "inspect_a",
        "inspect_b",
        "inspect_c",
    ]
    assert len({item["source_key"] for item in expanded["events"]}) == 6
    event["for_action_families"].append("attack")
    with pytest.raises(C0LawError, match="distinct declared Action"):
        _expand(source)


def test_event_successor_family_binds_each_generated_event_without_source_repetition() -> None:
    source = _source()
    source["events"].append(
        {
            "family": "dawn",
            "template": "resolve",
            "for_event_family": "resolve_attack",
            "source_prefix": "sample.dawn",
            "law": {"ref": "event.dawn", "args": {}},
        }
    )
    expanded = _expand(source)
    assert [item["trigger_event"] for item in expanded["events"][3:]] == [
        "resolve_attack_a",
        "resolve_attack_b",
        "resolve_attack_c",
    ]
    assert len({item["source_key"] for item in expanded["events"]}) == 6
    assert source["events"][-1]["for_event_family"] == "resolve_attack"


def test_shared_result_keeps_distinct_causal_bindings_and_one_successor() -> None:
    source = _source()
    source["events"][0]["share_result"] = True
    source["events"].append(
        {
            "family": "dawn",
            "template": "resolve",
            "for_event_family": "resolve_attack",
            "source_prefix": "sample.dawn",
            "law": {"ref": "event.dawn", "args": {}},
        }
    )
    expanded = _expand(source)
    first = expanded["events"][:3]
    assert len({row["source_key"] for row in first}) == 1
    assert len({row["causal_key"] for row in first}) == 3
    assert [row["trigger_action"] for row in first] == ["attack_a", "attack_b", "attack_c"]
    assert [row["trigger_event"] for row in expanded["events"][3:]] == ["resolve_attack_a"]

    source["events"][0]["share_result"] = False
    with pytest.raises(C0LawError, match="sharing must be explicit"):
        _expand(source)


def test_shared_result_rejects_aliased_family_source() -> None:
    source = _source()
    source["events"][0]["share_result"] = True
    other = deepcopy(source["events"][0])
    other["family"] = "other"
    other["law"] = {"ref": "event.other", "args": {}}
    source["events"].append(other)
    with pytest.raises(C0LawError, match="source identities alias"):
        _expand(source)


def test_event_successor_rejects_foreign_cycle_and_identity_alias() -> None:
    source = _source()
    successor = {
        "family": "dawn",
        "template": "resolve",
        "for_event_family": "missing",
        "source_prefix": "sample.dawn",
        "law": {"ref": "event.dawn", "args": {}},
    }
    source["events"].append(successor)
    with pytest.raises(C0LawError, match="foreign or forms a cycle"):
        _expand(source)
    successor["for_event_family"] = "dawn"
    with pytest.raises(C0LawError, match="foreign or forms a cycle"):
        _expand(source)
    successor["for_event_family"] = "resolve_attack"
    second = deepcopy(successor)
    second["family"] = "later"
    source["events"].append(second)
    with pytest.raises(C0LawError, match="source identities alias"):
        _expand(source)


def test_event_successor_can_bind_one_declared_actor_recipient() -> None:
    source = _source()
    source["events"].append(
        {
            "family": "notice",
            "template": "notice",
            "actor": "b",
            "for_event_family": "resolve_attack",
            "source_prefix": "sample.notice",
            "law": {"ref": "event.notice", "args": {}},
        }
    )
    expanded = expand_actor_bindings(
        source,
        OWNERS,
        {"attack": "a"},
        frozenset({"resolve"}),
        actor_event_templates=frozenset({"notice"}),
    )
    assert [row["actor"] for row in expanded["events"][3:]] == ["b"] * 3
    assert [row["trigger_event"] for row in expanded["events"][3:]] == [
        "resolve_attack_a",
        "resolve_attack_b",
        "resolve_attack_c",
    ]
    source["events"][-1]["actor"] = "missing"
    with pytest.raises(C0LawError, match="recipient is foreign"):
        expand_actor_bindings(
            source,
            OWNERS,
            {"attack": "a"},
            frozenset({"resolve"}),
            actor_event_templates=frozenset({"notice"}),
        )


def test_seat_family_can_add_a_declared_actor_only_capability() -> None:
    source = _source()
    source["actions"].append(
        {
            "name": "inspect_b",
            "template": "attack",
            "actor": "b",
            "source_key": "sample.inspect-b",
            "event_type": "sample.inspect-b.action",
            "law": {"ref": "action.inspect", "args": {}},
        }
    )
    source["seats"] = [
        {
            "seat_family": "participants",
            "names": {"a": "A", "b": "B", "c": "C"},
            "entries": ["attack"],
            "read": ["actor.name"],
            "offers": [],
            "additional": {
                "b": {
                    "entries": ["inspect_b"],
                    "offers": [
                        {
                            "entry": "inspect_b",
                            "label": "Inspect",
                            "when": {"const": True},
                            "payload": {},
                        }
                    ],
                }
            },
        }
    ]
    expanded = _expand(source)
    assert expanded["seats"][1]["entries"] == ["attack_b", "inspect_b"]
    assert expanded["seats"][0]["entries"] == ["attack_a"]
    source["seats"][0]["additional"]["a"] = source["seats"][0]["additional"].pop("b")
    with pytest.raises(C0LawError, match="additional Action is foreign"):
        _expand(source)


def _actor_event_source():
    source = _source()
    source["events"][0].update(template="notice")
    return source


def _expand_actor_event(source):
    return expand_actor_bindings(
        source,
        OWNERS,
        {"attack": "a"},
        frozenset({"resolve"}),
        actor_event_templates=frozenset({"notice"}),
    )


def test_action_family_preserves_explicit_participants_without_mutating_input():
    source = _source()
    source["actions"][0]["participants"] = {"victim": {"actors": ["b", "c"]}}
    before = deepcopy(source)
    expanded = _expand(source)
    assert source == before
    assert all(
        item["participants"] == {"victim": {"actors": ["b", "c"]}} for item in expanded["actions"]
    )
    expanded["actions"][0]["participants"]["victim"]["actors"].clear()
    assert expanded["actions"][1]["participants"]["victim"]["actors"] == ["b", "c"]
    assert source == before


@pytest.mark.parametrize("members", [["a", "b"], ["a", "b", "c", "new_npc"]])
def test_action_recipient_correlation_follows_only_the_selected_closed_domain(members):
    source = _actor_event_source()
    source["actor_domains"][0]["owners"] = members
    source["events"][0]["actor"] = {"from_trigger": "actor"}
    expanded = _expand_actor_event(source)
    assert [row["actor"] for row in expanded["events"]] == members
    assert [row["trigger_action"] for row in expanded["events"]] == [
        f"attack_{actor}" for actor in members
    ]
    assert len({row["causal_key"] for row in expanded["events"]}) == len(members)


def test_explicit_action_list_fans_out_only_to_declared_recipients():
    source = _actor_event_source()
    del source["events"][0]["for_action_family"]
    source["events"][0].update(
        for_actions=["attack_a", "attack_c"], actor_domain="participants", share_result=True
    )
    expanded = _expand_actor_event(source)
    events = expanded["events"]
    assert [(row["trigger_action"], row["actor"]) for row in events] == [
        (action, actor) for action in ("attack_a", "attack_c") for actor in ("a", "b", "c")
    ]
    assert len({row["source_key"] for row in events}) == 3
    assert len({row["causal_key"] for row in events}) == 6
    assert len({row["shared_result"] for row in events}) == 3


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda row: row.update(actor="missing"), "recipient is foreign"),
        (lambda row: row.update(actor_domain="missing"), "domain is foreign"),
        (
            lambda row: row.update(actor="b", actor_domain="participants"),
            "one Actor recipient",
        ),
        (lambda row: row.update(actor={"from_trigger": "scene"}), "correlation"),
        (lambda row: row.update(for_actions=["missing"]), "missing or unknown"),
        (lambda row: row.update(for_actions=["attack_a"]), "missing or unknown"),
    ],
)
def test_action_event_binding_rejects_foreign_or_ambiguous_declarations(change, message):
    source = _actor_event_source()
    change(source["events"][0])
    with pytest.raises(C0LawError, match=message):
        _expand_actor_event(source)


@pytest.mark.parametrize("triggers", [[], ["missing"], ["attack_a", "attack_a"], [{}]])
def test_explicit_action_triggers_must_be_closed_nonempty_and_distinct(triggers):
    source = _actor_event_source()
    event = source["events"][0]
    del event["for_action_family"]
    event.update(for_actions=triggers, actor="b")
    with pytest.raises(C0LawError, match="distinct declared Action"):
        _expand_actor_event(source)


def test_action_actor_correlation_is_not_available_on_an_event_trigger():
    source = _source()
    source["events"].append(
        {
            "family": "notice",
            "template": "notice",
            "actor": {"from_trigger": "actor"},
            "for_event_family": "resolve_attack",
            "source_prefix": "sample.notice",
            "law": {"ref": "event.notice", "args": {}},
        }
    )
    with pytest.raises(C0LawError, match="Action trigger actor"):
        _expand_actor_event(source)


def test_recipient_product_stops_at_the_existing_finite_expansion_limit():
    owners = {f"a{i}": (Actor, "name") for i in range(64)}
    source = _actor_event_source()
    source["actor_domains"][0]["owners"] = list(owners)
    source["events"][0]["actor_domain"] = "participants"
    with pytest.raises(C0LawError, match="C0-COMPILE-LIMIT.*event_results"):
        expand_actor_bindings(
            source,
            owners,
            {"attack": "a0"},
            frozenset(),
            actor_event_templates=frozenset({"notice"}),
        )


def test_seat_subdomain_can_select_an_explicitly_bound_action_family():
    source = _source()
    source["actor_domains"].append({"name": "pair", "actor_state": "Actor", "owners": ["a", "b"]})
    source["seats"] = [
        {
            "seat_family": "pair",
            "names": "upper",
            "entries": ["attack"],
            "read": ["actor.name"],
            "offers": [],
        }
    ]
    assert [row["entries"] for row in _expand(source)["seats"]] == [["attack_a"], ["attack_b"]]
    source["actor_domains"][1]["owners"].append("new_npc")
    with pytest.raises(C0LawError, match="entry or read"):
        _expand(source)


def test_correlated_shared_result_keeps_all_edges_and_separates_actual_recipients():
    source = _actor_event_source()
    other = deepcopy(source["actions"][0])
    other.update(family="inspect", source_prefix="sample.inspect")
    source["actions"].append(other)
    event = source["events"][0]
    del event["for_action_family"]
    event.update(
        for_action_families=["attack", "inspect"],
        actor={"from_trigger": "actor"},
        share_result=True,
    )
    events = _expand_actor_event(source)["events"]
    assert len(events) == len({row["causal_key"] for row in events}) == 6
    assert len({row["source_key"] for row in events}) == 3
    for actor in ("a", "b", "c"):
        aliases = [row for row in events if row["actor"] == actor]
        assert {row["source_key"] for row in aliases} == {f"sample.resolve-attack-{actor}"}
        assert {row["trigger_action"] for row in aliases} == {f"attack_{actor}", f"inspect_{actor}"}
