"""Equal nominal carriers do not grant writes to another owner endpoint."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import build, counter_documents
from nomos_kernel._settlement_outcome_abi import K0Published
from test_composable_action_v1 import READ_SOURCE, SOURCE, _ports, _read_ports
from test_world_binding_v1 import _layout

from nomos_c0 import C0LawError
from nomos_c0.composable_action_v1 import compile_composable_action
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.world_binding_v1 import bind_world


def _documents(write_root):
    lib, ports, source, assets = counter_documents(2, 1)
    action = ports["actions"][0]
    action["participants"] = [
        {
            "name": "peer",
            "selector": "closed_domain",
            "state": "Actor",
            "payload_field": "target",
            "write": write_root == "peer",
        }
    ]
    action["effects"] = {
        "scene": {}, "actor": {}, "peer": {},
        write_root: {"count": "count"},
    }
    action["value"]["write_paths"] = [f"{write_root}.count"]
    source["actions"][0]["participants"] = {"peer": {"actors": ["actor_1"]}}
    source["lawdefs"][0]["body"]["value"]["guard"] = {"const": True}
    source["seats"][0]["offers"][0]["payload"]["target"] = {"const": "actor_1"}
    assets["opening"]["actor_1"]["name"] = "actor_1"
    return lib, ports, source, assets


def test_same_carrier_peer_permission_cannot_authorize_actor_effect():
    lib, ports, source, _ = _documents("actor")
    ports["actions"][0]["value"]["write_paths"] = ["peer.count"]
    with pytest.raises(C0LawError, match="write port"):
        compile_owner_graph(build(lib, ports), source)


@pytest.mark.parametrize("root,changed", [("actor", "actor_0"), ("peer", "actor_1")])
def test_exact_permission_survives_compile_bind_and_publishes_only_selected_owner(root, changed):
    lib, ports, source, assets = _documents(root)
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    before = deepcopy(assets)
    result = session.submit("seat_0", "count_0", {"target": "actor_1"})
    assert isinstance(result, K0Published)
    states = dict(session.author_snapshot().owners)
    assert states[changed].count == 1
    other = "actor_1" if changed == "actor_0" else "actor_0"
    assert states[other].count == 0
    assert assets == before


def test_native_binding_cannot_fall_back_to_type_field_permission():
    ports = _read_ports()
    with pytest.raises(C0LawError, match="write port"):
        compile_composable_action(
            READ_SOURCE.read_text(),
            replace(ports, value_ports=replace(ports.value_ports, writable_paths=frozenset())),
        )


def test_independent_binding_rechecks_symbolic_owner_paths_not_shared_carrier_fields():
    lib, ports, source, _ = _documents("actor")
    program = compile_owner_graph(build(lib, ports), source)
    transition = program.world_ir.transitions[0]
    assert transition.body.value.ports.writable_paths == frozenset({"actor.count"})
    changed_value = replace(
        transition.body.value,
        ports=replace(transition.body.value.ports, writable_paths=frozenset({"peer.count"})),
    )
    world = replace(
        program.world_ir,
        transitions=(replace(transition, body=replace(transition.body, value=changed_value)),),
    )
    for layout in (program.world_layout, _layout(program)):
        with pytest.raises(C0LawError, match="write port"):
            bind_world(world, replace(layout, world=world))


def test_nested_field_permission_does_not_grant_replacement_of_its_container():
    ports = _ports()
    nested_only = frozenset({"scene.parcels[].status", "actor.receipts"})
    with pytest.raises(C0LawError, match="write port"):
        compile_composable_action(
            SOURCE.read_text(),
            replace(ports, value_ports=replace(ports.value_ports, writable_paths=nested_only)),
        )
