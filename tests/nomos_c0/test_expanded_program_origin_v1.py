"""Actual compiler emissions keep origins through whole Program binding and Run."""

from __future__ import annotations

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_family_runtime_v1 import _family_world
from test_authored_law_origin_v1 import _assets, _compile, _document, _no_context, _sample
from test_control_binding_v1 import _inputs

from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.author_document_v1 import C0OriginFrame, C0SourceContext, C0SourceIndex
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.program_binding_v1 import bind_program


def _documents(raws):
    return tuple(
        _document(raw, f"world.{part}.yaml")
        for raw, part in zip(raws, ("lib", "ports", "source"), strict=True)
    )


def test_scoped_origins_follow_path_components_not_shared_prefixes():
    global_frame = C0OriginFrame("control", "opening", "guard")
    frame = C0OriginFrame("actor_instance", "b", "guard.all[1]")
    context = C0SourceContext(
        C0SourceIndex({}), frames=(global_frame,), scoped_frames=(("guard.all[1]", (frame,)),)
    )
    assert context.frames_for("guard.all[1].eq[0]") == (global_frame, frame)
    assert context.frames_for("guard.all[10].eq[0]") == (global_frame,)
    assert context.frames_for("guard.all[0]") == (global_frame,)


@pytest.mark.parametrize("scopes", [[("guard", ())], (("guard",),), (("guard", (None,)),)])
def test_malformed_scoped_origins_are_rejected_without_an_unpacking_fault(scopes):
    with pytest.raises(ValueError, match="source context"):
        C0SourceContext(C0SourceIndex({}), scoped_frames=scopes)


