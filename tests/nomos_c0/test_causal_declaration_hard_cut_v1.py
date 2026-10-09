"""Source selects a causal rule; C0 derives its closed formation convention."""

from pathlib import Path

import pytest
from authored_counter_v1 import _actor_event_inputs, _scene
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_binding_v1 import _expand, _source

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.semantic_ir_v0 import C0FormationKind


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("form", "direct"),
        ("form", "direct_actor"),
        ("when_false", "no_event"),
        ("when_false", "defect"),
        ("when_false", None),
    ],
)
@pytest.mark.parametrize("recipient", [False, True])
def test_singleton_causal_source_rejects_retired_execution_fields(field, value, recipient):
    library, source, _ = _actor_event_inputs()
    source["events"][int(recipient)][field] = value
    with pytest.raises(C0LawError, match="compiler-owned"):
        compile_owner_graph(library, source)


@pytest.mark.parametrize("successor", [False, True])
@pytest.mark.parametrize("field", ["form", "when_false"])
def test_causal_family_rejects_retired_fields_before_expansion(field, successor):
    source = _source()
    event = source["events"][0]
    if successor:
        source["events"].append(dict(event, family="after", for_event_family=event["family"]))
        event = source["events"][-1]
        del event["for_action_family"]
    event[field] = "direct" if field == "form" else "no_event"
    with pytest.raises(C0LawError, match="compiler-owned"):
        _expand(source)


def test_selected_scene_and_actor_templates_form_one_real_causal_chain():
    library, source, assets = _actor_event_inputs()
    assert all(not {"form", "when_false", "effect"} & set(row) for row in source["events"])
    program = compile_owner_graph(library, source)
    assert all(
        event.ir.formation is C0FormationKind.AFTER_OCCURRENCE for _, event in program.events
    )
    session = program.start(assets)
    result = session.submit("seat_0", "count_0", {"target": "person_0"})
    assert isinstance(result, K0Published)
    action, scene_event, actor_event = result.occurrences
    assert scene_event.formation_basis.predecessor == action.occurrence
    assert actor_event.formation_basis.predecessor == scene_event.occurrence
    assert _scene(session).open_ref == scene_event.occurrence
    owner = next(row.owner for row in program.owners if row.symbol == "observer")
    assert session._runtime.read_owner(owner.key).view.notice.perception == actor_event.occurrence


@pytest.mark.parametrize(
    "path",
    [
        "src/nomos_c0/examples/three_seat_werewolf_v0.source.yaml",
        "src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml",
        "src/nomos_c0/examples/parcel_delivery_v0.source.json",
        "src/nomos_c0/examples/scene_unseal_v1.source.json",
        "src/nomos_c0/examples/scene_paid_read_v1.source.json",
    ],
)
def test_maintained_consumers_have_no_retired_causal_fields(path):
    root = Path(__file__).resolve().parents[2]
    document = read_author_document(root / path).to_data()
    assert all(not {"form", "when_false", "effect"} & set(row) for row in document["events"])
    for row in document.get("due_events", []):
        assert row["form"] == "due" and row["when_false"] == "defect"


def test_maintained_m1_bundle_has_no_retired_causal_fields():
    from nomos_c0.source_bundle_v1 import read_source_bundle

    root = Path(__file__).resolve().parents[2]
    bundle = read_source_bundle(
        root / "src/nomos_examples/everflame/world.bundle.yaml"
    )
    document = bundle.source.to_data()
    assert all(not {"form", "when_false", "effect"} & set(row) for row in document["events"])
    for row in document.get("due_events", []):
        assert row["form"] == "due" and row["when_false"] == "defect"
