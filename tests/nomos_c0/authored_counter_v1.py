"""Explicit author declarations for short counter/formation regressions."""

from __future__ import annotations

import json
from pathlib import Path

from nomos_kernel import K0OwnerKey

from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
MAX_INT = (1 << 63) - 1


def _record(name, fields, invariant=None):
    return {
        "name": name,
        "fields": [{"name": field, "type": kind} for field, kind in fields.items()],
        "invariant": invariant,
    }


def _owner(symbol, state, read, identity=None):
    return {
        "symbol": symbol,
        "key": f"c0.graph.{symbol}",
        "version": "counter-v1",
        "state": state,
        "identity_field": identity,
        "write": "replace_one",
        "seat_read": read,
    }


def _value(read, write, outputs=None, construct=()):
    value = {
        "read": read,
        "fields": {},
        "write_paths": write,
        "construct": list(construct),
        "collections": {},
    }
    if outputs is not None:
        value["outputs"] = outputs
    return value


def build(lib, ports):
    return check_graph_ports(ports, check_nominal_lib(lib))


def counter_documents(actor_count=1, seated=1, *, definitions=()):
    lib = {
        "schema": "c0.nominal_lib.v1",
        "records": [
            _record(
                "Scene",
                {
                    "marker": {"str": [1, 64]},
                    "open_ref": {"optional": "occurrence_ref"},
                    "signal": {"str": [1, 64]},
                },
                "state.marker != 'forbidden'",
            ),
            _record("Actor", {"name": {"str": [1, 64]}, "count": {"int": [0, MAX_INT]}}),
            _record("Attempt", {"actor": {"str": [1, 64]}, "target": {"str": [1, 64]}}),
            _record("Envelope", {"action": "occurrence_ref"}),
        ],
        "owners": [_owner("scene", "Scene", ["marker", "signal"])],
    }
    if definitions:
        lib["pure_definitions"] = list(definitions)
    ports = {
        "schema": "c0.graph_ports.v1",
        "scene_owner": "scene",
        "offer_provider": {"name": "finite_value", "version": "1", "limit": 16},
        "actions": [],
        "events": [],
        "due_events": [],
    }
    source = {
        "schema": "c0.owner_graph.v6",
        "game_form": {"mode": "manual"},
        "owners": ["scene"],
        "lawdefs": [
            {
                "name": "count",
                "family": "action",
                "formals": {"step": "int"},
                "body": {
                    "value": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": "payload.target == actor.name",
                        "outputs": {
                            "count": {"add": [{"ref": "actor.count"}, {"arg": "step"}]},
                            "action": {"ref": "occurrence"},
                        },
                    }
                },
            }
        ],
        "actions": [],
        "events": [],
        "seats": [],
        "offer_provider": {"name": "finite_value", "version": "1"},
    }
    assets = {
        "schema": "c0.owner_graph.assets.v1",
        "opening": {"scene": {"marker": "one", "open_ref": None, "signal": "quiet"}},
    }
    for index in range(actor_count):
        actor, entry, seat = f"actor_{index}", f"count_{index}", f"seat_{index}"
        lib["owners"].append(_owner(actor, "Actor", ["name", "count"], "name"))
        source["owners"].append(actor)
        assets["opening"][actor] = {"name": f"person_{index}", "count": 0}
        if index >= seated:
            continue
        ports["actions"].append(
            {
                "symbol": entry,
                "actor": actor,
                "payload": "Attempt",
                "envelope": "Envelope",
                "actor_identity_field": "name",
                "payload_actor_field": "actor",
                "effects": {"scene": {}, "actor": {"count": "count"}},
                "envelope_fields": {"action": "action"},
                "schedule": None,
                "value": _value(["actor.name", "actor.count", "payload.target"], ["actor.count"]),
            }
        )
        source["actions"].append(
            {
                "name": entry,
                "template": entry,
                "actor": actor,
                "source_key": f"c0.graph.{entry}",
                "event_type": f"c0.graph.{entry}.done",
                "law": {"ref": "count", "args": {"step": 1}},
            }
        )
        source["seats"].append(
            {
                "name": seat,
                "actor": actor,
                "entries": [entry],
                "read": ["scene.marker", f"{actor}.name", f"{actor}.count"],
                "offers": [
                    {
                        "entry": entry,
                        "label": "Count",
                        "when": {"const": True},
                        "payload": {"target": {"ref": "actor.name"}},
                    }
                ],
            }
        )
    return lib, ports, source, assets


def _inputs(actor_count, seated):
    lib, ports, source, assets = counter_documents(actor_count, seated)
    return build(lib, ports), source, assets


def _actor(session, index):
    return session._runtime.read_owner(K0OwnerKey(f"c0.graph.actor_{index}")).view


def _scene(session):
    return session._runtime.read_owner(K0OwnerKey("c0.graph.scene")).view


def direct_documents():
    lib, ports, _, assets = counter_documents(2, 2)
    ports["events"] = [
        {
            "symbol": "unseal",
            "form": "direct_scene",
            "actor": None,
            "actor_identity_field": None,
            "value": _value(
                ["scene.marker"],
                ["scene.marker", "scene.open_ref", "scene.signal"],
                {"marker": "scene.marker", "open_ref": "scene.open_ref"},
            ),
        }
    ]
    source = json.loads((ROOT / "scene_unseal_v1.source.json").read_text())
    assets["opening"]["scene"]["marker"] = "sealed"
    return lib, ports, source, assets


