"""Conditional effects couple scalar obligations without a second evaluator."""

from __future__ import annotations

from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._atomic_inmemory_session import K0SettlementDefect
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_value_effect_ir_v0 import Supply, _compile, _ports, _source

from nomos_c0 import C0LawError
from nomos_c0 import composable_value_v1 as values
from nomos_c0.composable_value_v1 import C0ValueRangeError

MAX = (1 << 63) - 1


def test_inactive_debit_keeps_each_endpoint_without_reading_an_unknown_cost():
    source = _source()
    source["effects"][0]["spend"].update(
        when="supply.maybe_cost is not None", amount="supply.maybe_cost"
    )
    program = _compile(source)
    result = program.evaluate({"supply": Supply(0, 99)}, occurrence=K0OccurrenceRef(1))
    assert result == {"stock": 0, "mirrored": 99, "action": K0OccurrenceRef(1)}
    active = program.evaluate(
        {"supply": Supply(3, 99, maybe_cost=2)}, occurrence=K0OccurrenceRef(2)
    )
    assert active["stock"] == active["mirrored"] == 1
    assert program.false_guard_clauses({"supply": Supply(1, 99, maybe_cost=2)})[0].path == (
        "effects.spend.sufficient"
    )


def test_inactive_branch_never_evaluates_an_unsafe_but_well_typed_amount():
    source = _source()
    source["effects"][0]["spend"].update(when=False, amount={"ceil_div": [1, 0]})
    program = _compile(source)
    assert program.evaluate({"supply": Supply(0, 99)}, occurrence=K0OccurrenceRef(1))["stock"] == 0
    source["effects"][0]["spend"]["when"] = True
    with pytest.raises(C0ValueRangeError):
        _compile(source).admits({"supply": Supply(0, 99)})


def test_conditional_effect_can_preserve_a_nullable_local_mirror():
    source = _source()
    source["effects"][0]["spend"].update(when="supply.cost == 1", mirror=["supply.known"])
    ports = replace(
        _ports(), outputs={"stock": int, "mirrored": int | None, "action": K0OccurrenceRef}
    )
    program = _compile(source, ports, {"supply.stock": "stock", "supply.known": "mirrored"})
    assert (
        program.evaluate({"supply": Supply(0, 99, cost=0)}, occurrence=K0OccurrenceRef(1))[
            "mirrored"
        ]
        is None
    )
    assert (
        program.evaluate({"supply": Supply(2, 99)}, occurrence=K0OccurrenceRef(2))["mirrored"] == 1
    )


def test_conditional_target_needs_a_branch_proof_and_preserves_none_when_inactive():
    source = _source()
    source["effects"][0]["spend"].update(
        debit="supply.known", when="supply.known is not None", mirror=[]
    )
    source["outputs"]["mirrored"] = 0
    ports = replace(
        _ports(), outputs={"stock": int | None, "mirrored": int, "action": K0OccurrenceRef}
    )
    program = _compile(source, ports, {"supply.known": "stock"})
    assert (
        program.evaluate({"supply": Supply(3, 99)}, occurrence=K0OccurrenceRef(1))["stock"] is None
    )
    assert (
        program.evaluate({"supply": Supply(3, 99, known=2)}, occurrence=K0OccurrenceRef(2))["stock"]
        == 1
    )
    source["effects"][0]["spend"]["when"] = True
    with pytest.raises(C0LawError, match="admission integers"):
        _compile(source, ports, {"supply.known": "stock"})


def test_effect_scope_does_not_skip_a_global_condition_or_required_binding():
    source = _source()
    source["effects"][0]["spend"]["when"] = False
    program = _compile(source)
    assert not program.admits({"supply": Supply(0, 99, permitted=False)})
    assert program.false_guard_clauses({"supply": Supply(0, 99, permitted=False)})[0].names == (
        "allowed",
    )
    source["bindings"] = [{"name": "bad", "stage": "admission", "let": {"ceil_div": [1, 0]}}]
    source["guard"] = {"eq": [{"ref": "bad"}, 0]}
    with pytest.raises(C0ValueRangeError):
        _compile(source).admits({"supply": Supply(0, 99)})


@pytest.mark.parametrize(
    "when",
    [
        1,
        "supply.secret == 1",
        {"ref": "occurrence"},
        {"eq": [{"die_roll": {"seed": 1, "sides": 6}}, 1]},
    ],
)
def test_activation_cannot_bypass_type_stage_or_permission(when):
    source = _source()
    source["effects"][0]["spend"]["when"] = when
    with pytest.raises(C0LawError):
        _compile(source)


