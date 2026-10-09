"""Endpoint declarations determine types without granting effects or public reads."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest
from nomos_kernel import K0OccurrenceRef, K0SourceSpecKey
from nomos_kernel._settlement_outcome_abi import K0Published
from test_multi_participant_action_v0 import _world as _participants
from test_program_binding_v1 import _block
from test_world_binding_v1 import ROOT, _compile, _documents, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.program_binding_v1 import bind_program


def _world():
    lib, ports, source = _documents("parcel_delivery_v0")
    assets = json.loads((ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    for action in ports["actions"]:
        del action["value"]["outputs"]
        action["effects"] = {root: list(mapping) for root, mapping in action["effects"].items()}
        action["envelope_fields"] = list(action["envelope_fields"])
    ports["due_events"][0]["value"]["outputs"] = {"parcel": "scene.parcel"}
    return lib, ports, source, assets


def _submit(session, seat):
    offer = session.offers(seat)[0]
    return session.submit(seat, offer.entry, dict(offer.payload))


def test_derived_signature_runs_action_causal_and_due_in_two_layouts(monkeypatch):
    lib, ports, source, assets = _world()
    ir, layout = check_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    alternate = _layout(SimpleNamespace(world_ir=ir.world, world_layout=layout))
    lib.clear()
    ports.clear()
    source.clear()
    _block(monkeypatch)
    for selected in (layout, alternate):
        program = bind_program(ir, selected)
        dispatch = dict(program.actions)["dispatch"]
        assert dispatch.value._ports.outputs["sent_ref"] == K0OccurrenceRef | None
        assert dispatch.value._ports.outputs["action"] is K0OccurrenceRef
        assert dispatch.value._ports.outputs["delay"] is int
        session = program.start(assets)
        assert isinstance(_submit(session, "sender"), K0Published)
        session.defer_form("sender")
        session.defer_form("receiver")
        assert session.continue_form("receiver").time == 2
        assert isinstance(_submit(session, "receiver"), K0Published)
        owners = dict(session.author_snapshot().owners)
        assert owners["scene"].parcel.status == "arrived"
        assert owners["receiver"].receipt.arrival == owners["scene"].parcel.arrival_ref
        history = session._runtime.occurrence_history()
        assert history[0].source == dispatch.source_key
        assert owners["receiver"].notice.departure == history[1].occurrence
        assert owners["receiver"].notice.notification in {item.occurrence for item in history}
        assert (
            next(
                item
                for item in history
                if item.occurrence == owners["receiver"].notice.notification
            ).source
            == dict(program.events)["notice"].ports.source_key
        )


def test_type_edit_has_no_copied_action_output_to_synchronize():
    lib, ports, source, assets = _world()
    sender = next(record for record in lib["records"] if record["name"] == "Sender")
    sender["fields"].append({"name": "enabled", "type": "bool"})
    action = ports["actions"][0]
    action["effects"]["actor"].append("enabled")
    action["value"]["write_paths"].append("actor.enabled")
    law = next(law for law in source["lawdefs"] if law["name"] == "action.dispatch")
    law["body"]["value"]["outputs"]["enabled"] = {"const": True}
    assets["opening"]["sender"]["enabled"] = False
    program = _compile(lib, ports, source)
    assert dict(program.actions)["dispatch"].value._ports.outputs["enabled"] is bool
    session = program.start(assets)
    assert isinstance(_submit(session, "sender"), K0Published)
    assert dict(session.author_snapshot().owners)["sender"].enabled is True
    assert "sender.enabled" not in dict(session.read("sender").fields)
    sender["fields"][-1]["type"] = {"int": [0, 9]}
    law["body"]["value"]["outputs"]["enabled"] = {"const": 7}
    assets["opening"]["sender"]["enabled"] = 0
    program = _compile(lib, ports, source)
    assert dict(program.actions)["dispatch"].value._ports.outputs["enabled"] is int
    session = program.start(assets)
    assert isinstance(_submit(session, "sender"), K0Published)
    assert dict(session.author_snapshot().owners)["sender"].enabled == 7


def test_upper_permission_does_not_create_an_actual_action_write():
    lib, ports, source, _ = _world()
    value = ports["actions"][0]["value"]
    value["write_paths"].append("scene.signal")
    value["outputs"] = {"signal": "scene.signal"}
    law = next(law for law in source["lawdefs"] if law["name"] == "action.dispatch")
    law["body"]["value"]["outputs"]["signal"] = {"const": "changed"}
    with pytest.raises(C0LawError, match="typed one-shot ports"):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_root",
        "unknown_read",
        "unknown_write",
        "unknown_output",
        "output_type",
        "missing_permission",
        "two_permissions",
        "duplicate_field",
        "duplicate_alias",
    ],
)
def test_signature_error_is_rejected_before_start(change):
    lib, ports, source, _ = _world()
    action = ports["actions"][0]
    value = action["value"]
    if change == "wrong_root":
        value["roots"] = {"scene": "Scene", "actor": "Receiver", "payload": "Attempt"}
    elif change == "unknown_read":
        value["read"].append("actor.missing")
    elif change == "unknown_write":
        value["write_paths"].append("actor.missing")
    elif change == "unknown_output":
        value["outputs"] = {"sent_ref": "actor.missing"}
    elif change == "output_type":
        value["outputs"] = {"delay": "str"}
    elif change == "missing_permission":
        value["write_paths"] = []
    elif change == "two_permissions":
        value["write"] = {"Sender": ["sent_ref"]}
    elif change == "duplicate_field":
        action["effects"]["actor"].append("sent_ref")
    else:
        action["effects"]["actor"] = {"sent_ref": "action"}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_a_private_law_read_does_not_grant_offer_read_permission():
    lib, ports, source, _ = _world()
    source["seats"][0]["offers"][0]["when"] = {"is_none": {"ref": "scene.parcel.depart_ref"}}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_participant_types_are_derived_but_actual_writes_stay_root_scoped():
    lib, ports, source, assets = _participants()
    action = ports["actions"][0]
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    owners = dict(session.author_snapshot().owners)
    assert owners["a"].enabled and not owners["b"].enabled
    assert session._runtime.occurrence_history()[0].source == K0SourceSpecKey(
        "c0.participants.enable"
    )
    action["participants"][1]["write"] = False
    with pytest.raises(C0LawError, match="write permission"):
        _compile(lib, ports, source)


def test_an_explicit_nonnull_output_can_narrow_but_not_widen_its_endpoint():
    lib, ports, source, _ = _world()
    ports["actions"][0]["value"]["outputs"] = {"sent_ref": "occurrence_ref"}
    program = _compile(lib, ports, source)
    assert dict(program.actions)["dispatch"].value._ports.outputs["sent_ref"] is K0OccurrenceRef
    ports["actions"][0]["value"]["outputs"] = {"action": {"optional": "occurrence_ref"}}
    with pytest.raises(C0LawError, match="endpoint type"):
        _compile(lib, ports, source)


def test_tuple_element_type_comes_from_the_declared_field_and_runs_in_k0():
    lib, ports, source, assets = _world()
    sender = next(record for record in lib["records"] if record["name"] == "Sender")
    sender["fields"].append(
        {"name": "history", "type": {"tuple": {"item": "occurrence_ref", "max": 8}}}
    )
    action = ports["actions"][0]
    action["effects"]["actor"].append("history")
    action["value"]["write_paths"].append("actor.history")
    action["value"]["read"].append("actor.history")
    law = next(law for law in source["lawdefs"] if law["name"] == "action.dispatch")
    law["body"]["value"]["outputs"]["history"] = {
        "append": [{"ref": "actor.history"}, {"ref": "occurrence"}]
    }
    assets["opening"]["sender"]["history"] = []
    program = _compile(lib, ports, source)
    assert (
        dict(program.actions)["dispatch"].value._ports.outputs["history"]
        == tuple[K0OccurrenceRef, ...]
    )
    session = program.start(assets)
    assert isinstance(_submit(session, "sender"), K0Published)
    assert dict(session.author_snapshot().owners)["sender"].history == (
        session._runtime.occurrence_history()[0].occurrence,
    )


def test_event_field_type_reference_is_not_write_permission():
    lib, ports, source, _ = _world()
    ports["events"][1]["value"]["write_paths"] = []
    with pytest.raises(C0LawError, match="explicit write permission"):
        _compile(lib, ports, source)


def test_collection_element_permission_uses_the_nominal_endpoint_field():
    lib, ports, source, _ = _world()
    value = ports["actions"][0]["value"]
    value["write_paths"].append("scene.routes[].travel")
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    route = get_type_hints(graph.actions[0].ports.value_ports.roots["scene"])["routes"]
    carrier = get_args(route)[0]
    assert graph.actions[0].ports.value_ports.writable_fields[carrier] == {"travel"}
    program = _compile(lib, ports, source)
    assert not any(
        root == "scene" for root, _, _ in dict(program.actions)["dispatch"].state_effects
    )


@pytest.mark.parametrize(
    "path",
    ["scene.routes[]", "scene.routes.travel", "scene.signal[].missing", "scene.routes[].missing"],
)
def test_collection_field_permission_rejects_non_record_or_non_tuple_paths(path):
    lib, ports, source, _ = _world()
    ports["actions"][0]["value"]["write_paths"].append(path)
    with pytest.raises(C0LawError, match="endpoint field"):
        _compile(lib, ports, source)


@pytest.mark.parametrize("legacy", ["roots", "write"])
def test_legacy_value_port_fields_are_rejected_even_when_they_match(legacy):
    lib, ports, source, _ = _world()
    value = ports["actions"][0]["value"]
    value[legacy] = (
        {"scene": "Scene", "actor": "Sender", "payload": "Attempt"}
        if legacy == "roots"
        else {"Sender": ["sent_ref"]}
    )
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        _compile(lib, ports, source)


def test_exact_action_output_copy_is_rejected_but_real_narrowing_is_retained():
    lib, ports, source, _ = _world()
    ports["actions"][0]["value"]["outputs"] = {"action": "occurrence_ref"}
    with pytest.raises(C0LawError, match="redundantly repeats"):
        _compile(lib, ports, source)
    ports["actions"][0]["value"]["outputs"] = {"sent_ref": "occurrence_ref"}
    assert (
        dict(_compile(lib, ports, source).actions)["dispatch"].value._ports.outputs["sent_ref"]
        is K0OccurrenceRef
    )
