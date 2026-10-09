"""T0 checks local-choice witnesses against real compiled C0 sessions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.examples.parcel_delivery_v0 import ROOT as PARCEL_ROOT
from nomos_c0.examples.parcel_delivery_v0 import library as parcel_library
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_runtime_v1 import C0OfferFault, C0OwnerGraphSession
from nomos_t0.author_check_v0 import main as author_main
from nomos_t0.witness_v0 import (
    T0Defer,
    T0Goal,
    T0LocalEquals,
    T0OfferExists,
    T0OfferSelector,
    T0OwnerFieldEquals,
    T0Rule,
    T0ScheduledTurn,
    T0SeatPolicy,
    T0SelectOffer,
    T0SourcePublished,
    T0Witness,
    check_witness,
)

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _document(name: str) -> dict[str, object]:
    result = read_author_document(ROOT / name).to_data()
    assert type(result) is dict
    return result


def _werewolf_program(lib: dict[str, object] | None = None):
    source = _document("six_seat_werewolf_v0.source.yaml")
    checked = check_nominal_lib(
        _document("three_seat_werewolf_v0.lib.yaml") if lib is None else lib,
        source["actor_domains"],
    )
    ports = check_graph_ports(_document("three_seat_werewolf_v0.ports.yaml"), checked)
    return compile_owner_graph(ports, source)


def _witch_b_assets() -> dict[str, object]:
    assets = _document("six_seat_werewolf_witch_v0.assets.yaml")
    assets["opening"]["scene"]["roles"][1]["role"] = "witch"
    assets["opening"]["scene"]["roles"][4]["role"] = "villager"
    assets["opening"]["b"]["own_role"] = "witch"
    assets["opening"]["b"]["healing_available"] = True
    assets["opening"]["e"]["own_role"] = "villager"
    assets["opening"]["e"]["healing_available"] = False
    return assets


def _offer(label: str) -> T0Rule:
    selector = T0OfferSelector(label=label)
    return T0Rule((T0OfferExists(selector),), T0SelectOffer(selector))


def _witch_witness() -> T0Witness:
    choices = {
        "A": ("Vote for C", "Skip inspection"),
        "B": ("Vote for C", "Save victim"),
        "C": ("Vote for C", "Attack B"),
        "D": ("Vote for A", "Attack B"),
        "E": ("Vote for A",),
        "F": ("Vote for A",),
    }
    return T0Witness(
        tuple(T0ScheduledTurn("decide", seat) for seat in "ABCDEFACDB"),
        tuple(
            T0SeatPolicy(seat, tuple(_offer(label) for label in labels))
            for seat, labels in choices.items()
        ),
        max_steps=10,
    )


def test_werewolf_one_local_witness_observes_k0_law_edit_without_forcing_outcome() -> None:
    lib = _document("three_seat_werewolf_v0.lib.yaml")
    restricted = deepcopy(lib)
    law = next(row for row in restricted["lawdefs"] if row["name"] == "action.witch_intervene")
    choice = next(
        item["save_choice"]
        for item in law["body"]["value"]["guard"]["require"]
        if "save_choice" in item
    )
    choice["if"]["then"]["require"].append({"no_self_heal": "actor.name != scene.pending_attack"})

    witness = _witch_witness()
    goal = T0Goal((T0OwnerFieldEquals("b", ("healing_available",), False),))
    assets = _witch_b_assets()
    allowed = check_witness(_werewolf_program(lib), deepcopy(assets), witness, goal)
    rejected = check_witness(_werewolf_program(restricted), deepcopy(assets), witness, goal)

    assert (allowed.stop_reason, allowed.goal_status, allowed.steps_completed) == (
        "scheduled_end",
        "met",
        10,
    )
    assert (rejected.stop_reason, rejected.goal_status, rejected.steps_completed) == (
        "k0_not_admitted",
        "not_met_within_bound",
        9,
    )
    assert rejected.published == allowed.published[: len(rejected.published)]
    assert len(allowed.published) > len(rejected.published)


def test_same_local_frame_hidden_role_change_does_not_change_controller_choice() -> None:
    program = _werewolf_program()
    first = _witch_b_assets()
    second = deepcopy(first)
    roles = second["opening"]["scene"]["roles"]
    roles[0]["role"], roles[4]["role"] = "villager", "seer"
    second["opening"]["a"]["own_role"] = "villager"
    second["opening"]["e"]["own_role"] = "seer"
    assert program.start(deepcopy(first)).read("B") == program.start(deepcopy(second)).read("B")

    rule = T0Rule(
        (T0LocalEquals("b.own_role", "witch"), T0OfferExists(T0OfferSelector(label="Vote for C"))),
        T0SelectOffer(T0OfferSelector(label="Vote for C")),
    )
    witness = T0Witness((T0ScheduledTurn("decide", "B"),), (T0SeatPolicy("B", (rule,)),), 1)
    goal = T0Goal((T0SourcePublished(dict(program.actions)["vote_b"].source_key.value),))
    reports = [check_witness(program, assets, witness, goal) for assets in (first, second)]
    assert [item.stop_reason for item in reports] == ["scheduled_end", "scheduled_end"]
    assert [item.goal_status for item in reports] == ["met", "met"]
    assert reports[0].published[0].semantic_envelope == reports[1].published[0].semantic_envelope


def test_parcel_witness_preserves_defer_and_due_as_different_kinds_of_history() -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    assets = json.loads((PARCEL_ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    program = compile_owner_graph(parcel_library(), source)
    witness = T0Witness(
        (
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "receiver"),
            T0ScheduledTurn("continue", "receiver"),
            T0ScheduledTurn("decide", "receiver"),
        ),
        (
            T0SeatPolicy("sender", (_offer("Dispatch parcel"), T0Rule((), T0Defer()))),
            T0SeatPolicy("receiver", (_offer("Acknowledge delivery"), T0Rule((), T0Defer()))),
        ),
        5,
    )
    goal = T0Goal(
        (
            T0SourcePublished("c0.parcel.arrive.due"),
            T0SourcePublished("c0.parcel.confirm"),
            T0OwnerFieldEquals("scene", ("parcel", "status"), "arrived"),
        )
    )
    report = check_witness(program, assets, witness, goal)
    assert (report.stop_reason, report.goal_status, report.steps_completed) == (
        "witness_stopped",
        "met",
        5,
    )
    assert [item.source for item in report.published].count("c0.parcel.arrive.due") == 1
    assert [item.choice for item in report.form_choices] == ["defer", "defer"]


def test_witness_reports_choice_and_bound_failures_separately_from_goal() -> None:
    program = _werewolf_program()
    assets = _witch_b_assets()
    goal = T0Goal((T0SourcePublished("c0.six-seat.vote-b"),))
    missing = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (T0SeatPolicy("B", (T0Rule((), T0SelectOffer(T0OfferSelector(label="No such vote"))),)),),
        1,
    )
    ambiguous = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (T0SeatPolicy("B", (T0Rule((), T0SelectOffer(T0OfferSelector(entry="vote_b"))),)),),
        1,
    )
    bounded = T0Witness(
        (T0ScheduledTurn("decide", "B"), T0ScheduledTurn("decide", "B")),
        (T0SeatPolicy("B", (_offer("Vote for C"),)),),
        1,
    )
    assert check_witness(program, assets, missing, goal).stop_reason == "choice_not_available"
    assert check_witness(program, assets, ambiguous, goal).stop_reason == "ambiguous_choice"
    report = check_witness(program, assets, bounded, goal)
    assert (report.stop_reason, report.goal_status, report.steps_completed) == (
        "bound_exhausted",
        "met",
        1,
    )
    indexed = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (
            T0SeatPolicy(
                "B", (T0Rule((), T0SelectOffer(T0OfferSelector(entry="vote_b", ordinal=3))),)
            ),
        ),
        1,
    )
    selected = check_witness(program, assets, indexed, goal)
    assert (selected.stop_reason, selected.goal_status) == ("scheduled_end", "met")
    assert selected.published[0].semantic_envelope[-1][-1] == ("target", "C")


def test_witness_reports_no_offer_stall_and_start_rejection() -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    assets = json.loads((PARCEL_ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    program = compile_owner_graph(parcel_library(), source)
    goal = T0Goal((T0SourcePublished("c0.parcel.arrive.due"),))
    no_offer = T0Witness(
        (T0ScheduledTurn("decide", "receiver"),),
        (T0SeatPolicy("receiver", (_offer("Acknowledge delivery"),)),),
        1,
    )
    stalled = T0Witness((T0ScheduledTurn("continue", "receiver"),), (), 1)
    assert check_witness(program, assets, no_offer, goal).stop_reason == "no_local_offer"
    assert check_witness(program, assets, stalled, goal).stop_reason == "control_stalled"
    bad_assets = deepcopy(assets)
    del bad_assets["opening"]["sender"]
    report = check_witness(program, bad_assets, stalled, goal)
    assert (report.stage, report.stop_reason, report.goal_status) == (
        "start",
        "start_rejected",
        "unknown",
    )


def test_bad_local_condition_and_unsupported_goal_are_finite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = _werewolf_program()
    assets = _witch_b_assets()
    goal = T0Goal((T0SourcePublished("c0.six-seat.vote-b"),))
    bad_condition = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (
            T0SeatPolicy(
                "B",
                (
                    T0Rule(
                        (T0LocalEquals(["scene", "roles"], "secret"),),
                        T0SelectOffer(T0OfferSelector(label="Vote for C")),
                    ),
                ),
            ),
        ),
        1,
    )
    assert check_witness(program, assets, bad_condition, goal).stop_reason == "witness_invalid"
    unsupported = check_witness(
        program,
        assets,
        T0Witness((), (), 1),
        T0Goal((T0OwnerFieldEquals("scene", ("missing",), True),)),
    )
    assert (unsupported.stop_reason, unsupported.goal_status) == ("unsupported_goal", "unknown")

    monkeypatch.setattr(
        C0OwnerGraphSession,
        "offer_faults",
        lambda self, seat: (C0OfferFault("vote_b", "Vote for C", "value_state"),),
    )
    witness = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (T0SeatPolicy("B", (_offer("Vote for C"),)),),
        1,
    )
    assert check_witness(program, assets, witness, goal).stop_reason == "offer_fault"


def test_scalar_comparison_does_not_equate_boolean_with_integer() -> None:
    program = _werewolf_program()
    assets = _witch_b_assets()
    witness = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (
            T0SeatPolicy(
                "B",
                (
                    T0Rule(
                        (T0LocalEquals("b.healing_available", 1),),
                        T0SelectOffer(T0OfferSelector(label="Vote for C")),
                    ),
                ),
            ),
        ),
        1,
    )
    goal = T0Goal((T0OwnerFieldEquals("b", ("healing_available",), 1),))
    report = check_witness(program, assets, witness, goal)
    assert (report.stop_reason, report.goal_status, report.published) == (
        "witness_stopped",
        "not_met_within_bound",
        (),
    )


def test_parcel_law_edit_changes_same_witness_actual_goal() -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    edited = deepcopy(source)
    edited["lawdefs"][5]["body"]["law"]["outputs"]["parcel"]["copy"]["changes"]["status"] = {
        "const": "held"
    }
    assets = json.loads((PARCEL_ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    witness = T0Witness(
        (
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "receiver"),
            T0ScheduledTurn("continue", "receiver"),
            T0ScheduledTurn("decide", "receiver"),
        ),
        (
            T0SeatPolicy("sender", (_offer("Dispatch parcel"), T0Rule((), T0Defer()))),
            T0SeatPolicy("receiver", (_offer("Acknowledge delivery"), T0Rule((), T0Defer()))),
        ),
        5,
    )
    goal = T0Goal((T0OwnerFieldEquals("scene", ("parcel", "status"), "arrived"),))
    original = check_witness(compile_owner_graph(parcel_library(), source), assets, witness, goal)
    changed = check_witness(compile_owner_graph(parcel_library(), edited), assets, witness, goal)
    assert (original.stop_reason, original.goal_status) == ("witness_stopped", "met")
    assert (changed.stop_reason, changed.goal_status) == (
        "witness_stopped",
        "not_met_within_bound",
    )
    assert changed.published == original.published[: len(changed.published)]


def test_parcel_finished_form_is_distinct_from_an_unfinished_witness() -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    assets = json.loads((PARCEL_ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    program = compile_owner_graph(parcel_library(), source)
    witness = T0Witness(
        (
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "receiver"),
            T0ScheduledTurn("continue", "receiver"),
            T0ScheduledTurn("decide", "receiver"),
            T0ScheduledTurn("decide", "sender"),
            T0ScheduledTurn("decide", "receiver"),
            T0ScheduledTurn("continue", "receiver"),
        ),
        (
            T0SeatPolicy("sender", (_offer("Dispatch parcel"), T0Rule((), T0Defer()))),
            T0SeatPolicy("receiver", (_offer("Acknowledge delivery"), T0Rule((), T0Defer()))),
        ),
        8,
    )
    goal = T0Goal((T0SourcePublished("c0.parcel.confirm"),))
    report = check_witness(program, assets, witness, goal)
    assert (report.stop_reason, report.goal_status, report.steps_completed) == (
        "game_form_finished",
        "met",
        8,
    )


def test_author_cli_uses_same_compiler_and_emits_structured_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = ROOT.parents[1] / "nomos_t0/examples/werewolf_self_heal_b.case.yaml"
    assets = ROOT.parents[1] / "nomos_t0/examples/werewolf_witch_b.assets.yaml"
    paths = [
        "--lib",
        str(ROOT / "three_seat_werewolf_v0.lib.yaml"),
        "--ports",
        str(ROOT / "three_seat_werewolf_v0.ports.yaml"),
        "--source",
        str(ROOT / "six_seat_werewolf_v0.source.yaml"),
        "--assets",
        str(assets),
        "--case",
        str(case),
        "--json",
    ]
    assert author_main(paths) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["stage"], report["goal_status"], report["steps_completed"]) == (
        "run",
        "met",
        10,
    )
    assert report["published"][-2]["source"] == "c0.six-seat.witch-b"

    source = _document("six_seat_werewolf_v0.source.yaml")
    source["actions"][0]["law"]["ref"] = "action.missing"
    bad_source = tmp_path / "bad.source.json"
    bad_source.write_text(json.dumps(source), encoding="utf-8")
    paths[paths.index("--source") + 1] = str(bad_source)
    assert author_main(paths) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert (rejected["stage"], rejected["stop_reason"], rejected["published"]) == (
        "compile",
        "compile_rejected",
        [],
    )

    paths[paths.index("--source") + 1] = str(tmp_path / "missing.source.yaml")
    assert author_main(paths) == 2
    rejected_input = json.loads(capsys.readouterr().out)
    assert (
        rejected_input["stage"],
        rejected_input["stop_reason"],
        rejected_input["published"],
    ) == (
        "compile",
        "input_rejected",
        [],
    )

    paths[paths.index("--source") + 1] = str(ROOT / "six_seat_werewolf_v0.source.yaml")
    malformed_case = tmp_path / "malformed.case.yaml"
    malformed_case.write_text("schema: [unterminated", encoding="utf-8")
    paths[paths.index("--case") + 1] = str(malformed_case)
    assert author_main(paths) == 2
    malformed = json.loads(capsys.readouterr().out)
    assert (malformed["stage"], malformed["stop_reason"], malformed["published"]) == (
        "compile",
        "input_rejected",
        [],
    )


def test_author_cli_does_not_exit_successfully_after_k0_rejects_a_met_opening_goal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    source["lawdefs"][0]["body"]["value"]["guard"]["all"].append({"const": False})
    source_path = tmp_path / "rejected.source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    case = {
        "schema": "t0.case.v0",
        "max_steps": 1,
        "schedule": ["sender"],
        "controllers": {"sender": [{"select": {"label": "Dispatch parcel"}}]},
        "goal": {
            "all": [
                {
                    "owner_field_eq": {
                        "owner": "scene",
                        "path": ["parcel", "status"],
                        "value": "home",
                    }
                }
            ]
        },
    }
    case_path = tmp_path / "opening-goal.case.json"
    case_path.write_text(json.dumps(case), encoding="utf-8")
    args = [
        "--lib",
        str(PARCEL_ROOT / "parcel_delivery_v0.lib.json"),
        "--ports",
        str(PARCEL_ROOT / "parcel_delivery_v0.ports.json"),
        "--source",
        str(source_path),
        "--assets",
        str(PARCEL_ROOT / "parcel_delivery_v0.a.assets.json"),
        "--case",
        str(case_path),
        "--json",
    ]
    assert author_main(args) == 3
    report = json.loads(capsys.readouterr().out)
    assert (report["stop_reason"], report["goal_status"], report["published"]) == (
        "k0_not_admitted",
        "met",
        [],
    )


def test_legal_action_can_finish_without_goal_and_external_input_is_not_invented() -> None:
    program = _werewolf_program()
    witness = T0Witness(
        (T0ScheduledTurn("decide", "B"),),
        (T0SeatPolicy("B", (_offer("Vote for C"),)),),
        1,
    )
    goal = T0Goal((T0SourcePublished("c0.six-seat.witch-b"),))
    report = check_witness(program, _witch_b_assets(), witness, goal)
    assert (report.stop_reason, report.goal_status, report.steps_completed) == (
        "scheduled_end",
        "not_met_within_bound",
        1,
    )
    assert [item.source for item in report.published] == ["c0.six-seat.vote-b"]

    external = T0Witness(witness.schedule, witness.controllers, 1, ("unmodelled rain",))
    unsupported = check_witness(program, _witch_b_assets(), external, goal)
    assert (unsupported.stop_reason, unsupported.goal_status, unsupported.published) == (
        "unsupported_input",
        "unknown",
        (),
    )


def test_k0_settlement_defect_remains_fatal_without_published_failed_wave() -> None:
    source = json.loads((PARCEL_ROOT / "parcel_delivery_v0.source.json").read_text())
    source["lawdefs"][4]["body"]["law"]["outputs"]["signal"] = {"const": "invalid"}
    assets = json.loads((PARCEL_ROOT / "parcel_delivery_v0.a.assets.json").read_text())
    program = compile_owner_graph(parcel_library(), source)
    witness = T0Witness(
        (T0ScheduledTurn("decide", "sender"),),
        (T0SeatPolicy("sender", (_offer("Dispatch parcel"),)),),
        1,
    )
    goal = T0Goal((T0SourcePublished("c0.parcel.depart"),))
    report = check_witness(program, assets, witness, goal)
    assert (report.stop_reason, report.goal_status, report.steps_completed) == (
        "settlement_defect",
        "unknown",
        0,
    )
    assert report.published == ()
