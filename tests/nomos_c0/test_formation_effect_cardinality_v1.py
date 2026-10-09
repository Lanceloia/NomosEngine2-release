"""Formation provenance is independent of an Event's number of write owners."""

from dataclasses import replace

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OwnerKey,
    K0SourceSpecKey,
)
from nomos_kernel._settlement_outcome_abi import K0Published
from test_world_binding_v1 import _compile

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.event_formation_v2 import C0FormationEntry, bind_event_formations
from nomos_c0.examples.parcel_delivery_v0 import ROOT, library
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _documents():
    return tuple(
        read_author_document(ROOT / f"parcel_delivery_v0.{part}.json").to_data()
        for part in ("lib", "ports", "source", "a.assets")
    )


def test_two_owner_due_event_retains_one_formation_and_both_real_writes():
    lib, ports, source, assets = _documents()
    due = ports["due_events"][0]
    due["owner_roots"] = ["sender"]
    due["value"]["write_paths"].append("sender.sent_ref")
    due["value"]["outputs"]["stamp"] = "sender.sent_ref"
    source["lawdefs"][-1]["body"]["law"]["outputs"]["stamp"] = {"ref": "occurrence"}
    session = _compile(lib, ports, source).start(assets)
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("receiver")
    occurrence = session._runtime.occurrence_history()[-1]
    assert session._runtime.read_owner(K0OwnerKey("c0.parcel-demo.sender")).view.sent_ref == (
        occurrence.occurrence
    )
    scene = session._runtime.read_owner(K0OwnerKey("c0.parcel-demo.scene")).view
    assert scene.parcel.arrival_ref == occurrence.occurrence
    assert session.formation_trace()[-1].occurrence == occurrence.occurrence


def test_formation_binding_does_not_require_a_write_owner_for_a_registered_event():
    _, _, source, _ = _documents()
    program = compile_owner_graph(library(), source)
    plan = program.formation_plan
    specs = tuple(
        replace(spec, contribution_owners=())
        if spec.occurrence_family is K0OccurrenceFamily.EVENT
        else spec
        for spec in program.profile.source_specs
    )
    profile = replace(program.profile, source_specs=specs)
    entries = tuple(
        C0FormationEntry(name, action.source_key, action.event_type, K0OccurrenceFamily.ACTION)
        for name, action in program.actions
    ) + tuple(
        C0FormationEntry(
            edge.port.result_entry,
            K0SourceSpecKey(edge.port.result_source),
            K0EventTypeKey(edge.port.result_event_type),
            K0OccurrenceFamily.EVENT,
            trigger_entry=edge.port.trigger_entry,
            causal_law=(
                None if edge.port.causal_law is None else K0CausalLawKey(edge.port.causal_law)
            ),
        )
        for edge in plan.edges
    )
    assert bind_event_formations(plan.semantic_program, entries, profile) == plan
