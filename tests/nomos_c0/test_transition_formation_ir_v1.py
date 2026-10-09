"""Transition bodies and formation edges preserve distinct K0 boundaries."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields, replace
from types import SimpleNamespace

import pytest
from authored_counter_v1 import (
    _action_value_inputs,
    _actor_event_inputs,
    _direct_inputs,
    _scene,
    _temporal_inputs,
)
from nomos_kernel import K0OccurrenceFamily, K0OwnerKey, K0ProfileError, K0SourceSpecKey
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_object_action_formation_v1 import _author_world, _compile, _submit

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.composable_value_v1 import C0ValueStateError
from nomos_c0.direct_actor_event_v1 import C0EventTrigger
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.semantic_ir_v0 import (
    C0CausalEdgeIR,
    C0FormationKind,
    C0TransitionIR,
)


def test_all_occurrence_bodies_have_explicit_immutable_formation_policy():
    library, source, _ = _actor_event_inputs()
    program = compile_owner_graph(library, source)
    action = dict(program.actions)["count_0"]
    unseal, observed = dict(program.events).values()
    library, source, _ = _action_value_inputs()
    due = dict(compile_owner_graph(library, source).due_laws)["pulse"]
    for body, kind, false_mode in (
        (action.ir, C0FormationKind.SUBMIT, "not_admitted"),
        (unseal.ir, C0FormationKind.AFTER_OCCURRENCE, "no_event"),
        (observed.ir, C0FormationKind.AFTER_OCCURRENCE, "no_event"),
        (due.ir, C0FormationKind.DUE, "defect"),
    ):
        assert isinstance(body, C0TransitionIR)
        assert body.formation is kind and kind.when_false == false_mode
        with pytest.raises(FrozenInstanceError):
            body.formation = C0FormationKind.SUBMIT
    assert unseal.edge.predecessor == action.occurrence_contract
    assert observed.edge.predecessor == unseal.occurrence_contract
    assert observed.ir.effects == (("actor", "notice", "notice"),)


@pytest.mark.parametrize("target", ("scene", "actor", "due"))
@pytest.mark.parametrize("change", ("source", "classification", "owner", "effects", "formation"))
def test_transition_body_cannot_cross_its_backend_binding(target, change):
    if target == "due":
        library, source, _ = _action_value_inputs()
        selected = dict(compile_owner_graph(library, source).due_laws)["pulse"]
    else:
        library, source, _ = _actor_event_inputs()
        selected = dict(compile_owner_graph(library, source).events)[
            "unseal" if target == "scene" else "observe"
        ]
    edits = {
        "source": {"source_key": "foreign.source"},
        "classification": {"event_type": "foreign.event"},
        "owner": {"owners": (replace(selected.ir.owners[0], key="foreign.owner"),)},
        "effects": {"effects": (("foreign", "name", "foreign_output"),)},
        "formation": {"formation": C0FormationKind.SUBMIT},
    }
    with pytest.raises(C0LawError):
        replace(selected, ir=replace(selected.ir, **edits[change]))


def test_multiple_formation_edges_keep_one_registered_body_and_actual_predecessors():
    library, source, assets = _direct_inputs()
    source["lawdefs"][2]["body"]["law"]["guard"] = {"const": True}
    first = source["events"][0]
    first["shared_result"] = "unseal_result"
    second = json.loads(json.dumps(first))
    second.update(name="from_second", trigger_action="count_1", causal_key="c0.graph.second")
    source["events"].append(second)
    program = compile_owner_graph(library, source)
    left, right = dict(program.events).values()
    assert left.ir == right.ir
    assert left.edge != right.edge
    assert sum(spec.key.value == left.ir.source_key for spec in program.profile.source_specs) == 1
    session = program.start(assets)
    for seat, entry, actor in (
        ("seat_0", "count_0", "person_0"),
        ("seat_1", "count_1", "person_1"),
    ):
        result = session.submit(seat, entry, {"target": actor})
        assert isinstance(result, K0Published)
        action, event = result.occurrences
        assert event.source.value == left.ir.source_key
        assert event.formation_basis.predecessor == action.occurrence
        assert event.semantic_envelope.trigger == action.occurrence
        assert _scene(session).open_ref == event.occurrence


@pytest.mark.parametrize("fault", ("target", "causal_key", "self_trigger"))
def test_causal_edge_cannot_alias_its_body_or_binding(fault):
    library, source, _ = _direct_inputs()
    selected = dict(compile_owner_graph(library, source).events)["unseal"]
    with pytest.raises(C0LawError):
        if fault == "self_trigger":
            C0CausalEdgeIR(
                selected.edge.causal_key, selected.occurrence_contract, selected.ir.source_key
            )
        else:
            replace(
                selected,
                edge=replace(selected.edge, **{fault: "foreign"})
                if fault == "causal_key"
                else replace(selected.edge, target_source="foreign"),
            )


@pytest.mark.parametrize("fault", ("source", "envelope", "participants", "family"))
def test_causal_contract_rejects_foreign_occurrence_before_reading_views(fault):
    library, source, assets = _actor_event_inputs()
    session = compile_owner_graph(library, source).start(assets)
    result = session.submit("seat_0", "count_0", {"target": "person_0"})
    predecessor = result.occurrences[1]
    selected = dict(session.program.events)["observe"]
    assert selected.edge.predecessor.matches(predecessor)
    altered = {
        "source": {"source": K0SourceSpecKey("foreign")},
        "envelope": {"semantic_envelope": predecessor.occurrence},
        "participants": {"participants": "observer"},
        "family": {"family": K0OccurrenceFamily.ACTION},
    }[fault]
    projector = session.program.profile.causal_laws[1].activation_projector
    if fault in {"envelope", "participants"}:
        with pytest.raises(K0ProfileError):
            replace(predecessor, **altered)
    malformed = SimpleNamespace(
        **(
            {field.name: getattr(predecessor, field.name) for field in fields(predecessor)}
            | altered
        )
    )
    assert projector.project(malformed, ()) == ()
    assert not selected.edge.predecessor.matches(SimpleNamespace(source="malformed"))


def test_false_causal_formation_publishes_no_event_and_formed_false_is_a_defect():
    library, source, assets = _direct_inputs()
    source["lawdefs"][2]["body"]["law"]["guard"] = {"const": False}
    program = compile_owner_graph(library, source)
    event = dict(program.events)["unseal"]
    session = program.start(assets)
    result = session.submit("seat_0", "count_0", {"target": "person_0"})
    assert isinstance(result, K0Published)
    roots = {"scene": _scene(session), "trigger": C0EventTrigger(result.occurrences[0].occurrence)}
    assert event.ir.condition(roots) is False
    with pytest.raises(C0ValueStateError):
        event.ir.condition(roots, formed=True)
    assert len(session._runtime.occurrence_history()) == 1
    assert _scene(session).open_ref is None


def test_causal_chain_consumes_checked_ir_not_mutated_text_or_runtime_parser(monkeypatch):
    library, source, assets = _actor_event_inputs()
    session = compile_owner_graph(library, source).start(assets)
    source["lawdefs"][2]["body"]["law"]["guard"] = {"const": False}

    def forbidden(*args, **kwargs):
        raise AssertionError("Run must not parse author text")

    monkeypatch.setattr(json, "loads", forbidden)
    result = session.submit("seat_0", "count_0", {"target": "person_0"})
    assert isinstance(result, K0Published)
    action, unseal, observed = result.occurrences
    assert observed.formation_basis.predecessor == unseal.occurrence
    assert unseal.formation_basis.predecessor == action.occurrence
    notice = session._runtime.read_owner(K0OwnerKey("c0.graph.observer")).view.notice
    assert (notice.arrival, notice.perception) == (unseal.occurrence, observed.occurrence)


@pytest.mark.parametrize("fault", ("source", "marker", "subject", "delay", "missing_marker"))
def test_schedule_checked_ir_and_backend_must_agree(fault):
    library, source, _ = _temporal_inputs()
    action = dict(compile_owner_graph(library, source).actions)["open"]
    schedule = action.ir.schedule
    assert schedule is not None and action.schedule is schedule
    edits = {
        "source": {"due_source": "foreign.due"},
        "marker": {"marker_output": "action"},
        "subject": {"subject_output": "foreign_output"},
        "delay": {"delay_output": "foreign_output"},
    }
    with pytest.raises(C0LawError):
        if fault == "missing_marker":
            replace(action, ir=replace(action.ir, effects=()))
        else:
            replace(action, ir=replace(action.ir, schedule=replace(schedule, **edits[fault])))


def test_well_typed_schedule_marker_must_still_be_the_exact_own_occurrence_node():
    library, source, _ = _temporal_inputs()
    source["lawdefs"][0]["body"]["value"]["outputs"]["schedule_ref"] = {
        "if": {
            "when": {"const": True},
            "then": {"ref": "occurrence"},
            "else": {"ref": "occurrence"},
        }
    }
    with pytest.raises(C0LawError, match="one-shot marker"):
        compile_owner_graph(library, source)


def test_schedule_and_object_formation_are_checked_effects_of_the_same_action():
    lib, ports, source, assets = _author_world()
    program = _compile(lib, ports, source)
    action = dict(program.actions)["dispatch"]
    assert action.form is action.ir.form and action.schedule is action.ir.schedule
    for edits in ({"family": "foreign.family"}, {"state_type": str}, {"initial_output": "action"}):
        with pytest.raises(C0LawError):
            replace(action, ir=replace(action.ir, form=replace(action.form, **edits)))
    session = program.start(assets)
    result = _submit(session, "dispatch")
    assert isinstance(result, K0Published)
    occurrence = result.occurrences[0].occurrence
    assert session.author_object_instances()[1].formed_by == occurrence
    pending = session._runtime._pending_due[0]
    assert pending.key.formation == occurrence
    assert pending.source.value == action.ir.schedule.due_source


def test_false_submit_and_false_required_due_still_have_different_failure_classes():
    library, source, assets = _direct_inputs()
    source["lawdefs"][0]["body"]["value"]["guard"] = {"const": False}
    session = compile_owner_graph(library, source).start(assets)
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_0", "count_0", {"target": "person_0"}), K0NotAdmitted)
    assert session.author_snapshot() == before
    library, source, assets = _action_value_inputs()
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = {"const": False}
    source["lawdefs"][-1]["body"]["law"]["guard"] = {"const": False}
    session = compile_owner_graph(library, source).start(assets)
    before = session._runtime.occurrence_history()
    with pytest.raises(K0SettlementDefect):
        session.continue_form("seat_0")
    assert session.time == 0 and session._runtime.occurrence_history() == before
    with pytest.raises(K0SettlementDefect):
        session.continue_form("seat_0")
