"""Source-instantiated six-seat owners share one closed Werewolf Lib and Ports."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0 import actor_binding_v1
from nomos_c0.actor_binding_v1 import expand_actor_bindings
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.compile_budget_v1 import C0CompileLimitError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.direct_actor_event_v1 import C0DirectActorPorts
from nomos_c0.direct_scene_event_v1 import C0DirectScenePorts
from nomos_c0.owner_graph_play_v1 import main as play_main
from nomos_c0.owner_graph_v1 import compile_owner_graph

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
THREE = ROOT / "three_seat_werewolf_v0"
SIX = ROOT / "six_seat_werewolf_v0"
WITCH = ROOT / "six_seat_werewolf_witch_v0"


def _part(stem: Path, name: str) -> dict[str, object]:
    result = read_author_document(stem.with_suffix(f".{name}.yaml")).to_data()
    assert type(result) is dict
    return result


def _program(source: dict[str, object] | None = None, lib: dict[str, object] | None = None):
    source = _part(SIX, "source") if source is None else source
    checked = check_nominal_lib(
        _part(THREE, "lib") if lib is None else lib, source["actor_domains"]
    )
    library = check_graph_ports(_part(THREE, "ports"), checked)
    return compile_owner_graph(library, source)


def _expanded_source(lib=None):
    source = _part(SIX, "source")
    checked = check_nominal_lib(
        _part(THREE, "lib") if lib is None else lib, source["actor_domains"]
    )
    library = check_graph_ports(_part(THREE, "ports"), checked)
    expanded = expand_actor_bindings(
        source,
        {item.symbol: (item.owner.state_type, item.identity_field) for item in library.owners},
        {item.symbol: item.actor for item in library.actions},
        frozenset(item.symbol for item in library.events if type(item.ports) is C0DirectScenePorts),
        actor_event_templates=frozenset(
            item.symbol for item in library.events if type(item.ports) is C0DirectActorPorts
        ),
    )
    expanded["actor_domains"] = source["actor_domains"]
    return library, expanded


def _scene(session):
    owner = next(item.owner for item in session.program.owners if item.symbol == "scene")
    return session._runtime.read_owner(owner.key).view


def _vote(session, seat: str, target: str) -> None:
    offer = next(
        item
        for item in session.offers(seat)
        if item.entry == f"vote_{seat.lower()}" and dict(item.payload)["target"] == target
    )
    assert isinstance(session.submit(seat, offer.entry, dict(offer.payload)), K0Published)


def _sized_opening(members: str, roles: dict[str, str]):
    source = _part(SIX, "source")
    source["actor_domains"][0]["owners"] = list(members.lower())
    assets = _part(SIX, "assets")
    opening = assets["opening"]
    opening["scene"]["players"] = [{"id": seat, "alive": True} for seat in members]
    opening["scene"]["roles"] = [{"id": seat, "role": roles[seat]} for seat in members]
    for owner in list(opening):
        if owner != "scene" and owner not in members.lower():
            del opening[owner]
    for seat in members:
        owner = seat.lower()
        if owner not in opening:
            opening[owner] = deepcopy(opening["b"])
        opening[owner]["name"] = seat
        opening[owner]["own_role"] = roles[seat]
        opening[owner]["healing_available"] = roles[seat] == "witch"
    return source, assets


@pytest.mark.parametrize(
    ("members", "roles"),
    [
        ("ABC", {"A": "seer", "B": "villager", "C": "wolf"}),
        (
            "ABCDEFGH",
            {
                "A": "seer",
                "B": "villager",
                "C": "wolf",
                "D": "wolf",
                "E": "villager",
                "F": "villager",
                "G": "wolf",
                "H": "villager",
            },
        ),
        (
            "ABCDEFGHIJKL",
            {
                **{seat: "villager" for seat in "ABCDEFGHIJKL"},
                "A": "seer",
                "C": "wolf",
                "D": "wolf",
            },
        ),
    ],
)
def test_one_participant_domain_builds_different_sizes_and_real_k0_votes(
    members: str, roles: dict[str, str]
) -> None:
    source, assets = _sized_opening(members, roles)
    program = _program(source)
    assert len(program.owners) == len(members) + 1
    assert {seat.symbol for seat in program.seats} == set(members)
    assert len(program.actions) == len(members) * 5
    session = program.start(assets)
    _vote(session, "A", "B")
    assert _scene(session).ballots[0].voter == "A"
    assert session._runtime.occurrence_history()[0].source == (
        dict(program.actions)["vote_a"].source_key
    )


def test_participant_bounds_and_opening_mismatch_reject_at_the_right_stage(monkeypatch) -> None:
    source, assets = _sized_opening("AB", {"A": "seer", "B": "wolf"})
    with pytest.raises(C0BindingError, match="opening guard"):
        _program(source).start(assets)

    source, assets = _sized_opening("ABC", {"A": "seer", "B": "villager", "C": "wolf"})
    assets["opening"]["c"]["own_role"] = "villager"
    with pytest.raises(C0BindingError, match="opening guard"):
        _program(source).start(assets)

    source = _part(SIX, "source")
    source["actor_domains"][0]["owners"] = list("abcdefghijklm")
    # Exercise the actual budget contract without depending on release defaults.
    with monkeypatch.context() as scoped:
        scoped.setattr(actor_binding_v1, "COMPILE_BUDGET",
                       replace(actor_binding_v1.COMPILE_BUDGET, actions=64))
        with pytest.raises(C0CompileLimitError) as failure:
            _program(source)
        assert failure.value.resource == "actions"
        assert failure.value.actual == 65 and failure.value.limit == 64

    source = _part(SIX, "source")
    source["opening_guard"]["all"][0]["lt"][1]["domain_size"] = "outsiders"
    with pytest.raises(C0LawError, match="opening domain size"):
        _program(source)


def test_source_instantiates_six_distinct_k0_actor_owners_and_capabilities() -> None:
    source = _part(SIX, "source")
    lib = _part(THREE, "lib")
    checked = check_nominal_lib(lib, source["actor_domains"])
    assert checked.owner_templates == (("participant", ("a", "b", "c", "d", "e", "f")),)
    assert {owner.symbol for owner in checked.owners} == {"scene", "a", "b", "c", "d", "e", "f"}
    assert len({owner.owner.key for owner in checked.owners}) == 7
    assert all(
        checked.owner(symbol).owner.key.value == f"c0.werewolf.actor.{symbol}"
        for symbol in "abcdef"
    )
    program = _program(source)
    assert len(program.events) == 37
    assert len(program.profile.causal_laws) == len(program.events)
    assert {name for name, _ in program.actions if name.startswith("witch_intervene_")} == {
        f"witch_intervene_{symbol}" for symbol in "abcdef"
    }
    assert {name for name, _ in program.events if name.startswith("witch_notice_")} == {
        f"witch_notice_select_target_attack_a-{symbol}" for symbol in "abcdef"
    }
    assert {seat.symbol for seat in program.seats} == set("ABCDEF")
    assert {name for name, _ in program.actions if name.startswith("attack_")} == {
        f"attack_{symbol}" for symbol in "abcdef"
    }
    session = program.start(_part(SIX, "assets"))
    for symbol in "ABCDEF":
        own = dict(session.read(symbol).fields)
        assert own[f"{symbol.lower()}.name"] == symbol
        assert "scene.roles" not in own
        assert len(session.offers(symbol)) == 6


def test_preexpanded_shared_event_rejects_incompatible_group_identity() -> None:
    library, expanded = _expanded_source()
    shared = [row for row in expanded["events"] if row.get("shared_result") == "select_target"]
    shared[1]["shared_result"] = "foreign"
    with pytest.raises(C0LawError, match="shared Event result has incompatible"):
        compile_owner_graph(library, expanded)


def test_shared_event_source_rejects_distinct_valid_law_bindings() -> None:
    lib = _part(THREE, "lib")
    original = next(item for item in lib["lawdefs"] if item["name"] == "event.select_unanimous")
    alternate = deepcopy(original)
    alternate["name"] = "event.select_unanimous.alternate"
    alternate["body"]["law"]["guard"] = {"const": True}
    lib["lawdefs"].append(alternate)
    library, expanded = _expanded_source(lib)
    shared = [row for row in expanded["events"] if row.get("shared_result") == "select_target"]
    all_alternate = deepcopy(expanded)
    for row in all_alternate["events"]:
        if row.get("shared_result") == "select_target":
            row["law"] = {"ref": alternate["name"], "args": {}}
    compile_owner_graph(library, all_alternate)
    shared[1]["law"] = {"ref": alternate["name"], "args": {}}
    with pytest.raises(C0LawError, match="shared Event result has incompatible source or Law"):
        compile_owner_graph(library, expanded)


def test_shared_event_aliases_cannot_double_write_one_owner() -> None:
    library, expanded = _expanded_source()
    night = next(row for row in expanded["events"] if row["name"].startswith("resolve_night_"))
    duplicate = deepcopy(night)
    duplicate.update(
        name="duplicate_night",
        trigger_event="select_target_attack_b",
        source_key="c0.six-seat.duplicate-night",
        event_type="c0.six-seat.duplicate-night.event",
        causal_key="c0.six-seat.duplicate-night.causes",
    )
    expanded["events"].append(duplicate)
    with pytest.raises(C0LawError, match="same-trigger owner fanout"):
        compile_owner_graph(library, expanded)


def test_shared_event_aliases_cannot_form_a_source_cycle() -> None:
    library, expanded = _expanded_source()
    selected = next(row for row in expanded["events"] if row["name"] == "select_target_attack_a")
    night = next(row for row in expanded["events"] if row["name"].startswith("resolve_night_"))
    back_edge = deepcopy(selected)
    back_edge.pop("trigger_action")
    back_edge.update(
        name="select_target_back_edge",
        trigger_event=night["name"],
        causal_key="c0.six-seat.select-target-back-edge.causes",
    )
    expanded["events"].append(back_edge)
    with pytest.raises(C0LawError, match="causal source cycle"):
        compile_owner_graph(library, expanded)


def test_six_votes_need_strict_majority_and_keep_action_provenance() -> None:
    session = _program().start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    scene = _scene(session)
    assert (scene.phase, scene.winner, scene.last_death) == ("night", "none", None)
    assert len({ballot.action for ballot in scene.ballots}) == 6
    assert len(session._runtime.occurrence_history()) == 7

    session = _program().start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCCAA", strict=True):
        _vote(session, seat, target)
    scene = _scene(session)
    assert (scene.phase, scene.winner, scene.last_death) == ("night", "none", "C")
    assert len(session._runtime.occurrence_history()) == 7
    assert session.offers("C") == ()
    assert {offer.label for offer in session.offers("D") if offer.entry == "attack_d"} == {
        "Attack A",
        "Attack B",
        "Attack E",
        "Attack F",
    }
    attack = next(offer for offer in session.offers("D") if offer.label == "Attack B")
    assert isinstance(session.submit("D", attack.entry, dict(attack.payload)), K0Published)
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    assert (_scene(session).phase, _scene(session).round) == ("day", 2)
    for seat in "ADEF":
        _vote(session, seat, "D")
    scene = _scene(session)
    assert len(scene.ballots) == 10
    assert [ballot.round for ballot in scene.ballots] == [1] * 6 + [2] * 4
    assert (scene.phase, scene.winner) == ("finished", "town")


def test_edit_only_lib_pure_count_changes_real_k0_outcome_with_same_source_assets():
    source, assets = _sized_opening("ABC", {"A": "seer", "B": "villager", "C": "wolf"})
    original = _part(THREE, "lib")
    changed = deepcopy(original)
    computation = changed["pure_definitions"][0]
    computation["body"] = {"add": [computation["body"], {"const": 1}]}
    sessions = []
    for lib in (original, changed):
        session = _program(source, lib).start(assets)
        _vote(session, "A", "C")
        _vote(session, "B", "C")
        _vote(session, "C", "A")
        sessions.append(session)
    assert (_scene(sessions[0]).phase, _scene(sessions[0]).winner) == ("finished", "town")
    assert (_scene(sessions[1]).phase, _scene(sessions[1]).winner) == ("night", "none")
    assert tuple((player.id, player.alive) for player in _scene(sessions[0]).players) == tuple(
        (player.id, player.alive) for player in _scene(sessions[1]).players
    )
    traces = [
        tuple(
            (row.occurrence, row.source, row.classification, row.formation_basis)
            for row in session._runtime.occurrence_history()
        )
        for session in sessions
    ]
    assert traces[0] == traces[1]
    assert tuple(owner.owner.owner_version for owner in sessions[0].program.owners) == tuple(
        owner.owner.owner_version for owner in sessions[1].program.owners
    )


def test_both_wolves_and_seer_close_the_night_through_k0_actions() -> None:
    session = _program().start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    assert {offer.label for offer in session.offers("C")} == {
        "Attack A",
        "Attack B",
        "Attack D",
        "Attack E",
        "Attack F",
    }
    assert {offer.label for offer in session.offers("A")} == {
        "Inspect B",
        "Inspect C",
        "Inspect D",
        "Inspect E",
        "Inspect F",
        "Skip inspection",
    }
    attack = next(offer for offer in session.offers("C") if offer.label == "Attack B")
    assert isinstance(session.submit("C", attack.entry, dict(attack.payload)), K0Published)
    assert _scene(session).phase == "night"
    assert _scene(session).selection_done is False
    choice = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", choice.entry, dict(choice.payload)), K0Published)
    assert _scene(session).phase == "night"
    attack = next(offer for offer in session.offers("D") if offer.label == "Attack B")
    published = session.submit("D", attack.entry, dict(attack.payload))
    assert isinstance(published, K0Published)
    assert len(published.occurrences) == 3
    scene = _scene(session)
    assert (scene.phase, scene.round, scene.last_death) == ("day", 2, "B")
    assert {ballot.voter for ballot in scene.wolf_ballots} == {"C", "D"}
    assert next(player for player in scene.players if player.id == "B").alive is False
    assert session.offers("B") == ()
    assert "scene.roles" not in dict(session.read("D").fields)


def test_shared_result_keeps_actual_trigger_for_two_action_families() -> None:
    result_sources = []
    trigger_sources = []
    for order in ("ACD", "CDA"):
        session = _program().start(_part(SIX, "assets"))
        for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
            _vote(session, seat, target)
        final = None
        for seat in order:
            label = "Skip inspection" if seat == "A" else "Attack B"
            offer = next(item for item in session.offers(seat) if item.label == label)
            final = session.submit(seat, offer.entry, dict(offer.payload))
            assert isinstance(final, K0Published)
        assert final is not None and len(final.occurrences) == 3
        action, selected = final.occurrences[:2]
        assert selected.semantic_envelope.trigger == action.occurrence
        result_sources.append(selected.source)
        trigger_sources.append(action.source)
        assert _scene(session).last_death == "B"
    assert result_sources[0] == result_sources[1]
    assert trigger_sources[0] != trigger_sources[1]


def test_split_wolf_ballots_select_no_victim_and_partner_target_is_legal() -> None:
    session = _program().start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    first = next(offer for offer in session.offers("C") if offer.label == "Attack D")
    assert isinstance(session.submit("C", first.entry, dict(first.payload)), K0Published)
    assert _scene(session).phase == "night"
    assert all(offer.entry != "attack_c" for offer in session.offers("C"))
    before = session._runtime.occurrence_history()
    action = dict(session.program.actions)["attack_c"]
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="C", target="B"))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before
    second = next(offer for offer in session.offers("D") if offer.label == "Attack B")
    assert isinstance(session.submit("D", second.entry, dict(second.payload)), K0Published)
    assert _scene(session).phase == "night"
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    result = session.submit("A", seer.entry, dict(seer.payload))
    assert isinstance(result, K0Published)
    assert len(result.occurrences) == 3
    scene = _scene(session)
    assert (scene.phase, scene.round, scene.last_death, scene.winner) == ("day", 2, None, "none")
    assert all(player.alive for player in scene.players)
    assert "scene.pending_attack" not in dict(session.read("B").fields)
    assert "scene.wolf_ballots" not in dict(session.read("B").fields)


def test_source_selects_unanimity_or_majority_without_changing_the_opening() -> None:
    source = _part(SIX, "source")
    assets = _part(SIX, "assets")
    assets["opening"]["scene"]["roles"][-1]["role"] = "wolf"
    assets["opening"]["f"]["own_role"] = "wolf"

    def run(selected: dict[str, object]):
        session = _program(selected).start(assets)
        for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
            _vote(session, seat, target)
        seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
        assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
        for seat, target in (("C", "F"), ("D", "F"), ("F", "E")):
            attack = next(
                offer for offer in session.offers(seat) if offer.label == f"Attack {target}"
            )
            assert isinstance(session.submit(seat, attack.entry, dict(attack.payload)), K0Published)
        return _scene(session), session

    unanimous, first = run(source)
    majority_source = deepcopy(source)
    majority_source["events"][1]["law"]["ref"] = "event.select_majority"
    majority, second = run(majority_source)
    assert (
        [ballot.target for ballot in unanimous.wolf_ballots]
        == [ballot.target for ballot in majority.wolf_ballots]
        == ["F", "F", "E"]
    )
    assert unanimous.last_death is None
    assert majority.last_death == "F"
    assert majority.winner == "none"
    assert unanimous.phase == majority.phase == "day"
    assert len(first._runtime.occurrence_history()) == len(second._runtime.occurrence_history())


def test_selected_victim_is_a_real_private_state_before_optional_dawn_law() -> None:
    source = _part(SIX, "source")
    source["events"] = [row for row in source["events"] if row.get("family") != "resolve_night"]
    session = _program(source).start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    for seat in "CD":
        attack = next(offer for offer in session.offers(seat) if offer.label == "Attack B")
        receipt = session.submit(seat, attack.entry, dict(attack.payload))
        assert isinstance(receipt, K0Published)
    assert len(receipt.occurrences) == 2
    scene = _scene(session)
    assert (scene.phase, scene.selection_done, scene.pending_attack) == ("night", True, "B")
    assert next(player for player in scene.players if player.id == "B").alive is True
    assert "scene.pending_attack" not in dict(session.read("B").fields)
    assert session.offers("C") == session.offers("D") == ()


def _witch_night(session) -> None:
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    for seat in "CD":
        attack = next(offer for offer in session.offers(seat) if offer.label == "Attack B")
        assert isinstance(session.submit(seat, attack.entry, dict(attack.payload)), K0Published)


def _moved_witch_assets():
    assets = _part(WITCH, "assets")
    assets["opening"]["scene"]["roles"][1]["role"] = "witch"
    assets["opening"]["scene"]["roles"][4]["role"] = "villager"
    assets["opening"]["b"]["own_role"] = "witch"
    assets["opening"]["b"]["healing_available"] = True
    assets["opening"]["e"]["own_role"] = "villager"
    assets["opening"]["e"]["healing_available"] = False
    return assets


def test_witch_receives_selected_victim_then_save_prevents_dawn_death() -> None:
    session = _program().start(_part(WITCH, "assets"))
    _witch_night(session)
    scene = _scene(session)
    assert (scene.phase, scene.pending_attack, scene.selection_done) == ("night", "B", True)
    assert next(player for player in scene.players if player.id == "B").alive
    own = dict(session.read("E").fields)
    assert own["e.witch_notice"].target == "B"
    assert own["e.witch_notice"].selection != own["e.witch_notice"].notice
    history = {item.occurrence: item for item in session._runtime.occurrence_history()}
    assert history[own["e.witch_notice"].notice].semantic_envelope.trigger == (
        own["e.witch_notice"].selection
    )
    assert "e.witch_notice" not in dict(session.read("B").fields)
    assert "scene.pending_attack" not in dict(session.read("B").fields)
    assert {offer.label for offer in session.offers("E")} == {"Save victim", "Do not heal"}
    save = next(offer for offer in session.offers("E") if offer.label == "Save victim")
    result = session.submit("E", save.entry, dict(save.payload))
    assert isinstance(result, K0Published)
    assert len(result.occurrences) == 2
    assert (_scene(session).phase, _scene(session).last_death) == ("day", None)
    choice = dict(session.read("E").fields)["e.witch_choices"][0]
    assert choice.saved is True and choice.target == "B"
    assert choice.action == result.occurrences[0].occurrence
    assert dict(session.read("E").fields)["e.healing_available"] is False
    assert all(offer.entry != "witch_intervene_e" for offer in session.offers("E"))


def test_witch_role_moves_with_private_notice_and_k0_capability() -> None:
    session = _program().start(_moved_witch_assets())
    _witch_night(session)
    assert dict(session.read("B").fields)["b.witch_notice"].target == "B"
    assert "e.witch_notice" not in dict(session.read("E").fields)
    assert {offer.label for offer in session.offers("B")} == {"Save victim", "Do not heal"}
    assert session.offers("E") == ()
    foreign = dict(session.program.actions)["witch_intervene_e"]
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(foreign.source_key, foreign.payload_type(actor="E", save=True))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before
    save = next(offer for offer in session.offers("B") if offer.label == "Save victim")
    result = session.submit("B", save.entry, dict(save.payload))
    assert isinstance(result, K0Published)
    assert _scene(session).last_death is None
    assert dict(session.read("B").fields)["b.witch_choices"][0].action == (
        result.occurrences[0].occurrence
    )


def test_one_lib_law_edit_changes_k0_self_heal_admission_with_same_opening() -> None:
    lib = _part(THREE, "lib")
    restricted = deepcopy(lib)
    law = next(row for row in restricted["lawdefs"] if row["name"] == "action.witch_intervene")
    choice = law["body"]["value"]["guard"]["require"][-1]["save_choice"]
    save_branch = choice["if"]["then"]["require"]
    save_branch.append({"no_self_heal": "actor.name != scene.pending_attack"})
    assets = _moved_witch_assets()
    permitted = _program(lib=lib).start(deepcopy(assets))
    prohibited = _program(lib=restricted).start(deepcopy(assets))
    for session in (permitted, prohibited):
        _witch_night(session)
        assert dict(session.read("B").fields)["b.witch_notice"].target == "B"
        assert _scene(session).pending_attack == "B"
    allowed = next(offer for offer in permitted.offers("B") if offer.label == "Save victim")
    rejected = next(offer for offer in prohibited.offers("B") if offer.label == "Save victim")
    permitted_action = dict(permitted.program.actions)[allowed.entry]
    assert (
        permitted_action.value.false_guard_clauses(
            permitted_action._roots(
                permitted._runtime.read_owner(permitted_action.scene_owner.key).view,
                permitted._runtime.read_owner(permitted_action.actor_owner.key).view,
                permitted_action.payload_type(actor="B", save=True),
            )
        )
        == ()
    )
    assert isinstance(permitted.submit("B", allowed.entry, dict(allowed.payload)), K0Published)
    before = prohibited._runtime.occurrence_history()
    assert isinstance(prohibited.submit("B", rejected.entry, dict(rejected.payload)), K0NotAdmitted)
    assert prohibited._runtime.occurrence_history() == before
    action = dict(prohibited.program.actions)[rejected.entry]
    actor = prohibited._runtime.read_owner(action.actor_owner.key).view
    scene = prohibited._runtime.read_owner(action.scene_owner.key).view
    payload = action.payload_type(actor="B", save=True)
    failures = action.value.false_guard_clauses(action._roots(scene, actor, payload))
    assert any(
        failure.names == ("save_choice", "no_self_heal")
        and failure.path == "guard.require.save_choice.if.then.require.no_self_heal"
        and '"ref":"scene.pending_attack"' in failure.expression
        for failure in failures
    )
    assert _scene(permitted).last_death is None
    assert (_scene(prohibited).phase, _scene(prohibited).pending_attack) == ("night", "B")


def test_witch_notice_recipient_domain_must_be_declared() -> None:
    source = _part(SIX, "source")
    notice = next(item for item in source["events"] if item.get("family") == "witch_notice")
    notice["actor_domain"] = "outsiders"
    with pytest.raises(C0LawError, match="Actor domain is foreign"):
        _program(source)


def test_chained_actor_recipient_fanout_stops_before_building_unbounded_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _part(SIX, "source")
    template = next(item for item in source["events"] if item.get("family") == "witch_notice")
    predecessor = "witch_notice"
    for index in range(3):
        successor = deepcopy(template)
        successor["family"] = f"fanout_{index}"
        successor["for_event_family"] = predecessor
        successor["source_prefix"] = f"c0.fanout-{index}"
        source["events"].append(successor)
        predecessor = successor["family"]
    copies = 0
    original_copy = actor_binding_v1.deepcopy

    def counted_copy(value: object) -> object:
        nonlocal copies
        copies += 1
        assert copies < 1300
        return original_copy(value)

    monkeypatch.setattr(actor_binding_v1, "deepcopy", counted_copy)
    monkeypatch.setattr(actor_binding_v1, "COMPILE_BUDGET",
                       replace(actor_binding_v1.COMPILE_BUDGET, causal_edges=128))
    with pytest.raises(C0CompileLimitError) as failure:
        _program(source)
    assert failure.value.resource == "causal_edges"
    assert failure.value.actual == 129 and failure.value.limit == 128


def test_witch_abstains_then_selected_victim_dies_at_dawn() -> None:
    session = _program().start(_part(WITCH, "assets"))
    _witch_night(session)
    leave = next(offer for offer in session.offers("E") if offer.label == "Do not heal")
    result = session.submit("E", leave.entry, dict(leave.payload))
    assert isinstance(result, K0Published)
    assert (_scene(session).phase, _scene(session).last_death) == ("day", "B")
    assert dict(session.read("E").fields)["e.healing_available"] is True


def test_witch_cannot_act_before_notice_or_repeat_a_choice() -> None:
    session = _program().start(_part(WITCH, "assets"))
    action = dict(session.program.actions)["witch_intervene_e"]
    attempt = _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="E", save=True))
    before = session._runtime.occurrence_history()
    assert isinstance(session._runtime.settle(attempt), K0NotAdmitted)
    assert session._runtime.occurrence_history() == before
    _witch_night(session)
    save = next(offer for offer in session.offers("E") if offer.label == "Save victim")
    assert isinstance(session.submit("E", save.entry, dict(save.payload)), K0Published)
    before = session._runtime.occurrence_history()
    assert isinstance(session._runtime.settle(attempt), K0NotAdmitted)
    assert session._runtime.occurrence_history() == before


def test_split_wolf_vote_gives_witch_a_no_victim_notice_without_a_save_offer() -> None:
    session = _program().start(_part(WITCH, "assets"))
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    for seat, target in (("C", "B"), ("D", "F")):
        attack = next(offer for offer in session.offers(seat) if offer.label == f"Attack {target}")
        assert isinstance(session.submit(seat, attack.entry, dict(attack.payload)), K0Published)
    assert _scene(session).pending_attack is None
    assert dict(session.read("E").fields)["e.witch_notice"].target is None
    assert {offer.label for offer in session.offers("E")} == {"Do not heal"}
    action = dict(session.program.actions)["witch_intervene_e"]
    history = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="E", save=True))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == history
    leave = session.offers("E")[0]
    assert isinstance(session.submit("E", leave.entry, dict(leave.payload)), K0Published)
    assert (_scene(session).phase, _scene(session).last_death) == ("day", None)


def test_witch_capability_rejects_wrong_actor_and_unassigned_role() -> None:
    session = _program().start(_part(WITCH, "assets"))
    _witch_night(session)
    action = dict(session.program.actions)["witch_intervene_e"]
    history = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="F", save=True))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == history
    assets = _part(SIX, "assets")
    session = _program().start(assets)
    assert "e.witch_notice" not in dict(session.read("E").fields)
    assert all(offer.entry != "witch_intervene_e" for offer in session.offers("E"))


def test_witch_has_only_one_healing_potion_across_nights() -> None:
    session = _program().start(_part(WITCH, "assets"))
    _witch_night(session)
    save = next(offer for offer in session.offers("E") if offer.label == "Save victim")
    assert isinstance(session.submit("E", save.entry, dict(save.payload)), K0Published)
    for seat, target in zip("ABCDEF", "CCCAAA", strict=True):
        _vote(session, seat, target)
    _witch_night_after_day(session)
    assert {offer.label for offer in session.offers("E")} == {"Do not heal"}
    action = dict(session.program.actions)["witch_intervene_e"]
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(action.source_key, action.payload_type(actor="E", save=True))
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before
    abstain = next(offer for offer in session.offers("E") if offer.label == "Do not heal")
    assert isinstance(session.submit("E", abstain.entry, dict(abstain.payload)), K0Published)
    assert _scene(session).last_death == "B"
    assert dict(session.read("E").fields)["e.healing_available"] is False


def _witch_night_after_day(session) -> None:
    seer = next(offer for offer in session.offers("A") if offer.label == "Skip inspection")
    assert isinstance(session.submit("A", seer.entry, dict(seer.payload)), K0Published)
    for seat in "CD":
        attack = next(offer for offer in session.offers(seat) if offer.label == "Attack B")
        assert isinstance(session.submit(seat, attack.entry, dict(attack.payload)), K0Published)


def test_witch_opening_rejects_unearned_notice_and_wrong_role_binding() -> None:
    assets = _part(WITCH, "assets")
    assets["opening"]["e"]["witch_notice"] = {
        "round": 1,
        "target": "B",
        "selection": 1,
        "notice": 2,
    }
    with pytest.raises(
        C0BindingError, match="opening occurrence or instance identity cannot be authored"
    ):
        _program().start(assets)
    assets = _part(WITCH, "assets")
    assets["opening"]["scene"]["roles"][4]["role"] = "villager"
    assets["opening"]["e"]["own_role"] = "villager"
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)
    assets = _part(WITCH, "assets")
    assets["opening"]["scene"]["roles"].append({"id": "F", "role": "witch"})
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)
    assets = _part(WITCH, "assets")
    assets["opening"]["scene"]["players"].append({"id": "extra", "alive": False})
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)


def test_template_binding_and_opening_cannot_invent_or_duplicate_actors() -> None:
    lib = _part(THREE, "lib")
    with pytest.raises(C0LawError, match="template"):
        check_nominal_lib(lib)

    source = _part(SIX, "source")
    source["actor_domains"][0]["owners"][-1] = "a"
    with pytest.raises(C0LawError, match="distinct"):
        _program(source)

    source = _part(SIX, "source")
    source["owners"][1]["domain"] = "outsiders"
    with pytest.raises(C0LawError, match="owner domain reference is foreign"):
        _program(source)

    assets = _part(SIX, "assets")
    del assets["opening"]["f"]
    with pytest.raises(C0BindingError, match="exact owner set"):
        _program().start(assets)

    assets = _part(SIX, "assets")
    assets["opening"]["f"]["name"] = "E"
    with pytest.raises(C0BindingError, match="identities alias"):
        _program().start(assets)


def test_same_shaped_foreign_template_cannot_borrow_participant_vote_port() -> None:
    lib = _part(THREE, "lib")
    spectator = deepcopy(lib["owners"][-1])
    spectator["template"] = "spectator"
    spectator["key_prefix"] = "c0.werewolf.spectator."
    lib["owners"].append(spectator)

    source = _part(SIX, "source")
    source["owners"].append("g")
    source["actor_domains"].append(
        {
            "name": "spectators",
            "owner_template": "spectator",
            "actor_state": "Actor",
            "owners": ["g"],
        }
    )
    source["actions"].append(
        {
            "family": "probe",
            "template": "vote",
            "domain": "spectators",
            "source_prefix": "c0.werewolf.spectator-vote",
            "law": {"ref": "action.vote", "args": {}},
        }
    )
    checked = check_nominal_lib(lib, source["actor_domains"])
    library = check_graph_ports(_part(THREE, "ports"), checked)
    with pytest.raises(C0LawError, match="template"):
        compile_owner_graph(library, source)


def test_json_source_uses_the_same_template_binding_path(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "six.source.json"
    source.write_text(json.dumps(_part(SIX, "source")), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "quit")
    assert (
        play_main(
            [
                "--lib",
                str(THREE.with_suffix(".lib.yaml")),
                "--ports",
                str(THREE.with_suffix(".ports.yaml")),
                "--source",
                str(source),
                "--assets",
                str(SIX.with_suffix(".assets.yaml")),
            ]
        )
        == 0
    )
    assert "Seats: A, B, C, D, E, F" in capsys.readouterr().out


def test_source_local_law_can_be_selected_without_shadowing_lib() -> None:
    lib = _part(THREE, "lib")
    source = _part(SIX, "source")
    local = deepcopy(next(row for row in lib["lawdefs"] if row["name"] == "event.resolve_day"))
    local["name"] = "event.resolve_day.local"
    leader = local["body"]["law"]["bindings"][0]["where"]["all"][1]
    votes_for_candidate = deepcopy(leader["let"]["value"])
    leader.clear()
    leader["le"] = [{"const": 5}, votes_for_candidate]
    source["lawdefs"].append(local)
    source["events"][0]["law"]["ref"] = local["name"]

    session = _program(source, lib).start(_part(SIX, "assets"))
    for seat, target in zip("ABCDEF", "CCCCAA", strict=True):
        _vote(session, seat, target)
    assert (_scene(session).phase, _scene(session).winner) == ("night", "none")


def test_duplicate_or_unauthorized_local_law_rejects_before_session() -> None:
    lib = _part(THREE, "lib")
    source = _part(SIX, "source")
    source["lawdefs"].append(deepcopy(lib["lawdefs"][0]))
    with pytest.raises(C0LawError, match="repeated"):
        _program(source, lib)

    source = _part(SIX, "source")
    local = deepcopy(next(row for row in lib["lawdefs"] if row["name"] == "action.vote"))
    local["name"] = "action.vote.local"
    local["body"]["value"]["outputs"]["roles"] = {"ref": "scene.roles"}
    source["lawdefs"].append(local)
    source["actions"][0]["law"]["ref"] = local["name"]
    with pytest.raises(C0LawError):
        _program(source, lib)


def test_lib_law_edit_does_not_change_nominal_owner_wire_version() -> None:
    original = _part(THREE, "lib")
    revised = deepcopy(original)
    law = next(row for row in revised["lawdefs"] if row["name"] == "event.resolve_day")
    law["body"]["law"]["bindings"][0]["where"]["all"][1] = {"const": True}
    domains = _part(SIX, "source")["actor_domains"]
    first = check_nominal_lib(original, domains)
    second = check_nominal_lib(revised, domains)
    assert first.owner("a").owner.owner_version == second.owner("a").owner.owner_version


def test_checked_lib_laws_are_immutable_and_malformed_declarations_reject() -> None:
    lib = _part(THREE, "lib")
    domains = _part(SIX, "source")["actor_domains"]
    checked = check_nominal_lib(lib, domains)
    frozen = checked.lawdefs
    lib["lawdefs"][0]["name"] = "changed.after.check"
    assert checked.lawdefs == frozen
    assert all(type(item) is str for item in frozen)

    bad = _part(THREE, "lib")
    bad["lawdefs"][0]["formals"] = {"unused": "str"}
    with pytest.raises(C0LawError, match="formal use"):
        check_nominal_lib(bad, domains)
