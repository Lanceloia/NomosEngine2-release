"""Author diagnostics render actual frozen checked nodes without changing the world."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_actor_family_runtime_v1 import _family_world
from test_authored_law_origin_v1 import _assets, _compile, _document, _sample

from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.author_diagnostics_v1 import render_author_guard_report
from nomos_c0.owner_graph_play_v1 import main
from nomos_c0.seat_offers_v0 import C0SeatOffer


def _documents(raws):
    return tuple(
        _document(raw, f"world.{part}.yaml")
        for raw, part in zip(raws, ("lib", "ports", "source"), strict=True)
    )


def test_two_source_bindings_report_generated_obligation_and_frozen_origin(monkeypatch):
    lib, ports, source = _sample(amount=3)
    documents = _documents((lib, ports, source))
    program = _compile(documents)
    source["actions"][0]["law"]["args"]["amount"] = 4
    other_program = _compile((documents[0], documents[1], _document(source, "other.source.yaml")))
    monkeypatch.setattr(
        Path, "read_text", lambda *args, **kwargs: pytest.fail("diagnostic reread author source")
    )
    for current, amount in ((program, 3), (other_program, 4)):
        session = current.start(_assets())
        offer = session.offers("a")[0]
        before = session.author_snapshot()
        assert isinstance(session.submit("a", offer.entry, dict(offer.payload)), K0NotAdmitted)
        report = session.author_guard_report("a", offer)
        assert report.status == "false_predicates"
        (failure,) = report.failures
        assert failure.path == "effects.payment.sufficient"
        assert failure.provenance[0].arguments == (("amount", amount),)
        text = "\n".join(render_author_guard_report(report))
        assert '"amount": ' + str(amount) in text
        assert "effects.payment.sufficient = false" in text
        assert "source_binding use_a" in text and "law_definition spend" in text
        assert documents[0].digest in text
        assert ("other.source.yaml:" if amount == 4 else "world.source.yaml:") in text
        assert session.author_snapshot() == before


def test_only_selected_branch_is_diagnosed_not_the_dead_branch():
    lib, ports, source = _sample(amount=1)
    lib["lawdefs"][0]["body"]["value"]["guard"] = {
        "if": {
            "when": "actor.name == 'a'",
            "then": {"require": [{"chosen": "scene.tokens > 3"}]},
            "else": {"require": [{"dead": "scene.tokens > 5"}]},
        }
    }
    session = _compile(_documents((lib, ports, source))).start(_assets())
    before = session.author_snapshot()
    report = session.author_guard_report("a", session.offers("a")[0])
    (failure,) = report.failures
    assert failure.names == ("chosen",) and failure.branches == ("guard.if.then",)
    text = "\n".join(render_author_guard_report(report))
    assert "chosen = false" in text and "Selected branch: guard.if.then" in text
    assert "dead" not in text and '"const":5' not in text
    assert session.author_snapshot() == before


def test_failed_any_preserves_alternative_group_and_selected_if_without_root_cause_claim():
    lib, ports, source = _sample(amount=1)
    lib["lawdefs"][0]["body"]["value"]["guard"] = {
        "require": [{"qualification": "actor.name == 'x' or scene.tokens > 3"}]
    }
    session = _compile(_documents((lib, ports, source))).start(_assets())
    report = session.author_guard_report("a", session.offers("a")[0])
    assert len(report.failures) == 2
    assert {failure.names for failure in report.failures} == {("qualification",)}
    alternatives = [failure.alternatives[0] for failure in report.failures]
    assert {alternative.index for alternative in alternatives} == {0, 1}
    assert len({alternative.identity for alternative in alternatives}) == 2
    assert all(
        alternative.path.startswith("guard.require.qualification") for alternative in alternatives
    )
    text = "\n".join(render_author_guard_report(report))
    assert "all alternatives failed; not independent errors" in text
    assert "guard.require.qualification" in text and "branch 1" in text and "branch 2" in text
    assert "guard.all[0]" not in text
    assert "root cause" not in text


def test_structured_any_alternatives_report_the_actual_author_paths():
    lib, ports, source = _sample(amount=1)
    lib["lawdefs"][0]["body"]["value"]["guard"] = {"require": [{"choice": {"any": [False, False]}}]}
    session = _compile(_documents((lib, ports, source))).start(_assets())
    before = session.author_snapshot()
    report = session.author_guard_report("a", session.offers("a")[0])
    assert {failure.alternatives[0].path for failure in report.failures} == {
        "guard.require.choice.any[0]",
        "guard.require.choice.any[1]",
    }
    text = "\n".join(render_author_guard_report(report))
    assert "guard.require.choice.any[0] (branch 1)" in text
    assert "guard.require.choice.any[1] (branch 2)" in text
    assert "guard.all[0]" not in text
    assert session.author_snapshot() == before


def test_no_false_predicates_does_not_promise_k0_admission():
    session = _compile(_documents(_sample(amount=1))).start(_assets())
    before = session.author_snapshot()
    report = session.author_guard_report("a", session.offers("a")[0])
    assert report.status == "no_false_predicates" and report.failures == ()
    assert "does not establish K0 admission" in "\n".join(render_author_guard_report(report))
    assert session.author_snapshot() == before


def test_broken_lookup_basis_is_not_invented_as_a_false_guard():
    lib, ports, source = _sample(amount=1)
    lib["records"].append(
        {"name": "Item", "fields": [{"name": "valid", "type": "bool"}], "invariant": None}
    )
    lib["records"][0]["fields"].append(
        {"name": "items", "type": {"tuple": {"item": "Item", "max": 4}}}
    )
    ports["actions"][0]["value"]["read"].append("scene.items")
    value = lib["lawdefs"][0]["body"]["value"]
    value["bindings"] = [
        {
            "name": "found",
            "collection": "scene.items",
            "as": "item",
            "where": True,
            "required": True,
        }
    ]
    assets = _assets()
    assets["opening"]["scene"]["items"] = []
    session = _compile(_documents((lib, ports, source))).start(assets)
    before = session.author_snapshot()
    report = session.author_guard_report("a", session.offers("a")[0])
    assert report.status == "no_false_predicates" and not report.failures
    assert session.author_snapshot() == before


def test_evaluation_fault_is_not_invented_as_a_false_predicate():
    lib, ports, source = _sample(amount=1)
    lib["lawdefs"][0]["body"]["value"]["guard"] = {
        "lt": [0, {"mul": [{"ref": "scene.tokens"}, 1 << 62]}]
    }
    session = _compile(_documents((lib, ports, source))).start(_assets())
    before = session.author_snapshot()
    report = session.author_guard_report("a", session.offers("a")[0])
    assert report.status == "evaluation_fault" and report.failures == ()
    assert session.author_snapshot() == before


def test_guard_diagnostic_does_not_roll_or_evaluate_world_effects():
    from test_finite_region_dice_v1 import _assets, _program

    session = _program().start(_assets(seed=17))
    offer = session.offers("traveler")[0]
    before = session.author_snapshot()
    for _ in range(3):
        assert session.author_guard_report("traveler", offer).status == "no_false_predicates"
    assert session.author_snapshot() == before
    result = session.submit("traveler", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].semantic_envelope.roll == 7


def test_dynamic_and_closed_participants_use_actual_current_owner_without_publishing():
    lib, ports, source, assets = _family_world({"actor": "b"})
    session = _compile(_documents((lib, ports, source))).start(assets)
    offer = next(item for item in session.offers("maker") if item.label == "Use one on a")
    before = session.author_snapshot()
    assert session.author_guard_report("maker", offer).status == "no_false_predicates"
    assert session.author_snapshot() == before
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0Published)
    after = session.author_snapshot()
    report = session.author_guard_report("maker", offer)
    assert report.status == "false_predicates"
    assert session.author_snapshot() == after

    payload = dict(offer.payload)
    payload["victim"] = "absent"
    assert (
        session.author_guard_report("maker", replace(offer, payload=tuple(payload.items()))).status
        == "basis_unavailable"
    )


def test_foreign_dynamic_target_and_foreign_entry_are_not_diagnosed_as_current_guard():
    lib, ports, source, assets = _family_world({"actor": "b"})
    program = _compile(_documents((lib, ports, source)))
    first, second = program.start(assets), program.start(assets)
    own = first.offers("maker")[0]
    foreign = second.offers("maker")[0]
    before = first.author_snapshot()
    assert first.author_guard_report("maker", foreign).status == "basis_unavailable"
    with pytest.raises(C0BindingError, match="bound seat Action"):
        first.author_guard_report("maker", C0SeatOffer("absent", "Absent", ()))
    assert first.author_snapshot() == before
    assert first.author_guard_report("maker", own).status == "no_false_predicates"


def test_single_object_target_guard_reads_the_actual_consumed_owner():
    from test_object_generic_law_v1 import _world

    lib, ports, source, assets = _world()
    session = _compile(_documents((lib, ports, source))).start(assets)
    offer = next(item for item in session.offers("actor") if item.label == "Inspect old")
    assert session.author_guard_report("actor", offer).status == "no_false_predicates"
    assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)
    before = session.author_snapshot()
    report = session.author_guard_report("actor", offer)
    assert report.status == "false_predicates"
    assert report.failures[0].expression == '{"ref":"target.ready"}'
    assert session.author_snapshot() == before


def test_fixed_participant_payload_is_resolved_by_the_existing_submission_path():
    from test_multi_participant_action_v0 import _fixed_world

    lib, ports, source, assets = _fixed_world()
    session = _compile(_documents((lib, ports, source))).start(assets)
    offer = session.offers("maker")[0]
    assert offer.payload == ()
    before = session.author_snapshot()
    assert session.author_guard_report("maker", offer).status == "no_false_predicates"
    assert session.author_snapshot() == before
    assert isinstance(session.submit("maker", offer.entry, {}), K0Published)


def test_unlocated_low_level_input_is_reported_as_unknown_not_a_guessed_file():
    session = _compile(_sample()).start(_assets())
    report = session.author_guard_report("a", session.offers("a")[0])
    text = "\n".join(render_author_guard_report(report))
    assert "location unavailable" in text
    assert "sha256=" not in text


@pytest.mark.parametrize("author", [False, True])
def test_real_file_terminal_only_renders_origins_on_explicit_author_flag(
    tmp_path, monkeypatch, capsys, author
):
    raws = (*_sample(amount=3), _assets())
    args = []
    for part, raw in zip(("lib", "ports", "source", "assets"), raws, strict=True):
        path = tmp_path / f"world.{part}.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        args.extend((f"--{part}", str(path)))
    if author:
        args.append("--author-diagnostics")
    commands = iter(("1", "quit"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(commands))
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "K0NotAdmitted" in output
    assert ("Author guard check" in output) is author
    assert ("world.lib.yaml:" in output) is author
    assert ("effects.payment.sufficient" in output) is author


def test_player_mode_rejects_author_flag_before_loading_files(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("player/author conflict loaded world")

    monkeypatch.setattr(Path, "read_text", forbidden)
    with pytest.raises(SystemExit) as error:
        main(["--player-view", "--author-diagnostics", "absent"])
    assert error.value.code == 2
    assert "cannot be used with player view" in capsys.readouterr().err
