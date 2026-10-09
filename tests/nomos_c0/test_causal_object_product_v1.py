"""Required causal Object products reuse real owner formation and atomic settlement."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _record, _value
from nomos_kernel import K0OccurrenceFamily
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from test_actor_formation_v1 import documents, submit_first
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.world_binding_v1 import bind_world


def product_documents(*, actor_event=False, capacity=2):
    lib, ports, source, assets = documents()
    lib["records"] += [
        _record(
            "Tool",
            {"label": {"str": [1, 32]}, "units": {"int": [0, 9]}, "formed": "occurrence_ref"},
        ),
        _record("ToolAttempt", {"actor": {"str": [1, 64]}, "item": "individual_ref"}),
        _record("Basis", {"ref": "actor_ref", "count": {"int": [0, 100]}}),
        _record("Domain", {"members": {"tuple": {"item": "Basis", "max": 4}}}),
    ]
    lib["records"][0]["fields"].append({"name": "product_done", "type": "bool"})
    assets["opening"]["scene"]["product_done"] = False
    lib["object_kinds"] = [
        {
            "symbol": "tool",
            "sort": "TEST.CAUSAL_TOOL@1",
            "state": "Tool",
            "version": "1",
            "max_instances": capacity,
        }
    ]
    source["object_kinds"] = [{"kind": "tool", "sort": "TEST.CAUSAL_TOOL@1"}]
    assets["opening_objects"] = []
    source["actor_templates"][0]["first_debt"] = 20
    initial = {
        "record": {
            "type": "Tool",
            "fields": {"label": {"const": "made"}, "units": 2, "formed": {"ref": "occurrence"}},
        }
    }
    value = _value(
        ["scene.product_done", "sprites.members"],
        ["scene.product_done"],
        {"done": "scene.product_done", "tool": "Tool"},
        ["Tool"],
    )
    value["fields"] = {"Basis": ["ref", "count"]}
    event = {
        "symbol": "produce",
        "form": "direct_scene",
        "actor": None,
        "actor_identity_field": None,
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
    guard = {
        "all": [
            {"not": {"ref": "scene.product_done"}},
            {
                "lt": [
                    0,
                    {
                        "count_matching": {
                            "collection": {"ref": "sprites.members"},
                            "as": "member",
                            "where": "member.count == 0",
                        }
                    },
                ]
            },
        ]
    }
    outputs = {"done": True, "tool": initial}
    if actor_event:
        event.update(form="direct_actor", actor="actor_0", actor_identity_field="name")
        event.pop("read_actor_domains")
        event["value"] = _value(
            ["actor.count"], ["actor.count"], {"count": "actor.count", "tool": "Tool"}, ["Tool"]
        )
        outputs = {"count": {"add": [{"ref": "actor.count"}, 1]}, "tool": initial}
        guard = True
    ports["events"].append(event)
    source["lawdefs"].append(
        {
            "name": "produce",
            "family": "direct_actor_event" if actor_event else "direct_event",
            "formals": {},
            "body": {
                "law": {"schema": "c0.value.v1", "bindings": [], "guard": guard, "outputs": outputs}
            },
        }
    )
    declaration = {
        "name": "produce",
        "template": "produce",
        "trigger_action": "count_0",
        "source_key": "test.produce",
        "event_type": "test.produce.event",
        "causal_key": "test.produce.law",
        "law": {"ref": "produce", "args": {}},
        "object_product": {"kind": "tool", "initial_output": "tool"},
    }
    if actor_event:
        declaration["actor"] = "actor_0"
    source["events"].append(declaration)
    ports["actions"].append(
        {
            "symbol": "use",
            "actor": "actor_0",
            "payload": "ToolAttempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "participants": [
                {
                    "name": "item",
                    "selector": "individual",
                    "state": "Tool",
                    "payload_field": "item",
                    "write": True,
                }
            ],
            "effects": {"scene": {}, "actor": {}, "item": {"units": "units"}},
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": _value(["item.units", "item.label"], ["item.units"]),
        }
    )
    source["lawdefs"].append(
        {
            "name": "use",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "item.units > 0",
                    "outputs": {
                        "units": {"sub": [{"ref": "item.units"}, 1]},
                        "action": {"ref": "occurrence"},
                    },
                }
            },
        }
    )
    source["actions"].append(
        {
            "name": "use",
            "template": "use",
            "actor": "actor_0",
            "source_key": "test.use",
            "event_type": "test.use.action",
            "participants": {"item": {"kind": "tool"}},
            "law": {"ref": "use", "args": {}},
        }
    )
    source["seats"][0]["entries"].append("use")
    source["seats"][0]["offers"].append(
        {
            "entry": "use",
            "for_each_participants": {
                "item": {"kind": "tool", "read": ["item.label", "item.units"]}
            },
            "label": [{"ref": "item.label"}],
            "visible_when": True,
            "when": "item.units > 0",
            "payload": {"item": {"ref": "item_ref"}},
        }
    )
    source["game_form"]["seats"][0]["costs"]["use"] = 1
    return lib, ports, source, assets


@pytest.mark.parametrize("actor_event", [False, True])
def test_action_to_event_forms_real_object_and_successor_uses_original_identity(actor_event):
    lib, ports, source, assets = product_documents(actor_event=actor_event)
    session = _compile(lib, ports, source).start(assets)
    assert session.author_object_instances() == ()
    result = submit_first(session)
    assert isinstance(result, K0Published)
    trigger, event = result.occurrences
    assert trigger.family is K0OccurrenceFamily.ACTION and event.family is K0OccurrenceFamily.EVENT
    (tool,) = session.author_object_instances()
    assert tool.formed_by == tool.current_state.formed == event.occurrence
    assert tool.predecessor == trigger.occurrence != tool.formed_by
    assert tool.owner != session.author_actor_instances()[0].owner
    session.continue_form("seat_0")
    offer = next(row for row in session.offers("seat_0") if row.entry == "use")
    assert dict(offer.payload)["item"] == tool.individual
    assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    current = session.author_object_instances()[0]
    assert current.individual == tool.individual and current.owner == tool.owner
    assert current.current_state.units == 1


def test_scene_domain_is_actual_readonly_and_once_marker_is_not_observer_state():
    lib, ports, source, assets = product_documents()
    session = _compile(lib, ports, source).start(assets)
    result = submit_first(session)
    actor = session.author_actor_instances()[0]
    event = result.occurrences[-1]
    assert event.participants.actors == (("sprites", actor.actor, actor.owner),)
    assert event.selected_owners == ()
    assert actor.current_state.count == 0
    assert dict(session.author_snapshot().owners)["scene"].product_done is True
    session.continue_form("seat_0")
    offer = next(row for row in session.offers("seat_0") if row.entry == "count_0")
    next_result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(next_result, K0Published) and len(next_result.occurrences) == 1
    assert len(session.author_object_instances()) == 1


def test_two_layouts_bind_without_frontend_and_keep_product_domain_contract(monkeypatch):
    lib, ports, source, assets = product_documents()
    program = _compile(lib, ports, source)
    layout = _layout(program)
    _block_frontend(monkeypatch)
    import nomos_c0.direct_scene_event_v1 as frontend

    monkeypatch.setattr(
        frontend, "compile_direct_scene_event", lambda *args: pytest.fail("frontend called")
    )
    for selected in (program.world_layout, layout):
        session = bind_program(program.program_ir, selected).start(assets)
        result = submit_first(session)
        assert isinstance(result, K0Published)
        (tool,) = session.author_object_instances()
        assert tool.formed_by == result.occurrences[-1].occurrence


@pytest.mark.parametrize("predecessor", ["scene_event", "actor_event", "due"])
def test_generic_scene_successor_reads_real_event_formed_actor(predecessor):
    lib, ports, source, assets = product_documents()
    _, birth_ports, birth_source, _ = documents(path="due" if predecessor == "due" else "event")
    del source["actions"][0]["actor_product"]
    del ports["actions"][0]["value"]["outputs"]["newborn"]
    del source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"]
    produce = source["events"][0]
    del produce["trigger_action"]
    if predecessor == "due":
        ports["due_events"] = birth_ports["due_events"]
        source["due_events"] = birth_source["due_events"]
        source["lawdefs"][1] = birth_source["lawdefs"][1]
        source["game_form"]["seats"][0]["eligible"] = False
        produce["trigger_event"] = source["due_events"][0]["name"]
    else:
        template = birth_ports["events"][0]
        declaration = birth_source["events"][0]
        law = birth_source["lawdefs"][-1]
        if predecessor == "actor_event":
            template.update(form="direct_actor", actor="actor_0", actor_identity_field="name")
            declaration.update(actor="actor_0")
            law["family"] = "direct_actor_event"
        ports["events"].insert(0, template)
        source["events"].insert(0, declaration)
        source["lawdefs"].append(law)
        produce["trigger_event"] = "birth"
    session = _compile(lib, ports, source).start(assets)
    if predecessor == "due":
        session.continue_form("seat_0")
    else:
        assert isinstance(submit_first(session), K0Published)
    (tool,) = session.author_object_instances()
    history = {record.occurrence: record for record in session._runtime.occurrence_history()}
    forming, basis = history[tool.formed_by], history[tool.predecessor]
    assert forming.source.value == "test.produce"
    assert basis.family is K0OccurrenceFamily.EVENT
    actor = session.author_actor_instances()[0]
    assert forming.participants.actors == (("sprites", actor.actor, actor.owner),)


@pytest.mark.parametrize("fault", ["false", "empty"])
def test_no_activation_has_no_object_and_no_physical_marker(fault):
    lib, ports, source, assets = product_documents()
    if fault == "false":
        source["lawdefs"][-2]["body"]["law"]["guard"] = False
    else:
        source["actions"][0]["actor_product"]["cardinality"] = "zero_or_one"
        ports["actions"][0]["value"]["outputs"]["newborn"] = {"optional": "Sprite"}
        source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"] = None
    session = _compile(lib, ports, source).start(assets)
    assert isinstance(submit_first(session), K0Published)
    assert session.author_object_instances() == ()
    assert dict(session.author_snapshot().owners)["scene"].product_done is False


@pytest.mark.parametrize("fault", ["capacity", "state", "successor"])
def test_product_defect_rolls_back_trigger_actor_birth_scene_marker_and_object(fault):
    lib, ports, source, assets = product_documents(capacity=1)
    if fault == "capacity":
        # The second checked causal source forms into the same finite family.
        extra = deepcopy(source["events"][0])
        extra.update(
            name="second",
            trigger_event="produce",
            source_key="test.second",
            event_type="test.second.event",
            causal_key="test.second.law",
        )
        del extra["trigger_action"]
        extra["law"] = {"ref": "second", "args": {}}
        source["events"].append(extra)
        law = deepcopy(source["lawdefs"][-2])
        law["name"] = "second"
        law["body"]["law"]["guard"] = True
        source["lawdefs"].append(law)
    elif fault == "state":
        next(row for row in lib["records"] if row["name"] == "Tool")["invariant"] = (
            "state.units == 0"
        )
    else:
        next(row for row in lib["records"] if row["name"] == "Scene")["invariant"] = (
            "state.signal != 'broken'"
        )
        ports["events"].append(
            {
                "symbol": "fail_later",
                "form": "direct_scene",
                "actor": None,
                "actor_identity_field": None,
                "value": _value(["scene.signal"], ["scene.signal"], {"signal": "scene.signal"}),
            }
        )
        source["lawdefs"].append(
            {
                "name": "fail_later",
                "family": "direct_event",
                "formals": {},
                "body": {
                    "law": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": True,
                        "outputs": {"signal": {"const": "broken"}},
                    }
                },
            }
        )
        source["events"].append(
            {
                "name": "fail_later",
                "template": "fail_later",
                "trigger_event": "produce",
                "source_key": "test.break",
                "event_type": "test.break.event",
                "causal_key": "test.break.law",
                "law": {"ref": "fail_later", "args": {}},
            }
        )
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    with pytest.raises(K0SettlementDefect):
        submit_first(session)
    assert session.author_snapshot().owners == before.owners
    assert session._runtime.occurrence_history() == before.occurrences
    assert session.author_object_instances() == () and session.author_actor_instances() == ()


@pytest.mark.parametrize(
    "fault", ["kind", "output", "optional", "multi", "domain_alias", "domain_field", "actor_write"]
)
def test_compile_rejects_nonclosed_product_or_read_domain(fault):
    lib, ports, source, _ = product_documents()
    product = source["events"][0]["object_product"]
    if fault == "kind":
        product["kind"] = "missing"
    elif fault == "output":
        product["initial_output"] = "done"
    elif fault in ("optional", "multi"):
        product["cardinality"] = "zero_or_one" if fault == "optional" else "many"
    elif fault == "domain_alias":
        ports["events"][0]["read_actor_domains"][0]["name"] = "scene"
    elif fault == "domain_field":
        ports["events"][0]["read_actor_domains"][0]["fields"]["count"] = "awake"
    else:
        ports["events"][0]["value"]["outputs"]["done"] = "actor.count"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("fault", ["kind", "output", "read_kind", "read_field", "write"])
def test_independent_bind_rejects_forged_product_or_domain(fault):
    lib, ports, source, _ = product_documents()
    program = _compile(lib, ports, source)
    world = program.world_ir
    event = next(row for row in world.transitions if row.kind == "scene_event")
    if fault == "kind":
        changed = replace(event, object_product=("missing", "tool"))
    elif fault == "output":
        changed = replace(event, object_product=("tool", "done"))
    elif fault in ("read_kind", "read_field"):
        domain = event.actor_reads[0]
        changed = replace(
            event,
            actor_reads=(
                replace(domain, kind="missing")
                if fault == "read_kind"
                else replace(domain, fields=(("count", "awake"),)),
            ),
        )
    else:
        changed = replace(event, effects=(("actor", "count", "done"),))
    with pytest.raises(C0LawError):
        forged = replace(
            world, transitions=tuple(changed if row is event else row for row in world.transitions)
        )
        bind_world(forged, program.world_layout)
