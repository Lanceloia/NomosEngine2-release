"""Local values compose with actual roles and trusted private singleton selectors."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_fixed_and_ranged_participants_v1 import _resource_world
from test_multi_participant_action_v0 import _compile, _owners
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _layout

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.visibility_binding_v1 import bind_visibility
from nomos_c0.world_binding_v1 import bind_world


def _world():
    lib, ports, source, assets = _resource_world()
    lib["records"].append(
        {
            "name": "Aim",
            "fields": [{"name": "label", "type": {"str": [1, 32]}}],
            "invariant": None,
        }
    )
    lib["records"][1]["fields"].append(
        {
            "name": "aims",
            "type": {"tuple": {"item": "Aim", "max": 8}},
        }
    )
    lib["owners"][1]["seat_read"].append("aims")
    for state in assets["opening"].values():
        if "known" in state:
            state["aims"] = []
    assets["opening"]["maker"]["aims"] = [{"label": "near"}, {"label": "far"}]
    lib["records"][3]["fields"].append({"name": "aim", "type": {"str": [1, 32]}})
    lib["records"][4]["fields"].append({"name": "aim", "type": {"str": [1, 32]}})
    for item in assets["opening_objects"]:
        if item["kind"] == "tool":
            item["state"]["aim"] = "unset"
    lib["lawdefs"][0]["body"]["value"]["outputs"]["aim"] = {"ref": "payload.aim"}
    action = ports["actions"][0]
    action["effects"]["tool"]["aim"] = "aim"
    action["value"]["read"].extend(["actor.aims", "payload.aim"])
    action["value"]["write_paths"].append("tool.aim")
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    source["seats"][0]["read"].append("maker.aims")
    offer = source["seats"][0]["offers"][0]
    offer["for_each"] = {"collection": {"ref": "actor.aims"}, "as": "aim"}
    offer["for_each_participants"]["victim"] = {"fixed_actor": "a", "private": True}
    offer["label"] = [{"ref": "tool.label"}, {"const": " / "}, {"ref": "aim.label"}]
    del offer["payload"]["victim"]
    offer["payload"]["aim"] = {"ref": "aim.label"}
    return lib, ports, source, assets


def test_two_objects_times_two_values_publish_actual_choice_and_private_owner():
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    offers = session.offers("maker")
    assert [offer.label for offer in offers] == [
        "one / near",
        "one / far",
        "two / near",
        "two / far",
    ]
    assert session.author_snapshot() == before
    assert all(set(dict(offer.payload)) == {"tool", "resource", "aim"} for offer in offers)
    chosen = offers[-1]
    selected = dict(chosen.payload)
    assert selected["aim"] == "far"
    assert selected["tool"] != dict(offers[0].payload)["tool"]
    assert selected["resource"] == dict(offers[0].payload)["resource"]
    published = session.submit("maker", chosen.entry, selected)
    assert isinstance(published, K0Published)
    rows = published.occurrences[0].selected_owners
    assert [(row.name, row.selector) for row in rows] == [
        ("resource", selected["resource"]),
        ("tool", selected["tool"]),
        ("victim", "a"),
    ]
    assert len({row.owner for row in rows}) == 3
    tools = [
        item.current_state
        for item in session.author_object_instances()
        if item.individual.family == "tool"
    ]
    assert [(tool.ready, tool.aim) for tool in tools] == [(True, "unset"), (False, "far")]
    assert (
        next(
            item.current_state.units
            for item in session.author_object_instances()
            if item.individual.family == "resource"
        )
        == 1
    )
    assert _owners(session)["a"].enabled and not _owners(session)["b"].enabled


def test_independent_ir_bind_keeps_enum_and_exact_public_private_partition(monkeypatch):
    lib, ports, source, assets = _world()
    program = _compile(lib, ports, source)
    params = dict(program.visibility_ir.seats[0].offers[0].parameters)
    assert params["local_range"].alias == "aim"
    assert [
        (item.payload_field, item.member, item.condition) for item in params["private_actor_fields"]
    ] == [("victim", "a", None)]
    assert set(params["payload"]) == {"tool", "resource", "aim"}
    layout = _layout(program)
    _block_frontend(monkeypatch)
    import nomos_c0.participant_candidates_v1 as frontend

    monkeypatch.setattr(
        frontend, "compile_participant_offer", lambda *args: pytest.fail("frontend called")
    )
    rebound = bind_program(program.program_ir, layout)
    declaration = rebound.seats[0].offers[0]
    assert [
        (item.payload_field, item.member, item.condition)
        for item in declaration.private_actor_fields
    ] == [("victim", "a", None)]
    assert "victim" not in declaration.ports.roots
    assert "victim.enabled" not in declaration.ports.readable_paths
    session = rebound.start(assets)
    offer = session.offers("maker")[-1]
    result = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    bound_owner = next(owner.owner.key for owner in rebound.owners if owner.symbol == "a")
    assert result.occurrences[0].selected_owners[-1].owner == bound_owner


@pytest.mark.parametrize("override", ["a", "b"])
def test_client_cannot_supply_private_selector_even_matching_checked_value(override):
    lib, ports, source, assets = _world()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", offer.entry, {**dict(offer.payload), "victim": override})
    assert session.author_snapshot() == before


def test_hidden_object_and_stale_combination_never_write():
    lib, ports, source, assets = _world()
    assets["opening_objects"][0]["state"]["visible"] = False
    session = _compile(lib, ports, source).start(assets)
    assert [offer.label for offer in session.offers("maker")] == ["two / near", "two / far"]
    old = session.offers("maker")[-1]
    assert isinstance(session.submit("maker", old.entry, dict(old.payload)), K0Published)
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", old.entry, dict(old.payload))
    assert session.author_snapshot() == before


@pytest.mark.parametrize(
    "alias",
    [
        "actor",
        "scene",
        "tool",
        "tool_ref",
        "resource",
        "victim",
        "victim_ref",
        "for",
        "occurrence",
        "payload",
        "initiator",
    ],
)
def test_compile_rejects_local_alias_shadowing(alias):
    lib, ports, source, _ = _world()
    source["seats"][0]["offers"][0]["for_each"]["as"] = alias
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_collection",
        "scalar_collection",
        "computed_collection",
        "object_read",
        "hidden_label",
        "hidden_condition",
        "private_payload",
        "wrong_fixed",
        "non_singleton",
        "private_false",
    ],
)
def test_compile_rejects_read_escape_or_invalid_private_partition(fault):
    lib, ports, source, _ = _world()
    offer = source["seats"][0]["offers"][0]
    if fault == "foreign_collection":
        offer["for_each"]["collection"] = {"ref": "victim.aims"}
    elif fault == "scalar_collection":
        offer["for_each"]["collection"] = {"ref": "actor.name"}
    elif fault == "computed_collection":
        offer["for_each"]["collection"] = {"const": ()}
    elif fault == "object_read":
        offer["for_each_participants"]["tool"]["read"].remove("tool.label")
    elif fault == "hidden_label":
        offer["label"] = [{"ref": "victim.name"}]
    elif fault == "hidden_condition":
        offer["when"] = {"ref": "victim.enabled"}
    elif fault == "private_payload":
        offer["payload"]["victim"] = {"const": "a"}
    elif fault == "wrong_fixed":
        offer["for_each_participants"]["victim"]["fixed_actor"] = "b"
    elif fault == "non_singleton":
        source["actions"][0]["participants"]["victim"]["actors"] = ["a", "b"]
    else:
        offer["for_each_participants"]["victim"]["private"] = False
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_symbol",
        "wrong_slot",
        "duplicate_private",
        "missing_private",
        "public_private",
        "alias",
        "foreign_collection",
        "wrong_type",
        "hidden_label",
        "read_expansion",
        "budget",
    ],
)
def test_independent_bind_rejects_forged_enum_or_partition(fault):
    lib, ports, source, _ = _world()
    program = _compile(lib, ports, source)
    ir = program.visibility_ir
    seat = ir.seats[0]
    offer = seat.offers[0]
    params = dict(offer.parameters)
    offer_ports = offer.ports
    if fault == "wrong_symbol":
        params["private_actor_fields"] = (("victim", "b"),)
    elif fault == "wrong_slot":
        params["private_actor_fields"] = (("tool", "a"),)
    elif fault == "duplicate_private":
        params["private_actor_fields"] *= 2
    elif fault == "missing_private":
        params["private_actor_fields"] = ()
    elif fault == "public_private":
        params["payload"] = {
            **params["payload"],
            "victim": replace(params["payload"]["aim"], operation="const", operand="a"),
        }
    elif fault == "alias":
        params["local_range"] = replace(params["local_range"], alias="tool_ref")
    elif fault in ("foreign_collection", "wrong_type"):
        collection = params["local_range"].collection
        params["local_range"] = replace(
            params["local_range"],
            collection=replace(
                collection, operand="actor.name" if fault == "wrong_type" else "victim.aims"
            ),
        )
    elif fault == "hidden_label":
        params["labels"] = (replace(params["labels"][0], operand="victim.name"),)
    elif fault == "read_expansion":
        offer_ports = replace(
            offer_ports,
            readable_paths=offer_ports.readable_paths | {"tool.aim"},
            admission_readable_paths=offer_ports.admission_readable_paths | {"tool.aim"},
        )
    else:
        params["max_candidates"] += 1
    changed = replace(
        offer,
        ports=offer_ports,
        parameters=tuple((key, params[key]) for key, _ in offer.parameters),
    )
    forged = replace(ir, seats=(replace(seat, offers=(changed,)),))
    with pytest.raises(C0LawError):
        bind_visibility(forged, bind_world(program.world_ir, program.world_layout))


@pytest.mark.parametrize("fault", ["input", "work", "output", "cumulative"])
def test_collection_work_and_output_bounds_reject_without_prefix_or_effect(fault):
    lib, ports, source, assets = _world()
    if fault == "input":
        ports["offer_provider"]["limit"] = 1
    elif fault == "work":
        ports["offer_provider"]["limit"] = 3
        assets["opening"]["maker"]["aims"].append({"label": "third"})
        assets["opening_objects"][:0] = deepcopy(assets["opening_objects"][:2])
        source["seats"][0]["offers"][0]["visible_when"] = {"const": False}
    elif fault == "output":
        ports["offer_provider"]["limit"] = 3
    else:
        ports["offer_provider"]["limit"] = 4
        second = deepcopy(source["seats"][0]["offers"][0])
        second["label"].insert(0, {"const": "Other "})
        source["seats"][0]["offers"].append(second)
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    assert session.offers("maker") == ()
    faults = session.offer_faults("maker")
    assert len(faults) == 1 and faults[0].code == "value_state"
    assert session.author_snapshot() == before


def test_optional_local_range_combines_with_real_actor_range_and_alias_cannot_shadow_it():
    lib, ports, source, assets = _world()
    source["actions"][0]["participants"]["victim"]["actors"] = ["a", "b"]
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["victim"] = {
        "collection": {"ref": "actor.known"},
        "as": "candidate",
    }
    offer["payload"]["victim"] = {"ref": "candidate.name"}
    session = _compile(lib, ports, source).start(assets)
    offers = session.offers("maker")
    assert len(offers) == 8
    assert {dict(row.payload)["victim"] for row in offers} == {"a", "b"}
    chosen = offers[-1]
    assert isinstance(session.submit("maker", chosen.entry, dict(chosen.payload)), K0Published)
    assert _owners(session)["b"].enabled and not _owners(session)["a"].enabled
    offer["for_each"]["as"] = "candidate"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("private", [False, True])
def test_private_binding_is_optional_and_does_not_require_local_enum(private):
    lib, ports, source, assets = _world()
    offer = source["seats"][0]["offers"][0]
    del offer["for_each"]
    offer["label"] = [{"ref": "tool.label"}]
    offer["payload"]["aim"] = {"const": "near"}
    if not private:
        del offer["for_each_participants"]["victim"]["private"]
        offer["payload"]["victim"] = {"const": "a"}
    session = _compile(lib, ports, source).start(assets)
    offers = session.offers("maker")
    assert len(offers) == 2
    assert ("victim" not in dict(offers[0].payload)) is private
    assert isinstance(
        session.submit("maker", offers[0].entry, dict(offers[0].payload)), K0Published
    )


def test_local_values_preserve_formed_actor_ref_through_independent_bind(monkeypatch):
    from test_actor_formation_v1 import submit_first
    from test_selected_actor_participant_v1 import documents

    lib, ports, source, assets = documents()
    lib["records"].append(
        {
            "name": "Amount",
            "fields": [{"name": "value", "type": {"int": [1, 2]}}],
            "invariant": None,
        }
    )
    actor = next(row for row in lib["records"] if row["name"] == "Actor")
    actor["fields"].append({"name": "amounts", "type": {"tuple": {"item": "Amount", "max": 2}}})
    assets["opening"]["actor_0"]["amounts"] = [{"value": 1}, {"value": 2}]
    assets["opening"]["actor_1"]["amounts"] = []
    lib["owners"][1]["seat_read"].append("amounts")
    source["seats"][0]["read"].append("actor_0.amounts")
    attempt = next(row for row in lib["records"] if row["name"] == "FundAttempt")
    attempt["fields"].append({"name": "amount", "type": {"int": [1, 2]}})
    ports["actions"][-1]["value"]["read"].append("payload.amount")
    source["lawdefs"][-1]["body"]["value"]["outputs"]["count"] = {
        "add": [{"ref": "recipient.count"}, {"ref": "payload.amount"}]
    }
    offer = source["seats"][0]["offers"][-1]
    offer["for_each"] = {"collection": {"ref": "actor.amounts"}, "as": "amount"}
    offer["payload"]["amount"] = {"ref": "amount.value"}
    program = _compile(lib, ports, source)
    layout = _layout(program)
    _block_frontend(monkeypatch)
    session = bind_program(program.program_ir, layout).start(assets)
    submit_first(session)
    target = session.author_actor_instances()[0]
    session.continue_form("seat_0")
    before = session.author_snapshot()
    offers = [row for row in session.offers("seat_0") if row.entry == "fund"]
    assert [dict(row.payload) for row in offers] == [
        {"recipient": target.actor, "amount": 1},
        {"recipient": target.actor, "amount": 2},
    ]
    assert session.author_snapshot() == before
    chosen = offers[-1]
    result = session.submit("seat_0", chosen.entry, dict(chosen.payload))
    assert isinstance(result, K0Published)
    selected = result.occurrences[0].selected_owners[0]
    assert (selected.selector, selected.owner) == (target.actor, target.owner)
    assert session._runtime.read_actor(target.actor).view.count == 2


def test_multiple_private_roles_are_filled_without_hiding_selected_object():
    lib, ports, source, assets = _world()
    lib["records"][4]["fields"].append({"name": "witness", "type": {"str": [1, 32]}})
    action = ports["actions"][0]
    action["participants"].append(
        {
            "name": "witness",
            "selector": "closed_domain",
            "state": "Person",
            "payload_field": "witness",
            "write": False,
        }
    )
    action["effects"]["witness"] = {}
    source["actions"][0]["participants"]["witness"] = {"actors": ["b"]}
    source["seats"][0]["offers"][0]["for_each_participants"]["witness"] = {
        "fixed_actor": "b",
        "private": True,
    }
    program = _compile(lib, ports, source)
    session = bind_program(program.program_ir, _layout(program)).start(assets)
    offer = session.offers("maker")[-1]
    assert set(dict(offer.payload)) == {"tool", "resource", "aim"}
    result = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert [(row.name, row.selector) for row in result.occurrences[0].selected_owners][-2:] == [
        ("victim", "a"),
        ("witness", "b"),
    ]
    assert _owners(session)["a"].enabled and not _owners(session)["b"].enabled


def test_visibility_and_condition_see_bound_local_value_without_new_reads():
    lib, ports, source, assets = _world()
    offer = source["seats"][0]["offers"][0]
    offer["visible_when"] = "tool.visible and aim.label == 'far'"
    offer["when"] = "tool.ready and aim.label != 'near'"
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    assert [row.label for row in session.offers("maker")] == ["one / far", "two / far"]
    assert session.author_snapshot() == before
