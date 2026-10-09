"""Action domains consume sealed actual members in one atomic settlement."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _record, _value
from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt, _K0InMemoryRuleInput
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._owner_abi import _K0OwnerView
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_actor_formation_v1 import documents as formation_documents
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.world_binding_v1 import bind_world


def documents():
    lib, ports, source, assets = formation_documents()
    for name in ("Actor", "Sprite"):
        record = next(row for row in lib["records"] if row["name"] == name)
        record["fields"].append({"name": "position", "type": {"int": [0, 10]}})
    sprite = next(row for row in lib["records"] if row["name"] == "Sprite")
    sprite["fields"].append({"name": "name", "type": {"str": [1, 32]}})
    for name in ("actor_0", "actor_1"):
        assets["opening"][name]["position"] = 0
    assets["opening"]["actor_1"]["name"] = "actor_1"
    third = deepcopy(lib["owners"][-1])
    third.update(symbol="actor_2", key="c0.graph.actor_2")
    lib["owners"].append(third)
    source["owners"].append("actor_2")
    assets["opening"]["actor_2"] = {"name": "actor_2", "count": 0, "position": 1}
    newborn = source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"]
    newborn["record"]["fields"].update(position={"ref": "actor.count"}, name={"const": "same"})
    scene = lib["records"][0]
    scene["fields"].append({"name": "die_seed", "type": {"int": [0, (1 << 63) - 1]}})
    assets["opening"]["scene"]["die_seed"] = 1
    lib["records"] += [
        _record("Charge", {"units": {"int": [0, 5]}}),
        _record(
            "BlastAttempt",
            {
                "actor": {"str": [1, 64]},
                "left": {"str": [1, 64]},
                "right": {"str": [1, 64]},
                "resource": "individual_ref",
            },
        ),
    ]
    lib["object_kinds"] = [
        {
            "symbol": "charge",
            "sort": "TEST.CHARGE@1",
            "state": "Charge",
            "version": "1",
            "max_instances": 1,
        }
    ]
    source["object_kinds"] = [{"kind": "charge", "sort": "TEST.CHARGE@1"}]
    assets["opening_objects"] = [{"kind": "charge", "state": {"units": 2}}]
    participants = [
        {
            "name": name,
            "selector": "closed_domain",
            "state": "Actor",
            "payload_field": name,
            "write": True,
        }
        for name in ("left", "right")
    ] + [
        {
            "name": "resource",
            "selector": "individual",
            "state": "Charge",
            "payload_field": "resource",
            "write": True,
        }
    ]
    participants.sort(key=lambda row: row["name"])
    reads = [
        "actor.count",
        "actor.position",
        "scene.die_seed",
        "resource.units",
        "left.count",
        "left.position",
        "right.count",
        "right.position",
    ]
    ports["actions"].append(
        {
            "symbol": "blast",
            "actor": "actor_0",
            "payload": "BlastAttempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "participants": participants,
            "effects": {
                "scene": {"die_seed": "seed"},
                "actor": {"count": "count"},
                "left": {"count": "left"},
                "right": {"count": "right"},
                "resource": {"units": "units"},
            },
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": _value(
                reads,
                ["scene.die_seed", "actor.count", "left.count", "right.count", "resource.units"],
            ),
            "actor_domains": [
                {
                    "name": "sprites",
                    "kind": "sprite",
                    "value": _value(
                        [
                            "actor.count",
                            "actor.awake",
                            "actor.position",
                            "initiator.count",
                            "initiator.position",
                            "resource.units",
                            "scene.die_seed",
                        ],
                        ["actor.count"],
                        {"count": "actor.count"},
                    ),
                }
            ],
        }
    )
    value = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": "resource.units > 0",
        "outputs": {
            "action": {"ref": "occurrence"},
            "seed": {"die_next_seed": {"ref": "scene.die_seed"}},
            "count": {"add": [{"ref": "actor.count"}, 1]},
            "units": {"sub": [{"ref": "resource.units"}, 1]},
        },
    }
    for name in ("left", "right"):
        value["outputs"][name] = {
            "if": {
                "when": f"{name}.position == actor.position",
                "then": {"ref": "resource.units"},
                "else": {"ref": f"{name}.count"},
            }
        }
    source["lawdefs"] += [
        {"name": "blast", "family": "action", "formals": {}, "body": {"value": value}},
        {
            "name": "hit",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "actor.awake",
                    "outputs": {
                        "count": {
                            "if": {
                                "when": "actor.position == initiator.position",
                                "then": {
                                    "add": [{"ref": "resource.units"}, {"ref": "initiator.count"}]
                                },
                                "else": {"ref": "actor.count"},
                            }
                        }
                    },
                }
            },
        },
    ]
    source["actions"].append(
        {
            "name": "blast",
            "template": "blast",
            "actor": "actor_0",
            "source_key": "c0.test.blast",
            "event_type": "c0.test.blast.action",
            "law": {"ref": "blast", "args": {}},
            "participants": {
                "left": {"actors": ["actor_1"]},
                "right": {"actors": ["actor_2"]},
                "resource": {"kind": "charge"},
            },
            "actor_domain_effects": [{"name": "sprites", "law": {"ref": "hit", "args": {}}}],
        }
    )
    seat = source["seats"][0]
    seat["entries"].append("blast")
    seat["offers"].append(
        {
            "entry": "blast",
            "label": [{"const": "Blast"}],
            "when": True,
            "visible_when": True,
            "for_each_participants": {
                "left": {"fixed_actor": "actor_1"},
                "right": {"fixed_actor": "actor_2"},
                "resource": {"fixed_kind": "charge", "read": []},
            },
            "payload": {
                "left": {"const": "actor_1"},
                "right": {"const": "actor_2"},
                "resource": {"ref": "resource_ref"},
            },
        }
    )
    source["game_form"]["seats"][0]["costs"]["blast"] = 3
    source["game_form"]["seats"][0]["costs"]["count_0"] = 1
    source["actor_templates"][0]["first_debt"] = 20
    return lib, ports, source, assets


def settle(session, entry):
    ready(session)
    action = dict(session.program.actions)[entry]
    payload = (
        {"actor": "person_0", "target": "person_0"}
        if entry == "count_0"
        else {
            "actor": "person_0",
            "left": "actor_1",
            "right": "actor_2",
            "resource": session.author_object_instances()[0].individual,
        }
    )
    return session._runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type(**payload))
    )


def ready(session):
    opportunity = session._runtime.action_opportunity()
    if opportunity is None or opportunity.seat != "seat_0":
        session.continue_form("seat_0")


def test_two_real_births_and_static_targets_share_one_action_prestate():
    lib, ports, source, assets = documents()
    before = deepcopy((lib, ports, source, assets))
    session = _compile(lib, ports, source).start(assets)
    for _ in range(2):
        assert isinstance(settle(session, "count_0"), K0Published)
    bindings = session._runtime.actors()
    assert all(binding.formed_by is not None for binding in bindings)
    assert [item.current_state.name for item in session.author_actor_instances()] == [
        "same",
        "same",
    ]
    result = settle(session, "blast")
    assert isinstance(result, K0Published)
    (occurrence,) = result.occurrences
    owners = dict(session.author_snapshot().owners)
    assert (owners["actor_0"].count, owners["actor_1"].count, owners["actor_2"].count) == (3, 2, 0)
    assert [item.current_state.count for item in session.author_actor_instances()] == [4, 0]
    assert session.author_object_instances()[0].current_state.units == 1
    assert owners["scene"].die_seed != 1
    assert occurrence.participants.actors == tuple(
        ("sprites", binding.actor, binding.owner) for binding in bindings
    )
    assert {binding.owner for binding in bindings}.isdisjoint(
        selected.owner for selected in occurrence.selected_owners
    )
    assert len({b.actor for b in bindings}) == len({b.owner for b in bindings}) == 2
    assert occurrence.source.value == "c0.test.blast"
    assert not any("sprites" in path for path, _ in session.read("seat_0").fields)
    assert all("sprites" not in dict(offer.payload) for offer in session.offers("seat_0"))
    assert (lib, ports, source, assets) == before


def test_empty_domain_then_later_birth_is_seen_by_next_action():
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    empty = settle(session, "blast")
    assert isinstance(empty, K0Published)
    assert empty.occurrences[0].participants.actors == ()
    assert isinstance(settle(session, "count_0"), K0Published)
    result = settle(session, "blast")
    assert isinstance(result, K0Published)
    assert len(result.occurrences[0].participants.actors) == 1
    assert session.author_object_instances()[0].current_state.units == 0


@pytest.mark.parametrize("fault", ["guard", "range", "invariant"])
def test_member_failure_keeps_resource_seed_owners_history_and_debts_atomic(fault):
    lib, ports, source, assets = documents()
    if fault == "guard":
        source["lawdefs"][-1]["body"]["value"]["guard"] = "actor.position == 0"
    elif fault == "range":
        output = source["lawdefs"][-1]["body"]["value"]["outputs"]["count"]
        output["if"]["else"] = {"add": [{"ref": "actor.count"}, 101]}
    else:
        sprite = next(row for row in lib["records"] if row["name"] == "Sprite")
        sprite["invariant"] = "state.count < 4"
    session = _compile(lib, ports, source).start(assets)
    settle(session, "count_0")
    settle(session, "count_0")
    ready(session)
    before = (
        session.author_snapshot(),
        session.author_object_instances(),
        session.author_actor_instances(),
        session._runtime.action_value_state(),
    )
    if fault == "guard":
        assert isinstance(settle(session, "blast"), K0NotAdmitted)
        assert not session._runtime._fatal
    else:
        with pytest.raises(K0SettlementDefect):
            settle(session, "blast")
        assert session._runtime._fatal
    assert (
        session.author_snapshot(),
        session.author_object_instances(),
        session.author_actor_instances(),
        session._runtime.action_value_state(),
    ) == before


def test_independent_bind_rekeys_nominal_carriers_and_runs_real_action(monkeypatch):
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    from test_nominal_signatures_v1 import forbid_frontend
    from test_world_binding_v1 import _forbid_checks

    from nomos_c0 import graph_frontend_v1

    layout = _layout(program)
    _forbid_checks(monkeypatch)
    monkeypatch.setattr(graph_frontend_v1, "check_owner_graph", forbid_frontend)
    rebound = bind_program(program.program_ir, layout)
    session = rebound.start(assets)
    assert isinstance(settle(session, "count_0"), K0Published)
    result = settle(session, "blast")
    assert isinstance(result, K0Published)
    assert session.author_actor_instances()[0].current_state.count == 3
    assert result.occurrences[0].source == dict(rebound.actions)["blast"].source_key


@pytest.mark.parametrize(
    "fault",
    [
        "kind",
        "missing",
        "duplicate",
        "field",
        "output",
        "initiator_write",
        "scene_write",
        "read",
        "family",
    ],
)
def test_author_domain_contract_rejects_without_mutating_input(fault):
    lib, ports, source, _ = documents()
    domain = ports["actions"][-1]["actor_domains"][0]
    if fault == "kind":
        domain["kind"] = "unknown"
    elif fault == "missing":
        source["actions"][-1]["actor_domain_effects"] = []
    elif fault == "duplicate":
        ports["actions"][-1]["actor_domains"] *= 2
    elif fault == "field":
        ports["actions"][-1]["actor_domains"][0]["value"]["outputs"]["count"] = "actor.awake"
    elif fault == "output":
        source["lawdefs"][-1]["body"]["value"]["outputs"]["count"] = True
    elif fault.endswith("write"):
        domain["value"]["write_paths"].append(
            "initiator.count" if fault == "initiator_write" else "scene.die_seed"
        )
    elif fault == "read":
        domain["value"]["read"].remove("initiator.position")
    else:
        source["lawdefs"][-1]["family"] = "due_event"
        source["lawdefs"][-1]["body"] = {"law": source["lawdefs"][-1]["body"]["value"]}
    before = deepcopy((lib, ports, source))
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
    assert (lib, ports, source) == before


@pytest.mark.parametrize("fault", ["kind", "effect", "root", "output"])
def test_independent_bind_rejects_changed_domain_contract(fault):
    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    world = program.world_ir
    action = next(row for row in world.transitions if row.symbol == "blast")
    (domain,) = action.actor_domains
    if fault == "kind":
        domain = replace(domain, kind="unknown")
    elif fault == "effect":
        domain = replace(domain, effects=(("awake", "count"),))
    else:
        value = domain.value.value
        if fault == "root":
            value = replace(
                value,
                ports=replace(
                    value.ports,
                    roots=tuple(
                        ("rogue" if name == "initiator" else name, kind)
                        for name, kind in value.ports.roots
                    ),
                ),
            )
        else:
            output_type = replace(value.ports.outputs[0][1], symbol="bool")
            value = replace(value, ports=replace(value.ports, outputs=(("count", output_type),)))
        domain = replace(domain, value=replace(domain.value, value=value))
    changed = replace(action, actor_domains=(domain,))
    with pytest.raises(C0LawError):
        forged = replace(
            world, transitions=tuple(changed if row is action else row for row in world.transitions)
        )
        bind_world(forged, program.world_layout)


def test_same_kind_self_domain_keeps_kernel_alias_guard():
    lib, ports, source, _ = documents()
    ports["actions"][2]["actor_domains"] = deepcopy(ports["actions"][-1]["actor_domains"])
    domain = ports["actions"][2]["actor_domains"][0]["value"]
    domain["read"] = ["actor.count", "initiator.count"]
    source["actions"][2]["actor_domain_effects"] = deepcopy(
        source["actions"][-1]["actor_domain_effects"]
    )
    source["lawdefs"][-1]["body"]["value"].update(
        guard=True, outputs={"count": {"ref": "actor.count"}}
    )
    with pytest.raises(K0ProfileError, match="alias"):
        _compile(lib, ports, source)


def test_selected_actor_kind_domain_keeps_kernel_alias_guard():
    from test_selected_actor_participant_v1 import documents as selected_documents

    lib, ports, source, _ = selected_documents()
    ports["actions"][-1]["actor_domains"] = [
        {
            "name": "sprites",
            "kind": "sprite",
            "value": _value(["actor.count"], ["actor.count"], {"count": "actor.count"}),
        }
    ]
    source["lawdefs"].append(
        {
            "name": "domain",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"count": {"ref": "actor.count"}},
                }
            },
        }
    )
    source["actions"][-1]["actor_domain_effects"] = [
        {
            "name": "sprites",
            "law": {"ref": "domain", "args": {}},
        }
    ]
    with pytest.raises(K0ProfileError, match="alias"):
        _compile(lib, ports, source)


def test_unselected_kind_does_not_join_domain_even_with_same_carrier_and_name():
    lib, ports, source, assets = documents()
    add_other_kind(lib, ports, source)
    assets["opening_actors"] = [
        {
            "kind": "other",
            "debt": 20,
            "state": {"count": 7, "position": 0, "name": "same", "awake": False},
        }
    ]
    session = _compile(lib, ports, source).start(assets)
    settle(session, "count_0")
    untouched = next(
        item for item in session.author_actor_instances() if item.actor.family == "other"
    )
    result = settle(session, "blast")
    assert isinstance(result, K0Published)
    assert all(ref.family == "sprite" for _, ref, _ in result.occurrences[0].participants.actors)
    assert (
        next(item for item in session.author_actor_instances() if item.actor.family == "other")
        == untouched
    )


def add_other_kind(lib, ports, source):
    other = deepcopy(lib["actor_kinds"][0])
    other["symbol"] = "other"
    lib["actor_kinds"].append(other)
    ability = deepcopy(ports["actions"][2])
    ability.update(symbol="other_step", actor={"self": "other"})
    ports["actions"].append(ability)
    action = deepcopy(source["actions"][2])
    action.update(
        name="other_step",
        template="other_step",
        actor={"self": "other"},
        source_key="c0.test.other.step",
        event_type="c0.test.other.step.action",
    )
    source["actions"].append(action)
    template = deepcopy(source["actor_templates"][0])
    template.update(
        kind="other",
        entries=["other_step"],
        costs={"other_step": 1},
        offers=[{"entry": "other_step", "label": "Step", "when": True, "payload": {}}],
    )
    source["actor_templates"].append(template)


def test_same_carrier_selected_roots_do_not_expand_domain_read_authority():
    lib, ports, source, _ = documents()
    domain = ports["actions"][-1]["actor_domains"][0]
    domain["value"]["read"].append("left.count")
    source["lawdefs"][-1]["body"]["value"]["outputs"]["count"] = {"ref": "right.count"}
    with pytest.raises(C0LawError, match="read"):
        _compile(lib, ports, source)


def test_action_family_preserves_domain_effects_through_actual_compile_and_run():
    lib, ports, source, assets = documents()
    original = source["actions"].pop()
    source["actor_domains"] = [{"name": "casters", "actor_state": "Actor", "owners": ["actor_0"]}]
    source["actions"].append(
        {
            "family": "blast",
            "template": "blast",
            "domain": "casters",
            "source_prefix": "c0.test.blast",
            "law": original["law"],
            "participants": original["participants"],
            "actor_domain_effects": original["actor_domain_effects"],
        }
    )
    source["seats"][0]["entries"][-1] = "blast_actor_0"
    source["seats"][0]["offers"][-1]["entry"] = "blast_actor_0"
    costs = source["game_form"]["seats"][0]["costs"]
    costs["blast_actor_0"] = costs.pop("blast")
    before = deepcopy((lib, ports, source))
    program = _compile(lib, ports, source)
    assert (lib, ports, source) == before
    session = program.start(assets)
    settle(session, "count_0")
    ready(session)
    offer = next(item for item in session.offers("seat_0") if item.entry == "blast_actor_0")
    result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].source.value == "c0.test.blast-actor_0"
    assert session.author_actor_instances()[0].current_state.count == 3


@pytest.mark.parametrize("fault", [None, "read", "write"])
def test_same_carrier_initiator_remains_exact_and_read_only(fault):
    lib, ports, source, assets = documents()
    add_other_kind(lib, ports, source)
    ports["actions"][2]["actor_domains"] = [
        {
            "name": "others",
            "kind": "other",
            "value": _value(
                ["actor.count", "initiator.count"], ["actor.count"], {"count": "actor.count"}
            ),
        }
    ]
    source["actions"][2]["actor_domain_effects"] = [
        {
            "name": "others",
            "law": {"ref": "copy_initiator", "args": {}},
        }
    ]
    source["lawdefs"].append(
        {
            "name": "copy_initiator",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"count": {"ref": "initiator.count"}},
                }
            },
        }
    )
    value = ports["actions"][2]["actor_domains"][0]["value"]
    if fault == "read":
        value["read"].remove("initiator.count")
    elif fault == "write":
        value["write_paths"] = ["initiator.count"]
    if fault:
        with pytest.raises(C0LawError):
            _compile(lib, ports, source)
        return
    source["game_form"]["seats"][0]["eligible"] = False
    source["actor_templates"][-1]["eligible"] = False
    assets["opening_actors"] = [
        {
            "kind": kind,
            "debt": debt,
            "state": {"name": "same", "count": count, "position": 0, "awake": True},
        }
        for kind, debt, count in (("sprite", 0, 1), ("other", 20, 0))
    ]
    session = _compile(lib, ports, source).start(assets)
    session.continue_form("seat_0")
    caster = next(
        binding for binding in session._runtime.actors() if binding.actor.family == "sprite"
    )
    (offer,) = session.offers(caster.seat)
    result = session.submit(caster.seat, offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    states = {
        item.actor.family: item.current_state.count for item in session.author_actor_instances()
    }
    assert states == {"sprite": 2, "other": 1}


@pytest.mark.parametrize("fault", ["participant_owner", "participant_ref", "view_kind"])
def test_sealed_domain_evidence_and_published_participants_cannot_diverge(fault):
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    settle(session, "count_0")
    ready(session)
    action = dict(session.program.actions)["blast"]
    (binding,) = session._runtime.actors()
    resource = session.author_object_instances()[0]
    views = tuple(
        _K0OwnerView(
            session.program.world_layout.owners.owner(symbol).owner.key,
            state,
            {"actor_1": "left", "actor_2": "right"}.get(symbol),
        )
        for symbol, state in session.author_snapshot().owners
    ) + (
        _K0OwnerView(resource.owner, resource.current_state, "resource"),
        _K0OwnerView(
            binding.owner, session._runtime.read_actor(binding.actor).view, "sprites", binding.actor
        ),
    )
    payload = action.payload_type("person_0", "actor_1", "actor_2", resource.individual)
    spec = action.build_spec()
    projection = spec.admission_capability.admit(payload, views)
    assert projection is not None
    evidence, participants = projection.evidence, projection.participants
    if fault == "view_kind":
        (view,) = evidence.actor_views
        evidence = replace(
            evidence,
            actor_views=(replace(view, actor_ref=replace(view.actor_ref, family="wrong")),),
        )
    else:
        name, ref, owner = participants.actors[0]
        if fault == "participant_owner":
            owner = K0OwnerKey("c0.wrong.owner")
        else:
            ref = replace(ref, family="wrong")
        participants = replace(participants, actors=((name, ref, owner),))
    rule_input = _K0InMemoryRuleInput(
        K0OccurrenceRef(100),
        action.source_key,
        evidence,
        participants,
        (),
        None,
        _K0FixedTime(session.time),
    )
    with pytest.raises(K0ProfileError):
        spec.rule.evaluate(rule_input)


def test_static_participant_alias_still_rejects_before_domain_or_resource_write():
    lib, ports, source, assets = documents()
    source["actions"][-1]["participants"]["right"]["actors"] = ["actor_1"]
    offer = source["seats"][0]["offers"][-1]
    offer["for_each_participants"]["right"]["fixed_actor"] = "actor_1"
    offer["payload"]["right"] = {"const": "actor_1"}
    session = _compile(lib, ports, source).start(assets)
    settle(session, "count_0")
    ready(session)
    before = (
        session.author_snapshot(),
        session.author_actor_instances(),
        session.author_object_instances(),
        session._runtime.action_value_state(),
    )
    offer = next(item for item in session.offers("seat_0") if item.entry == "blast")
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert (
        session.author_snapshot(),
        session.author_actor_instances(),
        session.author_object_instances(),
        session._runtime.action_value_state(),
    ) == before
    assert not session._runtime._fatal