def test_inactive_mirror_still_needs_its_own_read_permission():
    source = _source()
    source["effects"][0]["spend"]["when"] = False
    ports = _ports()
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(
            source,
            replace(
                ports,
                readable_paths=ports.readable_paths - {"supply.mirrored"},
                admission_readable_paths=ports.admission_readable_paths - {"supply.mirrored"},
            ),
        )


def _transfer_source(conditional=False):
    body = {
        "transfer": {"from": "supply.stock", "to": "supply.mirrored"},
        "amount": "supply.cost",
        "floor": "supply.minimum",
        "capacity": 10,
    }
    if conditional:
        body["when"] = "supply.permitted"
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "effects": [{"move": body}],
        "outputs": {"action": {"ref": "occurrence"}},
    }


@pytest.mark.parametrize(
    "stock,destination,amount,floor,remaining,received",
    [(5, 2, 3, 1, 2, 5), (2, 9, 1, 0, 1, 10), (MAX, 0, MAX, 0, 0, MAX)],
)
def test_transfer_conserves_quantity_and_uses_one_pre_state(
    stock, destination, amount, floor, remaining, received
):
    source = _transfer_source()
    source["effects"][0]["move"]["capacity"] = MAX if stock == MAX else 10
    program = _compile(source)
    result = program.evaluate(
        {"supply": Supply(stock, destination, cost=amount, minimum=floor)},
        occurrence=K0OccurrenceRef(1),
    )
    assert (result["stock"], result["mirrored"]) == (remaining, received)
    assert result["stock"] + result["mirrored"] == stock + destination


@pytest.mark.parametrize(
    "stock,destination,amount,floor,capacity,label",
    [
        (0, 0, 1, 0, 10, "sufficient"),
        (5, 10, 1, 0, 10, "capacity"),
        (5, 2, 0, 0, 10, "positive_amount"),
        (5, 2, -1, 0, 10, "positive_amount"),
        (5, 2, MAX + 1, 0, 10, "bounded_amount"),
        (5, 2, 1, -1, 10, "nonnegative_floor"),
        (0, 2, 1, 1, 10, "above_floor"),
        (-1, 2, 1, 0, 10, "above_floor"),
        (MAX + 1, 2, 1, 0, 10, "bounded_balance"),
        (5, -1, 1, 0, 10, "nonnegative_destination"),
        (5, 11, 1, 0, 10, "within_capacity"),
        (5, 2, 1, 0, -1, "within_capacity"),
        (5, MAX, 1, 0, MAX + 1, "bounded_capacity"),
        (5, MAX, 1, 0, MAX, "capacity"),
    ],
)
def test_resource_failure_refuses_before_unsafe_subtraction_or_addition(
    stock, destination, amount, floor, capacity, label
):
    source = _transfer_source()
    source["effects"][0]["move"]["capacity"] = "supply.secret"
    selected = _ports()
    selected = replace(
        selected,
        readable_paths=selected.readable_paths | {"supply.secret"},
        admission_readable_paths=selected.admission_readable_paths | {"supply.secret"},
        readable_fields={Supply: selected.readable_fields[Supply] | {"secret"}},
        admission_readable_fields={Supply: selected.admission_readable_fields[Supply] | {"secret"}},
    )
    program = _compile(source, selected)
    roots = {"supply": Supply(stock, destination, cost=amount, minimum=floor, secret=capacity)}
    assert not program.admits(roots)
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(1)) is None
    assert program.false_guard_clauses(roots)[0].path == f"effects.move.{label}"


def test_transfer_does_not_require_the_source_to_fit_the_destination_capacity():
    result = _compile(_transfer_source()).evaluate(
        {"supply": Supply(99, 0)}, occurrence=K0OccurrenceRef(1)
    )
    assert (result["stock"], result["mirrored"]) == (98, 1)


