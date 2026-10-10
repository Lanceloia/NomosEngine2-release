"""Short real and adversarial checks for two existing author-edit demonstrations."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from tools import release_world_edit_demo as demo


@pytest.fixture(scope="module")
def actual():
    examples = demo.HERE / "src/nomos_c0/examples"
    paths = {
        "lib": examples / "three_seat_werewolf_v0.lib.yaml",
        "ports": examples / "three_seat_werewolf_v0.ports.yaml",
        "source": examples / "six_seat_werewolf_v0.source.yaml",
        "assets": demo.HERE / "src/nomos_t0/examples/werewolf_witch_b.assets.yaml",
        "requests": demo.INPUTS / "actions.yaml",
    }
    data = {name: demo.read_author_document(path).to_data() for name, path in paths.items()}
    untouched = deepcopy(data)
    report, effective = demo.compare(**data)
    assert data == untouched
    return data, report, effective


def test_role_edit_changes_only_explicit_role_and_supply_assignments(actual):
    assets = actual[0]["assets"]
    changed = demo.move_witch(assets)
    assert changed != assets
    opening = changed["opening"]
    for name in "BE":
        opening[name.lower()] = deepcopy(assets["opening"][name.lower()])
    opening["scene"]["roles"] = deepcopy(assets["opening"]["scene"]["roles"])
    assert changed == assets
    assert actual[2]["six.source.yaml"] == actual[0]["source"]


def test_size_edit_adds_only_members_and_their_openings(actual):
    source, assets = demo.add_participants(actual[0]["source"], actual[0]["assets"])
    assert source["actor_domains"][0]["owners"] == list("abcdefgh")
    source["actor_domains"][0]["owners"] = list("abcdef")
    assert source == actual[0]["source"]
    opening = assets["opening"]
    for name in "gh":
        del opening[name]
    for field in ("players", "roles"):
        opening["scene"][field] = opening["scene"][field][:6]
    assert assets == actual[0]["assets"]


def test_real_role_notice_and_action_provenance_move_together(actual):
    versions = actual[1]["role_move"]
    for name, healer in (("witch_B", "B"), ("witch_E", "E")):
        version = versions[name]
        own = version["before_save"]["seats"][healer]["read"]
        notice = own[f"{healer.lower()}.witch_notice"]
        history = {row["occurrence"]: row for row in version["before_save"]["published"]}
        assert history[notice["notice"]["value"]]["family"] == "event"
        assert history[notice["notice"]["value"]]["source"].endswith(f"-{healer.lower()}")
        assert notice["selection"]["value"] != notice["notice"]["value"]
        final = version["actions"][-1]["published"]
        assert final[0]["source"] == f"c0.six-seat.witch-{healer.lower()}"
        assert final[1]["source"].endswith(f"-{healer.lower()}")
    assert versions["witch_E"]["B_candidate_check"] == {
        "offer_found": False, "submitted": False,
    }


def test_new_people_have_local_views_and_real_independent_votes(actual):
    version = actual[1]["size_change"]["eight"]
    for name in "GH":
        local = version["opening"]["seats"][name]
        assert local["read"][f"{name.lower()}.name"] == name
        assert len(local["offers"]) == 8
        assert all(not key.startswith(("a.", "b.")) for key in local["read"])
    assert [row["occurrence"] for row in version["after_votes"]["published"]] == [1, 2]
    assert len(version["after_votes"]["owners"]["g"]["votes"]) == 1
    assert not version["after_votes"]["owners"]["h"]["votes"]
    # JSON readback must remain valid despite tuple-to-array conversion.
    demo.validate(json.loads(json.dumps(actual[1])))


@pytest.mark.parametrize("fault", ["notice", "offers", "source", "owners", "vote", "ref"])
def test_unsupported_claims_are_rejected(actual, fault):
    report = deepcopy(actual[1])
    role = report["role_move"]["witch_E"]
    expanded = report["size_change"]["eight"]
    if fault == "notice":
        role["before_save"]["seats"]["E"]["read"]["e.witch_notice"]["target"] = "A"
    elif fault == "offers":
        role["before_save"]["seats"]["B"]["offers"] = [{"label": "Save victim"}]
    elif fault == "source":
        role["actions"][-1]["published"][0]["source"] = "host.fake"
    elif fault == "owners":
        del expanded["opening"]["owners"]["g"]
    elif fault == "vote":
        expanded["after_votes"]["owners"]["g"]["votes"][0]["target"] = "H"
    else:
        expanded["after_votes"]["owners"]["g"]["votes"][0]["action"]["value"] = 1
    with pytest.raises(ValueError):
        demo.validate(report)


def test_bad_opening_and_domain_are_not_silently_repaired(actual):
    assets = deepcopy(actual[0]["assets"])
    assets["opening"]["b"]["healing_available"] = False
    with pytest.raises(ValueError, match="supply must agree"):
        demo.move_witch(assets)
    source = deepcopy(actual[0]["source"])
    source["actor_domains"][0]["owners"].append("g")
    with pytest.raises(ValueError, match="six-person"):
        demo.add_participants(source, actual[0]["assets"])


def test_existing_record_is_not_overwritten(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("must reject the destination before starting worlds")

    monkeypatch.setattr(demo, "compare", forbidden)
    with pytest.raises(SystemExit) as failure:
        demo.main(["--record", str(tmp_path)])
    assert failure.value.code == 2


@pytest.mark.parametrize("directory", ["evidence", "evidence-predicates-v1"])
def test_saved_evidence_matches_manifest_and_exact_author_edits(directory):
    evidence = demo.INPUTS / directory
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["artifacts_sha256"].items():
        assert hashlib.sha256((evidence / name).read_bytes()).hexdigest() == digest
    demo.validate(json.loads((evidence / "result.json").read_text(encoding="utf-8")))
    documents = {name: demo.read_author_document(evidence / name).to_data()
                 for name in manifest["artifacts_sha256"] if name.endswith(".yaml")}
    assert documents["witch-E.assets.yaml"] == demo.move_witch(documents["witch-B.assets.yaml"])
    source, assets = demo.add_participants(
        documents["six.source.yaml"], documents["witch-B.assets.yaml"])
    assert source == documents["eight.source.yaml"]
    assert assets == documents["eight.assets.yaml"]
