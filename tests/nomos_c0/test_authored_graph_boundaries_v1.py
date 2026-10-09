"""Declared control and local authority cases preserved from native graph tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _actor, _scene, action_value_documents, build, counter_documents
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _appraisal():
    lib, ports, source, assets = action_value_documents()
    for name, step in (("count_alt", 2), ("wait", 0)):
        action = deepcopy(source["actions"][1])
        action.update(
            name=name,
            source_key=f"c0.graph.{name}",
            event_type=f"c0.graph.{name}.done",
            law={"ref": "count", "args": {"step": step}},
        )
        source["actions"].append(action)
        source["seats"][1]["entries"].append(name)
        offer = deepcopy(source["seats"][1]["offers"][0])
        offer.update(entry=name, label=name)
        source["seats"][1]["offers"].append(offer)
        source["game_form"]["seats"][1]["costs"][name] = {"const": 2}
    source["appraisal_profiles"] = [
        {
            "name": "count_first",
            "seat": "seat_1",
            "fallback_entry": "wait",
            "tie_order": ["count_1", "count_alt", "wait"],
            "rules": [
                {"entry": "count_1", "mode": "score", "value": {"const": 2}},
                {"entry": "count_alt", "mode": "score", "value": {"ref": "actor.count"}},
                {"entry": "wait", "mode": "default"},
            ],
        }
    ]
    assets["controllers"] = [
        {"seat": "seat_0", "mode": "human_prompt"},
        {"seat": "seat_1", "mode": "finite_appraisal", "profile": "count_first"},
    ]
    assets["action_value_openings"][0]["debt"] = 20
    assets["action_value_openings"][1]["debt"] = 0
    return lib, ports, source, assets


def test_appraisal_rejection_does_not_execute_its_fallback_or_spend_cost():
    lib, ports, source, assets = _appraisal()
    source["game_form"]["seats"][1]["costs"]["count_1"] = {"const": 0}
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    proposal = session.propose_appraisal("seat_1")
    assert proposal.chosen.entry == "count_1"
    before = session.author_snapshot()
    assert isinstance(session.commit_appraisal(proposal), K0NotAdmitted)
    assert session.author_snapshot() == before and not session._runtime.occurrence_history()
    assert session.appraisal_history()[-1].outcome == "not_admitted"
    assert session.propose_appraisal("seat_1").chosen.entry == "count_1"


def test_appraisal_recomputes_proposal_and_fallback_is_a_real_paid_action():
    lib, ports, source, assets = _appraisal()
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    proposal = session.propose_appraisal("seat_1")
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="stale or foreign"):
        session.commit_appraisal(replace(proposal, chosen=proposal.candidates[1].offer))
    assert session.author_snapshot() == before
    assert isinstance(session.commit_appraisal(proposal), K0Published)
    with pytest.raises(C0BindingError):
        session.commit_appraisal(proposal)
    source["appraisal_profiles"][0]["rules"][:2] = [
        {"entry": "count_1", "mode": "ignore"},
        {"entry": "count_alt", "mode": "ignore"},
    ]
    waiting = compile_owner_graph(build(lib, ports), source).start(assets)
    proposal = waiting.propose_appraisal("seat_1")
    assert proposal.chosen.entry == "wait"
    assert isinstance(waiting.commit_appraisal(proposal), K0Published)
    assert _actor(waiting, 1).count == 0
    assert waiting._runtime.action_value_history()[-1].cost == 2
    assert waiting._runtime.occurrence_history()[-1].source.value == "c0.graph.wait"


def test_unbounded_due_world_stop_is_checked_before_the_next_time_jump():
    lib, ports, source, assets = action_value_documents()
    source["game_form"]["end_at"] = None
    source["game_form"]["world_stops"] = [
        {
            "outcome": "pulse_seen",
            "owners": ["scene"],
            "when": {"eq": [{"ref": "scene.signal"}, {"const": "pulse"}]},
        }
    ]
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = {"const": False}
    source["temporal"]["periodic"][0]["max_occurrences"] = None
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    frame = session.continue_form("seat_0")
    assert frame.finished and frame.outcome == "pulse_seen" and frame.time == 5
    assert len(session._runtime.occurrence_history()) == 1
    assert _scene(session).signal == "pulse"


def test_stale_offer_still_rechecks_current_k0_admission():
    lib, ports, source, assets = counter_documents()
    source["lawdefs"][0]["body"]["value"]["guard"] = {
        "all": [
            source["lawdefs"][0]["body"]["value"]["guard"],
            {"lt": [{"ref": "actor.count"}, {"const": 1}]},
        ]
    }
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    offer = session.offers("seat_0")[0]
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    assert offer in session.offers("seat_0")
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before and session._runtime._fatal is False


def test_candidate_can_use_local_authority_without_publishing_the_field():
    lib, ports, source, assets = counter_documents()
    seat = source["seats"][0]
    seat["read"].remove("actor_0.count")
    seat["offers"][0]["when"] = {"eq": [{"ref": "actor.count"}, {"const": 0}]}
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    assert "actor_0.count" not in dict(session.read("seat_0").fields)
    offer = session.offers("seat_0")[0]
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    assert session.offers("seat_0") == ()
    assert "actor_0.count" not in dict(session.read("seat_0").fields)
    lib["owners"][1]["seat_read"].remove("count")
    with pytest.raises(C0LawError, match="read boundary"):
        compile_owner_graph(build(lib, ports), source)


def test_one_definition_has_independent_arguments_owners_and_published_sources():
    lib, ports, source, assets = counter_documents(3, 2)
    source["actions"][1]["law"]["args"]["step"] = 3
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    for index in (0, 1):
        result = session.submit(f"seat_{index}", f"count_{index}", {"target": f"person_{index}"})
        assert isinstance(result, K0Published)
        assert result.occurrences[0].source.value == f"c0.graph.count_{index}"
    assert [_actor(session, index).count for index in range(3)] == [1, 3, 0]
    assert len(set(item.occurrence for item in session._runtime.occurrence_history())) == 2
    with pytest.raises(C0BindingError):
        session.submit("seat_2", "count_0", {"target": "person_2"})


@pytest.mark.parametrize("backend", [None, object()])
def test_unqualified_library_is_rejected_before_any_program_binding(backend, monkeypatch):
    from nomos_c0 import program_binding_v1

    lib, ports, source, _ = counter_documents()
    library = build(lib, ports)

    def forbidden(*args, **kwargs):
        pytest.fail("an unqualified library reached Program binding")

    monkeypatch.setattr(program_binding_v1, "bind_program", forbidden)
    with pytest.raises(C0LawError, match="unsupported backend"):
        compile_owner_graph(replace(library, value_backend=backend), source)
