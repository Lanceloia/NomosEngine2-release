"""One ranged Object and a fixed resource need no invented Actor participant."""

from dataclasses import asdict, replace

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _compile, _world
from test_nominal_signatures_v1 import assert_symbolic
from test_world_binding_v1 import _layout

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.visibility_binding_v1 import bind_visibility
from nomos_c0.world_binding_v1 import bind_world


def _objects_only_world():
    lib, ports, source, assets = _world()
    lib["owners"] = [owner for owner in lib["owners"] if owner["symbol"] in ("scene", "maker")]
    source["owners"] = ["scene", "maker"]
    assets["opening"] = {
        name: state for name, state in assets["opening"].items() if name in source["owners"]
    }
    assets["opening"]["maker"]["known"] = []
    lib["object_kinds"].append(
        {
            "symbol": "resource",
            "sort": "EXAMPLE.RESOURCE@1",
            "state": "Tool",
            "version": "resource-v1",
            "max_instances": 1,
        }
    )
    assets["opening_objects"].append(
        {"kind": "resource", "state": {"label": "resource", "ready": True, "visible": True}}
    )
    attempt = next(record for record in lib["records"] if record["name"] == "EnableAttempt")
    attempt["fields"] = [field for field in attempt["fields"] if field["name"] != "victim"]
    attempt["fields"].append({"name": "resource", "type": "individual_ref"})
    action = ports["actions"][0]
    action["participants"] = [
        action["participants"][0],
        {
            "name": "resource",
            "selector": "individual",
            "state": "Tool",
            "payload_field": "resource",
            "write": True,
        },
    ]
    action["participants"].sort(key=lambda item: item["name"])
    action["effects"] = {
        "scene": {},
        "actor": {},
        "tool": {"ready": "ready"},
        "resource": {"ready": "resource_ready"},
    }
    action["value"]["read"] = ["tool.label", "tool.ready", "tool.visible", "resource.ready"]
    action["value"]["write_paths"] = ["tool.ready", "resource.ready"]
    value = lib["lawdefs"][0]["body"]["value"]
    value["guard"] = {
        "all": [{"ref": "tool.ready"}, {"ref": "tool.visible"}, {"ref": "resource.ready"}]
    }
    del value["outputs"]["enabled"]
    value["outputs"]["resource_ready"] = {"const": False}
    source["actions"][0]["participants"] = {
        "tool": {"kind": "tool"},
        "resource": {"kind": "resource"},
    }
    source["object_kinds"].append({"kind": "resource", "sort": "EXAMPLE.RESOURCE@1"})
    source["seats"][0]["offers"] = [
        {
            "entry": "enable",
            "for_each_participants": {
                "tool": {"kind": "tool", "read": ["tool.label", "tool.ready", "tool.visible"]},
                "resource": {"fixed_kind": "resource", "read": ["resource.ready"]},
            },
            "label": [{"const": "Use "}, {"ref": "tool.label"}],
            "visible_when": {"ref": "tool.visible"},
            "when": {"all": [{"ref": "tool.ready"}, {"ref": "resource.ready"}]},
            "payload": {"tool": {"ref": "tool_ref"}, "resource": {"ref": "resource_ref"}},
        }
    ]
    return lib, ports, source, assets


@pytest.mark.parametrize("chosen", ["one", "two"])
def test_one_law_uses_a_real_selected_object_and_fixed_resource_without_another_actor(chosen):
    lib, ports, source, assets = _objects_only_world()
    session = _compile(lib, ports, source).start(assets)
    assert len(session.program.seats) == 1
    assert len(session.program.owners) == 2
    assert [(offer.label, len(offer.payload)) for offer in session.offers("maker")] == [
        ("Use one", 2),
        ("Use two", 2),
    ]
    offer = next(offer for offer in session.offers("maker") if offer.label == "Use " + chosen)
    published = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(published, K0Published)
    states = {
        item.current_state.label: item.current_state for item in session.author_object_instances()
    }
    assert not states[chosen].ready and not states["resource"].ready
    assert states["two" if chosen == "one" else "one"].ready
    assert {owner.name for owner in published.occurrences[0].selected_owners} == {
        "tool",
        "resource",
    }
    assert session.offers("maker") == ()
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", offer.entry, dict(offer.payload))
    assert session.author_snapshot() == before


