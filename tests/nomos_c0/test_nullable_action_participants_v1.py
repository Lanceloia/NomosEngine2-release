"""Nullable closed roles retain declaration checks and omit absent runtime authority."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_multi_participant_action_v0 import _compile, _owners, _world

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.world_binding_v1 import bind_world


def _nullable_world():
    lib, ports, source, assets = _world()
    field = lib["records"][4]["fields"][-1]
    field["type"] = {"optional": field["type"]}
    ports["actions"][0]["participants"][-1]["nullable"] = True
    ports["actions"][0]["value"]["read"].append("victim")
    guard = lib["lawdefs"][0]["body"]["value"]["guard"]["all"]
    guard[-1] = {
        "any": [
            {"is_none": {"ref": "victim"}},
            {"all": [{"not_none": {"ref": "victim"}}, {"not": {"ref": "victim.enabled"}}]},
        ]
    }
    return lib, ports, source, assets


@pytest.mark.parametrize("victim", [None, "a", "b"])
def test_same_compiled_action_omits_or_updates_the_exact_closed_role(victim):
    lib, ports, source, assets = _nullable_world()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    action = dict(program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, victim))
    )
    assert isinstance(result, K0Published)
    assert _owners(session)["a"].enabled is (victim == "a")
    assert _owners(session)["b"].enabled is (victim == "b")
    assert session.author_object_instances()[0].current_state.ready is False
    selected = result.occurrences[0].selected_owners
    assert [item.name for item in selected] == (["tool"] if victim is None else ["tool", "victim"])
    assert action.ir.selected[-1].nullable is True
    assert program.world_ir.transitions[0].action.selected[-1].nullable is True


def test_optional_role_and_typed_roots_survive_independent_world_binding():
    lib, ports, source, _ = _nullable_world()
    program = _compile(lib, ports, source)
    rebound = bind_world(program.world_ir, program.world_layout)
    action = dict(rebound.actions)["enable"]
    assert action.ports.value_ports.roots["victim"] == action.participants[-1].state_type | None
    assert action.build_spec().participant_ports[-1].nullable is True


def test_existing_nonnull_public_offer_submits_through_same_nullable_action():
    lib, ports, source, assets = _nullable_world()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    assert dict(offer.payload)["victim"] == "a"
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False


def test_absent_candidate_root_does_not_read_any_closed_member():
    lib, ports, source, assets = _nullable_world()
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0]
    owners = _owners(session)

    class Reads:
        def owner(self, key):
            assert key == action.scene_owner.key
            return owners["scene"]

        def individual(self, ref):
            assert ref == tool.individual
            return tool.current_state

    payload = action.payload_type("maker", tool.individual, None)
    roots = session._selected_action_roots(action, owners["maker"], payload, Reads())
    assert roots["victim"] is None
    assert action.ir.condition(roots) is True


@pytest.mark.parametrize("victim", [None, "a"])
def test_nullable_participant_need_not_share_the_initiator_nominal_carrier(victim):
    lib, ports, source, assets = _nullable_world()
    passenger = deepcopy(lib["records"][1])
    passenger["name"] = "Passenger"
    lib["records"].append(passenger)
    for owner in lib["owners"]:
        if owner["symbol"] in ("a", "b"):
            owner["state"] = "Passenger"
    ports["actions"][0]["participants"][-1]["state"] = "Passenger"
    session = _compile(lib, ports, source).start(assets)
    assert type(_owners(session)["maker"]) is not type(_owners(session)["a"])
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, victim))
    )
    assert isinstance(result, K0Published)
    assert _owners(session)["a"].enabled is (victim == "a")
    assert _owners(session)["b"].enabled is False


def test_absent_middle_role_does_not_shift_a_later_required_role():
    lib, ports, source, assets = _nullable_world()
    lib["records"][4]["fields"].append({"name": "witness", "type": {"str": [1, 32]}})
    action_ports = ports["actions"][0]
    action_ports["participants"].append(
        {
            "name": "witness",
            "selector": "closed_domain",
            "state": "Person",
            "payload_field": "witness",
            "write": False,
        }
    )
    action_ports["effects"]["witness"] = {}
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    source["actions"][0]["participants"]["witness"] = {"actors": ["b"]}
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["witness"] = {"fixed_actor": "b"}
    offer["payload"]["witness"] = {"const": "b"}
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, None, "b"))
    )
    assert isinstance(result, K0Published)
    assert [item.name for item in result.occurrences[0].selected_owners] == ["tool", "witness"]
    assert _owners(session)["a"].enabled is False
    assert _owners(session)["b"].enabled is False


@pytest.mark.parametrize("fault", ["required", "object", "malformed", "unguarded", "write"])
def test_compile_checks_optional_type_permissions_and_proofs_even_when_absent(fault):
    lib, ports, source, _ = _nullable_world()
    action = ports["actions"][0]
    if fault == "required":
        action["participants"][-1]["nullable"] = False
    elif fault == "object":
        action["participants"][0]["nullable"] = True
    elif fault == "malformed":
        action["participants"][-1]["nullable"] = 1
    elif fault == "unguarded":
        lib["lawdefs"][0]["body"]["value"]["guard"]["all"][-1] = {"ref": "victim.enabled"}
    else:
        action["participants"][-1]["write"] = False
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("nullable", [False, 1])
def test_independent_bind_rejects_tampered_nullability(nullable):
    lib, ports, source, _ = _nullable_world()
    program = _compile(lib, ports, source)
    transition = program.world_ir.transitions[0]
    selected = transition.action.selected
    changed = replace(
        transition.action, selected=(*selected[:-1], replace(selected[-1], nullable=nullable))
    )
    world = replace(program.world_ir, transitions=(replace(transition, action=changed),))
    with pytest.raises(C0LawError):
        bind_world(world, program.world_layout)


def test_unknown_closed_member_is_finitely_rejected_without_write():
    lib, ports, source, assets = _nullable_world()
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    before = session.author_snapshot()
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "absent"))
    )
    assert isinstance(result, K0NotAdmitted)
    assert session.author_snapshot() == before


def test_invalid_present_member_rolls_back_all_other_outputs():
    lib, ports, source, assets = _nullable_world()
    lib["records"][1]["invariant"] = {"not": {"ref": "state.enabled"}}
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["enable"]
    tool = session.author_object_instances()[0].individual
    before = session.author_snapshot()
    objects = session.author_object_instances()
    with pytest.raises(K0SettlementDefect):
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type("maker", tool, "a"))
        )
    assert session.author_object_instances() == objects
    assert session.author_snapshot().owners == before.owners
    assert session._runtime.occurrence_history() == before.occurrences
