"""Authored Action formation creates independent Objects in the current K0 Session."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceFamily, K0OwnerKey, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_runtime_v1 import C0ObjectTraceError

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _json(name: str) -> dict[str, object]:
    return json.loads((ROOT / f"parcel_delivery_v0.{name}.json").read_text(encoding="utf-8"))


def _author_world(*, capacity: int = 4):
    lib = _json("lib")
    lib["records"].append(
        {
            "name": "Tool",
            "fields": [
                {"name": "label", "type": {"str": [1, 64]}},
                {"name": "ready", "type": "bool"},
            ],
            "invariant": None,
        }
    )
    lib["object_kinds"] = [
        {
            "symbol": "tool",
            "sort": "EXAMPLE.TOOL@1",
            "state": "Tool",
            "version": "tool-v1",
            "max_instances": capacity,
        }
    ]
    ports = _json("ports")
    dispatch = ports["actions"][0]
    dispatch["value"]["outputs"]["formed_tool"] = "Tool"
    dispatch["value"]["construct"].append("Tool")
    ports["actions"].append(
        {
            "symbol": "make",
            "actor": "sender",
            "payload": "Attempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "effects": {"scene": {}, "actor": {}},
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": {
                "read": ["scene.parcel.id", "payload.item_id"],
                "fields": {},
                "write_paths": [],
                "outputs": {"formed_tool": "Tool"},
                "construct": ["Tool"],
                "collections": {},
            },
        }
    )
    source = _json("source")
    source["object_kinds"] = [{"kind": "tool", "sort": "EXAMPLE.TOOL@1"}]
    source["actions"][0]["form"] = {"kind": "tool", "initial_output": "formed_tool"}
    source["actions"].append(
        {
            "name": "make",
            "template": "make",
            "actor": "sender",
            "source_key": "c0.parcel.make",
            "event_type": "c0.parcel.make.action",
            "law": {"ref": "action.make", "args": {}},
            "form": {"kind": "tool", "initial_output": "formed_tool"},
        }
    )
    sender = source["seats"][0]
    sender["entries"].append("make")
    sender["offers"].append(
        {
            "entry": "make",
            "label": "Make tool",
            "when": {"const": True},
            "payload": {
                "item_id": {"ref": "scene.parcel.id"},
                "destination": {"ref": "scene.parcel.destination"},
            },
        }
    )
    tool_expression = {
        "record": {
            "type": "Tool",
            "fields": {"label": {"ref": "payload.item_id"}, "ready": {"const": True}},
        }
    }
    dispatch_law = next(item for item in source["lawdefs"] if item["name"] == "action.dispatch")
    dispatch_law["body"]["value"]["outputs"]["formed_tool"] = tool_expression
    source["lawdefs"].append(
        {
            "name": "action.make",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": {"eq": [{"ref": "payload.item_id"}, {"ref": "scene.parcel.id"}]},
                    "outputs": {
                        "action": {"ref": "occurrence"},
                        "formed_tool": tool_expression,
                    },
                }
            },
        }
    )
    assets = _json("a.assets")
    assets["opening_objects"] = [{"kind": "tool", "state": {"label": "old", "ready": True}}]
    return lib, ports, source, assets


def _compile(lib, ports, source):
    checked = check_nominal_lib(lib)
    return compile_owner_graph(check_graph_ports(ports, checked), source)


def _submit(session, entry: str):
    offer = next(item for item in session.offers("sender") if item.entry == entry)
    return session.submit("sender", offer.entry, dict(offer.payload))


def test_authored_action_forms_two_new_objects_with_distinct_identity_and_basis() -> None:
    lib, ports, source, assets = _author_world()
    session = _compile(lib, ports, source).start(assets)
    assert len(session.author_object_instances()) == 1
    offer = next(item for item in session.offers("sender") if item.entry == "make")
    assert isinstance(_submit(session, "make"), K0Published)
    assert "sender" not in session.form_frame("sender").ready_seats
    action = dict(session.program.actions)["make"]
    sender = session._runtime.read_owner(action.actor_owner.key).view
    payload = action.payload_type(sender.name, **dict(offer.payload))
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload)),
        K0Published,
    )
    objects = session.author_object_instances()
    assert len(objects) == 3
    assert len({item.individual for item in objects}) == 3
    assert len({item.owner for item in objects}) == 3
    assert objects[0].formed_by is None
    assert objects[1].formed_by != objects[2].formed_by
    assert {item.formed_by for item in objects[1:]} <= {
        item.occurrence for item in session._runtime.occurrence_history()
    }
    assert all(item.sort.identity.value == "EXAMPLE.TOOL@1" for item in objects)
    assert [item.current_state.label for item in objects] == ["old", "P-1", "P-1"]
    assert len(session.offers("sender")) == 2


def test_one_authored_action_can_form_an_object_and_schedule_due() -> None:
    lib, ports, source, assets = _author_world()
    session = _compile(lib, ports, source).start(assets)
    published = _submit(session, "dispatch")
    assert isinstance(published, K0Published)
    formed = session.author_object_instances()[1]
    assert formed.formed_by == published.occurrences[0].occurrence
    assert session._runtime._pending_due


@pytest.mark.parametrize(
    "fault", ("event_basis", "wrong_action", "wrong_family", "wrong_owner", "duplicate")
)
def test_object_audit_rejects_unmatched_runtime_individual(fault: str) -> None:
    lib, ports, source, assets = _author_world()
    session = _compile(lib, ports, source).start(assets)
    assert isinstance(_submit(session, "dispatch"), K0Published)
    bindings = session._runtime._individual_bindings
    formed = bindings[-1]
    if fault == "event_basis":
        event = next(
            record
            for record in session._runtime.occurrence_history()
            if record.family is K0OccurrenceFamily.EVENT
        )
        changed = replace(formed, formed_by=event.occurrence)
        session._runtime._individual_bindings = bindings[:-1] + (changed,)
    elif fault == "wrong_action":
        tape = session._runtime._tape
        session._runtime._tape = (
            replace(tape[0], source=K0SourceSpecKey("c0.parcel.confirm")),
        ) + tape[1:]
    elif fault == "wrong_family":
        changed = replace(
            formed,
            individual=_K0IndividualRef(
                formed.individual.scope, formed.individual.ordinal, "foreign"
            ),
        )
        session._runtime._individual_bindings = bindings[:-1] + (changed,)
    elif fault == "wrong_owner":
        changed = replace(formed, owner=K0OwnerKey("foreign.owner"))
        session._runtime._individual_bindings = bindings[:-1] + (changed,)
    else:
        session._runtime._individual_bindings = bindings + (formed,)
    with pytest.raises(C0ObjectTraceError):
        session.author_object_instances()


@pytest.mark.parametrize("fault", ("unselected", "wrong_type", "reused", "unused", "missing"))
def test_formation_binding_and_output_must_be_exact(fault: str) -> None:
    lib, ports, source, _ = _author_world()
    if fault == "unselected":
        source["actions"][-1]["form"]["kind"] = "foreign"
    elif fault == "wrong_type":
        ports["actions"][-1]["value"]["outputs"]["formed_tool"] = "Sender"
    elif fault == "reused":
        lib["records"].append(
            {
                "name": "ToolEnvelope",
                "fields": [{"name": "tool", "type": "Tool"}],
                "invariant": None,
            }
        )
        ports["actions"][-1]["envelope"] = "ToolEnvelope"
        ports["actions"][-1]["envelope_fields"] = {"tool": "formed_tool"}
    elif fault == "unused":
        del source["actions"][0]["form"]
    else:
        source["actions"][-1]["form"]["initial_output"] = "missing"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_unadmitted_action_does_not_form_an_object() -> None:
    lib, ports, source, assets = _author_world()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    action = dict(program.actions)["make"]
    payload = action.payload_type("sender", "foreign", "dock")
    outcome = session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload))
    assert isinstance(outcome, K0NotAdmitted)
    assert len(session.author_object_instances()) == 1


def test_formation_capacity_failure_rolls_back_action_and_owner() -> None:
    lib, ports, source, assets = _author_world(capacity=2)
    session = _compile(lib, ports, source).start(assets)
    offer = next(item for item in session.offers("sender") if item.entry == "make")
    assert isinstance(_submit(session, "make"), K0Published)
    before = session.author_object_instances()
    history = session._runtime.occurrence_history()
    action = dict(session.program.actions)["make"]
    sender = session._runtime.read_owner(action.actor_owner.key).view
    payload = action.payload_type(sender.name, **dict(offer.payload))
    with pytest.raises(K0SettlementDefect):
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload))
    assert session.author_object_instances() == before
    assert session._runtime.occurrence_history() == history


def _target_world(*, capacity: int = 4):
    lib, ports, source, assets = _author_world(capacity=capacity)
    tool = next(item for item in lib["records"] if item["name"] == "Tool")
    tool["fields"].append({"name": "visible", "type": "bool"})
    sender = next(item for item in lib["records"] if item["name"] == "Sender")
    sender["fields"].append({"name": "can_see_tools", "type": "bool"})
    next(item for item in lib["owners"] if item["symbol"] == "sender")["seat_read"].append(
        "can_see_tools"
    )
    lib["records"].append(
        {
            "name": "TargetAttempt",
            "fields": [
                {"name": "actor", "type": {"str": [1, 64]}},
                {"name": "target", "type": "individual_ref"},
            ],
            "invariant": None,
        }
    )
    ports["actions"].append(
        {
            "symbol": "inspect",
            "actor": "sender",
            "payload": "TargetAttempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "target": {"state": "Tool", "payload_field": "target", "write": True},
            "effects": {"scene": {}, "actor": {}, "target": {"ready": "ready"}},
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": {
                "read": ["actor.can_see_tools", "target.ready", "target.visible", "target.label"],
                "fields": {},
                "write_paths": ["target.ready"],
                "construct": [],
                "collections": {},
            },
        }
    )
    source["actions"].append(
        {
            "name": "inspect",
            "template": "inspect",
            "actor": "sender",
            "source_key": "c0.parcel.inspect",
            "event_type": "c0.parcel.inspect.action",
            "target": {"kind": "tool"},
            "law": {"ref": "action.inspect", "args": {}},
        }
    )
    source["lawdefs"].append(
        {
            "name": "action.inspect",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": {
                        "all": [
                            {"ref": "actor.can_see_tools"},
                            {"ref": "target.visible"},
                            {"ref": "target.ready"},
                        ]
                    },
                    "outputs": {"action": {"ref": "occurrence"}, "ready": {"const": False}},
                }
            },
        }
    )
    seat = source["seats"][0]
    seat["entries"].append("inspect")
    seat["read"].append("sender.can_see_tools")
    seat["offers"].append(
        {
            "entry": "inspect",
            "for_each_object": {
                "kind": "tool",
                "read": ["target.label", "target.ready", "target.visible"],
            },
            "label": {"prefix": "Inspect ", "value": {"ref": "target.label"}},
            "visible_when": {"all": [{"ref": "actor.can_see_tools"}, {"ref": "target.visible"}]},
            "when": {"ref": "target.ready"},
            "payload": {"target": {"ref": "individual"}},
        }
    )
    assets["opening"]["sender"]["can_see_tools"] = True
    assets["opening_objects"] = [
        {"kind": "tool", "state": {"label": "old", "ready": True, "visible": True}},
        {"kind": "tool", "state": {"label": "hidden", "ready": True, "visible": False}},
    ]
    for law in source["lawdefs"]:
        if law["name"] in ("action.dispatch", "action.make"):
            law["body"]["value"]["outputs"]["formed_tool"]["record"]["fields"]["visible"] = {
                "const": True
            }
    return lib, ports, source, assets


def test_one_authored_target_law_applies_to_opening_and_formed_objects() -> None:
    lib, ports, source, assets = _target_world()
    session = _compile(lib, ports, source).start(assets)
    opening, hidden = session.author_object_instances()

    def inspect():
        return [item for item in session.offers("sender") if item.entry == "inspect"]

    assert [item.label for item in inspect()] == ["Inspect old"]
    assert isinstance(_submit(session, "make"), K0Published)
    formed = session.author_object_instances()[2]
    assert {item.label for item in inspect()} == {"Inspect old", "Inspect P-1"}
    assert hidden.individual not in [dict(item.payload)["target"] for item in inspect()]
    first = next(item for item in inspect() if dict(item.payload)["target"] == opening.individual)
    assert isinstance(session.submit("sender", "inspect", dict(first.payload)), K0Published)
    assert session.author_object_instances()[0].current_state.ready is False
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("sender", "inspect", dict(first.payload))
    action = dict(session.program.actions)["inspect"]
    sender = session._runtime.read_owner(action.actor_owner.key).view
    stale = action.payload_type(sender.name, opening.individual)
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, stale)), K0NotAdmitted
    )
    assert session._runtime.occurrence_history() == before
    second = next(item for item in inspect() if dict(item.payload)["target"] == formed.individual)
    assert isinstance(session.submit("sender", "inspect", dict(second.payload)), K0Published)
    assert session.author_object_instances()[2].current_state.ready is False
    assert len({item.owner for item in session.author_object_instances()}) == 3


def test_target_binding_rejects_foreign_wrong_kind_and_missing_visibility() -> None:
    lib, ports, source, assets = _target_world()
    session = _compile(lib, ports, source).start(assets)
    action = dict(session.program.actions)["inspect"]
    sender = session._runtime.read_owner(action.actor_owner.key).view
    opening, hidden = session.author_object_instances()
    foreign = _compile(lib, ports, source).start(assets).author_object_instances()[0]
    wrong = _K0IndividualRef(opening.individual.scope, opening.individual.ordinal, "other")
    missing = _K0IndividualRef(opening.individual.scope, 999, "tool")
    before = session._runtime.occurrence_history()
    for ref in (foreign.individual, wrong, missing, hidden.individual):
        outcome = session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(sender.name, ref))
        )
        assert isinstance(outcome, K0NotAdmitted)
    assert session._runtime.occurrence_history() == before
    assets["opening"]["sender"]["can_see_tools"] = False
    blind = _compile(lib, ports, source).start(assets)
    assert all(item.entry != "inspect" for item in blind.offers("sender"))


def test_authored_object_target_files_compile_and_binding_changes_effect() -> None:
    files = {
        part: read_author_document(ROOT / f"object_target_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    }
    session = _compile(files["lib"], files["ports"], files["source"]).start(files["assets"])
    assert [item.label for item in session.offers("actor")] == [
        "Make a tool",
        "Inspect old",
    ]
    old = next(item for item in session.offers("actor") if item.entry == "inspect")
    assert isinstance(session.submit("actor", "inspect", dict(old.payload)), K0Published)
    assert isinstance(session.submit("actor", "make", {}), K0Published)
    new = next(item for item in session.offers("actor") if item.entry == "inspect")
    assert new.label == "Inspect new"
    assert isinstance(session.submit("actor", "inspect", dict(new.payload)), K0Published)
    assert [item.current_state.ready for item in session.author_object_instances()] == [
        False,
        True,
        False,
    ]

    edited = files["source"]
    law = next(item for item in files["lib"]["lawdefs"] if item["name"] == "action.inspect_consume")
    original_guard = law["body"]["value"]["guard"]
    law["body"]["value"]["guard"] = {"const": False}
    refused = _compile(files["lib"], files["ports"], edited).start(files["assets"])
    attempt = next(item for item in refused.offers("actor") if item.entry == "inspect")
    before = refused.author_snapshot()
    assert isinstance(refused.submit("actor", attempt.entry, dict(attempt.payload)), K0NotAdmitted)
    assert refused.author_snapshot() == before
    law["body"]["value"]["guard"] = original_guard
    edited["operation_bindings"][0]["using"] = "preserving_inspection"
    changed = _compile(files["lib"], files["ports"], edited).start(files["assets"])
    offer = next(item for item in changed.offers("actor") if item.entry == "inspect")
    assert isinstance(changed.submit("actor", "inspect", dict(offer.payload)), K0Published)
    assert changed.author_object_instances()[0].current_state.ready is True
    assert any(item.entry == "inspect" for item in changed.offers("actor"))


@pytest.mark.parametrize("fault", ("kind", "state", "ref_type", "unselected", "write"))
def test_target_binding_rejects_malformed_author_ports(fault: str) -> None:
    lib, ports, source, _ = _target_world()
    if fault == "kind":
        source["actions"][-1]["target"]["kind"] = "foreign"
    elif fault == "state":
        ports["actions"][-1]["target"]["state"] = "Sender"
    elif fault == "ref_type":
        payload = next(item for item in lib["records"] if item["name"] == "TargetAttempt")
        payload["fields"][1]["type"] = {"str": [1, 64]}
    elif fault == "write":
        ports["actions"][-1]["target"]["write"] = False
    else:
        source["object_kinds"] = []
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_target_offer_need_not_disclose_a_world_admission_input() -> None:
    lib, ports, source, assets = _target_world()
    next(item for item in lib["records"] if item["name"] == "Tool")["fields"].append(
        {"name": "secret", "type": "bool"}
    )
    inspect = ports["actions"][-1]
    inspect["value"]["read"].append("target.secret")
    action_law = next(item for item in source["lawdefs"] if item["name"] == "action.inspect")
    action_law["body"]["value"]["guard"]["all"].append({"ref": "target.secret"})
    for item in assets["opening_objects"]:
        item["state"]["secret"] = True
    for law in source["lawdefs"]:
        if law["name"] in ("action.dispatch", "action.make"):
            law["body"]["value"]["outputs"]["formed_tool"]["record"]["fields"]["secret"] = {
                "const": True
            }
    assets["opening_objects"][0]["state"]["secret"] = False
    program = _compile(lib, ports, source)
    projection = next(item for item in program.seats[0].offers if item.entry == "inspect")
    assert "target.secret" not in projection.ports.readable_paths
    session = program.start(assets)
    attempt = next(item for item in session.offers("sender") if item.entry == "inspect")
    before = session.author_snapshot()
    assert isinstance(session.submit("sender", attempt.entry, dict(attempt.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    source["seats"][0]["offers"][-1]["for_each_object"]["read"].append("target.secret")
    source["seats"][0]["offers"][-1]["when"] = {
        "all": [{"ref": "target.ready"}, {"ref": "target.secret"}]
    }
    session = _compile(lib, ports, source).start(assets)
    assert all(item.entry != "inspect" for item in session.offers("sender"))


def test_hidden_object_count_does_not_change_public_offers() -> None:
    lib, ports, source, assets = _target_world(capacity=20)
    assets["opening_objects"].extend(
        {"kind": "tool", "state": {"label": f"hidden-{index}", "ready": True, "visible": False}}
        for index in range(15)
    )
    session = _compile(lib, ports, source).start(assets)
    assert [item.label for item in session.offers("sender") if item.entry == "inspect"] == [
        "Inspect old"
    ]
    assert session.offer_faults("sender") == ()


def test_optional_nested_object_read_port_has_finite_compilation() -> None:
    lib, ports, source, assets = _target_world()
    lib["records"].append(
        {
            "name": "Detail",
            "fields": [{"name": "name", "type": {"str": [1, 64]}}],
            "invariant": None,
        }
    )
    next(item for item in lib["records"] if item["name"] == "Tool")["fields"].append(
        {"name": "detail", "type": {"optional": "Detail"}}
    )
    ports["actions"][-1]["value"]["read"].append("target.detail.name")
    source["seats"][0]["offers"][-1]["for_each_object"]["read"].append("target.detail.name")
    for item in assets["opening_objects"]:
        item["state"]["detail"] = None
    for law in source["lawdefs"]:
        if law["name"] in ("action.dispatch", "action.make"):
            law["body"]["value"]["outputs"]["formed_tool"]["record"]["fields"]["detail"] = {
                "const": None
            }
    session = _compile(lib, ports, source).start(assets)
    assert any(item.entry == "inspect" for item in session.offers("sender"))