def test_missing_fixed_resource_or_hidden_object_does_not_generate_an_option():
    lib, ports, source, assets = _objects_only_world()
    program = _compile(lib, ports, source)
    assets["opening_objects"][1]["state"]["visible"] = False
    session = program.start(assets)
    assert [offer.label for offer in session.offers("maker")] == ["Use one"]
    assets["opening_objects"] = assets["opening_objects"][:2]
    assert program.start(assets).offers("maker") == ()


@pytest.mark.parametrize("fault", ["resource_ref", "alias", "undeclared_read", "actor_label"])
def test_object_resource_offer_checks_exact_selector_domain_and_projection(fault):
    lib, ports, source, _ = _objects_only_world()
    offer = source["seats"][0]["offers"][0]
    if fault == "resource_ref":
        offer["payload"]["resource"] = {"ref": "tool_ref"}
    elif fault == "alias":
        source["actions"][0]["participants"]["resource"] = {"kind": "tool"}
    elif fault == "undeclared_read":
        offer["for_each_participants"]["resource"]["read"].append("resource.visible")
    else:
        offer["label"].append({"ref": "candidate.name"})
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_foreign_resource_and_spent_target_are_rejected_without_owner_writes():
    lib, ports, source, assets = _objects_only_world()
    program = _compile(lib, ports, source)
    session, foreign = program.start(assets), program.start(assets)
    action = dict(program.actions)["enable"]
    offer = session.offers("maker")[0]
    values = dict(offer.payload)
    foreign_resource = next(
        item.individual
        for item in foreign.author_object_instances()
        if item.individual.family == "resource"
    )
    before, objects = session.author_snapshot(), session.author_object_instances()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key,
                action.payload_type(actor="maker", tool=values["tool"], resource=foreign_resource),
            )
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before and session.author_object_instances() == objects
    assert isinstance(session.submit("maker", offer.entry, values), K0Published)
    before, objects = session.author_snapshot(), session.author_object_instances()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key, action.payload_type(actor="maker", **values)
            )
        ),
        K0NotAdmitted,
    )
    assert session.author_snapshot() == before and session.author_object_instances() == objects


def test_object_resource_visibility_ir_rebinds_without_frontend_under_two_layouts(monkeypatch):
    from test_visibility_binding_v1 import _block_frontend

    lib, ports, source, assets = _objects_only_world()
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    assert_symbolic(program.visibility_ir)
    assert program.seats[0].offers[0].actor_range is None
    _block_frontend(monkeypatch)
    outcomes = []
    for layout in (program.world_layout, alternate):
        session = bind_program(program.program_ir, layout).start(assets)
        offer = session.offers("maker")[0]
        published = session.submit("maker", offer.entry, dict(offer.payload))
        assert isinstance(published, K0Published)
        outcomes.append(
            tuple(asdict(item.current_state) for item in session.author_object_instances())
        )
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize(
    "fault", ["absent", "alias", "foreign_domain", "domain_type", "collection", "identity"]
)
def test_actor_range_is_one_checked_optional_bundle_at_ir_bind(fault):
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    offer = seat.offers[0]
    actor_range = dict(offer.parameters)["actor_range"]
    changed = (
        None
        if fault == "absent"
        else replace(
            actor_range,
            **{
                "alias": {"alias": "scene"},
                "foreign_domain": {"domain": ("maker",)},
                "domain_type": {"domain": list(actor_range.domain)},
                "collection": {"collection": True},
                "identity": {"identity_field": "other"},
            }[fault],
        )
    )
    forged = replace(
        ir,
        seats=(
            replace(
                seat,
                offers=(
                    replace(
                        offer,
                        parameters=tuple(
                            (name, changed if name == "actor_range" else value)
                            for name, value in offer.parameters
                        ),
                    ),
                ),
            ),
            *ir.seats[1:],
        ),
    )
    with pytest.raises(C0LawError):
        bind_visibility(forged, bind_world(program.world_ir, program.world_layout))


def test_absent_actor_range_still_fills_an_explicit_fixed_actor_argument():
    lib, ports, source, assets = _world()
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["victim"] = {"fixed_actor": "a"}
    offer["payload"]["victim"] = {"const": "a"}
    del offer["label"][2:]
    session = _compile(lib, ports, source).start(assets)
    assert [item.label for item in session.offers("maker")] == ["Use one", "Use two"]
    chosen = session.offers("maker")[0]
    assert dict(chosen.payload)["victim"] == "a"
    assert isinstance(session.submit("maker", chosen.entry, dict(chosen.payload)), K0Published)
    owners = dict(session.author_snapshot().owners)
    assert owners["a"].enabled and not owners["b"].enabled
