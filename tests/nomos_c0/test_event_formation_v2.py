"""Static causal/due Event types are separate from actual K0 occurrences."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from nomos_kernel import K0CausalLawKey, K0EventTypeKey, K0OccurrenceFamily, K0SourceSpecKey
from nomos_kernel._event_jump_abi import _K0DueFormation, _K0PendingDueKey
from nomos_kernel._occurrence_formation_abi import _K0CausalFormation
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.event_formation_binding_v2 import EventFormationPlanError, bind_event_formation_ports
from nomos_c0.event_formation_ir_v2 import (
    EventFormationProgram,
    EventFormationRule,
    FormationMechanism,
    FormationTriggerKind,
)
from nomos_c0.event_formation_v2 import (
    C0FormationEntry,
    C0FormationSessionScope,
    C0FormationTraceError,
    compile_event_formations,
    project_formed_events,
)
from nomos_c0.examples.parcel_delivery_v0 import ROOT, library
from nomos_c0.nominal_types_v1 import EventSortRef, IRValidationError, SemanticIdentity
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _source() -> dict[str, object]:
    return json.loads((ROOT / "parcel_delivery_v0.source.json").read_text(encoding="utf-8"))


def _assets(suffix: str = "a") -> dict[str, object]:
    return json.loads(
        (ROOT / f"parcel_delivery_v0.{suffix}.assets.json").read_text(encoding="utf-8")
    )


def _dispatch(session: object) -> K0Published | K0NotAdmitted:
    offer = session.form_frame("sender").offers[0]
    return session.submit("sender", offer.entry, dict(offer.payload))


@pytest.mark.parametrize("suffix", ("a", "b"))
def test_checked_static_plan_only_projects_real_published_events(suffix: str) -> None:
    program = compile_owner_graph(library(), _source())
    plan = program.formation_plan
    assert plan is not None
    assert plan.semantic_program.canonical_projection() == (
        "c0.event_formation.v2",
        (
            "PARCEL.ARRIVAL@1",
            "PARCEL.DEPARTURE@1",
            "PARCEL.MANIFEST@1",
            "PARCEL.NOTICE@1",
        ),
        (
            ("arrive", "PARCEL.ARRIVAL@1", "dispatch", "action", "due", ""),
            ("depart", "PARCEL.DEPARTURE@1", "dispatch", "action", "causal", ""),
            (
                "manifest",
                "PARCEL.MANIFEST@1",
                "depart",
                "event",
                "causal",
                "PARCEL.DEPARTURE@1",
            ),
            (
                "notice",
                "PARCEL.NOTICE@1",
                "depart",
                "event",
                "causal",
                "PARCEL.DEPARTURE@1",
            ),
        ),
    )
    session = program.start(_assets(suffix))
    assert session.formation_trace() == ()
    assert isinstance(_dispatch(session), K0Published)
    action, depart, notice, manifest = session._runtime.occurrence_history()
    formed = session.formation_trace()
    assert tuple(item.occurrence for item in formed) == (
        depart.occurrence,
        notice.occurrence,
        manifest.occurrence,
    )
    assert tuple(item.event_sort.identity.value for item in formed) == (
        "PARCEL.DEPARTURE@1",
        "PARCEL.NOTICE@1",
        "PARCEL.MANIFEST@1",
    )
    assert formed[0].predecessor == action.occurrence
    assert formed[1].predecessor == depart.occurrence
    assert formed[2].predecessor == depart.occurrence
    assert all(item.mechanism is FormationMechanism.CAUSAL for item in formed)

    session.defer_form("sender")
    session.defer_form("receiver")
    arrival_tick = 2 if suffix == "a" else 4
    assert session.continue_form("receiver").time == arrival_tick
    arrival = session._runtime.occurrence_history()[-1]
    formed = session.formation_trace()
    assert len(formed) == 4
    assert formed[-1].occurrence == arrival.occurrence
    assert formed[-1].event_sort.identity.value == "PARCEL.ARRIVAL@1"
    assert formed[-1].mechanism is FormationMechanism.DUE
    assert formed[-1].causal_law is None
    assert formed[-1].predecessor == action.occurrence
    assert formed[-1].scheduled_at == arrival_tick


def test_non_admitted_action_creates_no_typed_event() -> None:
    assets = _assets()
    assets["opening"]["scene"]["routes"] = []
    session = compile_owner_graph(library(), _source()).start(assets)
    assert isinstance(_dispatch(session), K0NotAdmitted)
    assert session.formation_trace() == ()
    assert session._runtime.occurrence_history() == ()


def test_same_local_ref_in_independent_starts_is_not_one_formed_event() -> None:
    program = compile_owner_graph(library(), _source())
    first, second = program.start(_assets()), program.start(_assets())
    assert isinstance(_dispatch(first), K0Published)
    assert isinstance(_dispatch(second), K0Published)
    assert first.formation_trace() == first.formation_trace()
    assert first.formation_trace()[0].occurrence == second.formation_trace()[0].occurrence
    assert first.formation_trace()[0] != second.formation_trace()[0]


def test_unannotated_program_cannot_claim_formation_proof() -> None:
    source = _source()
    del source["ontology"]
    session = compile_owner_graph(library(), source).start(_assets())
    with pytest.raises(C0BindingError, match="no checked Event formation"):
        session.formation_trace()


def test_due_binding_uses_scheduler_source_not_globally_unique_action_type() -> None:
    source = _source()
    source["events"] = []
    source["ontology"]["event_sorts"] = source["ontology"]["event_sorts"][:1]
    source["ontology"]["formations"] = source["ontology"]["formations"][:1]
    source["actions"][1]["event_type"] = source["actions"][0]["event_type"]

    program = compile_owner_graph(library(), source)
    assert program.formation_plan is not None
    assert program.formation_plan.edges[0].mechanism is FormationMechanism.DUE

    source["ontology"]["formations"][0]["trigger"] = "confirm"
    with pytest.raises(C0LawError, match="world formation"):
        compile_owner_graph(library(), source)


def test_due_binding_rejects_wrong_final_profile_scheduler() -> None:
    source = _source()
    program = compile_owner_graph(library(), source)
    assert program.formation_plan is not None
    confirm = dict(program.actions)["confirm"]
    arrive = next(
        edge.port for edge in program.formation_plan.edges if edge.port.result_entry == "arrive"
    )
    ontology = {
        "schema": "c0.event_formation.v2",
        "event_sorts": source["ontology"]["event_sorts"][:1],
        "formations": [
            {
                "entry": "arrive",
                "sort": "arrival",
                "trigger": "confirm",
                "trigger_kind": "action",
                "mechanism": "due",
            }
        ],
    }
    entries = (
        C0FormationEntry(
            "confirm", confirm.source_key, confirm.event_type, K0OccurrenceFamily.ACTION
        ),
        C0FormationEntry(
            "arrive",
            K0SourceSpecKey(arrive.result_source),
            K0EventTypeKey(arrive.result_event_type),
            K0OccurrenceFamily.EVENT,
            trigger_entry="confirm",
        ),
    )
    with pytest.raises(C0LawError, match="final K0 due scheduler"):
        compile_event_formations(ontology, entries, program.profile)


@pytest.mark.parametrize(
    ("mutate", "match"),
    (
        (lambda row: row.update(schema="c0.event_formation.v1"), "schema"),
        (lambda row: row["event_sorts"].append(row["event_sorts"][0]), "sort symbol"),
        (lambda row: row["formations"][3].update(sort="foreign"), "undeclared sort"),
        (lambda row: row["formations"][3].update(trigger_sort="notice"), "invalid"),
        (lambda row: row["formations"][3].update(trigger="manifest"), "invalid"),
        (lambda row: row["formations"][0].update(trigger_kind="event"), "missing or unknown"),
        (lambda row: row["formations"][0].update(trigger="confirm"), "world formation"),
        (lambda row: row["formations"][0].update(mechanism="causal"), "world formation"),
        (lambda row: row["formations"][3].update(mechanism="due"), "invalid"),
    ),
)
def test_false_ontology_claim_is_rejected_at_compile(mutate, match: str) -> None:
    source = _source()
    mutate(source["ontology"])
    with pytest.raises(C0LawError, match=match):
        compile_owner_graph(library(), source)


def test_published_causal_law_and_predecessor_are_rechecked() -> None:
    program = compile_owner_graph(library(), _source())
    session = program.start(_assets())
    assert isinstance(_dispatch(session), K0Published)
    history = list(session._runtime.occurrence_history())
    notice = history[2]
    history[2] = replace(
        notice,
        formation_basis=_K0CausalFormation(history[1].occurrence, K0CausalLawKey("wrong")),
    )
    with pytest.raises(C0FormationTraceError, match="violates"):
        project_formed_events(program.formation_plan, tuple(history), C0FormationSessionScope())
    history[2] = replace(
        notice,
        formation_basis=_K0CausalFormation(
            history[0].occurrence, notice.formation_basis.causal_law
        ),
    )
    with pytest.raises(C0FormationTraceError, match="violates"):
        project_formed_events(program.formation_plan, tuple(history), C0FormationSessionScope())


def test_published_due_rechecks_the_actual_scheduling_action_ref() -> None:
    program = compile_owner_graph(library(), _source())
    session = program.start(_assets())
    assert isinstance(_dispatch(session), K0Published)
    assert len(session.formation_trace()) == 3
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("sender")
    history = list(session._runtime.occurrence_history())
    due = history[-1]
    basis = due.formation_basis
    assert type(basis) is _K0DueFormation
    history[-1] = replace(
        due,
        formation_basis=_K0DueFormation(
            _K0PendingDueKey(history[1].occurrence, basis.key.ordinal), basis.scheduled_at
        ),
    )
    with pytest.raises(C0FormationTraceError, match="violates"):
        project_formed_events(program.formation_plan, tuple(history), C0FormationSessionScope())


def test_semantic_projection_rejects_unclosed_event_trigger_sort() -> None:
    departure = EventSortRef(SemanticIdentity("PARCEL.DEPARTURE@1"))
    notice = EventSortRef(SemanticIdentity("PARCEL.NOTICE@1"))
    with pytest.raises(IRValidationError, match="trigger sort"):
        EventFormationProgram(
            (departure, notice),
            (
                EventFormationRule(
                    "depart",
                    departure,
                    "dispatch",
                    FormationTriggerKind.ACTION,
                    FormationMechanism.CAUSAL,
                ),
                EventFormationRule(
                    "notice",
                    notice,
                    "depart",
                    FormationTriggerKind.EVENT,
                    FormationMechanism.CAUSAL,
                    notice,
                ),
            ),
        )


def test_port_binding_rejects_rebinding_after_semantic_check() -> None:
    plan = compile_owner_graph(library(), _source()).formation_plan
    assert plan is not None
    depart, notice = (
        next(edge.port for edge in plan.edges if edge.port.result_entry == name)
        for name in ("depart", "notice")
    )
    wrong = replace(notice, trigger_source="c0.parcel.manifest")
    with pytest.raises(EventFormationPlanError, match="trigger binding"):
        bind_event_formation_ports(
            plan.semantic_program,
            tuple(
                wrong if edge.port.result_entry == "notice" else edge.port for edge in plan.edges
            ),
        )
    wrong = replace(notice, result_source=depart.result_source)
    with pytest.raises(EventFormationPlanError, match="conflicting Event sorts"):
        bind_event_formation_ports(
            plan.semantic_program,
            tuple(
                wrong if edge.port.result_entry == "notice" else edge.port for edge in plan.edges
            ),
        )


def test_profile_binding_rejects_unregistered_causal_law() -> None:
    source = _source()
    program = compile_owner_graph(library(), source)
    assert program.formation_plan is not None
    # C0's profile is the authority; a copied claim with a different final Law cannot bind.
    depart = dict(program.events)["depart"]
    dispatch = dict(program.actions)["dispatch"]
    wrong = (
        C0FormationEntry(
            "dispatch", dispatch.source_key, dispatch.event_type, K0OccurrenceFamily.ACTION
        ),
        C0FormationEntry(
            "depart",
            depart.ports.source_key,
            depart.ports.event_type,
            K0OccurrenceFamily.EVENT,
            K0CausalLawKey("wrong"),
            "dispatch",
        ),
    )
    ontology = {
        "schema": "c0.event_formation.v2",
        "event_sorts": [
            item for item in source["ontology"]["event_sorts"] if item["symbol"] == "departure"
        ],
        "formations": [
            item for item in source["ontology"]["formations"] if item["entry"] == "depart"
        ],
    }
    with pytest.raises(C0LawError, match="final K0 causal law"):
        compile_event_formations(ontology, wrong, program.profile)
