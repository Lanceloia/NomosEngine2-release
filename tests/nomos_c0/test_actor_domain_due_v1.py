"""Compiled due domains address actual current instances, never a host actor roster."""

from copy import deepcopy

import pytest
from authored_counter_v1 import _value
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from test_actor_formation_v1 import documents, submit_first
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError


def domain_documents():
    lib, ports, source, assets = documents(
        opening=[
            {
                "kind": "sprite",
                "state": {"count": 0, "awake": False},
                "debt": 20,
            }
        ]
    )
    ports["due_events"][0]["actor_domains"] = [
        {
            "name": "sprites",
            "kind": "sprite",
            "value": _value(
                ["actor.count", "actor.awake", "scene.signal", "due.subject"],
                ["actor.count"],
                {"count": "actor.count"},
            ),
        }
    ]
    source["actor_templates"][0]["first_debt"] = 20
    source["lawdefs"].append(
        {
            "name": "age",
            "family": "due_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "due.subject == 'clock'",
                    "outputs": {
                        "count": {"add": [{"ref": "actor.count"}, 1]},
                    },
                }
            },
        }
    )
    source["due_events"][0]["actor_domain_effects"] = [
        {
            "name": "sprites",
            "law": {"ref": "age", "args": {}},
        }
    ]
    return lib, ports, source, assets


def test_current_domain_contains_opening_and_actual_birth_with_exact_refs():
    lib, ports, source, assets = domain_documents()
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    old, new = session._runtime.actors()
    session.continue_form("seat_0")
    assert [item.current_state.count for item in session.author_actor_instances()] == [1, 1]
    (event,) = [
        record
        for record in session._runtime.occurrence_history()
        if record.source.value == "c0.graph.pulse"
    ]
    assert event.participants.actors == (("sprites", old.actor), ("sprites", new.actor))
    assert event.semantic_envelope.actors == event.participants.actors
    assert dict(session.author_snapshot().owners)["scene"].signal == "pulse"
    assert not any("sprite" in path for path, _ in session.read("seat_0").fields)


def test_empty_domain_does_not_cancel_required_due():
    lib, ports, source, assets = domain_documents()
    assets["opening_actors"] = []
    source["game_form"]["seats"][0]["eligible"] = False
    session = _compile(lib, ports, source).start(assets)
    session.continue_form("seat_0")
    assert session.author_actor_instances() == ()
    (record,) = session._runtime.occurrence_history()
    assert record.source.value == "c0.graph.pulse"
    assert record.participants.actors == ()
    assert dict(session.author_snapshot().owners)["scene"].signal == "pulse"


def test_instance_failure_rolls_back_entire_due_and_debts():
    lib, ports, source, assets = domain_documents()
    source["lawdefs"][-1]["body"]["law"]["guard"] = "actor.awake"
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    before = (session.author_snapshot(), session._runtime.action_value_state())
    with pytest.raises(K0SettlementDefect):
        session.continue_form("seat_0")
    assert (session.author_snapshot(), session._runtime.action_value_state()) == before
    assert session._runtime._fatal


@pytest.mark.parametrize("mutation", ["unknown", "missing", "write", "duplicate"])
def test_domain_declaration_errors_fail_during_compile(mutation):
    lib, ports, source, _ = domain_documents()
    if mutation == "unknown":
        ports["due_events"][0]["actor_domains"][0]["kind"] = "unknown"
    elif mutation == "missing":
        source["due_events"][0]["actor_domain_effects"] = []
    elif mutation == "write":
        ports["due_events"][0]["actor_domains"][0]["value"]["outputs"]["count"] = "actor.awake"
    else:
        ports["due_events"][0]["actor_domains"] *= 2
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_domain_law_edit_changes_actual_instance_effect_not_the_host():
    lib, ports, source, assets = domain_documents()
    alternate = deepcopy(source)
    alternate["lawdefs"][-1]["body"]["law"]["outputs"]["count"]["add"][1] = 2
    results = []
    for authored in (source, alternate):
        session = _compile(lib, ports, authored).start(assets)
        submit_first(session)
        session.continue_form("seat_0")
        results.append([item.current_state.count for item in session.author_actor_instances()])
    assert results == [[1, 1], [2, 2]]
