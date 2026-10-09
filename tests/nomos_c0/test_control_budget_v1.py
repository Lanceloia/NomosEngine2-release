"""A finite control budget stops orchestration, not a valid world history."""

import pytest
from authored_counter_v1 import _actor, action_value_documents, build
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0ControlBudgetExceeded
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_t0.witness_v0 import (
    T0Goal,
    T0OwnerFieldEquals,
    T0ScheduledTurn,
    T0Witness,
    check_witness,
)


def _world():
    lib, ports, source, assets = action_value_documents()
    source["game_form"]["end_at"] = 2048
    for index, seat in enumerate(source["game_form"]["seats"]):
        seat.update(
            tempo=1,
            eligible="actor.count < 1025" if index == 0 else True,
            costs={f"count_{index}": 1},
        )
        assets["action_value_openings"][index]["debt"] = 0 if index == 0 else 1025
    source["appraisal_profiles"] = [
        {
            "name": "counting",
            "seat": "seat_0",
            "fallback_entry": "count_0",
            "tie_order": ["count_0"],
            "rules": [{"entry": "count_0", "mode": "default"}],
        }
    ]
    assets["controllers"] = [
        {"seat": "seat_0", "mode": "finite_appraisal", "profile": "counting"},
        {"seat": "seat_1", "mode": "human_prompt"},
    ]
    return compile_owner_graph(build(lib, ports), source), assets


def test_exhausted_control_call_keeps_its_prefix_and_next_call_can_continue():
    program, assets = _world()
    session = program.start(assets)
    with pytest.raises(C0ControlBudgetExceeded) as caught:
        session.continue_form("seat_1")
    assert caught.value.transition_limit == 1024
    prefix = session._runtime.occurrence_history()
    assert session.time == 1022
    assert len(prefix) == 1024 and len(session.appraisal_history()) == 1023
    assert _actor(session, 0).count == 1023
    frame = session.continue_form("seat_1")
    assert frame.time == 1025 and frame.ready_seats == ("seat_1",) and not frame.finished
    assert session._runtime.occurrence_history()[: len(prefix)] == prefix
    assert _actor(session, 0).count == 1025
    offer = frame.offers[0]
    assert isinstance(session.submit("seat_1", offer.entry, dict(offer.payload)), K0Published)


def test_t0_reports_control_budget_not_a_rejected_world_or_global_unreachability():
    program, assets = _world()
    witness = T0Witness((T0ScheduledTurn("continue", "seat_1"),), (), max_steps=1)
    report = check_witness(
        program, assets, witness, T0Goal((T0OwnerFieldEquals("actor_0", ("count",), 1025),))
    )
    assert report.stop_reason == "control_budget_exhausted"
    assert report.goal_status == "not_met_within_bound"
    assert report.steps_completed == 0 and report.requested_step == 1
    assert len(report.published) == 1024
    assert "may continue" in report.detail
