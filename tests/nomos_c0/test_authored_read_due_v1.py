"""Short declared acquisition, projection fault and same-time rollback evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest
from authored_counter_v1 import MAX_INT
from authored_paid_read_v1 import compile_documents, documents, owner, submit
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_runtime_v1 import C0OfferFault


def test_paid_read_keeps_cost_acquisition_and_exact_published_references():
    lib, ports, source, assets = documents()
    session = compile_documents(lib, ports, source).start(assets)
    assert owner(session, "b").budget == 1 and owner(session, "b").acquired is None
    with pytest.raises(C0BindingError, match="current seat offer"):
        submit(session, "seat_b", "read")
    assert isinstance(submit(session, "seat_a", "open"), K0Published)
    action, event = session._runtime.occurrence_history()
    assert isinstance(event.formation_basis, _K0CausalFormation)
    assert event.formation_basis.predecessor == action.occurrence
    assert owner(session, "scene").open_ref == event.occurrence
    assert owner(session, "b").acquired is None
    assert isinstance(submit(session, "seat_b", "read"), K0Published)
    read = session._runtime.occurrence_history()[-1]
    state = owner(session, "b")
    assert state.budget == 0
    assert (state.acquired.content, state.acquired.open_ref, state.acquired.read_ref) == (
        "hidden-a",
        event.occurrence,
        read.occurrence,
    )
    with pytest.raises(C0BindingError, match="current seat offer"):
        submit(session, "seat_b", "read")
    assert len(session._runtime.occurrence_history()) == 3


@pytest.mark.parametrize("balance,cost,admitted", [(0, 1, False), (1, 2, False), (2, 2, True)])
def test_budget_and_authored_cost_are_rechecked_with_zero_write_rejection(balance, cost, admitted):
    lib, ports, source, assets = documents()
    assets["opening"]["actor_b"]["budget"] = balance
    source["lawdefs"][1]["body"]["value"]["bindings"][0]["const"] = cost
    session = compile_documents(lib, ports, source).start(assets)
    submit(session, "seat_a", "open")
    before = session.author_snapshot()
    result = submit(session, "seat_b", "read")
    assert isinstance(result, K0Published if admitted else K0NotAdmitted)
    if admitted:
        assert owner(session, "b").budget == balance - cost
        assert owner(session, "b").acquired.content == "hidden-a"
    else:
        assert session.author_snapshot() == before
        assert session._runtime._fatal is False


def test_paid_read_underflow_rolls_back_after_admission_and_is_fatal():
    lib, ports, source, assets = documents()
    source["lawdefs"][1]["body"]["value"]["guard"]["all"].pop()
    assets["opening"]["actor_b"]["budget"] = 0
    session = compile_documents(lib, ports, source).start(assets)
    submit(session, "seat_a", "open")
    before, cursor = session.author_snapshot(), session._runtime._cursor
    with pytest.raises(K0SettlementDefect):
        submit(session, "seat_b", "read")
    assert session.author_snapshot() == before and session._runtime._cursor == cursor
    assert session._runtime._fatal is True


@pytest.mark.parametrize("balance", [0, 1])
def test_local_read_and_offers_do_not_leak_unread_asset_contents(balance):
    lib, ports, source, assets = documents()
    assets["opening"]["actor_b"]["budget"] = balance
    other = deepcopy(assets)
    other["opening"]["scene"]["content"] = "hidden-b"
    program = compile_documents(lib, ports, source)
    first, second = program.start(assets), program.start(other)
    assert first.read("seat_b") == second.read("seat_b")
    assert first.offers("seat_b") == second.offers("seat_b") == ()
    for session in (first, second):
        submit(session, "seat_a", "open")
    assert first.read("seat_b") == second.read("seat_b")
    assert first.offers("seat_b") == second.offers("seat_b")
    assert "hidden-a" not in repr(first.offers("seat_b"))
    before = (first.author_snapshot(), second.author_snapshot())
    results = [submit(session, "seat_b", "read") for session in (first, second)]
    if balance == 0:
        assert all(isinstance(result, K0NotAdmitted) for result in results)
        assert (first.author_snapshot(), second.author_snapshot()) == before
    else:
        assert all(isinstance(result, K0Published) for result in results)
        assert dict(first.read("seat_b").fields)["actor_b.acquired.content"] == "hidden-a"
        assert dict(second.read("seat_b").fields)["actor_b.acquired.content"] == "hidden-b"
        assert "actor_b.acquired.content" not in dict(first.read("seat_a").fields)


@pytest.mark.parametrize(
    "path", ["scene.content", "actor_a.name", "actor_b.acquired.content.__class__"]
)
def test_seat_read_cannot_expand_into_hidden_or_foreign_authority(path):
    lib, ports, source, _ = documents()
    source["seats"][1]["read"].append(path)
    with pytest.raises(C0LawError):
        compile_documents(lib, ports, source)


def test_scheduled_delivery_still_requires_a_separate_paid_read():
    lib, ports, source, assets = documents(temporal=True)
    session = compile_documents(lib, ports, source).start(assets)
    assert isinstance(submit(session, "seat_a", "open"), K0Published)
    assert owner(session, "scene").mode == "sealed" and session.time == 4
    assert session.offers("seat_b") == ()
    action = session._runtime.occurrence_history()[0]
    assert owner(session, "a").schedule_ref == action.occurrence
    pending = session._runtime._pending_due[0]
    assert pending.key.formation == action.occurrence
    receipt = session.advance("seat_b", 9)
    assert session.time == 6 and len(receipt.occurrences) == 1
    due = receipt.occurrences[0]
    assert due.source.value == "c0.paid.unseal.due"
    assert owner(session, "scene").open_ref == due.occurrence
    assert owner(session, "b").acquired is None
    assert isinstance(submit(session, "seat_b", "read"), K0Published)
    assert owner(session, "b").acquired.open_ref == due.occurrence


def test_same_time_due_reprojects_the_candidate_and_keeps_actual_sources():
    lib, ports, source, assets = documents(temporal=True, two_due=True)
    session = compile_documents(lib, ports, source).start(assets)
    for entry in ("open", "annotate"):
        assert isinstance(submit(session, "seat_a", entry), K0Published)
    actions = session._runtime.occurrence_history()
    receipt = session.advance("seat_b", 9)
    assert session.time == 6 and len(receipt.occurrences) == 2
    assert [item.source.value for item in receipt.occurrences] == [
        "c0.paid.unseal.due",
        "c0.paid.annotate.due",
    ]
    assert [item.formation_basis.key.formation for item in receipt.occurrences] == [
        item.occurrence for item in actions
    ]
    assert owner(session, "scene").mode == "accessible"
    assert owner(session, "scene").content == "annotated"
    assert owner(session, "b").acquired is None
    assert isinstance(submit(session, "seat_b", "read"), K0Published)
    assert owner(session, "b").acquired.content == "annotated"


def test_reversing_same_time_due_rolls_back_time_state_history_pending_and_cursor():
    lib, ports, source, assets = documents(temporal=True, two_due=True)
    source["temporal"]["order"].reverse()
    session = compile_documents(lib, ports, source).start(assets)
    for entry in ("open", "annotate"):
        submit(session, "seat_a", entry)
    before = (session.author_snapshot(), session._runtime._pending_due, session._runtime._cursor)
    with pytest.raises(K0SettlementDefect):
        session.advance("seat_b", 9)
    assert (
        session.author_snapshot(),
        session._runtime._pending_due,
        session._runtime._cursor,
    ) == before
    assert session._runtime._fatal is True


@pytest.mark.parametrize("overflow", [False, True])
def test_duplicate_and_faulty_offers_after_publication_do_not_undo_the_action(overflow):
    lib, ports, source, assets = documents(temporal=True)
    source["game_form"] = {
        "mode": "event_jump_stop",
        "seats": ["seat_a", "seat_b"],
        "end_at": 9,
        "wake_at": [],
    }
    first = source["seats"][0]["offers"][0]
    first["when"] = {"const": True}
    second = deepcopy(first)
    second["label"] = "Second label"
    second["when"] = {"lt": [{"const": 0}, {"ref": "actor.opens"}]}
    if overflow:
        assets["opening"]["actor_a"]["opens"] = MAX_INT - 1
        second["when"] = {
            "lt": [{"add": [{"ref": "actor.opens"}, {"const": 1}]}, {"const": MAX_INT}]
        }
    source["seats"][0]["offers"].append(second)
    session = compile_documents(lib, ports, source).start(assets)
    assert session.form_frame("seat_a").offer_faults == ()
    assert isinstance(submit(session, "seat_a", "open"), K0Published)
    frame = session.form_frame("seat_a")
    assert len(frame.offers) == 1 and frame.offers[0].label == first["label"]
    assert frame.offer_faults == (
        (C0OfferFault("open", "Second label", "value_state"),) if overflow else ()
    )
    assert session.form_frame("seat_b").offer_faults == ()
    assert len(session._runtime.occurrence_history()) == 1 and session._runtime._fatal is False
