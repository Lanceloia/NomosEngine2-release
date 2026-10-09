"""Release entries use installed author resources, not research-tree fallback."""

import tomllib
from pathlib import Path

import pytest

from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.source_bundle_v1 import read_source_bundle
from nomos_examples import __main__ as examples
from nomos_examples import everflame_bundle_path


def test_m1_installed_resource_has_a_closed_readable_author_bundle():
    path = everflame_bundle_path()
    assert path.is_file()
    bundle = read_source_bundle(path)
    source = bundle.source.to_data()
    assert source["schema"] == "c0.owner_graph.v6"
    assert source["game_form"]["mode"] == "action_value_event_jump"
    assert "adventurer" in {seat.get("name") for seat in source["seats"]}
    assert (path.parents[1] / "M1_ATTRIBUTION.md").is_file()


@pytest.mark.parametrize("world", ["everflame", "werewolf"])
def test_example_entry_delegates_only_paths_to_the_production_terminal(monkeypatch, world):
    calls = []
    monkeypatch.setattr(examples, "play", lambda argv: calls.append(argv) or 0)
    assert examples.main([world]) == 0
    (argv,) = calls
    if world == "everflame":
        assert argv == ["--bundle", str(everflame_bundle_path()), "--player-view"]
    else:
        assert argv[::2] == ["--lib", "--ports", "--source", "--assets"]
        assert all(Path(value).is_file() for value in argv[1::2])


def test_player_entry_cannot_enable_author_diagnostics():
    with pytest.raises(SystemExit) as caught:
        examples.main(["everflame", "--author-diagnostics"])
    assert caught.value.code == 2


def test_packaging_patterns_cover_every_m1_author_resource():
    root = Path(__file__).resolve().parents[2]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    patterns = metadata["tool"]["setuptools"]["package-data"]["nomos_examples"]
    package = everflame_bundle_path().parents[1]
    resources = tuple(package.glob("everflame/**/*.yaml"))
    assert resources
    assert all(
        any(resource.relative_to(package).match(pattern) for pattern in patterns)
        for resource in resources
    )


def test_m1_action_effects_have_exact_owner_write_declarations():
    bundle = read_source_bundle(everflame_bundle_path())
    nominal = check_nominal_lib(bundle.lib, bundle.source.to_data().get("actor_domains"))
    library = check_graph_ports(bundle.ports, nominal)
    assert library.actions
    for action in library.actions:
        for root, effects in action.ports.state_effects.items():
            for field in effects:
                assert f"{root}.{field}" in action.ports.value_ports.writable_paths, (
                    action.symbol, root, field
                )