@pytest.mark.parametrize(
    "recipient",
    [{"actor": "b"}, {"actor_domain": "recipients"}, {"actor": {"from_trigger": "actor"}}],
)
def test_emitted_actor_instances_keep_true_family_binding_trigger_and_recipient(recipient):
    lib, ports, source, assets = _family_world(recipient)
    documents = _documents((lib, ports, source))
    program = _compile(documents)
    for name, action in program.actions:
        frames = action.value.guard_ir.expression.provenance
        assert frames[0].span == documents[2].spans["actions", 0, "law"]
        assert frames[1].kind == "actor_instance" and frames[1].name == name
        assert dict(frames[1].arguments) == {
            "family": "enable",
            "actor": name.removeprefix("enable_"),
        }
    for name, event in program.events:
        frames = event.value.guard_ir.expression.provenance
        assert frames[0].span == documents[2].spans["events", 0, "law"]
        assert frames[1].name == name and frames[1].kind == "actor_instance"
        arguments = dict(frames[1].arguments)
        assert arguments["trigger_action"].startswith("enable_")
        assert arguments["recipient"] == next(
            owner.symbol for owner in program.owners if owner.owner is event.ports.actor_owner
        )
    for seat in program.seats:
        assert (
            seat.offers[0].condition.provenance[-1].span
            == documents[2].spans["seats", 0, "offers", 0, "when"]
        )
        assert dict(seat.offers[0].condition.provenance[0].arguments)["actor"] == seat.actor
    session = program.start(assets)
    for actor, label in (("maker", "Use one on a"), ("other", "Use two on b")):
        offer = next(item for item in session.offers(actor) if item.label == label)
        result = session.submit(actor, offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        assert all(
            item.formation_basis.predecessor == result.occurrences[0].occurrence
            for item in result.occurrences[1:]
        )
    _no_context(program)


def test_successor_family_keeps_original_position_after_dependency_ordering():
    from test_actor_binding_v1 import OWNERS, _source

    from nomos_c0.actor_binding_v1 import expand_actor_bindings

    source = _source()
    source["events"].insert(
        0,
        {
            "family": "receipt",
            "template": "resolve",
            "for_event_family": "resolve_attack",
            "source_prefix": "test.receipt",
            "law": {"ref": "event.receipt", "args": {}},
        },
    )
    document = _document(source, "successor.yaml")
    origins = {}
    result = expand_actor_bindings(
        source,
        OWNERS,
        {"attack": "a"},
        frozenset({"resolve"}),
        source_context=document.context(),
        origins=origins,
    )
    for event in result["events"]:
        index = 0 if event["name"].startswith("receipt_") else 1
        context = origins["events", event["name"]]
        assert context.locate("law") == document.spans["events", index, "law"]
        if index == 0:
            assert dict(context.frames[0].arguments)["trigger_event"] == event["trigger_event"]


def test_seat_additional_offer_locates_its_original_list_not_concatenated_index():
    lib, ports, source = _sample()
    source["actor_domains"] = [{"name": "people", "actor_state": "Actor", "owners": ["a", "b"]}]
    source["actions"] = [
        {
            "family": "use",
            "template": "use",
            "domain": "people",
            "source_prefix": "origin.use",
            "law": {"ref": "spend", "args": {"amount": 1}},
        },
        {
            "name": "extra_b",
            "template": "use",
            "actor": "b",
            "source_key": "origin.extra",
            "event_type": "origin.extra.action",
            "law": {"ref": "spend", "args": {"amount": 1}},
        },
    ]
    source["seats"] = [
        {
            "seat_family": "people",
            "names": "upper",
            "entries": ["use"],
            "read": ["actor.name", "scene.tokens"],
            "offers": [
                {"entry_family": "use", "label": "Use", "when": {"const": True}, "payload": {}}
            ],
            "additional": {
                "b": {
                    "entries": ["extra_b"],
                    "offers": [
                        {
                            "entry": "extra_b",
                            "label": "Extra",
                            "when": {"const": True},
                            "payload": {},
                        }
                    ],
                }
            },
        }
    ]
    documents = _documents((lib, ports, source))
    program = _compile(documents)
    (extra,) = [
        offer for seat in program.seats for offer in seat.offers if offer.entry == "extra_b"
    ]
    assert (
        extra.condition.provenance[-1].span
        == documents[2].spans["seats", 0, "additional", "b", "offers", 0, "when"]
    )
    assert len(program.seats[0].offers) == 1 and len(program.seats[1].offers) == 2
    session = program.start(_assets())
    assert isinstance(session.submit("B", "extra_b", {}), K0Published)
    _no_context(program)


def test_two_output_roots_and_nested_pure_calls_share_template_not_instance_origin():
    lib, ports, source = _sample(amount=1)
    lib["records"][1]["fields"].append({"name": "tokens", "type": {"int": [0, 10]}})
    lib["pure_definitions"] = [
        {
            "name": "less_one",
            "parameters": {"number": "int"},
            "result": "int",
            "stage": "admission",
            "body": {"sub": [{"ref": "number"}, 1]},
        }
    ]
    port = ports["actions"][0]
    port["effects"]["actor"] = {"tokens": "actor_remaining"}
    port["value"]["read"].append("actor.tokens")
    port["value"]["write_paths"].append("actor.tokens")
    law = lib["lawdefs"][0]
    law["formals"] = {}
    value = law["body"]["value"]
    del value["effects"]
    value["output_families"] = [
        {
            "name": "pay",
            "owners": ["scene", "actor"],
            "as": "payer",
            "fields": {
                "tokens": {"call": {"ref": "less_one", "args": {"number": {"ref": "payer.tokens"}}}}
            },
        }
    ]
    for action in source["actions"]:
        action["law"]["args"] = {}
    documents = _documents((lib, ports, source))
    program = _compile(documents)
    outputs = dict(program.actions)["use_a"].value._tree["outputs"]
    for output, owner in (("remaining", "scene"), ("actor_remaining", "actor")):
        expression = outputs[output]
        instance = next(frame for frame in expression.provenance if frame.kind == "output_instance")
        assert dict(instance.arguments) == {"family": "pay", "owner": owner, "field": "tokens"}
        assert (
            expression.provenance[-1].span
            == documents[0].spans[
                "lawdefs", 0, "body", "value", "output_families", 0, "fields", "tokens"
            ]
        )
        body = expression["call"]["body"]
        assert instance in body.provenance
        assert body.provenance[-1].span == documents[0].spans["pure_definitions", 0, "body"]
    assets = _assets()
    assets["opening"]["a"]["tokens"] = 6
    assets["opening"]["b"]["tokens"] = 7
    session = program.start(assets)
    result = session.submit("a", "use_a", {})
    assert isinstance(result, K0Published) and len(result.occurrences) == 1
    owners = dict(session.author_snapshot().owners)
    assert (owners["scene"].tokens, owners["a"].tokens, owners["b"].tokens) == (1, 5, 7)
    _no_context(program)


@pytest.mark.parametrize("with_base", [False, True])
def test_opening_actor_guard_reindexing_keeps_actual_source_and_each_actor(with_base):
    lib, ports, source = _sample(amount=1)
    source["actor_domains"] = [{"name": "people", "actor_state": "Actor", "owners": ["a", "b"]}]
    if with_base:
        source["opening_guard"] = {"require": [{"balance": "scene.tokens > 0"}]}
    source["opening_actor_guards"] = [
        {
            "domain": "people",
            "when": {"not": {"eq": [{"ref": "actor.name"}, {"const": "bad"}]}},
        }
    ]
    documents = _documents((lib, ports, source))
    program = _compile(documents)
    assets = _assets()
    assets["opening"]["b"]["name"] = "bad"
    roots = {
        owner.symbol: owner.owner.state_type(**assets["opening"][owner.symbol])
        for owner in program.owners
    }
    (failure,) = program.opening_guard.false_guard_clauses(roots)
    assert failure.names == ()
    assert failure.provenance[-1].span == documents[2].spans["opening_actor_guards", 0, "when"]
    assert (
        next(
            dict(frame.arguments)["actor"]
            for frame in failure.provenance
            if frame.kind == "actor_instance"
        )
        == "b"
    )
    with pytest.raises(C0BindingError, match="opening"):
        program.start(assets)
    _no_context(program)


def test_all_control_and_visibility_sources_survive_rebinding_without_author_files(monkeypatch):
    lib, ports, source, assets = _inputs()
    documents = _documents((lib, ports, source))
    ir, layout = check_owner_graph(
        check_graph_ports(documents[1], check_nominal_lib(documents[0])), documents[2]
    )
    lib.clear()
    ports.clear()
    source.clear()
    from pathlib import Path

    monkeypatch.setattr(
        Path, "read_text", lambda *args, **kwargs: pytest.fail("Run reread author source")
    )
    program = bind_program(ir, layout)
    projection = program.profile.action_value_policy.seats[0].projector.value
    assert (
        projection._tree["outputs"]["tempo"].provenance[-1].span
        == documents[2].spans["game_form", "seats", 0, "tempo"]
    )
    assert (
        projection._tree["outputs"]["eligible"].provenance[-1].span
        == documents[2].spans["game_form", "seats", 0, "eligible"]
    )
    spec = next(
        item
        for item in program.profile.source_specs
        if item.key == dict(program.actions)["dispatch"].source_key
    )
    cost = spec.action_cost_projector.value._tree["outputs"]["cost"]
    assert (
        cost.provenance[-1].span == documents[2].spans["game_form", "seats", 0, "costs", "dispatch"]
    )
    score = program.appraisal_profiles[0].rules[1].value._tree["outputs"]["score"]
    assert (
        score.provenance[-1].span
        == documents[2].spans["appraisal_profiles", 0, "rules", 1, "value"]
    )
    assert (
        program.profile.terminal_policy.clauses[0]
        .projector.value.guard_ir.expression.provenance[-1]
        .span
        == documents[2].spans["game_form", "world_stops", 0, "when"]
    )
    assert (
        program.seats[0].offers[0].condition.provenance[-1].span
        == documents[2].spans["seats", 0, "offers", 0, "when"]
    )
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    assert session._runtime.action_value_history()[-1].cost == 4
    assert session.continue_form("sender").time == 3
    _no_context(program)


def test_record_invariant_origin_is_not_a_nominal_type_or_version_change():
    lib, ports, source = _sample()
    lib["records"][0]["invariant"] = {"require": [{"positive": "state.tokens > 0"}]}
    documents = _documents((lib, ports, source))
    located = check_nominal_lib(documents[0])
    plain = check_nominal_lib(lib)
    assert located.signatures == plain.signatures
    assert [owner.owner.owner_version for owner in located.owners] == [
        owner.owner.owner_version for owner in plain.owners
    ]
    carrier = dict(located.records)["Scene"]
    (failure,) = carrier.__nomos_invariant__.false_guard_clauses({"state": carrier(tokens=0)})
    assert failure.provenance[0].kind == "record_invariant"
    assert failure.provenance[0].name == "Scene"
    assert (
        failure.provenance[-1].span
        == documents[0].spans["records", 0, "invariant", "require", 0, "positive"]
    )
    _no_context(located.signatures)


def test_output_family_nodes_retain_template_and_distinct_instance_origins():
    import json
    from dataclasses import replace

    from test_output_family_v1 import _ports, _source

    from nomos_c0.composable_value_v1 import compile_value_program

    document = _document(_source(), "output.yaml")
    value = compile_value_program(
        json.dumps(document.to_data()),
        replace(_ports(), source_context=document.context()),
        state_outputs={"one.amount": "first_slot", "two.amount": "second_slot"},
    )
    first, second = (value._tree["outputs"][name] for name in ("first_slot", "second_slot"))
    assert (
        first.provenance[-1].span
        == second.provenance[-1].span
        == document.spans["output_families", 0, "fields", "amount"]
    )
    assert first.provenance[0].arguments != second.provenance[0].arguments
    _no_context(value)
