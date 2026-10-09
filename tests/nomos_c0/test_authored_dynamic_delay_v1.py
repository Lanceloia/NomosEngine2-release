"""Declared scheduling delays retain admission, time and provenance boundaries."""

from __future__ import annotations

from copy import deepcopy

import pytest
from authored_counter_v1 import MAX_INT
from authored_paid_read_v1 import compile_documents, documents, owner, submit
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0InMemoryRuleInput
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_action_v1 import C0ValueActionEvidence, C0ValueActionParticipants


def _delay_value(source):
    return source["lawdefs"][0]["body"]["value"]


def _unchanged_state(session):
    return session.author_snapshot(), session._runtime._pending_due, session._runtime._cursor


def test_one_compiled_program_uses_current_actor_state_for_actual_due_time():
    lib, ports, source, assets = documents(temporal=True)
    _delay_value(source)["outputs"]["delay"] = {"add": [{"ref": "actor.opens"}, {"const": 2}]}
    other = deepcopy(assets)
    other["opening"]["actor_a"]["opens"] = 1
    program = compile_documents(lib, ports, source)
    first, second = program.start(assets), program.start(other)
    for session, expected_time in ((first, 6), (second, 7)):
        assert isinstance(submit(session, "seat_a", "open"), K0Published)
        action = session._runtime.occurrence_history()[0]
        pending = session._runtime._pending_due[0]
        assert pending.key.formation == action.occurrence
        assert pending.at == _K0FixedTime(expected_time)
    assert first.advance("seat_a", 6).occurrences
    assert second.advance("seat_a", 6).occurrences == ()
    assert owner(second, "scene").mode == "sealed"
    due = second.advance("seat_a", 7).occurrences[0]
    assert due.formation_basis.key.formation == second._runtime.occurrence_history()[0].occurrence
    assert first.time == 6 and second.time == 7
    assert owner(first, "scene").mode == owner(second, "scene").mode == "accessible"


def test_source_delay_edit_changes_real_schedule_without_a_host_branch():
    lib, ports, source, assets = documents(temporal=True)
    changed = deepcopy(source)
    _delay_value(changed)["outputs"]["delay"] = {"const": 3}
    first = compile_documents(lib, ports, source).start(assets)
    second = compile_documents(lib, ports, changed).start(assets)
    for session in (first, second):
        assert isinstance(submit(session, "seat_a", "open"), K0Published)
    assert first.advance("seat_a", 6).occurrences
    assert second.advance("seat_a", 6).occurrences == ()
    assert owner(second, "scene").mode == "sealed"
    assert second.advance("seat_a", 9).occurrences
    assert second.time == 7
    assert [item.source for item in first._runtime.occurrence_history()] == [
        item.source for item in second._runtime.occurrence_history()
    ]


@pytest.mark.parametrize(
    "expression,opens,time",
    [
        ({"ref": "actor.opens"}, 0, 4),
        ({"add": [{"ref": "actor.opens"}, {"const": MAX_INT}]}, 1, 4),
        ({"add": [{"ref": "actor.opens"}, {"const": 2}]}, 1, MAX_INT - 2),
    ],
    ids=["zero", "expression-overflow", "due-time-overflow"],
)
def test_invalid_current_delay_is_a_finite_zero_write_rejection(expression, opens, time):
    lib, ports, source, assets = documents(temporal=True)
    _delay_value(source)["outputs"]["delay"] = expression
    assets["opening"]["actor_a"]["opens"] = opens
    assets["time"] = time
    session = compile_documents(lib, ports, source).start(assets)
    before = _unchanged_state(session)
    for _ in range(2):
        assert isinstance(submit(session, "seat_a", "open"), K0NotAdmitted)
        assert _unchanged_state(session) == before
        assert session._runtime._fatal is False


def test_due_at_the_maximum_time_is_admitted_and_really_published():
    lib, ports, source, assets = documents(temporal=True)
    _delay_value(source)["outputs"]["delay"] = {"add": [{"ref": "actor.opens"}, {"const": 2}]}
    assets["time"] = MAX_INT - 2
    session = compile_documents(lib, ports, source).start(assets)
    assert isinstance(submit(session, "seat_a", "open"), K0Published)
    pending = session._runtime._pending_due[0]
    assert pending.at == _K0FixedTime(MAX_INT)
    due = session.advance("seat_a", MAX_INT).occurrences[0]
    assert session.time == MAX_INT
    assert due.formation_basis.key == pending.key
    assert owner(session, "scene").open_ref == due.occurrence


@pytest.mark.parametrize("effect_binding", [False, True])
def test_delay_cannot_depend_on_future_occurrence_or_effect_stage(effect_binding):
    lib, ports, source, _ = documents(temporal=True)
    value = _delay_value(source)
    value["outputs"]["delay"] = {"ref": "occurrence"}
    if effect_binding:
        value["bindings"].append(
            {"name": "later_delay", "let": {"ref": "actor.opens"}, "stage": "effect"}
        )
        value["outputs"]["delay"] = {"ref": "later_delay"}
    with pytest.raises(C0LawError):
        compile_documents(lib, ports, source)


@pytest.mark.parametrize("delay", [0, -1, MAX_INT + 1])
def test_invalid_literal_delay_is_rejected_before_start(delay):
    lib, ports, source, _ = documents(temporal=True)
    _delay_value(source)["outputs"]["delay"] = {"const": delay}
    with pytest.raises(C0LawError):
        compile_documents(lib, ports, source)


def test_rule_rejects_delay_that_disagrees_with_current_admission():
    lib, ports, source, assets = documents(temporal=True)
    _delay_value(source)["outputs"]["delay"] = {"add": [{"ref": "actor.opens"}, {"const": 2}]}
    program = compile_documents(lib, ports, source)
    session = program.start(assets)
    action = dict(program.actions)["open"]
    payload = action.payload_type("A", "folio")
    rule_input = _K0InMemoryRuleInput(
        K0OccurrenceRef(1),
        action.source_key,
        C0ValueActionEvidence(owner(session, "scene"), owner(session, "a"), payload, 3),
        C0ValueActionParticipants("A"),
        (),
        None,
        _K0FixedTime(4),
    )
    before = _unchanged_state(session)
    with pytest.raises(K0ProfileError, match="typed delay"):
        action.build_spec().rule.evaluate(rule_input)
    assert _unchanged_state(session) == before
