"""Offers pass opaque readable evidence, not integers or implicit history access."""

from copy import deepcopy
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.seat_offers_v0 import compile_seat_offers


def record(name, fields):
    return {
        "name": name,
        "fields": [{"name": key, "type": kind} for key, kind in fields],
        "invariant": None,
    }


def fixture():
    text = {"str": [1, 32]}
    lib = {
        "schema": "c0.nominal_lib.v1",
        "records": [
            record("Scene", [("label", text)]),
            record("Evidence", [("label", text), ("reference", "occurrence_ref")]),
            record(
                "Actor",
                [
                    ("name", text),
                    ("evidence", {"optional": "Evidence"}),
                    ("candidates", {"tuple": {"item": "Evidence", "max": 4}}),
                ],
            ),
            record("Attempt", [("actor", text), ("basis", "occurrence_ref")]),
            record("Envelope", [("action", "occurrence_ref")]),
        ],
        "owners": [
            {
                "symbol": "scene",
                "key": "offer.scene",
                "version": "1",
                "state": "Scene",
                "identity_field": None,
                "write": "replace_one",
                "seat_read": [],
            },
            {
                "symbol": "actor",
                "key": "offer.actor",
                "version": "1",
                "state": "Actor",
                "identity_field": "name",
                "write": "replace_one",
                "seat_read": ["name", "evidence", "evidence.reference", "candidates"],
            },
        ],
        "lawdefs": [],
    }
    ports = {
        "schema": "c0.graph_ports.v1",
        "scene_owner": "scene",
        "offer_provider": {"name": "finite_value", "version": "1", "limit": 4},
        "actions": [
            {
                "symbol": "ack",
                "actor": "actor",
                "payload": "Attempt",
                "envelope": "Envelope",
                "actor_identity_field": "name",
                "payload_actor_field": "actor",
                "effects": {"scene": {}, "actor": {}},
                "envelope_fields": {"action": "action"},
                "schedule": None,
                "value": {
                    "read": [
                        "actor.name",
                        "actor.evidence",
                        "actor.evidence.reference",
                        "actor.candidates",
                    ],
                    "fields": {"Evidence": ["label", "reference"]},
                    "write_paths": [],
                    "construct": [],
                    "collections": {},
                },
            }
        ],
        "events": [],
        "due_events": [],
    }
    nominal = check_nominal_lib(lib)
    library = check_graph_ports(ports, nominal)
    return library, dict(nominal.records)


def compile_offers(declarations, reads=None):
    library, records = fixture()
    ports = library.actions[0].ports
    declarations = compile_seat_offers(
        declarations,
        ("ack",),
        tuple(
            reads
            if reads is not None
            else ("actor.name", "actor.evidence", "actor.evidence.reference", "actor.candidates")
        ),
        {"ack": ports},
        {"ack": "scene"},
        "actor",
        library.offer_provider,
    )
    return declarations, records


def offer(condition=None, basis=None):
    return {
        "entry": "ack",
        "label": "Acknowledge evidence",
        "when": {"not_none": {"ref": "actor.evidence"}} if condition is None else condition,
        "payload": {"basis": {"ref": "actor.evidence.reference"} if basis is None else basis},
    }


def test_condition_dominates_payload_and_preserves_readable_opaque_reference():
    declarations, records = compile_offers([offer()])
    scene = records["Scene"](label="test")
    actor = records["Actor"](name="reader", evidence=None, candidates=())
    assert declarations[0].evaluate_many(scene, actor) == ()
    evidence = records["Evidence"](label="seen", reference=K0OccurrenceRef(7))
    actor = records["Actor"](name="reader", evidence=evidence, candidates=())
    result = declarations[0].evaluate_many(scene, actor)
    assert dict(result[0].payload)["basis"] is evidence.reference


def test_ranged_offer_passes_each_own_evidence_without_minting_or_reinterpreting_refs():
    ranged = offer(condition={"const": True}, basis={"ref": "candidate.reference"})
    ranged["for_each"] = {"collection": {"ref": "actor.candidates"}, "as": "candidate"}
    ranged["label"] = {"prefix": "Acknowledge ", "value": {"ref": "candidate.label"}}
    declarations, records = compile_offers([ranged])
    evidence = tuple(
        records["Evidence"](label=label, reference=K0OccurrenceRef(index))
        for index, label in enumerate(("first", "second"), 1)
    )
    actor = records["Actor"](name="reader", evidence=None, candidates=evidence)
    result = declarations[0].evaluate_many(records["Scene"](label="test"), actor)
    assert [dict(item.payload)["basis"] for item in result] == [item.reference for item in evidence]


@pytest.mark.parametrize(
    "condition",
    [
        {"const": True},
        {"any": [{"not_none": {"ref": "actor.evidence"}}, {"const": True}]},
        {"not": {"not_none": {"ref": "actor.evidence"}}},
    ],
)
def test_non_dominating_conditions_cannot_license_nullable_payload_reads(condition):
    with pytest.raises(C0LawError, match="nullable"):
        compile_offers([offer(condition=condition)])


