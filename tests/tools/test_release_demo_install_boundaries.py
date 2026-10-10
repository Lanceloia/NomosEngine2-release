"""Installed demos run normally; checkout-specific evidence cannot misattribute them."""

import json

import pytest

from tools import release_rule_edit_demo, release_wolf_vote_demo, release_world_edit_demo

DEMOS = (release_rule_edit_demo, release_wolf_vote_demo, release_world_edit_demo)


@pytest.mark.parametrize("demo", DEMOS, ids=("rule", "wolf", "world"))
def test_normal_demo_does_not_require_modules_below_the_tool_checkout(demo, tmp_path, capsys,
                                                                     monkeypatch):
    monkeypatch.setattr(demo, "HERE", tmp_path)
    assert demo.main([]) == 0
    output = capsys.readouterr().out
    if demo is release_rule_edit_demo:
        report = json.loads(output)
        assert report["unchanged_published_prefix"] == 12
        assert report["edited"]["stop_reason"] == "k0_not_admitted"
    elif demo is release_wolf_vote_demo:
        assert "death=None" in output and "death=F" in output
    else:
        assert "witch-e" in output and "G/H" in output


@pytest.mark.parametrize("demo", DEMOS, ids=("rule", "wolf", "world"))
def test_record_rejects_foreign_module_origins_before_world_execution(demo, tmp_path, capsys,
                                                                    monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("foreign checkout evidence must reject before world execution")

    monkeypatch.setattr(demo, "HERE", tmp_path)
    monkeypatch.setattr(demo, "compile_owner_graph", forbidden)
    destination = tmp_path / "evidence"
    with pytest.raises(SystemExit) as caught:
        demo.main(["--record", str(destination)])
    assert caught.value.code == 2
    assert "installed from this checkout" in capsys.readouterr().err
    assert not destination.exists()
