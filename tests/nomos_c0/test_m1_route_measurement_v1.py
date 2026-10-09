"""The benchmark selects current offers and never bypasses admission."""

import json
from types import SimpleNamespace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from tools.c0_benchmark_m1_route import Journey, payload_json


def _journey(offers=(), *, ready=("adventurer",), finished=False, result=None):
    calls = []
    frame = SimpleNamespace(ready_seats=ready, finished=finished, outcome="stopped", offers=offers)

    def submit(seat, entry, payload):
        calls.append((seat, entry, payload))
        return result

    session = SimpleNamespace(continue_form=lambda seat: frame, submit=submit, time=0)
    return Journey(session), calls


@pytest.mark.parametrize("offers", [(), (SimpleNamespace(entry="other", payload=()),)])
def test_missing_offer_never_submits_a_fabricated_payload(offers):
    journey, calls = _journey(offers)
    with pytest.raises(ValueError, match="exactly one current offer"):
        journey.choose("wanted")
    assert calls == [] and journey.actions == []


def test_duplicate_matching_offers_are_not_silently_selected():
    offer = SimpleNamespace(entry="wanted", payload=(("target", "here"),))
    journey, calls = _journey((offer, offer))
    with pytest.raises(ValueError, match="exactly one current offer"):
        journey.choose("wanted", target="here")
    assert calls == []


def test_rejected_submission_stops_the_route_without_recording_success():
    offer = SimpleNamespace(entry="wanted", payload=(("target", "here"), ("cost", 10)))
    journey, calls = _journey((offer,), result=object())
    with pytest.raises(ValueError, match="Action rejected"):
        journey.choose("wanted", target="here")
    assert calls == [("adventurer", "wanted", {"target": "here", "cost": 10})]
    assert journey.actions == []


@pytest.mark.parametrize("ready,finished", [((), True), (("other",), False)])
def test_no_player_opportunity_never_controls_another_seat(ready, finished):
    journey, calls = _journey(ready=ready, finished=finished)
    with pytest.raises(ValueError, match="lost player opportunity"):
        journey.choose("wanted")
    assert calls == []


def test_report_payload_encodes_opaque_local_refs_without_erasing_family_or_ordinal():
    value = {"torch": _K0IndividualRef("first", 2, "torch"), "basis": K0OccurrenceRef(3)}
    encoded = json.loads(json.dumps(value, default=payload_json))
    assert encoded["torch"] == {
        "kind": "_K0IndividualRef",
        "family": "torch",
        "ordinal": 2,
        "scope": "local",
    }
    assert encoded["basis"] == {"kind": "K0OccurrenceRef", "value": 3}
    changed = {**value, "torch": _K0IndividualRef("second", 2, "torch")}
    assert json.loads(json.dumps(changed, default=payload_json)) == encoded
    with pytest.raises(TypeError, match="unsupported benchmark payload"):
        json.dumps(object(), default=payload_json)