def test_one_offer_cannot_borrow_another_offers_nonnull_proof():
    second = offer(condition={"const": True})
    second["label"] = "Another judgement"
    with pytest.raises(C0LawError, match="nullable"):
        compile_offers([offer(), second])


def test_nonnull_proof_does_not_grant_a_private_read_path():
    with pytest.raises(C0LawError, match="read boundary"):
        compile_offers([offer()], reads=("actor.name",))


@pytest.mark.parametrize("basis", [{"const": 7}, {"const": "7"}, {"ref": "occurrence"}])
def test_menu_cannot_cast_an_integer_or_create_an_occurrence_reference(basis):
    with pytest.raises(C0LawError):
        compile_offers([offer(basis=basis)])


def reference_binding_world(kind, proof_gate):
    root = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
    stem = "object_target_v1" if kind == "object" else "multi_participant_v0"
    lib, ports, source, assets = (
        read_author_document(root / f"{stem}.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )
    if kind == "object":
        actor, record_name, attempt_name, entry, evidence = (
            "actor",
            "Actor",
            "InspectAttempt",
            "inspect",
            "make_ref",
        )
    else:
        actor, record_name, attempt_name, entry, evidence = (
            "maker",
            "Person",
            "EnableAttempt",
            "enable",
            "evidence",
        )
        person = next(r for r in lib["records"] if r["name"] == record_name)
        person["fields"].append({"name": evidence, "type": {"optional": "occurrence_ref"}})
        for opening in assets["opening"].values():
            if "enabled" in opening:
                opening[evidence] = None
        next(o for o in lib["owners"] if o["symbol"] == actor)["seat_read"].append(evidence)
        source["seats"][0]["read"].append(f"{actor}.{evidence}")
        action = ports["actions"][0]
        action["effects"]["actor"][evidence] = evidence
        action["value"]["write_paths"].append(f"actor.{evidence}")
        action["value"]["outputs"] = {evidence: "occurrence_ref"}
        lib["lawdefs"][0]["body"]["value"]["outputs"][evidence] = {"ref": "occurrence"}
        # The first genuine Action supplies evidence for a later participant offer.
        seed_record = deepcopy(next(r for r in lib["records"] if r["name"] == attempt_name))
        seed_record["name"] = "SeedAttempt"
        lib["records"].append(seed_record)
        seed_port = deepcopy(action)
        seed_port.update(symbol="seed", payload="SeedAttempt")
        ports["actions"].append(seed_port)
        seed_action = deepcopy(source["actions"][0])
        seed_action.update(
            name="seed", template="seed", source_key="test.seed", event_type="test.seed.action"
        )
        source["actions"].append(seed_action)
        source["seats"][0]["entries"].append("seed")
        seed_offer = deepcopy(source["seats"][0]["offers"][0])
        seed_offer.update(entry="seed", when={"is_none": {"ref": f"actor.{evidence}"}})
        source["seats"][0]["offers"].append(seed_offer)
    payload = next(r for r in lib["records"] if r["name"] == attempt_name)
    payload["fields"].append({"name": "basis", "type": "occurrence_ref"})
    action = next(p for p in ports["actions"] if p["symbol"] == entry)
    action["value"]["read"].append(f"actor.{evidence}")
    offer = next(o for o in source["seats"][0]["offers"] if o["entry"] == entry)
    offer[proof_gate] = {"all": [offer[proof_gate], {"not_none": {"ref": f"actor.{evidence}"}}]}
    offer["payload"]["basis"] = {"ref": f"actor.{evidence}"}
    return lib, ports, source, assets, actor, entry, evidence


@pytest.mark.parametrize("kind", ["object", "participant"])
@pytest.mark.parametrize("proof_gate", ["visible_when", "when"])
def test_selected_object_payload_preserves_evidence_only_after_both_conditions_pass(
    kind, proof_gate
):
    lib, ports, source, assets, actor, entry, evidence = reference_binding_world(kind, proof_gate)
    program = compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    game = program.start(assets)
    assert not any(o.entry == entry for o in game.offers(actor))
    initial_entry = "make" if kind == "object" else "seed"
    initial = next(o for o in game.offers(actor) if o.entry == initial_entry)
    result = game.submit(actor, initial.entry, dict(initial.payload))
    assert isinstance(result, K0Published)
    actual = result.occurrences[0].occurrence
    selected = next(
        o
        for o in game.offers(actor)
        if o.entry == entry and (kind == "object" or dict(o.payload)["victim"] == "b")
    )
    assert dict(selected.payload)["basis"] == actual
    assert getattr(dict(game.author_snapshot().owners)[actor], evidence) == actual
    assert isinstance(game.submit(actor, selected.entry, dict(selected.payload)), K0Published)


@pytest.mark.parametrize("kind", ["object", "participant"])
def test_object_visibility_any_is_not_a_nonnull_proof_for_payload(kind):
    lib, ports, source, _, _, entry, evidence = reference_binding_world(kind, "visible_when")
    offer = next(o for o in source["seats"][0]["offers"] if o["entry"] == entry)
    offer["visible_when"] = {"any": [{"not_none": {"ref": f"actor.{evidence}"}}, {"const": True}]}
    with pytest.raises(C0LawError, match="payload has a foreign public type"):
        compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
