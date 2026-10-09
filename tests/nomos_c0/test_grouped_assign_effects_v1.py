"""Grouped assignments use checked endpoints and one pre-state, never microsteps."""

from __future__ import annotations

from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect
from nomos_kernel._settlement_outcome_abi import K0Published
from test_multi_participant_action_v0 import _compile as compile_world
from test_multi_participant_action_v0 import _world
from test_value_effect_ir_v0 import Supply, _compile, _ports

from nomos_c0 import C0LawError
from nomos_c0.composable_value_v1 import C0ValueRangeError


def _source(when="selected"):
    return {
        "schema": "c0.value.v1",
        "bindings": [{"name": "selected", "stage": "effect", "let": "supply.cost == 1"}],
        "guard": True,
        "effects": [
            {
                "exchange": {
                    "when": when,
                    "assign": {
                        "supply.stock": "supply.mirrored",
                        "supply.mirrored": "supply.stock",
                    },
                }
            }
        ],
        "outputs": {"action": {"ref": "occurrence"}},
    }


@pytest.mark.parametrize("cost,expected", [(1, (9, 3)), (0, (3, 9))])
def test_true_updates_all_fields_false_keeps_each_and_still_publishes_output(cost, expected):
    program = _compile(_source())
    roots = {"supply": Supply(3, 9, cost=cost)}
    assert program.admits(roots)
    result = program.evaluate(roots, occurrence=K0OccurrenceRef(7))
    assert (result["stock"], result["mirrored"]) == expected
    assert result["action"] == K0OccurrenceRef(7)
    assert roots["supply"].stock == 3
    effect = program.effects[0]
    assert effect.checks is None
    assert effect.activation is dict(effect.results)[effect.writes[0][1]]["if"]["when"]
    assert dict(effect.results)["mirrored"] is program._tree["outputs"]["mirrored"]


def test_unconditional_swap_reads_pre_state_and_does_not_require_preservation_read():
    source = _source()
    del source["effects"][0]["exchange"]["when"]
    program = _compile(source)
    result = program.evaluate({"supply": Supply(3, 9, cost=0)}, occurrence=K0OccurrenceRef(7))
    assert (result["stock"], result["mirrored"]) == (9, 3)
    source["effects"][0]["exchange"]["assign"]["supply.mirrored"] = 1
    source["effects"][0]["exchange"]["assign"]["supply.stock"] = 2
    source["bindings"] = []
    ports = _ports()
    program = _compile(
        source,
        replace(
            ports,
            readable_paths=frozenset(),
            readable_fields={},
            admission_readable_paths=frozenset(),
            admission_readable_fields={},
        ),
    )
    assert program.evaluate({"supply": Supply(3, 9)}, occurrence=K0OccurrenceRef(7))["stock"] == 2


def test_inactive_unsafe_branch_is_not_evaluated_or_promoted_into_admission():
    source = _source(False)
    source["effects"][0]["exchange"]["assign"]["supply.stock"] = {"ceil_div": [1, 0]}
    program = _compile(source)
    roots = {"supply": Supply(3, 9)}
    assert program.admits(roots)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(7))["stock"] == 3
    source["effects"][0]["exchange"]["when"] = True
    program = _compile(source)
    assert program.admits(roots)
    with pytest.raises(C0ValueRangeError):
        program.evaluate(roots, occurrence=K0OccurrenceRef(7))


def test_independent_group_conditions_and_resource_checks_share_one_pre_state():
    source = _source()
    source["effects"] = [
        {"mark": {"when": "supply.stock == 3", "assign": {"supply.mirrored": "supply.stock"}}},
        {"spend": {"debit": "supply.stock", "amount": 1, "floor": 0}},
    ]
    program = _compile(source)
    assert program.effects[0].checks is None
    assert program.effects[1].checks is program.guard_ir.expression["all"][1]["all"][0]
    result = program.evaluate({"supply": Supply(3, 9)}, occurrence=K0OccurrenceRef(7))
    assert (result["stock"], result["mirrored"]) == (2, 3)
    assert program.evaluate({"supply": Supply(0, 9)}, occurrence=K0OccurrenceRef(7)) is None
    assert (
        program.false_guard_clauses({"supply": Supply(0, 9)})[0].path == "effects.spend.sufficient"
    )


def test_two_groups_activate_independently_without_reading_each_others_results():
    source = _source()
    source["effects"] = [
        {"first": {"when": "selected", "assign": {"supply.stock": 7}}},
        {"second": {"when": "supply.stock == 3", "assign": {"supply.mirrored": "supply.stock"}}},
    ]
    program = _compile(source)
    active = program.evaluate({"supply": Supply(3, 9)}, occurrence=K0OccurrenceRef(7))
    inactive = program.evaluate({"supply": Supply(3, 9, cost=0)}, occurrence=K0OccurrenceRef(7))
    assert (active["stock"], active["mirrored"]) == (7, 3)
    assert (inactive["stock"], inactive["mirrored"]) == (3, 3)


