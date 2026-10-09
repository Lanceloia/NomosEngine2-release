"""Declared read/acquisition and ordered-due test worlds, without native owners."""

from __future__ import annotations

from copy import deepcopy

from authored_counter_v1 import MAX_INT, ROOT, _record, _value, build
from nomos_kernel import K0OwnerKey

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.owner_graph_v1 import compile_owner_graph


def documents(*, temporal=False, two_due=False):
    lib = {
        "schema": "c0.nominal_lib.v1",
        "records": [
            _record(
                "Scene",
                {
                    "target": {"str": [1, 64]},
                    "mode": {"str": [1, 24]},
                    "content": {"str": [1, 64]},
                    "open_ref": {"optional": "occurrence_ref"},
                },
                "(state.mode == 'sealed' or state.mode == 'accessible') "
                "and ((state.mode == 'sealed') == (state.open_ref == None))",
            ),
            _record(
                "AState",
                {
                    "name": {"str": [1, 64]},
                    "opens": {"int": [0, MAX_INT]},
                    "schedule_ref": {"optional": "occurrence_ref"},
                    "second_ref": {"optional": "occurrence_ref"},
                },
            ),
            _record(
                "Acquired",
                {
                    "content": {"str": [1, 64]},
                    "open_ref": "occurrence_ref",
                    "read_ref": "occurrence_ref",
                },
            ),
            _record(
                "BState",
                {
                    "name": {"str": [1, 64]},
                    "budget": {"int": [0, MAX_INT]},
                    "acquired": {"optional": "Acquired"},
                },
            ),
            _record("Attempt", {"actor": {"str": [1, 64]}, "target": {"str": [1, 64]}}),
            _record("Envelope", {"action": "occurrence_ref"}),
        ],
        "owners": [
            {
                "symbol": symbol,
                "key": key,
                "version": "paid-v1",
                "state": state,
                "identity_field": identity,
                "write": "replace_one",
                "seat_read": read,
            }
            for symbol, key, state, identity, read in (
                ("scene", "c0.paid.scene", "Scene", None, ["target", "mode", "open_ref"]),
                (
                    "actor_a",
                    "c0.paid.a",
                    "AState",
                    "name",
                    ["name", "opens", "schedule_ref", "second_ref"],
                ),
                (
                    "actor_b",
                    "c0.paid.b",
                    "BState",
                    "name",
                    [
                        "name",
                        "budget",
                        "acquired",
                        "acquired.content",
                        "acquired.open_ref",
                        "acquired.read_ref",
                    ],
                ),
            )
        ],
    }
    ports = {
        "schema": "c0.graph_ports.v1",
        "scene_owner": "scene",
        "offer_provider": {"name": "finite_value", "version": "1", "limit": 16},
        "actions": [
            {
                "symbol": name,
                "actor": actor,
                "payload": "Attempt",
                "envelope": "Envelope",
                "actor_identity_field": "name",
                "payload_actor_field": "actor",
                "effects": {"scene": {}, "actor": effects},
                "envelope_fields": {"action": "action"},
                "schedule": None,
                "value": value,
            }
            for name, actor, effects, value in (
                (
                    "open",
                    "actor_a",
                    {"opens": "opens"},
                    _value(
                        ["scene.target", "scene.mode", "actor.opens", "payload.target"],
                        ["actor.opens"],
                    ),
                ),
                (
                    "read",
                    "actor_b",
                    {"budget": "budget", "acquired": "acquired"},
                    _value(
                        [
                            "scene.target",
                            "scene.mode",
                            "scene.open_ref",
                            "scene.content",
                            "actor.budget",
                            "actor.acquired",
                            "payload.target",
                        ],
                        ["actor.budget", "actor.acquired"],
                        {"acquired": "Acquired"},
                        ["Acquired"],
                    ),
                ),
            )
        ],
        "events": [
            {
                "symbol": "unseal",
                "form": "direct_scene",
                "actor": None,
                "actor_identity_field": None,
                "value": _value(
                    ["scene.mode"],
                    ["scene.mode", "scene.open_ref"],
                    {"mode": "scene.mode", "open_ref": "scene.open_ref"},
                ),
            }
        ],
        "due_events": [],
    }
    source = read_author_document(ROOT / "scene_paid_read_v1.source.json").to_data()
    assets = {
        "schema": "c0.owner_graph.assets.v1",
        "opening": {
            "scene": {"target": "folio", "mode": "sealed", "content": "hidden-a", "open_ref": None},
            "actor_a": {"name": "A", "opens": 0, "schedule_ref": None, "second_ref": None},
            "actor_b": {"name": "B", "budget": 1, "acquired": None},
        },
    }
    if not temporal:
        return lib, ports, source, assets
    ports["events"] = []
    source["events"] = []
    action = ports["actions"][0]
    action["schedule"] = {
        "one_shot_field": "schedule_ref",
        "subject_output": "subject",
        "delay_output": "delay",
    }
    action["effects"]["actor"]["schedule_ref"] = "schedule_ref"
    action["value"]["read"].append("actor.schedule_ref")
    action["value"]["write_paths"].append("actor.schedule_ref")
    action["value"]["outputs"] = {"schedule_ref": "occurrence_ref"}
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"]["all"].append({"is_none": {"ref": "actor.schedule_ref"}})
    value["outputs"].update(
        schedule_ref={"ref": "occurrence"}, subject={"ref": "payload.target"}, delay={"const": 2}
    )
    source["actions"][0]["schedule"] = {
        "source": "c0.paid.unseal.due",
    }
    seat = source["seats"][0]
    seat["read"].append("actor_a.schedule_ref")
    seat["offers"][0]["when"] = {
        "all": [seat["offers"][0]["when"], {"is_none": {"ref": "actor.schedule_ref"}}]
    }
    ports["due_events"] = [
        {
            "symbol": "unseal_due",
            "value": _value(
                ["scene.target", "scene.mode", "due.subject", "time.ordinal"],
                ["scene.mode", "scene.open_ref"],
                {
                    "mode": "scene.mode",
                    "open_ref": {"target": "scene.open_ref", "type": "occurrence_ref"},
                },
            ),
        }
    ]
    source["due_events"] = [
        {
            "name": "unseal_due",
            "template": "unseal_due",
            "form": "due",
            "source_key": "c0.paid.unseal.due",
            "event_type": "c0.paid.unseal.due.event",
            "when_false": "defect",
            "law": {"ref": "event.unseal_due", "args": {}},
        }
    ]
    due = deepcopy(source["lawdefs"][2])
    due.update(name="event.unseal_due", family="due_event")
    due["body"]["law"]["guard"] = {
        "all": [
            {"eq": [{"ref": "scene.target"}, {"ref": "due.subject"}]},
            {"eq": [{"ref": "scene.mode"}, {"const": "sealed"}]},
        ]
    }
    source["lawdefs"].append(due)
    source["temporal"] = {
        "mechanism": "ordered_due_microsteps",
        "order": ["unseal_due"],
        "max_pending": 1,
        "advance_seats": ["seat_a", "seat_b"],
    }
    assets["time"] = 4
    if not two_due:
        return lib, ports, source, assets
    alternate_port = deepcopy(action)
    alternate_port.update(symbol="annotate")
    alternate_port["value"]["read"].remove("actor.schedule_ref")
    alternate_port["value"]["read"].append("actor.second_ref")
    alternate_port["value"]["write_paths"] = ["actor.opens", "actor.second_ref"]
    alternate_port["effects"]["actor"]["second_ref"] = alternate_port["effects"]["actor"].pop(
        "schedule_ref"
    )
    alternate_port["schedule"]["one_shot_field"] = "second_ref"
    ports["actions"].append(alternate_port)
    alternate_action = deepcopy(source["actions"][0])
    alternate_action.update(
        name="annotate",
        template="annotate",
        source_key="c0.paid.annotate",
        event_type="c0.paid.annotate.action",
        law={"ref": "action.annotate", "args": {}},
    )
    alternate_action["schedule"]["source"] = "c0.paid.annotate.due"
    source["actions"].append(alternate_action)
    alternate_def = deepcopy(source["lawdefs"][0])
    alternate_def["name"] = "action.annotate"
    alternate_def["body"]["value"]["guard"]["all"][-1] = {"is_none": {"ref": "actor.second_ref"}}
    source["lawdefs"].append(alternate_def)
    ports["due_events"].append(
        {
            "symbol": "annotate_due",
            "value": _value(
                ["scene.target", "scene.mode", "due.subject"],
                ["scene.content"],
                {"content": "scene.content"},
            ),
        }
    )
    alternate_due = deepcopy(source["due_events"][0])
    alternate_due.update(
        name="annotate_due",
        template="annotate_due",
        source_key="c0.paid.annotate.due",
        event_type="c0.paid.annotate.due.event",
        law={"ref": "event.annotate_due", "args": {}},
    )
    source["due_events"].append(alternate_due)
    alternate_due_def = deepcopy(due)
    alternate_due_def["name"] = "event.annotate_due"
    alternate_due_def["body"]["law"]["guard"]["all"][1] = {
        "eq": [{"ref": "scene.mode"}, {"const": "accessible"}]
    }
    alternate_due_def["body"]["law"]["outputs"] = {"content": {"const": "annotated"}}
    source["lawdefs"].append(alternate_due_def)
    source["temporal"]["order"].append("annotate_due")
    source["temporal"]["max_pending"] = 2
    seat["entries"].append("annotate")
    seat["read"].append("actor_a.second_ref")
    offer = deepcopy(seat["offers"][0])
    offer.update(entry="annotate", label="Annotate folio")
    offer["when"]["all"][1] = {"is_none": {"ref": "actor.second_ref"}}
    seat["offers"].append(offer)
    return lib, ports, source, assets


def compile_documents(lib, ports, source):
    return compile_owner_graph(build(lib, ports), source)


def owner(session, name):
    return session._runtime.read_owner(K0OwnerKey(f"c0.paid.{name}")).view


def submit(session, seat, entry):
    return session.submit(seat, entry, {"target": "folio"})
