"""Small recording contracts; actual worlds are still executed by C0/T0/K0."""

import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from tools import showcase_recording as recording


def test_edit_is_one_clause_and_does_not_change_other_inputs(tmp_path):
    work = tmp_path / "work"
    recording.prepare(work)
    before = {name: (work / name).read_bytes() for name in recording.INPUTS}
    recording.edit(work)
    assert (work / "lib.yaml").read_text().count(recording.CLAUSE) == 1
    assert (work / "original.lib.yaml").read_bytes() == before["lib.yaml"]
    assert all((work / name).read_bytes() == raw
               for name, raw in before.items() if name != "lib.yaml")
    edited = (work / "lib.yaml").read_bytes()
    with pytest.raises(ValueError, match="unique, unedited"):
        recording.edit(work)
    assert (work / "lib.yaml").read_bytes() == edited


def test_existing_workspace_is_not_overwritten(tmp_path):
    work = tmp_path / "work"
    recording.prepare(work)
    with pytest.raises(FileExistsError):
        recording.prepare(work)


def test_html_embeds_output_as_data_not_executable_markup():
    value = {"chapters": [{"output": "</script><script>throw Error('forged')</script>"}]}
    before = deepcopy(value)
    page = recording.render_page(value)
    assert "__RECORDING__" not in page
    assert "\\u003c/script>" in page
    assert "</script><script>throw" not in page
    assert value == before


def test_actual_short_rule_edit_and_zero_write_refusal(tmp_path, capsys):
    work = tmp_path / "work"
    recording.prepare(work)
    assert recording.replay(work, "original") == 0
    recording.edit(work)
    assert recording.replay(work, "changed") == 3
    recording.compare(work)
    proof = recording.load_json(work / "comparison.json")
    assert proof["equal_published_prefix"] == 12
    assert proof["candidate_still_present"]
    assert proof["refusal_snapshot_before"] == proof["refusal_snapshot_after"]
    assert proof["original_lib_sha256"] != proof["changed_lib_sha256"]
    assert all(proof["unchanged_inputs"].values())
    assert "save_choice/not_self = false" in capsys.readouterr().out


def test_compare_rejects_a_modified_published_prefix(tmp_path):
    recording.write_json(tmp_path / "original.json", {
        "goal_status": "met", "steps_completed": 10,
        "published": [{"family": "action", "source": "different"}] * 14,
    })
    recording.write_json(tmp_path / "changed.json", {
        "stop_reason": "k0_not_admitted", "steps_completed": 9,
        "requested_step": 10, "published": ["tampered"] * 12,
    })
    with pytest.raises(ValueError, match="do not support"):
        recording.compare(tmp_path)


@pytest.mark.parametrize("fault", ["missing_suffix", "wrong_suffix_source"])
def test_compare_rejects_unsupported_original_publication(tmp_path, fault):
    value = recording.load_json(
        recording.ROOT / "docs/showcase/self-heal-predicates-v1/result.json")
    original = deepcopy(value["original"])
    if fault == "missing_suffix":
        original["published"] = original["published"][:12]
    else:
        original["published"][12]["source"] = "not-the-witch"
    recording.write_json(tmp_path / "original.json", original)
    recording.write_json(tmp_path / "changed.json", value["edited"])
    with pytest.raises(ValueError, match="do not support"):
        recording.compare(tmp_path)


def test_recording_phase_has_a_bounded_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        recording.run_phase("sleep 30", recording.os.environ.copy(), timeout=0.05)


@pytest.mark.skipif(shutil.which("node") is None, reason="optional video exporter needs Node")
def test_export_releases_reservation_when_dependency_is_missing(tmp_path):
    result = subprocess.run([
        "node", str(recording.ROOT / "tools/render_showcase_recording.cjs"), str(tmp_path),
        str(tmp_path / "missing-playwright.cjs"),
    ], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 1
    assert "Cannot find module" in result.stderr
    assert not (tmp_path / ".video-export.lock").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="optional video exporter needs Node")
def test_export_preserves_existing_media_without_loading_browser(tmp_path):
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"existing evidence")
    result = subprocess.run([
        "node", str(recording.ROOT / "tools/render_showcase_recording.cjs"), str(tmp_path),
        str(tmp_path / "missing-playwright.cjs"),
    ], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 1
    assert "never overwrite" in result.stderr
    assert poster.read_bytes() == b"existing evidence"
    assert not (tmp_path / ".video-export.lock").exists()


def test_saved_capture_outputs_and_reports_match_their_digests():
    directory = Path(__file__).resolve().parents[2] / "docs/showcase/recording/capture-v1"
    manifest = recording.load_json(directory / "manifest.json")
    for name, expected in manifest["artifacts_sha256"].items():
        assert recording.digest((directory / name).read_bytes()) == expected
    original = recording.load_json(directory / "original.json")
    changed = recording.load_json(directory / "changed.json")
    comparison = recording.load_json(directory / "comparison.json")
    assert original["goal_status"] == "met"
    assert changed["stop_reason"] == "k0_not_admitted"
    assert changed["requested_step"] == 10
    assert changed["published"] == original["published"][:12]
    assert comparison["refusal_snapshot_before"] == comparison["refusal_snapshot_after"]
    assert comparison["candidate_still_present"] is True
    assert all(comparison["unchanged_inputs"].values())
    captured = recording.load_json(directory / "recording.json")
    cast = [recording.json.loads(line) for line in (directory / "session.cast").read_text(
        encoding="utf-8").splitlines()]
    assert len(cast) == 1 + 2 * len(captured["chapters"])
    for index, chapter in enumerate(captured["chapters"]):
        assert cast[2 + index * 2][2].replace("\r\n", "\n") == chapter["output"]
