"""Selected-entry projection preserves current offers and the full menu budget."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _compile, _world
from test_visibility_binding_v1 import _inputs

from nomos_c0 import program_runtime_v1 as runtime
from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.composable_value_v1 import C0ValueStateError
from nomos_c0.program_runtime_v1 import _ProjectionReads
from nomos_c0.seat_offers_v0 import C0ParticipantOfferDeclaration, _offer_count_upper_bound
from nomos_c0.visibility_ir_v1 import OFFER_FIELDS


def two_entries(limit=8):
    lib, ports, source, assets = _world()
    ports["offer_provider"]["limit"] = limit
    other = deepcopy(source["actions"][0])
    other.update(name="other", source_key="sample.other", event_type="sample.other.action")
    source["actions"].append(other)
    seat = source["seats"][0]
    seat["entries"].append("other")
    offer = deepcopy(seat["offers"][0])
    offer["entry"] = "other"
    seat["offers"].append(offer)
    return lib, ports, source, assets


def test_submit_does_not_evaluate_unrelated_declarations_when_capacity_is_proven(monkeypatch):
    lib, ports, source, assets = two_entries()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    evaluate = C0ParticipantOfferDeclaration.evaluate_many
    visited = []

    def observed(declaration, *args):
        visited.append(declaration.entry)
        assert declaration.entry != "other"
        return evaluate(declaration, *args)

    monkeypatch.setattr(C0ParticipantOfferDeclaration, "evaluate_many", observed)
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert visited == ["enable"]
    assert len(session._runtime.occurrence_history()) == 1


def test_unproven_capacity_still_checks_the_complete_menu_and_refuses_overflow(monkeypatch):
    lib, ports, source, assets = two_entries(7)
    session = _compile(lib, ports, source).start(assets)
    selected = session.program._seats_by_symbol["maker"]
    assert not session._can_project_entry(selected, _ProjectionReads(session._runtime))
    reads = _ProjectionReads(session._runtime)
    selected_only = session._project_offers("maker", reads, entry="enable")[0]
    assert len(selected_only) == 4
    before = session.author_snapshot()
    assert session.offers("maker") == ()
    visited = []
    original = C0ParticipantOfferDeclaration.evaluate_many

    def observed(declaration, *args):
        visited.append(declaration.entry)
        return original(declaration, *args)

    monkeypatch.setattr(C0ParticipantOfferDeclaration, "evaluate_many", observed)
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", dict(selected_only[0].payload))
    assert visited == ["enable", "other"]
    assert session.author_snapshot() == before


def test_same_entry_multiple_declarations_keep_original_candidate_check_indices():
    lib, ports, source, assets = two_entries(16)
    ports["candidate_inputs"] = [
        {
            "symbol": "available",
            "action": "enable",
            "read": ["tool.ready", "victim.enabled"],
            "fields": {},
        }
    ]
    seat = source["seats"][0]
    second = deepcopy(seat["offers"][0])
    second["availability"] = {"ref": "available", "when": "not victim.enabled"}
    seat["offers"][0]["when"] = False
    seat["offers"].append(second)
    assets["opening"]["a"]["enabled"] = True
    session = _compile(lib, ports, source).start(assets)
    enabled = [item for item in session.offers("maker") if item.entry == "enable"]
    assert [item.label for item in enabled] == ["Use one on b", "Use two on b"]
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", {**dict(enabled[0].payload), "victim": "a"})
    assert isinstance(session.submit("maker", "enable", dict(enabled[-1].payload)), K0Published)


@pytest.mark.parametrize("fault", ["stale", "foreign", "extra"])
def test_targeted_recheck_does_not_accept_stale_foreign_or_injected_payload(fault):
    lib, ports, source, assets = two_entries()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    offer = session.offers("maker")[0]
    payload = dict(offer.payload)
    if fault == "stale":
        assert isinstance(session.submit("maker", offer.entry, payload), K0Published)
    elif fault == "foreign":
        other = program.start(assets)
        payload = dict(other.offers("maker")[0].payload)
    else:
        payload["private"] = True
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", offer.entry, payload)
    assert session.author_snapshot() == before


def test_current_offer_still_goes_through_k0_guard():
    lib, ports, source, assets = two_entries()
    lib["lawdefs"][0]["body"]["value"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    before = session.author_snapshot()
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before


def test_bound_counts_raw_combinations_before_deduplication_and_condition_filtering():
    lib, ports, source, assets = two_entries()
    session = _compile(lib, ports, source).start(assets)
    selected = session.program._seats_by_symbol["maker"]
    declaration = selected.offers[0]
    action = session.program._actions_by_name[declaration.entry]
    reads = _ProjectionReads(session._runtime)
    scene, actor = reads.owner(action.scene_owner.key), reads.owner(action.actor_owner.key)
    assert _offer_count_upper_bound(declaration, scene, actor, {"tool": 2}) == 4
    assert _offer_count_upper_bound(declaration, scene, actor, {}) == 0
    assert _offer_count_upper_bound(declaration, scene, actor, {"tool": 20}) == 8
    # A repeated role is another product dimension, not a union of families.
    repeated = replace(declaration, objects=(*declaration.objects, *declaration.objects))
    assert _offer_count_upper_bound(repeated, scene, actor, {"tool": 2}) == 8


def test_unknown_declaration_has_no_capacity_proof():
    assert _offer_count_upper_bound(object(), None, None, {}) is None


@pytest.mark.parametrize("kind", tuple(OFFER_FIELDS))
def test_every_offer_shape_has_the_same_targeted_payloads_and_previews(kind):
    lib, ports, source, assets = _inputs(kind)
    session = _compile(lib, ports, source).start(assets)
    selected = session.program.seats[0]
    seat = selected.symbol
    assert session._can_project_entry(selected, _ProjectionReads(session._runtime))
    complete = session.offers(seat)
    for entry in selected.entries:
        targeted = session._project_offers(seat, _ProjectionReads(session._runtime), entry=entry)[0]
        assert targeted == tuple(offer for offer in complete if offer.entry == entry)


def test_uncertain_collection_proof_runs_the_complete_path_instead_of_refusing(monkeypatch):
    lib, ports, source, assets = two_entries()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]

    def uncertain(*args):
        raise C0ValueStateError("collection cannot be proved")

    monkeypatch.setattr(runtime, "_offer_count_upper_bound", uncertain)
    visited = []
    original = C0ParticipantOfferDeclaration.evaluate_many

    def observed(declaration, *args):
        visited.append(declaration.entry)
        return original(declaration, *args)

    monkeypatch.setattr(C0ParticipantOfferDeclaration, "evaluate_many", observed)
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    assert visited == ["enable", "other"]


def test_duplicate_payloads_do_not_reduce_the_global_budget_proof():
    lib, ports, source, assets = two_entries(7)
    source["seats"][0]["offers"][1]["entry"] = "enable"
    source["seats"][0]["offers"][1]["label"][0] = {"const": "Another "}
    session = _compile(lib, ports, source).start(assets)
    selected = session.program.seats[0]
    assert not session._can_project_entry(selected, _ProjectionReads(session._runtime))
    assert session.offers("maker") == ()