def test_transfer_explicit_mirrors_follow_their_side_and_keep_own_inactive_values():
    source = _transfer_source(True)
    source["effects"][0]["move"]["mirror"] = {"from": ["supply.known"], "to": ["supply.maybe_cost"]}
    selected = replace(
        _ports(),
        writable_fields={Supply: frozenset({"stock", "mirrored", "known", "maybe_cost"})},
        outputs={**_ports().outputs, "source_view": int | None, "target_view": int | None},
    )
    mapping = {
        "supply.stock": "stock",
        "supply.mirrored": "mirrored",
        "supply.known": "source_view",
        "supply.maybe_cost": "target_view",
    }
    program = _compile(source, selected, mapping)
    result = program.evaluate({"supply": Supply(5, 2, known=88)}, occurrence=K0OccurrenceRef(1))
    assert (result["source_view"], result["target_view"]) == (4, 3)
    result = program.evaluate(
        {"supply": Supply(0, 99, permitted=False, known=88)}, occurrence=K0OccurrenceRef(2)
    )
    assert (result["stock"], result["mirrored"], result["source_view"], result["target_view"]) == (
        0,
        99,
        88,
        None,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"transfer": {"from": "supply.stock", "to": "supply.stock"}},
        {"transfer": {"from": "supply.stock"}},
        {"mirror": ["supply.known"]},
        {"mirror": {"other": []}},
        {"mirror": {"to": ["supply.stock"]}},
        {"consume": "supply.permitted"},
        {"amount": True},
        {"capacity": {"ref": "occurrence"}},
        {"transfer": {"from": "supply.stock", "to": "supply.secret"}},
    ],
)
def test_transfer_rejects_aliases_malformed_maps_and_crossed_ports(change):
    source = _transfer_source()
    source["effects"][0]["move"].update(change)
    with pytest.raises(C0LawError):
        _compile(source)


def test_exclusive_conditions_do_not_permit_overlapping_effect_writes():
    source = _source()
    source["effects"][0]["spend"]["when"] = "supply.cost == 1"
    source["effects"].append(
        {
            "otherwise": {
                "when": "supply.cost != 1",
                "debit": "supply.stock",
                "amount": 1,
                "floor": 0,
            }
        }
    )
    with pytest.raises(C0LawError, match="overlap"):
        _compile(source)


def _consume_source():
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": True,
        "effects": [{"use": {"when": "supply.cost == 1", "consume": "supply.permitted"}}],
        "outputs": {"action": {"ref": "occurrence"}},
    }


def _consume(source=None):
    return _compile(
        _consume_source() if source is None else source,
        replace(_ports(), outputs={"available": bool, "action": K0OccurrenceRef}),
        {"supply.permitted": "available"},
    )


@pytest.mark.parametrize(
    "active,available,result", [(True, True, False), (False, False, False), (False, True, True)]
)
def test_consume_is_boolean_once_only_and_skip_does_not_require_availability(
    active, available, result
):
    program = _consume()
    roots = {"supply": Supply(0, 99, cost=1 if active else 0, permitted=available)}
    assert program.evaluate(roots, occurrence=K0OccurrenceRef(1))["available"] is result
    assert not program.admits({"supply": Supply(0, 99, permitted=False)})
    assert (
        program.false_guard_clauses({"supply": Supply(0, 99, permitted=False)})[0].path
        == "effects.use.available"
    )


def test_consume_does_not_treat_an_integer_as_a_boolean():
    source = _consume_source()
    source["effects"][0]["use"]["consume"] = "supply.stock"
    with pytest.raises(C0LawError, match="booleans"):
        _compile(
            source,
            replace(_ports(), outputs={"available": int, "action": K0OccurrenceRef}),
            {"supply.stock": "available"},
        )


def test_effect_ir_points_only_at_nodes_in_the_one_checked_guard_and_output_tree(monkeypatch):
    program = _compile(_transfer_source(True))
    (effect,) = program.effects
    assert effect.operation == "transfer"
    assert effect.endpoints == (("from", "supply.stock"), ("to", "supply.mirrored"))
    assert effect.checks is program.guard_ir.expression["all"][1]["all"][0]
    assert effect.activation is effect.checks["if"]["when"]
    assert all(node is program._tree["outputs"][output] for output, node in effect.results)
    with pytest.raises(TypeError):
        effect.activation["ref"] = "supply.secret"

    def forbidden(*args, **kwargs):
        raise AssertionError("Run entered Compile")

    monkeypatch.setattr(values, "read_value_effects", forbidden)
    monkeypatch.setattr(values, "lower_author_expression", forbidden)
    monkeypatch.setattr(values, "_infer_expr_type", forbidden)
    assert program.evaluate({"supply": Supply(3, 0)}, occurrence=K0OccurrenceRef(1))["stock"] == 2


def test_named_activation_clauses_have_their_own_scopes_and_source_paths():
    source = _transfer_source(True)
    source["effects"][0]["move"]["when"] = {"require": [{"selected": "supply.permitted"}]}
    program = _compile(source)
    assert program.effects[0].activation["all"][0].origin == "effects.move.when.require.selected"
    assert (
        program.evaluate({"supply": Supply(0, 99, permitted=False)}, occurrence=K0OccurrenceRef(1))[
            "mirrored"
        ]
        == 99
    )


