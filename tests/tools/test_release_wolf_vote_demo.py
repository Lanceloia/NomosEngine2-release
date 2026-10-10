"""Short evidence checks for one existing rule-replacement comparison."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from tools import release_wolf_vote_demo as demo


@pytest.fixture(scope="module")
def actual():
    examples = demo.HERE / "src/nomos_c0/examples"
    data = {
        name: demo.read_author_document(examples / filename).to_data()
        for name, filename in (
            ("lib", "three_seat_werewolf_v0.lib.yaml"),
            ("ports", "three_seat_werewolf_v0.ports.yaml"),
            ("source", "six_seat_werewolf_v0.source.yaml"),
        )
    }
    data["assets"] = demo.read_author_document(demo.INPUTS / "opening.assets.yaml").to_data()
    requests = demo.read_requests(demo.INPUTS / "actions.yaml")
    untouched = deepcopy(data)
    report = demo.compare(**data, requests=requests)
    assert data == untouched
    return data, report


def test_only_one_law_reference_changes(actual):
    source = actual[0]["source"]
    changed = demo.replace_selection(source)
    selection = next(row for row in changed["events"] if row.get("family") == "select_target")
    assert selection["law"]["ref"] == "event.select_majority"
    selection["law"]["ref"] = "event.select_unanimous"
    assert changed == source


def test_real_runs_accept_same_requests_but_change_world_post_state(actual):
    report = actual[1]
    first, second = report["versions"].values()
    assert first["opening"] == second["opening"]
    assert first["steps"][:9] == second["steps"][:9]
    for version in (first, second):
        rows = version["steps"][-1]["published"]
        assert len(rows) == 13
        assert sum(row["family"] == "action" for row in rows) == 10
        assert version["steps"][-1]["scene"]["winner"] == "none"
    assert first["steps"][-1]["scene"]["last_death"] is None
    assert second["steps"][-1]["scene"]["last_death"] == "F"
    assert first["steps"][-1]["other_owners"]["f"]["own_role"] == "wolf"
    assert "Both versions accept" in demo.summary(report)
    json.dumps(report)


@pytest.mark.parametrize("fault", ["prefix", "payload", "outcome", "missing_action", "history"])
def test_unsupported_evidence_is_rejected(actual, fault):
    versions = deepcopy(actual[1]["versions"])
    steps = versions["majority"]["steps"]
    if fault == "prefix":
        steps[0]["other_owners"]["a"]["own_role"] = "wolf"
    elif fault == "payload":
        steps[-1]["payload"]["target"] = "A"
    elif fault == "outcome":
        steps[-1]["scene"]["last_death"] = None
    elif fault == "missing_action":
        steps.pop()
    else:
        steps[-1]["published"].pop()
    with pytest.raises(ValueError):
        demo.validate_versions(versions)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_law"])
def test_wrong_selection_binding_does_not_silently_pick_a_row(actual, fault):
    source = deepcopy(actual[0]["source"])
    selection = next(row for row in source["events"] if row.get("family") == "select_target")
    if fault == "missing":
        source["events"].remove(selection)
    elif fault == "duplicate":
        source["events"].append(deepcopy(selection))
    else:
        selection["law"]["ref"] = "event.resolve_night"
    with pytest.raises(ValueError, match="exactly one"):
        demo.replace_selection(source)


def test_requests_are_finite_and_missing_offer_is_not_invented(actual, tmp_path):
    path = tmp_path / "actions.yaml"
    path.write_text("steps: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ten"):
        demo.read_requests(path)
    data = actual[0]
    requests = deepcopy(actual[1]["requests"])
    requests[0]["label"] = "Unprovided action"
    with pytest.raises(ValueError, match="no unique current offer"):
        demo.compare(**data, requests=requests)


def test_existing_capture_is_not_overwritten_before_world_execution(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not compile a world when the destination exists")

    monkeypatch.setattr(demo, "compare", forbidden)
    with pytest.raises(SystemExit) as failure:
        demo.main(["--record", str(tmp_path)])
    assert failure.value.code == 2


def test_saved_report_and_effective_sources_match_their_manifest():
    evidence = demo.INPUTS / "evidence"
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    raw = (evidence / "result.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["result_sha256"]
    report = json.loads(raw)
    assert demo.validate_versions(report["versions"])
    sources = {}
    for name, digest in manifest["effective_sources_sha256"].items():
        path = evidence / f"{name}.source.yaml"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        sources[name] = demo.read_author_document(path).to_data()
    assert sources["majority"] == demo.replace_selection(sources["unanimous"])
