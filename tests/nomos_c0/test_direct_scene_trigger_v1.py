"""Scene causal guards and effects read the same checked actual predecessor."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import direct_documents
from nomos_kernel._settlement_outcome_abi import K0Published
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program


def documents(*, predecessor="action"):
    lib, ports, source, assets = direct_documents()
    event = next(row for row in source["lawdefs"] if row["name"] == "event.unseal")
    port = ports["events"][0]
    if predecessor == "event":
        following = deepcopy(source["events"][0])
        following.pop("trigger_action")
        following.update(
            name="follow",
            template="follow",
            trigger_event="unseal",
            source_key="c0.follow",
            event_type="c0.follow.event",
            causal_key="c0.follow.causes",
            law={"ref": "follow", "args": {}},
        )
        source["events"].append(following)
        event = deepcopy(event)
        event["name"] = "follow"
        source["lawdefs"].append(event)
        port = deepcopy(port)
        port["symbol"] = "follow"
        ports["events"].append(port)
    else:
        action = ports["actions"][0]
        action["effects"]["scene"] = {"open_ref": "opened"}
        action["value"]["write_paths"].append("scene.open_ref")
        source["lawdefs"][0]["body"]["value"]["outputs"]["opened"] = {"ref": "occurrence"}
    port["value"]["read"] += ["scene.open_ref", "trigger.occurrence"]
    event["body"]["law"]["guard"] = "scene.open_ref == trigger.occurrence"
    event["body"]["law"]["outputs"]["open_ref"] = {"ref": "trigger.occurrence"}
    return lib, ports, source, assets


@pytest.mark.parametrize("predecessor", ["action", "event"])
def test_actual_trigger_in_projector_guard_and_rule_output_survives_independent_bind(
    predecessor, monkeypatch
):
    lib, ports, source, assets = documents(predecessor=predecessor)
    program = _compile(lib, ports, source)
    layouts = program.world_layout, _layout(program)
    _block_frontend(monkeypatch)
    for layout in layouts:
        session = bind_program(program.program_ir, layout).start(assets)
        offer = session.offers("seat_0")[0]
        result = session.submit("seat_0", offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        expected = result.occurrences[-2].occurrence
        actual = result.occurrences[-1]
        assert len(result.occurrences) == (2 if predecessor == "action" else 3)
        assert actual.semantic_envelope.trigger == expected
        assert actual.formation_basis.predecessor == expected
        assert dict(session.author_snapshot().owners)["scene"].open_ref == expected
        assert expected != actual.occurrence
        if predecessor == "event":
            assert expected != result.occurrences[0].occurrence


def test_false_actual_trigger_guard_does_not_project_an_event():
    lib, ports, source, assets = documents(predecessor="event")
    first = next(row for row in source["lawdefs"] if row["name"] == "event.unseal")
    first["body"]["law"]["outputs"]["open_ref"] = {"ref": "trigger.occurrence"}
    ports["events"][0]["value"]["read"].append("trigger.occurrence")
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("seat_0")[0]
    result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published) and len(result.occurrences) == 2
    assert (
        dict(session.author_snapshot().owners)["scene"].open_ref == result.occurrences[0].occurrence
    )


@pytest.mark.parametrize("fault", ["undeclared", "unknown_field", "write"])
def test_trigger_is_explicit_readonly_occurrence_authority(fault):
    lib, ports, source, _ = documents()
    value = ports["events"][0]["value"]
    if fault == "undeclared":
        value["read"].remove("trigger.occurrence")
    elif fault == "unknown_field":
        value["read"].append("trigger.actor")
    else:
        value["write_paths"].append("trigger.occurrence")
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("fault", ["missing_root", "wrong_carrier", "extra_root", "write_grant"])
def test_independent_bind_rejects_forged_trigger_roots(fault):
    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    ir = program.program_ir
    transition = next(row for row in ir.world.transitions if row.symbol == "unseal")
    value = transition.body.value
    roots = dict(value.ports.roots)
    if fault == "missing_root":
        roots.pop("trigger")
    elif fault == "wrong_carrier":
        roots["trigger"] = roots["scene"]
    elif fault == "extra_root":
        roots["fake_trigger"] = roots["trigger"]
    changed = replace(value.ports, roots=tuple(roots.items()))
    if fault == "write_grant":
        changed = replace(
            changed,
            writable_fields=(
                *changed.writable_fields,
                (roots["trigger"], frozenset({"occurrence"})),
            ),
        )
    value = replace(value, ports=changed)
    transitions = tuple(
        replace(row, body=replace(row.body, value=value)) if row is transition else row
        for row in ir.world.transitions
    )
    with pytest.raises(C0LawError):
        bind_program(
            replace(ir, world=replace(ir.world, transitions=transitions)), _layout(program)
        )


def test_unrequested_trigger_read_preserves_existing_scene_event_behavior():
    lib, ports, source, assets = direct_documents()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("seat_0")[0]
    result = session.submit("seat_0", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published) and len(result.occurrences) == 2
    assert (
        dict(session.author_snapshot().owners)["scene"].open_ref
        == result.occurrences[-1].occurrence
    )