def _transfer_world(fault=False, causal=False):
    from test_multi_participant_action_v0 import _compile as compile_world
    from test_multi_participant_action_v0 import _world

    lib, ports, source, assets = _world()
    person = next(item for item in lib["records"] if item["name"] == "Person")
    person["fields"].append({"name": "balance", "type": {"int": [0, 10]}})
    for owner in ("maker", "a", "b"):
        assets["opening"][owner]["balance"] = 1 if owner == "maker" else 0
    if fault and not causal:
        # Nominal owner validation occurs after all proposed owner writes.
        person["invariant"] = "state.balance != 2"
        assets["opening"]["a"]["balance"] = 1
    action = ports["actions"][0]
    action["effects"]["actor"]["balance"] = "remaining"
    action["effects"]["victim"]["balance"] = "received"
    action["value"]["read"].extend(["actor.balance", "victim.balance"])
    action["value"]["write_paths"].extend(["actor.balance", "victim.balance"])
    value = lib["lawdefs"][0]["body"]["value"]
    value["outputs"]["ready"] = {"ref": "tool.ready"}
    value["outputs"]["enabled"] = {"ref": "victim.enabled"}
    value["effects"] = [
        {
            "move": {
                "transfer": {"from": "actor.balance", "to": "victim.balance"},
                "amount": 1,
                "floor": 0,
                "capacity": 3,
            }
        }
    ]
    if causal:
        scene = next(item for item in lib["records"] if item["name"] == "Scene")
        if fault:
            scene["invariant"] = "state.title != 'settled'"
        lib["lawdefs"].append(
            {
                "name": "event.settle",
                "family": "direct_event",
                "formals": {},
                "body": {
                    "law": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": "scene.title != 'settled'",
                        "outputs": {"title": {"const": "settled"}},
                    }
                },
            }
        )
        ports["events"] = [
            {
                "symbol": "settle",
                "form": "direct_scene",
                "actor": None,
                "actor_identity_field": None,
                "value": {
                    "read": ["scene.title"],
                    "fields": {},
                    "write_paths": ["scene.title"],
                    "outputs": {"title": "scene.title"},
                    "construct": [],
                    "collections": {},
                },
            }
        ]
        source["events"] = [
            {
                "name": "settle",
                "template": "settle",
                "trigger_action": "enable",
                "source_key": "c0.transfer.settle",
                "event_type": "c0.transfer.settle.event",
                "causal_key": "c0.transfer.causes-settle",
                "law": {"ref": "event.settle", "args": {}},
            }
        ]
    return compile_world(lib, ports, source).start(assets)


def test_real_k0_transfer_rechecks_resources_and_rejection_is_zero_write():
    session = _transfer_world()
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    owners = dict(session.author_snapshot().owners)
    assert owners["maker"].balance == 0 and owners["a"].balance == 1
    (event,) = session._runtime.occurrence_history()
    assert event.source == dict(session.program.actions)["enable"].source_key
    before = session.author_snapshot()
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_real_k0_transfer_and_successor_keep_distinct_occurrences_and_trigger():
    session = _transfer_world(causal=True)
    offer = session.offers("maker")[0]
    published = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(published, K0Published)
    action, successor = published.occurrences
    assert successor.semantic_envelope.trigger == action.occurrence
    assert successor.source != action.source
    owners = dict(session.author_snapshot().owners)
    assert (owners["maker"].balance, owners["a"].balance) == (0, 1)
    assert owners["scene"].title == "settled"


@pytest.mark.parametrize("causal", [False, True])
def test_real_k0_transfer_or_successor_fault_rolls_back_every_participant(causal):
    session = _transfer_world(fault=True, causal=causal)
    offer = session.offers("maker")[0]
    before = session.author_snapshot()
    with pytest.raises(K0SettlementDefect):
        session.submit("maker", offer.entry, dict(offer.payload))
    assert session._runtime.occurrence_history() == ()
    # The failed C0 controller is closed, but its original K0 owner rows remain.
    assert all(
        session._runtime.read_owner(owner.owner.key).view == dict(before.owners)[owner.symbol]
        for owner in session.program.owners
    )
    with pytest.raises((ValueError, K0SettlementDefect)):
        session.submit("maker", offer.entry, dict(offer.payload))
