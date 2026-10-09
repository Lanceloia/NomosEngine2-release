"""Action and Event labels have distinct formation namespaces."""

from copy import deepcopy

import pytest
from authored_counter_v1 import build, direct_documents
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0 import C0LawError
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _world(same_result=False):
    lib, ports, source, assets = direct_documents()
    source["events"][0]["trigger_action"] = "count_1"
    other = deepcopy(source["events"][0])
    other.update(
        name="count_1",
        trigger_action="count_0",
        source_key="c0.other.event",
        event_type="c0.other.type",
        causal_key="c0.other.causes",
    )
    if same_result:
        source["events"] = [other]
        source["events"][0]["trigger_action"] = "count_1"
    else:
        source["events"].append(other)
    source["ontology"] = {
        "schema": "c0.event_formation.v2",
        "event_sorts": [{"symbol": "change", "identity": "TEST.CHANGE@1"}],
        "formations": [
            {
                "entry": event["name"],
                "sort": "change",
                "trigger": event["trigger_action"],
                "trigger_kind": "action",
                "mechanism": "causal",
            }
            for event in source["events"]
        ],
    }
    return compile_owner_graph(build(lib, ports), source), assets


@pytest.mark.parametrize("same_result", [False, True])
def test_same_action_and_event_name_preserves_exact_predecessor_and_real_event(same_result):
    program, assets = _world(same_result)
    session = program.start(assets)
    offer = session.offers("seat_1")[0]
    receipt = session.submit("seat_1", offer.entry, dict(offer.payload))
    assert isinstance(receipt, K0Published)
    action, event = receipt.occurrences
    assert action.source.value == "c0.graph.count_1"
    trace = session.formation_trace()
    assert len(trace) == 1
    assert trace[0].source == event.source and trace[0].predecessor == action.occurrence


def test_action_trigger_cannot_be_relabelled_as_an_event_trigger():
    lib, ports, source, _ = direct_documents()
    source["ontology"] = {
        "schema": "c0.event_formation.v2",
        "event_sorts": [{"symbol": "change", "identity": "TEST.CHANGE@1"}],
        "formations": [
            {
                "entry": "unseal",
                "sort": "change",
                "trigger": "count_0",
                "trigger_kind": "event",
                "trigger_sort": "change",
                "mechanism": "causal",
            }
        ],
    }
    with pytest.raises(C0LawError):
        compile_owner_graph(build(lib, ports), source)