def test_nullable_assignment_uses_the_same_branch_proofs_as_regular_outputs():
    source = _source("supply.known is not None")
    source["effects"][0]["exchange"]["assign"] = {
        "supply.known": {"sub": ["supply.known", 1]},
        "supply.mirrored": 4,
    }
    ports = replace(
        _ports(), outputs={"stock": int | None, "mirrored": int, "action": K0OccurrenceRef}
    )
    program = _compile(source, ports, {"supply.known": "stock", "supply.mirrored": "mirrored"})
    assert (
        program.evaluate({"supply": Supply(3, 9)}, occurrence=K0OccurrenceRef(7))["stock"] is None
    )
    assert (
        program.evaluate({"supply": Supply(3, 9, known=2)}, occurrence=K0OccurrenceRef(7))["stock"]
        == 1
    )
    source["effects"][0]["exchange"]["when"] = True
    with pytest.raises(C0LawError):
        _compile(source, ports, {"supply.known": "stock", "supply.mirrored": "mirrored"})


@pytest.mark.parametrize(
    "fault",
    ["endpoint", "read", "write", "condition", "type", "output", "group", "resource", "admission"],
)
def test_assign_cannot_bypass_permissions_types_overlap_or_stage(fault):
    source, ports, mapping = _source(), _ports(), None
    body = source["effects"][0]["exchange"]
    if fault == "endpoint":
        body["assign"]["supply.secret"] = 1
    elif fault == "read":
        ports = replace(
            ports,
            readable_paths=ports.readable_paths - {"supply.stock"},
            admission_readable_paths=ports.admission_readable_paths - {"supply.stock"},
        )
        body["assign"]["supply.mirrored"] = 1
    elif fault == "write":
        ports = replace(ports, writable_fields={Supply: frozenset({"mirrored"})})
    elif fault == "condition":
        body["when"] = 1
    elif fault == "type":
        body["assign"]["supply.stock"] = True
    elif fault == "output":
        source["outputs"]["stock"] = 1
    elif fault == "group":
        source["effects"].append({"another": {"assign": {"supply.stock": 1}}})
    elif fault == "resource":
        source["effects"].append({"spend": {"debit": "supply.stock", "amount": 1, "floor": 0}})
    else:
        source["guard"] = "selected"
    with pytest.raises(C0LawError):
        _compile(source, ports, mapping)


@pytest.mark.parametrize(
    "body", [{"assign": {}}, {"assign": []}, {"assign": {"supply.stock": 1}, "mirror": []}]
)
def test_malformed_assignment_has_a_finite_author_error(body):
    source = _source()
    source["effects"] = [{"exchange": body}]
    with pytest.raises(C0LawError):
        _compile(source)


def _assignment_world(fault=False):
    lib, ports, source, assets = _world()
    value = lib["lawdefs"][0]["body"]["value"]
    for name in ("ready", "enabled"):
        del value["outputs"][name]
    value["effects"] = [
        {"enable": {"when": True, "assign": {"tool.ready": False, "victim.enabled": True}}}
    ]
    if fault:
        next(item for item in lib["records"] if item["name"] == "Person")["invariant"] = (
            "not state.enabled"
        )
    return compile_world(lib, ports, source).start(assets)


def test_assignment_visibility_and_effect_ir_rebind_without_frontend(monkeypatch):
    from test_world_binding_v1 import _forbid_checks, _layout

    from nomos_c0.program_binding_v1 import bind_program

    original = _assignment_world().program
    layout = _layout(original)
    _forbid_checks(monkeypatch)
    rebound = bind_program(original.program_ir, layout)
    effect = dict(rebound.actions)["enable"].value.effects[0]
    assert effect.checks is None and effect.activation.stage == "effect"
    session = rebound.start(_world()[3])
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert dict(session.author_snapshot().owners)["a"].enabled


def test_actual_k0_action_publishes_multi_owner_assignment():
    session = _assignment_world()
    offer = session.offers("maker")[0]
    result = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert dict(session.author_snapshot().owners)["a"].enabled
    assert not session.author_object_instances()[0].current_state.ready
    assert result.occurrences[0].source == dict(session.program.actions)["enable"].source_key


def test_failed_owner_invariant_rolls_back_all_assignment_outputs_and_history():
    session = _assignment_world(True)
    offer = session.offers("maker")[0]
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    with pytest.raises(K0SettlementDefect):
        session.submit("maker", offer.entry, dict(offer.payload))
    assert session.author_snapshot() == before
    assert session._runtime.occurrence_history() == history
    with pytest.raises(K0SettlementDefect):
        session.submit("maker", offer.entry, dict(offer.payload))
