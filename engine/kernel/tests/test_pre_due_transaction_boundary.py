"""Actor-first boundary queries share the transaction/reentry failure contract."""

from dataclasses import replace

import pytest
import test_event_jump_inmemory as sample
from nomos_kernel import K0ProfileError
from nomos_kernel._action_value_abi import _K0ActionValueRecord
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._coordinates import (
    _K0FixedTime,
    _K0TemporalAdvanceRequest,
    _K0TemporalInterval,
)
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect


def _image(session):
    return (
        session._states,
        session._cursor,
        session.occurrence_history(),
        session._pending_due,
        session._pre_due_phase,
        session.read_time(),
        session.action_value_state(),
        session.action_value_history(),
        session.temporal_history(),
        session._same_time_actions,
    )


@pytest.mark.parametrize("failure", ["query", "nested_advance", "nested_settle"])
def test_pre_due_query_failure_rolls_back_and_nested_actions_cannot_publish(monkeypatch, failure):
    session = sample._action_value_session(opening_debt=0 if failure == "nested_settle" else 3)
    before = _image(session)
    values = session.action_value_state()
    record = _K0ActionValueRecord(
        _K0FixedTime(3),
        "advance",
        None,
        values,
        tuple(replace(item, debt=item.debt - 3) for item in values),
    )
    request = _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(3)))
    visited = []

    def project(projector, view):
        visited.append(session._settling)
        if failure == "nested_advance":
            session.advance(request)
        elif failure == "nested_settle":
            session.settle(_K0InMemoryActionAttempt(sample.START, sample._Attempt("start")))
        else:
            raise K0ProfileError("invalid current action-value projection")
        raise AssertionError("nested transition must reject before returning")

    monkeypatch.setattr(sample._ActionValueProjector, "project", project)
    with pytest.raises(K0SettlementDefect):
        session.begin_pre_due(request, _action_value_record=record)
    assert visited == [True]
    assert _image(session) == before
    assert session._fatal and not session._settling
    with pytest.raises(K0SettlementDefect, match="fatal"):
        session.begin_pre_due(request)


def test_no_due_rejection_stays_nonfatal_and_does_not_enter_a_phase():
    session = sample._action_value_session()
    before = _image(session)
    request = _K0TemporalAdvanceRequest(_K0TemporalInterval(_K0FixedTime(0), _K0FixedTime(1)))
    result = session.begin_pre_due(request)
    assert type(result).__name__ == "_K0TemporalRejected"
    assert _image(session) == before
    assert not session._fatal and not session._settling
