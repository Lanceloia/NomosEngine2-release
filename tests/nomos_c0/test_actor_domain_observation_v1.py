"""Actual finite Actor instances are observed only through checked local Events."""

from copy import deepcopy

import pytest
from authored_counter_v1 import _record, _value
from test_actor_formation_v1 import documents, submit_first
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError


def observation_documents():
    lib, ports, source, assets = documents(path="event")
    actor = next(record for record in lib["records"] if record["name"] == "Actor")
    actor["fields"].append({"name": "sighting", "type": {"optional": "Sighting"}})
    lib["records"] += [
        _record("Basis", {"ref": "actor_ref", "count": {"int": [0, 100]}}),
        _record("Domain", {"members": {"tuple": {"item": "Basis", "max": 4}}}),
        _record("Sighting", {"subject": "actor_ref", "observation": "occurrence_ref"}),
    ]
    for name in ("actor_0", "actor_1"):
        assets["opening"][name]["sighting"] = None
    lib["owners"][1]["seat_read"].append("sighting")
    source["seats"][0]["read"].append("actor_0.sighting")
    value = _value(
        ["actor.name", "sprites.members"],
        ["actor.sighting"],
        {"sighting": "actor.sighting"},
        ["Sighting"],
    )
    value["fields"] = {"Basis": ["ref", "count"]}
    ports["events"].append(
        {
            "symbol": "observe",
            "form": "direct_actor",
            "actor": "actor_0",
            "actor_identity_field": "name",
            "value": value,
            "read_actor_domains": [
                {
                    "name": "sprites",
                    "kind": "sprite",
                    "wrapper": "Domain",
                    "members_field": "members",
                    "record": "Basis",
                    "identity_field": "ref",
                    "fields": {"count": "count"},
                }
            ],
        }
    )
    source["lawdefs"].append(
        {
            "name": "observe",
            "family": "direct_actor_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [
                        {
                            "name": "visible",
                            "collection": "sprites.members",
                            "as": "candidate",
                            "where": "candidate.count == 0",
                            "required": False,
                        }
                    ],
                    "guard": "visible is not None",
                    "outputs": {
                        "sighting": {
                            "record": {
                                "type": "Sighting",
                                "fields": {
                                    "subject": {"ref": "visible.ref"},
                                    "observation": {"ref": "occurrence"},
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
            "actor": "actor_0",
            "trigger_event": "birth",
            "source_key": "c0.test.sprite.observe",
            "event_type": "c0.test.sprite.observe.event",
            "causal_key": "c0.test.sprite.observe.law",
            "law": {"ref": "observe", "args": {}},
        }
    )
    return lib, ports, source, assets


def test_post_birth_observation_records_actual_ref_only_in_recipient_owner():
    session = _compile(*observation_documents()[:3]).start(observation_documents()[3])
    assert dict(session.read("seat_0").fields).get("actor_0.sighting") is None
    submit_first(session)
    (birth,) = session.author_actor_instances()
    sighting = dict(session.read("seat_0").fields)["actor_0.sighting"]
    assert sighting.subject == birth.actor
    record = next(
        item
        for item in session._runtime.occurrence_history()
        if item.source.value == "c0.test.sprite.observe"
    )
    assert sighting.observation == record.occurrence
    assert dict(session.author_snapshot().owners)["actor_1"].sighting is None


def test_failed_local_observation_guard_keeps_birth_but_grants_no_knowledge():
    lib, ports, source, assets = observation_documents()
    source["lawdefs"][-1]["body"]["law"]["bindings"][0]["where"] = "candidate.count > 0"
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    assert len(session.author_actor_instances()) == 1
    assert dict(session.read("seat_0").fields).get("actor_0.sighting") is None
    assert not any(
        item.source.value == "c0.test.sprite.observe"
        for item in session._runtime.occurrence_history()
    )


def test_multiple_matching_instances_do_not_choose_an_arbitrary_subject():
    lib, ports, source, assets = observation_documents()
    assets["opening_actors"] = [
        {"kind": "sprite", "state": {"count": 0, "awake": True}, "debt": 20}
    ]
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    assert len(session.author_actor_instances()) == 2
    assert dict(session.read("seat_0").fields).get("actor_0.sighting") is None
    assert not any(
        item.source.value == "c0.test.sprite.observe"
        for item in session._runtime.occurrence_history()
    )


@pytest.mark.parametrize("domain", ["not_a_list", [{"kind": "unknown", "wrapper": "missing"}]])
def test_scene_event_cannot_silently_discard_read_actor_domain_declaration(domain):
    lib, ports, source, _ = documents(path="event")
    ports["events"][0]["read_actor_domains"] = domain
    with pytest.raises(C0LawError, match="finite list|missing or unknown fields"):
        _compile(lib, ports, source)


def test_scene_event_accepts_an_explicit_empty_read_domain_declaration():
    lib, ports, source, _ = documents(path="event")
    ports["events"][0]["read_actor_domains"] = []
    assert _compile(lib, ports, source).events[0][1].ports.read_actor_domains == ()


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_type",
        "unknown_kind",
        "private_field",
        "aliased_root",
        "narrow_range",
        "short_wrapper",
    ],
)
def test_observation_ports_reject_missing_or_undeclared_authority(mutation):
    lib, ports, source, _ = observation_documents()
    domain = ports["events"][-1]["read_actor_domains"][0]
    if mutation == "wrong_type":
        domain["fields"]["count"] = "awake"
    elif mutation == "unknown_kind":
        domain["kind"] = "unknown"
    elif mutation == "aliased_root":
        domain["name"] = "actor"
    elif mutation == "narrow_range":
        next(row for row in lib["records"] if row["name"] == "Basis")["fields"][1]["type"] = {
            "int": [0, 10]
        }
    elif mutation == "short_wrapper":
        next(row for row in lib["records"] if row["name"] == "Domain")["fields"][0]["type"][
            "tuple"
        ]["max"] = 1
    else:
        source["lawdefs"][-1]["body"]["law"]["bindings"][0]["where"] = "candidate.awake"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_event_family_keeps_its_real_actor_product():
    lib, ports, source, assets = documents(path="event")
    event = source["events"][0]
    source["events"][0] = {
        "family": "birth",
        "template": "birth",
        "for_actions": ["count_0"],
        "source_prefix": "c0.test.sprite.family-birth",
        "law": event["law"],
        "actor_product": event["actor_product"],
    }
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    (birth,) = session.author_actor_instances()
    actual = next(
        record
        for record in session._runtime.occurrence_history()
        if record.occurrence == birth.formed_by
    )
    assert actual.source.value == "c0.test.sprite.family-birth-count_0"


def test_checked_read_domain_rebinds_without_frontend_or_native_profile_capture(monkeypatch):
    from nomos_c0 import graph_frontend_v1
    from nomos_c0.program_binding_v1 import bind_program

    lib, ports, source, assets = observation_documents()
    program = _compile(lib, ports, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("Bind must not parse Source")

    monkeypatch.setattr(graph_frontend_v1, "check_owner_graph", forbidden)
    rebound = bind_program(program.program_ir, program.world_layout)
    session = rebound.start(deepcopy(assets))
    submit_first(session)
    assert (
        dict(session.read("seat_0").fields)["actor_0.sighting"].subject
        == session.author_actor_instances()[0].actor
    )
