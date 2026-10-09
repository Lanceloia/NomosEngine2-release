"""Availability reads only the current Action's explicitly selected participants."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _world
from test_object_action_formation_v1 import _target_world
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.program_runtime_v1 import _ProjectionReads


def _authored():
    lib, ports, source, assets = _world()
    ports["candidate_inputs"] = [
        {
            "symbol": "selected_available",
            "action": "enable",
            "read": ["tool.ready", "victim.enabled"],
            "fields": {},
        }
    ]
    source["seats"][0]["offers"][0]["availability"] = {
        "ref": "selected_available",
        "when": "tool.ready and not victim.enabled",
    }
    return lib, ports, source, assets


def test_current_selected_owners_filter_without_laundering_read_or_writing(monkeypatch):
    lib, ports, source, assets = _authored()
    program = _compile(lib, ports, source)
    layouts = program.world_layout, _layout(program)
    _block_frontend(monkeypatch)
    for layout in layouts:
        opening = deepcopy(assets)
        opening["opening"]["a"]["enabled"] = True
        session = bind_program(program.program_ir, layout).start(opening)
        before = session.author_snapshot()
        history = session._runtime.occurrence_history()
        offers = session.offers("maker")
        assert tuple(row.label for row in offers) == ("Use one on b", "Use two on b")
        assert session.offers("maker") == offers
        assert session.author_snapshot() == before
        assert session._runtime.occurrence_history() == history
        assert tuple(path for path, _ in session.read("maker").fields) == (
            "maker.name",
            "maker.known",
        )
        offer = offers[0]
        assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
        assert not session.offers("maker")
        assert dict(session.author_snapshot().owners)["b"].enabled
        assert [row.current_state.ready for row in session.author_object_instances()] == [
            False,
            True,
        ]


@pytest.mark.parametrize("path", ["victim.known", "tool.missing", "undeclared.enabled"])
def test_condition_requires_the_selected_actions_exact_read_grant(path):
    lib, ports, source, _ = _authored()
    ports["candidate_inputs"][0]["read"].append(path)
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("slot", ["when", "label", "payload"])
def test_private_participant_signal_cannot_be_used_in_public_candidate_fields(slot):
    lib, ports, source, _ = _authored()
    offer = source["seats"][0]["offers"][0]
    if slot == "when":
        offer["when"] = "not victim.enabled"
    elif slot == "label":
        offer["label"] = [{"if": {"when": "victim.enabled", "then": "yes", "else": "no"}}]
    else:
        offer["payload"]["victim"] = {"if": {"when": "victim.enabled", "then": "a", "else": "b"}}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_available_candidate_still_requires_the_real_world_guard():
    lib, ports, source, assets = _authored()
    lib["lawdefs"][0]["body"]["value"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    before = session.author_snapshot()
    history = session._runtime.occurrence_history()
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    assert session._runtime.occurrence_history() == history


def test_independent_bind_rejects_a_removed_participant_read_with_a_retained_condition():
    lib, ports, source, _ = _authored()
    program = _compile(lib, ports, source)
    visibility = program.visibility_ir
    seat = visibility.seats[0]
    check = seat.candidate_checks[0]
    value = check.body.value
    narrowed = replace(
        value.ports,
        readable_paths=value.ports.readable_paths - {"victim.enabled"},
        admission_readable_paths=value.ports.admission_readable_paths - {"victim.enabled"},
    )
    altered = replace(check, body=replace(check.body, value=replace(value, ports=narrowed)))
    seats = (replace(seat, candidate_checks=(altered,)), *visibility.seats[1:])
    ir = replace(program.program_ir, visibility=replace(visibility, seats=seats))
    with pytest.raises(C0LawError, match="exact read authority"):
        bind_program(ir, program.world_layout)


@pytest.mark.parametrize("fault", ["missing", "wrong_type", "extra"])
def test_independent_bind_rechecks_the_participants_nominal_roots(fault):
    lib, ports, source, _ = _authored()
    program = _compile(lib, ports, source)
    visibility = program.visibility_ir
    seat = visibility.seats[0]
    check = seat.candidate_checks[0]
    value = check.body.value
    roots = dict(value.ports.roots)
    if fault == "missing":
        del roots["victim"]
    elif fault == "wrong_type":
        roots["tool"] = roots["victim"]
    else:
        roots["undeclared"] = roots["victim"]
    altered = replace(
        check,
        body=replace(
            check.body, value=replace(value, ports=replace(value.ports, roots=tuple(roots.items())))
        ),
    )
    ir = replace(
        program.program_ir,
        visibility=replace(
            visibility, seats=(replace(seat, candidate_checks=(altered,)), *visibility.seats[1:])
        ),
    )
    with pytest.raises(C0LawError):
        bind_program(ir, program.world_layout)


def test_selected_actor_motion_changes_only_the_explicit_local_signal():
    lib, ports, source, assets = _authored()
    person = next(row for row in lib["records"] if row["name"] == "Person")
    person["fields"].append({"name": "site", "type": {"str": [1, 32]}})
    for actor in assets["opening"].values():
        if "name" in actor:
            actor["site"] = "here"
    action = ports["actions"][0]
    action["value"]["read"].extend(["actor.site", "victim.site"])
    action["value"]["write_paths"].append("victim.site")
    action["effects"]["victim"]["site"] = "destination"
    lib["lawdefs"][0]["body"]["value"]["outputs"]["destination"] = {"const": "away"}
    ports["candidate_inputs"][0]["read"] = ["actor.site", "victim.site", "tool.ready"]
    source["seats"][0]["offers"][0]["availability"]["when"] = (
        "actor.site == victim.site and tool.ready"
    )
    program = _compile(lib, ports, source)
    for layout in (program.world_layout, _layout(program)):
        session = bind_program(program.program_ir, layout).start(assets)
        offers = session.offers("maker")
        assert len(offers) == 4
        assert isinstance(session.submit("maker", "enable", dict(offers[0].payload)), K0Published)
        assert tuple(row.label for row in session.offers("maker")) == ("Use two on b",)
        assert "a.site" not in dict(session.read("maker").fields)
        assert dict(session.author_snapshot().owners)["a"].site == "away"


@pytest.mark.parametrize("fault", ["foreign", "wrong_family", "wrong_member"])
def test_candidate_resolution_and_k0_reject_unbound_selectors_without_write(fault):
    lib, ports, source, assets = _authored()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    values = dict(session.offers("maker")[0].payload)
    if fault == "foreign":
        values["tool"] = program.start(assets).author_object_instances()[0].individual
    elif fault == "wrong_family":
        values["tool"] = replace(values["tool"], family="unselected")
    else:
        values["victim"] = "maker"
    action = dict(program.actions)["enable"]
    payload = action.payload_type(actor="maker", **values)
    reads = _ProjectionReads(session._runtime)
    actor = reads.owner(action.actor_owner.key)
    before = session.author_snapshot()
    assert session._selected_action_roots(action, actor, payload, reads) is None
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload)),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before


def test_single_target_uses_its_current_individual_in_an_independent_binding():
    lib, ports, source, assets = _target_world()
    ports["candidate_inputs"] = [
        {"symbol": "target_ready", "action": "inspect", "read": ["target.ready"], "fields": {}}
    ]
    offer = next(row for row in source["seats"][0]["offers"] if row["entry"] == "inspect")
    offer["when"] = {"const": True}
    offer["availability"] = {"ref": "target_ready", "when": {"ref": "target.ready"}}
    program = _compile(lib, ports, source)
    for layout in (program.world_layout, _layout(program)):
        session = bind_program(program.program_ir, layout).start(assets)
        target_offer = next(row for row in session.offers("sender") if row.entry == "inspect")
        assert isinstance(
            session.submit("sender", "inspect", dict(target_offer.payload)), K0Published
        )
        assert not any(row.entry == "inspect" for row in session.offers("sender"))
