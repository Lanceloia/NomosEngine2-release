"""Authored stops bind once to K0; Run never judges them a second time."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _value, action_value_documents
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from nomos_kernel._terminal_settlement_abi import _K0SessionClosed
from test_control_binding_v1 import _inputs
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.composable_value_v1 import C0ValueProgram
from nomos_c0.control_binding_v1 import bind_control
from nomos_c0.world_binding_v1 import bind_world


def _stop(source, when, *, owners=("scene",), outcome="stopped"):
    source["game_form"]["world_stops"] = [
        {"outcome": outcome, "owners": list(owners), "when": when},
    ]


def _dispatch(session):
    offer = session.form_frame("sender").offers[0]
    return session.submit("sender", offer.entry, dict(offer.payload))


def test_action_stop_waits_for_full_closure_and_has_one_k0_authority(monkeypatch):
    lib, ports, source, assets = _inputs()
    _stop(source, {"eq": [{"ref": "scene.parcel.status"}, {"const": "transit"}]})
    program = _compile(lib, ports, source)
    session = program.start(assets)
    result = _dispatch(session)
    assert isinstance(result, K0Published) and len(result.occurrences) == 4
    owners = dict(session.author_snapshot().owners)
    assert owners["scene"].signal == "manifested"
    assert owners["receiver"].notice is not None
    terminal = session._runtime.terminal_state()
    assert terminal.trigger == result.occurrences[0].occurrence
    assert terminal.checkpoint == "action" and terminal.time.ordinal == 0
    assert len(terminal.not_reached) == 1
    assert program.game_form.world_stops == ()
    before = (session.author_snapshot(), session._runtime.occurrence_history())

    original = C0ValueProgram.admits
    predicate = program.profile.terminal_policy.clauses[0].projector.value

    def forbidden(self, *args, **kwargs):
        if self is predicate:
            raise AssertionError("C0 must not recompute a published terminal predicate")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(C0ValueProgram, "admits", forbidden)
    assert session.form_frame("sender").outcome == "stopped"
    assert session.form_frame("receiver").finished
    assert session.form_frame("sender").offers == ()
    assert isinstance(session._runtime.settle(object()), _K0SessionClosed)
    assert isinstance(session._runtime.continue_action_value(), _K0SessionClosed)
    assert (session.author_snapshot(), session._runtime.occurrence_history()) == before


def test_due_stop_is_published_before_next_seat_opportunity():
    lib, ports, source, assets = _inputs()
    _stop(source, {"eq": [{"ref": "scene.parcel.status"}, {"const": "arrived"}]})
    session = _compile(lib, ports, source).start(assets)
    _dispatch(session)
    frame = session.continue_form("sender")
    assert frame.finished and frame.outcome == "stopped" and frame.time == 2
    terminal = session._runtime.terminal_state()
    assert terminal.checkpoint == "due"
    assert terminal.trigger == session._runtime.occurrence_history()[-1].occurrence
    assert session._runtime.action_opportunity() is None
    assert session.appraisal_history() == ()
    assert session._runtime.action_value_history()[-1].at.ordinal == 2


def test_opening_stop_has_no_occurrence_and_still_validates_assets():
    lib, ports, source, assets = _inputs()
    _stop(source, {"const": True})
    program = _compile(lib, ports, source)
    session = program.start(assets)
    assert session.form_frame("sender").finished
    assert session._runtime.terminal_state().trigger is None
    assert session._runtime.occurrence_history() == ()
    assert session._runtime.action_value_history() == ()
    assets["opening"]["sender"]["sent_ref"] = 1
    with pytest.raises(C0BindingError, match="occurrence"):
        program.start(assets)


def test_clause_priority_is_authored_order_not_owner_order():
    lib, ports, source, assets = _inputs()
    _stop(source, {"const": True}, outcome="first")
    source["game_form"]["world_stops"].append(
        {"outcome": "second", "owners": ["sender"], "when": {"const": True}}
    )
    assert _compile(lib, ports, source).start(assets).form_frame("sender").outcome == "first"
    source["game_form"]["world_stops"].reverse()
    assert _compile(lib, ports, source).start(assets).form_frame("sender").outcome == "second"


def test_terminal_guard_cannot_draw_random_or_allocate_occurrence():
    lib, ports, source, _ = _inputs()
    for value in ({"die_roll": {"seed": 7, "sides": 6}}, {"ref": "occurrence"}):
        _stop(source, {"eq": [value, 1]})
        with pytest.raises(C0LawError, match="admission"):
            _compile(lib, ports, source)


def test_bind_rejects_terminal_effect_and_foreign_root_ports():
    lib, ports, source, _ = _inputs()
    program = _compile(lib, ports, source)
    stop = program.control_ir.world_stops[0]
    value = stop.predicate.value
    for changed in (
        replace(value.ports, writable_fields=((value.ports.roots[0][1], frozenset({"receipt"})),)),
        replace(value.ports, admission_readable_paths=frozenset()),
    ):
        predicate = replace(stop.predicate, value=replace(value, ports=changed))
        ir = replace(program.control_ir, world_stops=(replace(stop, predicate=predicate),))
        with pytest.raises(C0LawError):
            bind_control(ir, bind_world(program.world_ir, program.world_layout))


def test_terminal_predicate_fault_rolls_back_complete_action_closure():
    lib, ports, source, assets = _inputs()
    _stop(
        source,
        {
            "all": [
                {"not_none": {"ref": "sender.sent_ref"}},
                {
                    "eq": [
                        {
                            "ceil_div": [
                                1,
                                {
                                    "count_matching": {
                                        "collection": "scene.routes",
                                        "as": "route",
                                        "where": {"const": False},
                                    }
                                },
                            ]
                        },
                        1,
                    ]
                },
            ]
        },
        owners=("scene", "sender"),
    )
    session = _compile(lib, ports, source).start(assets)
    offer = session.form_frame("sender").offers[0]
    action = dict(session.program.actions)[offer.entry]
    before = (
        session.author_snapshot(),
        session._runtime.occurrence_history(),
        session._runtime.action_value_history(),
    )
    with pytest.raises(K0SettlementDefect):
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key, action.payload_type(actor="Mira", **dict(offer.payload))
            )
        )
    assert (
        session.author_snapshot(),
        session._runtime.occurrence_history(),
        session._runtime.action_value_history(),
    ) == before
    assert session._runtime.terminal_state() is None and session._runtime._fatal


@pytest.mark.parametrize("stop", [True, False])
def test_authored_same_time_dues_keep_whole_child_closure_and_cut_only_suffix(stop):
    lib, ports, source, assets = action_value_documents()
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = False
    ports["events"].append(
        {
            "symbol": "mark",
            "form": "direct_actor",
            "actor": "actor_0",
            "actor_identity_field": "name",
            "value": _value(["actor.count"], ["actor.count"], {"count": "actor.count"}),
        }
    )
    source["lawdefs"].append(
        {
            "name": "mark",
            "family": "direct_actor_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"count": {"add": [{"ref": "actor.count"}, 1]}},
                }
            },
        }
    )
    source["events"].append(
        {
            "name": "mark",
            "template": "mark",
            "actor": "actor_0",
            "trigger_event": "pulse",
            "source_key": "c0.terminal.mark",
            "event_type": "c0.terminal.mark.event",
            "causal_key": "c0.terminal.mark.law",
            "law": {"ref": "mark", "args": {}},
        }
    )
    suffix = deepcopy(source["lawdefs"][1])
    suffix["name"] = "suffix"
    suffix["body"]["law"]["outputs"]["signal"] = "'suffix'"
    source["lawdefs"].append(suffix)
    suffix = deepcopy(source["due_events"][0])
    suffix.update(
        name="suffix",
        law={"ref": "suffix", "args": {}},
        source_key="c0.terminal.suffix",
        event_type="c0.terminal.suffix.event",
    )
    source["due_events"].append(suffix)
    source["temporal"]["order"].append("suffix")
    source["temporal"]["max_pending"] = 2
    source["temporal"]["periodic"].append(
        {
            "name": "suffix_clock",
            "due": "suffix",
            "interval": 5,
            "max_occurrences": 1,
            "subject": "clock",
        }
    )
    assets["periodic_due_openings"].append({"plan": "suffix_clock", "first_at": 5})
    _stop(source, {"eq": [{"ref": "actor_0.count"}, 1]} if stop else False, owners=("actor_0",))
    session = _compile(lib, ports, source).start(assets)
    frame = session.continue_form("seat_0")
    history = session._runtime.occurrence_history()
    assert [row.source.value for row in history] == [
        "c0.graph.pulse",
        "c0.terminal.mark",
        *([] if stop else ["c0.terminal.suffix"]),
    ]
    assert dict(session.author_snapshot().owners)["actor_0"].count == 1
    assert dict(session.author_snapshot().owners)["scene"].signal == ("pulse" if stop else "suffix")
    assert frame.outcome == ("stopped" if stop else None)
    if stop:
        terminal = session._runtime.terminal_state()
        assert len(terminal.not_reached) == 1
        assert len(terminal.closed_plans) == 2
        assert terminal.closed_plans[0].last_occurrence == history[0].occurrence
        assert terminal.closed_plans[1].last_occurrence is None
        assert frame.time == 5 and frame.finished
