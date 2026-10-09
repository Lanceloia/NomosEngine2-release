"""Due and scheduled Action wiring has one checked Ports authority."""

import pytest
from authored_counter_v1 import _scene, _temporal_inputs, action_value_documents, build
from authored_paid_read_v1 import documents
from nomos_kernel import K0OccurrenceRef
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.owner_graph_v1 import compile_owner_graph


@pytest.mark.parametrize("effect", [None, {}, {"scene": {"signal": "signal"}}])
def test_source_due_rejects_retired_effect_even_when_matching(effect):
    lib, ports, source, _ = action_value_documents()
    source["due_events"][0]["effect"] = effect
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_due_alias_does_not_determine_its_destination():
    lib, ports, source, assets = action_value_documents()
    ports["due_events"][0]["value"]["outputs"] = {"after": "scene.signal"}
    law = source["lawdefs"][-1]["body"]["law"]
    law["outputs"]["after"] = law["outputs"].pop("signal")
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = False
    session = _compile(lib, ports, source).start(assets)
    session.continue_form("seat_0")
    assert _scene(session).signal == "pulse"


@pytest.mark.parametrize("fault", ["permission", "duplicate", "wrong_owner", "type_only"])
def test_due_destination_does_not_guess_or_expand_write_rights(fault):
    lib, ports, source, _ = action_value_documents()
    value = ports["due_events"][0]["value"]
    if fault == "permission":
        value["write_paths"] = []
    elif fault == "duplicate":
        value["outputs"]["other"] = "scene.signal"
    elif fault == "wrong_owner":
        value["outputs"]["signal"] = "actor_0.count"
    else:
        value["outputs"]["signal"] = "str"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("key", ["subject_output", "delay_output"])
def test_source_schedule_rejects_repeated_alias_even_when_matching(key):
    library, source, _ = _temporal_inputs()
    source["actions"][0]["schedule"][key] = "subject" if key == "subject_output" else "delay"
    with pytest.raises(C0LawError, match="schedule identity"):
        compile_owner_graph(library, source)


def test_paid_read_due_preserves_explicit_nonempty_refinement():
    lib, ports, source, _ = documents(temporal=True)
    checked = build(lib, ports)
    outputs = checked.due_events[0].ports.value_ports.outputs
    assert outputs["open_ref"] is K0OccurrenceRef
    _compile(lib, ports, source)


def test_shared_state_type_does_not_grant_another_root_write_permission():
    lib, ports, source, _ = action_value_documents()
    template = ports["due_events"][0]
    template["owner_roots"] = ["actor_0", "actor_1"]
    value = template["value"]
    value["write_paths"].append("actor_0.count")
    value["outputs"]["other"] = "actor_1.count"
    with pytest.raises(C0LawError, match="explicit write permission"):
        _compile(lib, ports, source)
