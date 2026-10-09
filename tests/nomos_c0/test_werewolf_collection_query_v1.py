"""A dead role holder does not delay actual K0 dawn settlement."""

from nomos_kernel._settlement_outcome_abi import K0Published
from test_six_seat_werewolf_v0 import WITCH, _part, _program, _scene, _vote


def test_dead_witch_is_excluded_by_current_players_join_without_host_resolution():
    session = _program().start(_part(WITCH, "assets"))
    for seat, target in zip("ABCDEF", "EEEEAA", strict=True):
        _vote(session, seat, target)
    scene = _scene(session)
    assert scene.phase == "night" and scene.last_death == "E"
    assert next(role for role in scene.roles if role.id == "E").role == "witch"
    assert not next(player for player in scene.players if player.id == "E").alive
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    for seat in "CD":
        attack = next(offer for offer in session.offers(seat) if offer.label == "Attack B")
        receipt = session.submit(seat, attack.entry, dict(attack.payload))
        assert isinstance(receipt, K0Published)
    scene = _scene(session)
    assert (scene.phase, scene.round, scene.last_death) == ("day", 2, "B")
    assert not next(player for player in scene.players if player.id == "B").alive
    assert session.offers("E") == ()
    witch_owner = next(item.owner for item in session.program.owners if item.symbol == "e")
    assert session._runtime.read_owner(witch_owner.key).view.witch_notice is None
    assert "scene.roles" not in dict(session.read("D").fields)
    assert len(receipt.occurrences) == 3
