"""Small recording contracts; actual worlds are still executed by C0/T0/K0."""

from copy import deepcopy

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
        "goal_status": "met", "published": ["different"] * 14,
    })
    recording.write_json(tmp_path / "changed.json", {
        "stop_reason": "k0_not_admitted", "steps_completed": 9,
        "requested_step": 10, "published": ["tampered"] * 12,
    })
    with pytest.raises(ValueError, match="do not support"):
        recording.compare(tmp_path)
