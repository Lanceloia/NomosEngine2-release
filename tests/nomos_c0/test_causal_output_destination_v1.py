"""Explicit endpoint destinations are the sole causal owner effect authority."""

from dataclasses import replace

import pytest
from authored_counter_v1 import _actor_event_inputs, _scene, build, direct_documents
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_binding_v1 import _expand, _source
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.owner_graph_v1 import compile_owner_graph


def test_output_alias_is_not_a_destination_and_field_type_is_derived():
    lib, ports, source, assets = direct_documents()
    ports["events"][0]["value"]["outputs"] = {
        "changed": "scene.marker",
        "published": {"target": "scene.open_ref", "type": "occurrence_ref"},
    }
    outputs = source["lawdefs"][-1]["body"]["law"]["outputs"]
    outputs["changed"] = outputs.pop("marker")
    outputs["published"] = outputs.pop("open_ref")
    program = _compile(lib, ports, source)
    event = dict(program.events)["unseal"]
    assert event.ir.effects == (("scene", "marker", "changed"), ("scene", "open_ref", "published"))
    session = program.start(assets)
    result = session.submit("seat_0", "count_0", {"target": "person_0"})
    assert isinstance(result, K0Published)
    assert _scene(session).marker == "accessible"
    assert _scene(session).open_ref == result.occurrences[1].occurrence


@pytest.mark.parametrize("recipient", [False, True])
@pytest.mark.parametrize("effect", [{}, {"scene": {"marker": "marker"}}, None])
def test_source_rejects_effect_even_when_it_matches_or_is_empty(recipient, effect):
    library, source, _ = _actor_event_inputs()
    source["events"][int(recipient)]["effect"] = effect
    with pytest.raises(C0LawError, match="compiler-owned"):
        compile_owner_graph(library, source)


@pytest.mark.parametrize("successor", [False, True])
def test_family_rejects_effect_before_expansion(successor):
    source = _source()
    event = source["events"][0]
    if successor:
        event["for_event_family"] = event.pop("for_action_family")
    event["effect"] = {"scene": {"marker": "marker"}}
    with pytest.raises(C0LawError, match="compiler-owned"):
        _expand(source)


@pytest.mark.parametrize(
    "fault",
    ["permission", "alias", "trigger", "actor", "unknown", "type_only", "refinement"],
)
def test_output_destination_cannot_invent_permission_or_infer_a_field(fault):
    lib, ports, source, _ = direct_documents()
    value = ports["events"][0]["value"]
    if fault == "permission":
        value["write_paths"].remove("scene.marker")
    elif fault == "alias":
        value["outputs"]["open_ref"] = "scene.marker"
    elif fault == "refinement":
        value["outputs"]["marker"] = {"target": "scene.marker", "type": "int"}
    else:
        value["outputs"]["marker"] = {
            "trigger": "trigger.occurrence",
            "actor": "actor.count",
            "unknown": "scene.missing",
            "type_only": "str",
        }[fault]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_immutable_checked_destination_survives_raw_ports_mutation():
    lib, ports, source, _ = direct_documents()
    library = build(lib, ports)
    ports["events"][0]["value"]["outputs"].clear()
    program = compile_owner_graph(library, source)
    assert dict(program.events)["unseal"].ir.effects == (
        ("scene", "marker", "marker"),
        ("scene", "open_ref", "open_ref"),
    )


def test_forged_checked_target_is_still_subject_to_backend_write_permissions():
    lib, ports, source, _ = direct_documents()
    library = build(lib, ports)
    event = library.events[0]
    forged = replace(event, effects=(("signal", "marker"), ("open_ref", "open_ref")))
    # A declared upper permission does not make a host-invented field legal to write.
    value = replace(event.ports.value_ports, writable_fields={})
    forged = replace(forged, ports=replace(event.ports, value_ports=value))
    with pytest.raises(C0LawError):
        compile_owner_graph(replace(library, events=(forged,)), source)
