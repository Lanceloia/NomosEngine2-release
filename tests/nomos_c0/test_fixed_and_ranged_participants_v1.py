"""One ranged Object, one singleton resource and a local Actor candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_multi_participant_action_v0 import _compile, _owners, _world
from test_world_binding_v1 import _layout

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.visibility_binding_v1 import bind_visibility
from nomos_c0.world_binding_v1 import bind_world


def _resource_world():
    lib, ports, source, assets = deepcopy(_world())
    lib["records"].append(
        {
            "name": "Resource",
            "fields": [{"name": "units", "type": {"int": [0, 5]}}],
            "invariant": None,
        }
    )
    lib["records"][4]["fields"].append({"name": "resource", "type": "individual_ref"})
    lib["object_kinds"].append(
        {
            "symbol": "resource",
            "sort": "EXAMPLE.RESOURCE@1",
            "state": "Resource",
            "version": "resource-v1",
            "max_instances": 1,
        }
    )
    body = lib["lawdefs"][0]["body"]["value"]
    body["guard"]["all"].append({"lt": [{"const": 0}, {"ref": "resource.units"}]})
    body["outputs"]["units"] = {"sub": [{"ref": "resource.units"}, {"const": 1}]}
    action = ports["actions"][0]
    action["participants"].append(
        {
            "name": "resource",
            "selector": "individual",
            "state": "Resource",
            "payload_field": "resource",
            "write": True,
        }
    )
    action["participants"].sort(key=lambda item: item["name"])
    action["effects"]["resource"] = {"units": "units"}
    action["value"]["read"].append("resource.units")
    action["value"]["write_paths"].append("resource.units")
    source["object_kinds"].append({"kind": "resource", "sort": "EXAMPLE.RESOURCE@1"})
    source["actions"][0]["participants"]["resource"] = {"kind": "resource"}
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["resource"] = {
        "fixed_kind": "resource",
        "read": ["resource.units"],
    }
    offer["payload"]["resource"] = {"ref": "resource_ref"}
    assets["opening_objects"].append({"kind": "resource", "state": {"units": 2}})
    return lib, ports, source, assets


def test_ranged_objects_bind_the_same_singleton_resource_atomically():
    lib, ports, source, assets = _resource_world()
    session = _compile(lib, ports, source).start(assets)
    offers = session.offers("maker")
    assert [item.label for item in offers] == [
        "Use one on a",
        "Use one on b",
        "Use two on a",
        "Use two on b",
    ]
    first, second = offers[0], offers[-1]
    assert dict(first.payload)["resource"] == dict(second.payload)["resource"]
    assert dict(first.payload)["tool"] != dict(second.payload)["tool"]
    assert isinstance(session.submit("maker", first.entry, dict(first.payload)), K0Published)
    states = session.author_object_instances()
    assert [item.current_state.ready for item in states if item.individual.family == "tool"] == [
        False,
        True,
    ]
    assert (
        next(item.current_state.units for item in states if item.individual.family == "resource")
        == 1
    )
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_empty_resource_has_no_partial_effect(missing):
    lib, ports, source, assets = _resource_world()
    if missing:
        assets["opening_objects"].pop()
    else:
        assets["opening_objects"][-1]["state"]["units"] = 0
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    if missing:
        assert session.offers("maker") == ()
        with pytest.raises(C0BindingError, match="current seat offer"):
            session.submit("maker", "enable", {})
    else:
        offer = session.offers("maker")[0]
        assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


@pytest.mark.parametrize("fault", ["foreign", "wrong_family", "stale"])
def test_invalid_participant_attempt_is_rejected_without_any_write(fault):
    lib, ports, source, assets = _resource_world()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    offer = session.offers("maker")[0]
    values = dict(offer.payload)
    if fault == "foreign":
        foreign = program.start(assets)
        values["resource"] = dict(foreign.offers("maker")[0].payload)["resource"]
    elif fault == "wrong_family":
        values["resource"] = values["tool"]
    else:
        assert isinstance(session.submit("maker", offer.entry, values), K0Published)
    action = dict(program.actions)[offer.entry]
    before = session.author_snapshot()
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="maker", **values))
    )
    assert isinstance(result, K0NotAdmitted)
    assert session.author_snapshot() == before


def test_downstream_invariant_failure_rolls_back_resource_object_and_actor():
    lib, ports, source, assets = _resource_world()
    lib["records"][1]["invariant"] = {"not": {"ref": "state.enabled"}}
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    before = session.author_snapshot()
    objects = session.author_object_instances()
    with pytest.raises(K0SettlementDefect):
        session.submit("maker", offer.entry, dict(offer.payload))
    assert session.author_object_instances() == objects
    assert session.author_snapshot().owners == before.owners
    assert session._runtime.occurrence_history() == before.occurrences


@pytest.mark.parametrize("fault", ["non_singleton", "wrong_kind", "wrong_ref", "undeclared_read"])
def test_compile_rejects_fixed_object_domain_or_read_escape(fault):
    lib, ports, source, _ = _resource_world()
    offer = source["seats"][0]["offers"][0]
    if fault == "non_singleton":
        lib["object_kinds"][-1]["max_instances"] = 2
    elif fault == "wrong_kind":
        offer["for_each_participants"]["resource"]["fixed_kind"] = "tool"
    elif fault == "wrong_ref":
        offer["payload"]["resource"] = {"ref": "tool_ref"}
    else:
        offer["for_each_participants"]["resource"]["read"] = ["resource.secret"]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_fixed_read_subset_and_instances_survive_new_layout_binding():
    lib, ports, source, assets = _resource_world()
    source["seats"][0]["offers"][0]["for_each_participants"]["resource"]["read"] = []
    program = _compile(lib, ports, source)
    rebound = bind_program(program.program_ir, _layout(program))
    declaration = rebound.seats[0].offers[0]
    assert "resource.units" not in declaration.ports.readable_paths
    assert "resource.units" in dict(rebound.actions)["enable"].value._ports.readable_paths
    session = rebound.start(assets)
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)


@pytest.mark.parametrize(
    "fault", ["wrong_family", "read_escape", "wrong_payload", "ranged_object", "ranged_actor"]
)
def test_visibility_ir_cannot_expand_fixed_participant_authority(fault):
    lib, ports, source, _ = _resource_world()
    program = _compile(lib, ports, source)
    ir = program.visibility_ir
    seat = ir.seats[0]
    offer = seat.offers[0]
    values = dict(offer.parameters)
    if fault == "wrong_family":
        values["objects"] = tuple(
            replace(role, kinds=("tool",)) if role.name == "resource" else role
            for role in values["objects"]
        )
    elif fault == "read_escape":
        values["objects"] = tuple(
            replace(role, read_paths=("resource.secret",)) if role.name == "resource" else role
            for role in values["objects"]
        )
    elif fault == "wrong_payload":
        values["payload"] = {
            **values["payload"],
            "resource": replace(values["payload"]["resource"], operand="tool_ref"),
        }
    elif fault == "ranged_object":
        values["payload"] = {
            **values["payload"],
            "tool": replace(values["payload"]["tool"], operand="resource_ref"),
        }
    else:
        values["payload"] = {
            **values["payload"],
            "victim": replace(values["payload"]["victim"], operation="const", operand="b"),
        }
    changed = replace(offer, parameters=tuple((key, values[key]) for key, _ in offer.parameters))
    forged = replace(ir, seats=(replace(seat, offers=(changed,)),))
    world = bind_world(program.world_ir, program.world_layout)
    with pytest.raises(C0LawError):
        bind_visibility(forged, world)