def _direct_inputs():
    lib, ports, source, assets = direct_documents()
    return build(lib, ports), source, assets


def _actor_event_inputs():
    lib, ports, source, assets = direct_documents()
    lib["records"].extend(
        [
            _record("notice", {"arrival": "occurrence_ref", "perception": "occurrence_ref"}),
            _record("Observer", {"name": {"str": [1, 64]}, "notice": {"optional": "notice"}}),
        ]
    )
    lib["owners"].append(_owner("observer", "Observer", ["name"], "name"))
    source["owners"].append("observer")
    assets["opening"]["observer"] = {"name": "observer", "notice": None}
    assets["opening"]["scene"]["signal"] = "observer"
    ports["events"].append(
        {
            "symbol": "observe",
            "form": "direct_actor",
            "actor": "observer",
            "actor_identity_field": "name",
            "value": _value(
                [
                    "scene.open_ref",
                    "scene.signal",
                    "actor.name",
                    "actor.notice",
                    "trigger.occurrence",
                ],
                ["actor.notice"],
                {"notice": "actor.notice"},
                ["notice"],
            ),
        }
    )
    source["lawdefs"].append(
        {
            "name": "event.observe",
            "family": "direct_actor_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": {
                        "all": [
                            {"not_none": {"ref": "scene.open_ref"}},
                            {"eq": [{"ref": "scene.open_ref"}, {"ref": "trigger.occurrence"}]},
                            {"eq": [{"ref": "scene.signal"}, {"ref": "actor.name"}]},
                            {"is_none": {"ref": "actor.notice"}},
                        ]
                    },
                    "outputs": {
                        "notice": {
                            "record": {
                                "type": "notice",
                                "fields": {
                                    "arrival": {"ref": "trigger.occurrence"},
                                    "perception": {"ref": "occurrence"},
                                },
                            }
                        }
                    },
                }
            },
        }
    )
    source["events"].append(
        {
            "name": "observe",
            "template": "observe",
            "actor": "observer",
            "trigger_event": "unseal",
            "source_key": "c0.graph.observed",
            "event_type": "c0.graph.observed.event",
            "causal_key": "c0.graph.observed.causes",
            "law": {"ref": "event.observe", "args": {}},
        }
    )
    return build(lib, ports), source, assets


def action_value_documents():
    lib, ports, source, assets = counter_documents(2, 2)
    ports["due_events"] = [
        {
            "symbol": "pulse",
            "value": _value(
                ["due.subject", "time.ordinal"], ["scene.signal"], {"signal": "scene.signal"}
            ),
        }
    ]
    source["lawdefs"].append(
        {
            "name": "pulse",
            "family": "due_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "due.subject == 'clock' and time.ordinal == 5",
                    "outputs": {"signal": "'pulse'"},
                }
            },
        }
    )
    source["due_events"] = [
        {
            "name": "pulse",
            "template": "pulse",
            "form": "due",
            "source_key": "c0.graph.pulse",
            "event_type": "c0.graph.pulse.event",
            "when_false": "defect",
            "law": {"ref": "pulse", "args": {}},
        }
    ]
    source["temporal"] = {
        "mechanism": "action_value_event_jump",
        "order": ["pulse"],
        "max_pending": 1,
        "periodic": [
            {
                "name": "clock",
                "due": "pulse",
                "interval": 5,
                "max_occurrences": 1,
                "subject": "clock",
            }
        ],
    }
    source["game_form"] = {
        "mode": "action_value_event_jump",
        "seats": [
            {
                "seat": "seat_0",
                "tempo": 1,
                "eligible": "actor.count < 3",
                "costs": {
                    "count_0": {
                        "ceil_div": [
                            {"mul": [{"const": 10}, {"const": 5}]},
                            {"add": [{"ref": "actor.count"}, {"const": 3}]},
                        ]
                    }
                },
            },
            {"seat": "seat_1", "tempo": 2, "eligible": "actor.count < 3", "costs": {"count_1": 17}},
        ],
        "end_at": 30,
        "max_same_time_actions": 8,
    }
    assets.update(
        time=0,
        periodic_due_openings=[{"plan": "clock", "first_at": 5}],
        action_value_openings=[
            {"seat": "seat_0", "debt": 5, "tie_priority": 0},
            {"seat": "seat_1", "debt": 10, "tie_priority": 1},
        ],
    )
    return lib, ports, source, assets


def _action_value_inputs():
    lib, ports, source, assets = action_value_documents()
    return build(lib, ports), source, assets


def _temporal_inputs():
    from nomos_c0.author_document_v1 import read_author_document

    lib, ports, source = (
        read_author_document(ROOT / f"parcel_delivery_v0.{part}.json").to_data()
        for part in ("lib", "ports", "source")
    )
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    ports["actions"][0]["effects"]["actor"] = {"sent_ref": "schedule_ref"}
    ports["actions"][0]["value"]["outputs"] = {"schedule_ref": "occurrence_ref"}
    source["actions"][0]["name"] = "open"
    value = source["lawdefs"][0]["body"]["value"]["outputs"]
    value["schedule_ref"] = value.pop("sent_ref")
    seat = source["seats"][0]
    seat["entries"] = ["open"]
    seat["offers"][0]["entry"] = "open"
    for event in source["events"]:
        if event.get("trigger_action") == "dispatch":
            event["trigger_action"] = "open"
    for formation in source["ontology"]["formations"]:
        if formation["trigger_kind"] == "action" and formation["trigger"] == "dispatch":
            formation["trigger"] = "open"
    return build(lib, ports), source, assets
