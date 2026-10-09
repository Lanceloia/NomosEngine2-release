"""A decision shares its projection, never its subsequent transition's proof."""

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._action_value_abi import _K0ActionValueProjection
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from test_event_jump_inmemory import (
    START,
    _action_value_session,
    _ActionValueProjector,
    _Attempt,
)


def test_decision_projects_once_and_temporal_admission_independently_rechecks(monkeypatch):
    session = _action_value_session()
    samples = []
    project = session._action_value_projections

    def observe():
        samples.append(session.read_time().ordinal)
        return project()

    monkeypatch.setattr(session, "_action_value_projections", observe)
    opportunity = session.continue_action_value()
    # Initial decision, independent debt admission, new decision at the new time.
    assert samples == [0, 0, 3]
    assert opportunity.at.ordinal == 3
    assert session.action_value_history()[0].kind == "advance"


def test_new_calls_and_world_changes_never_inherit_projections(monkeypatch):
    session = _action_value_session(freeze_while_baking=True)
    project = _ActionValueProjector.project
    modes = []

    def observe(projector, view):
        modes.append(view.view.mode)
        return project(projector, view)

    monkeypatch.setattr(_ActionValueProjector, "project", observe)
    session.continue_action_value()
    count = len(modes)
    session.continue_action_value()
    assert len(modes) == count + 1
    session.settle(_K0InMemoryActionAttempt(START, _Attempt("start")))
    modes.clear()
    session.continue_action_value()
    assert modes and all(mode == "baking" for mode in modes)


def test_independent_debt_admission_rejects_changed_projection_without_partial_advance(monkeypatch):
    session = _action_value_session()
    before = (session.read_time(), session.action_value_state(), session.occurrence_history())
    calls = []

    def unstable():
        calls.append(None)
        return {"worker": _K0ActionValueProjection(len(calls), True)}

    monkeypatch.setattr(session, "_action_value_projections", unstable)
    with pytest.raises((K0ProfileError, K0SettlementDefect), match="debt|temporal"):
        session.continue_action_value()
    assert len(calls) == 2
    assert before == (
        session.read_time(), session.action_value_state(), session.occurrence_history()
    )
    assert session.action_value_history() == ()
