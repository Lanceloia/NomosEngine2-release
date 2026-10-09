"""Immediate NPC preparation is local; public commits still revalidate proposals."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_control_binding_v1 import _inputs
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0BindingError


@pytest.fixture(scope="module")
def compiled():
    lib, ports, source, assets = _inputs()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    return _compile(lib, ports, source), assets


def dispatched(compiled):
    program, assets = compiled
    session = program.start(deepcopy(assets))
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    return session


def receiver_ready(compiled):
    session = dispatched(compiled)
    while True:
        opportunity = session._runtime.continue_action_value()
        if getattr(opportunity, "seat", None) == "receiver":
            return session


def test_internal_auto_prepares_once_and_matches_public_path(compiled, monkeypatch):
    session = dispatched(compiled)
    preparations = []
    original = session._prepare_appraisal

    def prepare(seat):
        preparations.append(seat)
        return original(seat)

    monkeypatch.setattr(session, "_prepare_appraisal", prepare)
    frame = session.continue_form("sender")
    assert preparations == ["receiver"]
    assert frame.finished and frame.outcome == "delivered" and frame.time == 3
    reference = receiver_ready(compiled)
    proposal = reference.propose_appraisal("receiver")
    assert isinstance(reference.commit_appraisal(proposal), K0Published)
    assert reference.author_snapshot() == session.author_snapshot()
    assert reference.appraisal_history() == session.appraisal_history()
    assert reference._runtime.action_value_history() == session._runtime.action_value_history()


def test_one_preparation_generates_one_menu_and_reuses_owner_reads(compiled, monkeypatch):
    session = receiver_ready(compiled)
    projections, reads = [], []
    project = session._project_offers
    read = session._runtime.read_owner

    def project_once(seat, context):
        projections.append(seat)
        return project(seat, context)

    def read_once(key):
        reads.append(key)
        return read(key)

    monkeypatch.setattr(session, "_project_offers", project_once)
    monkeypatch.setattr(session._runtime, "read_owner", read_once)
    proposal, attempt = session._prepare_appraisal("receiver")
    assert proposal.chosen.entry == "confirm_alt" and attempt is not None
    assert projections == ["receiver"]
    assert reads and len(reads) == len(set(reads))


@pytest.mark.parametrize("defect", ["score", "time", "profile"])
def test_public_commit_recomputes_and_rejects_tampering_without_write(
    compiled, monkeypatch, defect
):
    session = receiver_ready(compiled)
    proposal = session.propose_appraisal("receiver")
    if defect == "score":
        first = replace(proposal.candidates[0], score=proposal.candidates[0].score + 1)
        forged = replace(proposal, candidates=(first, *proposal.candidates[1:]))
    elif defect == "time":
        forged = replace(proposal, time=proposal.time + 1)
    else:
        forged = replace(proposal, profile="foreign")
    snapshot = session.author_snapshot()
    calls = []
    prepare = session._prepare_appraisal

    def current(seat):
        calls.append(seat)
        return prepare(seat)

    monkeypatch.setattr(session, "_prepare_appraisal", current)
    with pytest.raises(C0BindingError, match="stale or foreign"):
        session.commit_appraisal(forged)
    assert calls == ["receiver"]
    assert session.author_snapshot() == snapshot and session.appraisal_history() == ()
    assert isinstance(session.commit_appraisal(proposal), K0Published)
    with pytest.raises(C0BindingError, match="opportunity"):
        session.commit_appraisal(proposal)


def test_auto_k0_refusal_is_recorded_once_without_fallback(compiled, monkeypatch):
    session = receiver_ready(compiled)
    snapshot = session.author_snapshot()
    monkeypatch.setattr(session._runtime, "settle", lambda attempt: K0NotAdmitted(attempt.source))
    with pytest.raises(C0BindingError, match="rejected by K0"):
        session.continue_form("sender")
    assert session.author_snapshot() == snapshot
    assert len(session.appraisal_history()) == 1
    assert session.appraisal_history()[0].outcome == "not_admitted"


def test_current_authored_guard_is_still_rechecked_by_real_k0():
    lib, ports, source, assets = _inputs()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    law = next(item for item in source["lawdefs"] if item["name"] == "action.confirm")
    law["body"]["value"]["guard"]["all"].append({"const": False})
    session = receiver_ready((_compile(lib, ports, source), assets))
    assert session.propose_appraisal("receiver").chosen.entry == "confirm_alt"
    snapshot = session.author_snapshot()
    debt = session._runtime.action_value_history()
    with pytest.raises(C0BindingError, match="rejected by K0"):
        session.continue_form("sender")
    assert session.author_snapshot() == snapshot
    assert session._runtime.action_value_history() == debt
    assert session.appraisal_history()[0].outcome == "not_admitted"


def test_player_read_is_projected_only_at_entry_and_actual_return(compiled, monkeypatch):
    session = dispatched(compiled)
    reference = dispatched(compiled)
    original = session.form_frame
    calls = []

    def frame(seat):
        result = original(seat)
        calls.append((result.time, result.finished))
        return result

    monkeypatch.setattr(session, "form_frame", frame)
    result = session.continue_form("sender")
    assert calls == [(0, False), (3, True)]
    assert result == reference.continue_form("sender")
    assert session.author_snapshot() == reference.author_snapshot()
    assert session.appraisal_history() == reference.appraisal_history()


def test_return_read_fault_does_not_gate_or_rollback_committed_npc_actions(compiled, monkeypatch):
    session = dispatched(compiled)
    original = session.form_frame
    calls = []

    def frame(seat):
        result = original(seat)
        calls.append(result.time)
        if result.time == 3:
            raise C0BindingError("derived read fault")
        return result

    monkeypatch.setattr(session, "form_frame", frame)
    with pytest.raises(C0BindingError, match="derived read fault"):
        session.continue_form("sender")
    assert calls[0] == 0 and calls[-1] == 3
    assert len(session.appraisal_history()) == 1
    assert session.appraisal_history()[0].outcome == "published"
    assert any(row.source.value == "c0.parcel.alt" for row in session._runtime.occurrence_history())


def test_entry_read_fault_prevents_any_automatic_transition(compiled, monkeypatch):
    session = dispatched(compiled)
    snapshot = session.author_snapshot()
    history = session._runtime.action_value_history()

    def frame(seat):
        raise C0BindingError("entry read fault")

    monkeypatch.setattr(session, "form_frame", frame)
    with pytest.raises(C0BindingError, match="entry read fault"):
        session.continue_form("sender")
    assert session.author_snapshot() == snapshot
    assert session._runtime.action_value_history() == history
    assert session.appraisal_history() == ()
