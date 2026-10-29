"""Exercise the showcase's real rule edit and reject unrelated edits."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_real_self_save_rule_edit_and_reports(tmp_path):
    run = runpy.run_path(str(ROOT / "showcase.py"))["run"]
    result = run(tmp_path / "result")
    assert result["passed"] is True
    cases = result["cases"]
    assert cases["allow"]["profile"]["witch"]["alive"] is True
    assert cases["decline"]["profile"]["witch"]["alive"] is False
    assert cases["deny"]["profile"]["rejected_without_change"] is True
    assert cases["deny"]["witness"]["steps_completed"] == 5
    assert cases["deny"]["witness"]["requested_step"] == 6
    assert len({case["profile"]["prefix_sha256"] for case in cases.values()}) == 1
    assert result["timing"]["action_samples"] == 18
    disk = json.loads((tmp_path / "result/result.json").read_text())
    assert disk["inputs"] == result["inputs"]
    assert disk["cases"]["allow"]["witness"]["goal_status"] == "met"
    report = (tmp_path / "result/report.html").read_text()
    assert "禁止自救：同一选择在第6步被拒绝" in report
    assert "不用于证明电脑策略水平" in report
    with pytest.raises(FileExistsError):
        run(tmp_path / "result")


def test_unrelated_rule_edit_is_refused_before_compilation(tmp_path):
    run = runpy.run_path(str(ROOT / "showcase.py"))["run"]
    demo = tmp_path / "demo"
    demo.mkdir()
    allowed = "allow_self_save: true\nallow_two_potions: true\n"
    (demo / "allow.source.yaml").write_text(allowed)
    (demo / "deny.source.yaml").write_text(
        allowed.replace("allow_self_save: true", "allow_self_save: false").replace(
            "allow_two_potions: true", "allow_two_potions: false"
        )
    )
    run.__globals__["DEMO"] = demo
    with pytest.raises(RuntimeError, match="differ only in self-save policy"):
        run(tmp_path / "invalid-result")
    assert not (tmp_path / "invalid-result/allow.py").exists()
