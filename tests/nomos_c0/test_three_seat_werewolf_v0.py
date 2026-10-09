"""The three-seat authored world must use the same C0 Program and K0 Session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from yaml.constructor import ConstructorError

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_play_v1 import main as play_main
from nomos_c0.owner_graph_v1 import compile_owner_graph

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
STEM = ROOT / "three_seat_werewolf_v0"


def _part(name: str) -> dict[str, object]:
    document = read_author_document(STEM.with_suffix(f".{name}.yaml")).to_data()
    assert type(document) is dict
    return document


def _program(source=None, lib=None):
    source = _part("source") if source is None else source
    checked = check_nominal_lib(_part("lib") if lib is None else lib, source["actor_domains"])
    library = check_graph_ports(_part("ports"), checked)
    return compile_owner_graph(library, source)


def _session():
    return _program().start(_part("assets"))


def _submit(session, seat: str, entry: str, target: str | None = None) -> None:
    offer = next(
        item
        for item in session.offers(seat)
        if item.entry == entry and (target is None or dict(item.payload)["target"] == target)
    )
    assert isinstance(session.submit(seat, offer.entry, dict(offer.payload)), K0Published)


def _scene(session):
    owner = next(item.owner for item in session.program.owners if item.symbol == "scene")
    return session._runtime.read_owner(owner.key).view


@pytest.mark.parametrize(
    ("change", "diagnostic"),
    (
        ("append_member", "unknown or mistyped operation"),
        ("replacement_key", "unique replacement uses a foreign key"),
        ("quantifier_guard", "bounded quantifier predicate is not boolean"),
    ),
)
def test_v6_collection_laws_reject_malformed_author_edits(change: str, diagnostic: str) -> None:
    lib = _part("lib")
    vote = next(item for item in lib["lawdefs"] if item["name"] == "action.vote")
    resolution = next(item for item in lib["lawdefs"] if item["name"] == "event.resolve_day")
    if change == "append_member":
        vote["body"]["value"]["outputs"]["ballots"]["append"][1] = {"ref": "scene.round"}
    elif change == "replacement_key":
        resolution["body"]["law"]["outputs"]["players"]["if"]["then"]["replace_unique"]["key"] = (
            "alive"
        )
    else:
        vote["body"]["value"]["guard"]["all"][-1]["none_matching"]["where"] = {"const": 1}
    with pytest.raises(C0LawError, match=diagnostic):
        _program(lib=lib)


def test_duplicate_keyed_append_rolls_back_the_second_vote() -> None:
    lib = _part("lib")
    source = _part("source")
    vote = next(item for item in lib["lawdefs"] if item["name"] == "action.vote")
    vote_guard = vote["body"]["value"]["guard"]["all"]
    vote_guard[:] = [item for item in vote_guard if "none_matching" not in item]
    offer_guard = source["seats"][0]["offers"][0]["when"]["all"]
    offer_guard[:] = [item for item in offer_guard if "none_matching" not in item]
    session = _program(source=source, lib=lib).start(_part("assets"))
    _submit(session, "A", "vote_a", "C")
    before_scene = _scene(session)
    before_view = session.read("A")
    before_history = session._runtime.occurrence_history()
    offer = next(item for item in session.offers("A") if dict(item.payload)["target"] == "C")
    with pytest.raises(K0SettlementDefect) as defect:
        session.submit("A", offer.entry, dict(offer.payload))
    assert "declared collection key is not unique" in str(defect.value.__cause__.__cause__)
    assert session._runtime.occurrence_history() == before_history
    assert _scene(session) == before_scene
    assert session.read("A") == before_view


def test_same_round_vote_is_rejected_by_k0_after_offer_disappears() -> None:
    session = _session()
    _submit(session, "A", "vote_a", "C")
    assert session.offers("A") == ()
    action = dict(session.program.actions)["vote_a"]
    attempted = action.payload_type(actor="A", target="B")
    before_scene = _scene(session)
    before_history = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, attempted)),
        K0NotAdmitted,
    )
    assert _scene(session) == before_scene
    assert session._runtime.occurrence_history() == before_history


def test_expanded_actor_opening_guard_rejects_unknown_field_at_compile() -> None:
    source = _part("source")
    source["opening_actor_guards"][0]["when"]["all"][0]["eq"][0]["count_matching"]["where"]["eq"][
        1
    ] = {"ref": "actor.missing"}
    with pytest.raises(C0LawError, match="reference crosses a declared read boundary"):
        _program(source=source)


def test_conditional_event_effect_rejects_incompatible_branch_at_compile() -> None:
    lib = _part("lib")
    resolution = next(item for item in lib["lawdefs"] if item["name"] == "event.resolve_day")
    resolution["body"]["law"]["outputs"]["players"]["if"]["else"] = {"const": 1}
    with pytest.raises(C0LawError, match="value output has a wrong nominal type"):
        _program(lib=lib)


def test_count_matching_rejects_foreign_actor_collection_at_compile() -> None:
    lib = _part("lib")
    resolution = next(item for item in lib["lawdefs"] if item["name"] == "event.resolve_day")
    threshold = resolution["body"]["law"]["bindings"][0]["where"]["all"][1]
    threshold["lt"][0]["count_matching"]["collection"] = {"ref": "actor.votes"}
    with pytest.raises(C0LawError, match="reference has no declared root"):
        _program(lib=lib)


def test_replacement_of_noncurrent_member_rolls_back_triggering_vote() -> None:
    lib = _part("lib")
    resolution = next(item for item in lib["lawdefs"] if item["name"] == "event.resolve_day")
    replacement = resolution["body"]["law"]["outputs"]["players"]["if"]["then"]["replace_unique"]
    replacement["old"] = {
        "copy": {"from": {"ref": "leader"}, "changes": {"alive": {"const": False}}}
    }
    session = _program(lib=lib).start(_part("assets"))
    _submit(session, "A", "vote_a", "C")
    _submit(session, "B", "vote_b", "C")
    before_scene = _scene(session)
    before_view = session.read("C")
    before_history = session._runtime.occurrence_history()
    offer = next(item for item in session.offers("C") if dict(item.payload)["target"] == "B")
    with pytest.raises(K0SettlementDefect) as defect:
        session.submit("C", offer.entry, dict(offer.payload))
    assert "unique replacement lost its current member" in str(defect.value.__cause__.__cause__)
    assert session._runtime.occurrence_history() == before_history
    assert _scene(session) == before_scene
    assert session.read("C") == before_view


def test_three_seats_cast_provenance_bearing_votes_without_role_leak() -> None:
    session = _session()
    for seat, expected_role in (("A", "seer"), ("B", "villager"), ("C", "wolf")):
        fields = dict(session.read(seat).fields)
        assert fields[f"{seat.lower()}.own_role"] == expected_role
        assert "scene.roles" not in fields
        assert "scene.ballots" not in fields
        assert len(session.offers(seat)) == 3

    for seat, target in (("A", "C"), ("B", "C"), ("C", "B")):
        offer = next(
            item for item in session.offers(seat) if dict(item.payload)["target"] == target
        )
        result = session.submit(seat, offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        assert session.offers(seat) == ()

    scene = _scene(session)
    assert [(vote.voter, vote.target) for vote in scene.ballots] == [
        ("A", "C"),
        ("B", "C"),
        ("C", "B"),
    ]
    assert len({vote.action for vote in scene.ballots}) == 3
    history = session._runtime.occurrence_history()
    assert len(history) == 4
    assert scene.phase == "finished"
    assert scene.winner == "town"
    assert scene.last_death == "C"
    assert {player.id: player.alive for player in scene.players} == {
        "A": True,
        "B": True,
        "C": False,
    }
    assert history[-1].semantic_envelope.trigger == history[-2].occurrence
    assert "scene.ballots" not in dict(session.read("A").fields)


def test_authored_actor_domain_instantiates_one_capability_per_participant() -> None:
    source = _part("source")
    ports = _part("ports")
    assert [item["symbol"] for item in ports["actions"]] == [
        "vote",
        "attack",
        "divine",
        "skip_inspection",
        "witch_intervene",
    ]
    assert source["actor_domains"] == [
        {
            "name": "participants",
            "owner_template": "participant",
            "actor_state": "Actor",
            "owners": ["a", "b", "c"],
        }
    ]
    assert len(source["opening_actor_guards"]) == 1
    assert source["opening_actor_guards"][0]["domain"] == "participants"
    scene_record = next(row for row in _part("lib")["records"] if row["name"] == "Scene")
    assert {"a_id", "b_id", "c_id"}.isdisjoint({field["name"] for field in scene_record["fields"]})
    assert [item["family"] for item in source["actions"]] == [
        "vote",
        "attack",
        "divine",
        "skip_inspection",
    ]
    assert len(source["seats"]) == 1
    seat_family = source["seats"][0]
    assert seat_family["seat_family"] == "participants"
    assert seat_family["entries"] == ["vote", "attack", "divine", "skip_inspection"]
    assert [offer["entry_family"] for offer in seat_family["offers"]] == [
        "vote",
        "divine",
        "attack",
        "skip_inspection",
    ]
    assert all("for_each" in offer for offer in seat_family["offers"][:3])
    assert {name for name, _action in _program().actions} >= {
        "attack_a",
        "attack_b",
        "attack_c",
    }


def test_wolf_route_uses_private_inspection_and_two_night_deaths() -> None:
    session = _session()
    for seat, target in (("A", "C"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    assert _scene(session).phase == "night"
    assert _scene(session).last_death is None
    assert all(player.alive for player in _scene(session).players)

    _submit(session, "A", "divine_a", "C")
    observations = dict(session.read("A").fields)["a.observations"]
    assert [(item.target, item.faction) for item in observations] == [("C", "wolf")]
    assert dict(session.read("B").fields)["b.observations"] == ()
    assert dict(session.read("C").fields)["c.observations"] == ()

    _submit(session, "C", "attack_c", "B")
    assert (_scene(session).phase, _scene(session).round, _scene(session).winner) == (
        "day",
        2,
        "none",
    )
    assert not next(player for player in _scene(session).players if player.id == "B").alive
    assert session.offers("B") == ()

    _submit(session, "A", "vote_a", "C")
    _submit(session, "C", "vote_c", "A")
    assert _scene(session).phase == "night"
    _submit(session, "C", "attack_c", "A")
    assert _scene(session).phase == "night"
    _submit(session, "A", "skip_inspection_a")
    assert (_scene(session).phase, _scene(session).winner, _scene(session).last_death) == (
        "finished",
        "wolf",
        "A",
    )
    assert all(session.offers(seat) == () for seat in ("A", "B", "C"))


def test_wolf_first_attack_waits_for_seer_choice_without_leaking_it() -> None:
    session = _session()
    for seat, target in (("A", "C"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    _submit(session, "C", "attack_c", "B")
    assert _scene(session).phase == "night"
    assert all(player.alive for player in _scene(session).players)
    assert session.offers("C") == ()
    assert dict(session.read("C").fields)["c.attacks"][0].target == "B"
    assert {offer.label for offer in session.offers("A")} == {
        "Inspect B",
        "Inspect C",
        "Skip inspection",
    }
    _submit(session, "A", "skip_inspection_a")
    assert (_scene(session).phase, _scene(session).last_death) == ("day", "B")
    assert dict(session.read("A").fields)["a.observations"] == ()
    choices = dict(session.read("A").fields)["a.choices"]
    assert [(choice.round, choice.kind) for choice in choices] == [(1, "pass")]
    assert dict(session.read("C").fields)["c.choices"] == ()


def test_wolf_first_then_inspection_and_pass_first_both_close_the_night() -> None:
    for choice in ("divine_a", "skip_inspection_a"):
        session = _session()
        for seat, target in (("A", "C"), ("B", "A"), ("C", "B")):
            _submit(session, seat, f"vote_{seat.lower()}", target)
        if choice == "skip_inspection_a":
            _submit(session, "A", choice)
            assert _scene(session).phase == "night"
            _submit(session, "C", "attack_c", "B")
        else:
            _submit(session, "C", "attack_c", "B")
            _submit(session, "A", choice, "C")
        assert (_scene(session).phase, _scene(session).last_death) == ("day", "B")
        assert len(dict(session.read("A").fields)["a.observations"]) == (
            1 if choice == "divine_a" else 0
        )


def test_dead_seer_does_not_block_night_settlement() -> None:
    session = _session()
    for seat, target in (("A", "A"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    assert _scene(session).phase == "night"
    assert session.offers("A") == ()
    _submit(session, "C", "attack_c", "B")
    assert (_scene(session).phase, _scene(session).winner) == ("finished", "wolf")


def test_exiling_the_last_town_player_ends_the_game_immediately() -> None:
    session = _session()
    for seat, target in (("A", "C"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    _submit(session, "A", "divine_a", "C")
    _submit(session, "C", "attack_c", "B")
    _submit(session, "A", "vote_a", "A")
    _submit(session, "C", "vote_c", "A")
    assert (_scene(session).phase, _scene(session).winner, _scene(session).last_death) == (
        "finished",
        "wolf",
        "A",
    )
    assert all(session.offers(seat) == () for seat in ("A", "B", "C"))


def test_same_program_accepts_role_swap_but_rejects_inconsistent_opening() -> None:
    program = _program()
    assets = _part("assets")
    assets["opening"]["scene"]["roles"][0]["role"] = "wolf"
    assets["opening"]["scene"]["roles"][2]["role"] = "seer"
    with pytest.raises(C0BindingError, match="opening guard"):
        program.start(assets)
    assets["opening"]["a"]["own_role"] = "wolf"
    assets["opening"]["c"]["own_role"] = "seer"
    session = program.start(assets)
    assert dict(session.read("A").fields)["a.own_role"] == "wolf"
    assert dict(session.read("C").fields)["c.own_role"] == "seer"
    assert "scene.roles" not in dict(session.read("B").fields)
    for seat, target in (("A", "C"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    assert {offer.label for offer in session.offers("A")} == {"Attack B", "Attack C"}
    assert {offer.label for offer in session.offers("C")} == {
        "Inspect A",
        "Inspect B",
        "Skip inspection",
    }


def test_majority_law_edit_changes_the_real_event_not_the_ballots() -> None:
    lib = _part("lib")
    law = next(item for item in lib["lawdefs"] if item["name"] == "event.resolve_day")
    threshold = law["body"]["law"]["bindings"][0]["where"]["all"][1]
    assert "lt" in threshold
    threshold.clear()
    threshold["le"] = [
        {"const": 3},
        {
            "count_matching": {
                "collection": {"ref": "scene.ballots"},
                "as": "ballot",
                "where": {
                    "all": [
                        {"eq": [{"ref": "ballot.round"}, {"ref": "scene.round"}]},
                        {"eq": [{"ref": "ballot.target"}, {"ref": "candidate.id"}]},
                    ]
                },
            }
        },
    ]
    session = _program(lib=lib).start(_part("assets"))
    for seat, target in (("A", "C"), ("B", "C"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    assert [(item.voter, item.target) for item in _scene(session).ballots] == [
        ("A", "C"),
        ("B", "C"),
        ("C", "B"),
    ]
    assert _scene(session).phase == "night"
    assert _scene(session).winner == "none"
    assert all(item.alive for item in _scene(session).players)


def test_manual_terminal_runs_authored_files_without_a_game_specific_host(
    monkeypatch, capsys
) -> None:
    commands = iter(("3", "seat B", "3", "seat C", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    assert play_main(["three_seat_werewolf_v0"]) == 0
    output = capsys.readouterr().out
    assert "scene.winner: 'town'" in output
    assert "No current offers." in output
    assert "scene.roles" not in output
    assert "scene.ballots" not in output


def test_manual_terminal_accepts_explicit_yaml_author_paths(monkeypatch, capsys) -> None:
    commands = iter(("3", "seat B", "3", "seat C", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    assert (
        play_main(
            [
                "--lib",
                str(STEM.with_suffix(".lib.yaml")),
                "--ports",
                str(STEM.with_suffix(".ports.yaml")),
                "--source",
                str(STEM.with_suffix(".source.yaml")),
                "--assets",
                str(STEM.with_suffix(".assets.yaml")),
            ]
        )
        == 0
    )
    assert "scene.winner: 'town'" in capsys.readouterr().out


def test_yaml_reader_rejects_duplicate_keys_and_tags(tmp_path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema: first\nschema: second\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        read_author_document(duplicate).to_data()

    tagged = tmp_path / "tagged.yaml"
    tagged.write_text("opening: !!python/object/apply:eval ['1 + 1']\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be parsed") as error:
        read_author_document(tagged).to_data()
    assert isinstance(error.value.__cause__, ConstructorError)


def test_author_reader_keeps_json_input_usable() -> None:
    path = ROOT / "parcel_delivery_v0.lib.json"
    document = read_author_document(path)
    assert document.to_data() == json.loads(path.read_text(encoding="utf-8"))
    assert type(document) is type(read_author_document(STEM.with_suffix(".lib.yaml")))


def test_stale_vote_and_wrong_role_are_rejected_without_occurrences() -> None:
    session = _session()
    offer = next(item for item in session.offers("A") if dict(item.payload)["target"] == "C")
    assert isinstance(session.submit("A", offer.entry, dict(offer.payload)), K0Published)
    before = session._runtime.occurrence_history()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("A", offer.entry, dict(offer.payload))
    assert session._runtime.occurrence_history() == before

    _submit(session, "B", "vote_b", "A")
    _submit(session, "C", "vote_c", "B")
    action = dict(session.program.actions)["attack_a"]
    attempted = action.payload_type(actor="A", target="B")
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, attempted)),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before


def test_dead_target_is_not_offered_or_admitted() -> None:
    session = _session()
    for seat, target in (("A", "A"), ("B", "A"), ("C", "B")):
        _submit(session, seat, f"vote_{seat.lower()}", target)
    assert _scene(session).last_death == "A"
    assert session.offers("A") == ()
    assert not any(dict(offer.payload)["target"] == "A" for offer in session.offers("C"))
    action = dict(session.program.actions)["attack_c"]
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="C", target="A"))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before
