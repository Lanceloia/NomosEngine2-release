"""Both authored selection policies count current living role holders through one query."""

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_six_seat_werewolf_v0 import SIX, _part, _program, _scene, _vote


@pytest.mark.parametrize("policy", ["unanimous", "majority"])
@pytest.mark.parametrize("opening", ["seer_last", "dead_seer", "dead_wolf"])
def test_selection_waits_only_for_current_living_role_holders(policy, opening):
    source, assets = _part(SIX, "source"), _part(SIX, "assets")
    source["events"][1]["law"]["ref"] = f"event.select_{policy}"
    session = _program(source).start(assets)
    targets = {"seer_last": "CCCAAA", "dead_seer": "BAAAAA", "dead_wolf": "CCACCC"}[opening]
    for seat, target in zip("ABCDEF", targets, strict=True):
        _vote(session, seat, target)
    assert _scene(session).phase == "night"
    if opening == "dead_wolf":
        seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
        assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
        assert session.offers("C") == ()
    elif opening == "dead_seer":
        assert not any(offer.label == "Skip inspection" for offer in session.offers("A"))

    active_wolves = "D" if opening == "dead_wolf" else "CD"
    for index, seat in enumerate(active_wolves):
        attack = next(offer for offer in session.offers(seat) if offer.label == "Attack B")
        receipt = session.submit(seat, attack.entry, dict(attack.payload))
        assert isinstance(receipt, K0Published)
        if opening == "seer_last" or index < len(active_wolves) - 1:
            assert _scene(session).selection_done is False
            assert len(receipt.occurrences) == 1
    if opening == "seer_last":
        seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
        receipt = session.submit("A", seer.entry, dict(seer.payload))
        assert isinstance(receipt, K0Published)
    assert len(receipt.occurrences) == 3
    action, selected, dawn = receipt.occurrences
    assert selected.semantic_envelope.trigger == action.occurrence
    assert dawn.semantic_envelope.trigger == selected.occurrence
    scene = _scene(session)
    assert (scene.phase, scene.round, scene.last_death) == ("day", 2, "B")
    assert not next(player for player in scene.players if player.id == "B").alive
    assert "scene.roles" not in dict(session.read("D").fields)
