"""Closed selection reuse still passes each Action's nominal port checks."""

from copy import deepcopy

import pytest
import yaml
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_binding_v1 import OWNERS, _expand, _source
from test_multi_participant_action_v0 import _compile, _owners, _world

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.participant_binding_v1 import expand_participant_bindings
from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle


def _shared():
    lib, ports, source, assets = _world()
    source["participant_bindings"] = [
        {"name": "tools", "participants": {"tool": {"kind": "tool"}}},
        {"name": "people", "participants": {"victim": {"actors": ["a", "b"]}}},
    ]
    source["actions"][0].pop("participants")
    source["actions"][0]["use_participants"] = ["tools", "people"]
    return lib, ports, source, assets


def test_shared_selections_publish_the_same_real_action_and_selected_owners():
    lib, ports, source, assets = _shared()
    before = deepcopy(source)
    program = _compile(lib, ports, source)
    session = program.start(assets)
    offer = session.offers("maker")[0]
    published = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(published, K0Published)
    assert _owners(session)["a"].enabled
    assert not _owners(session)["b"].enabled
    assert [item.name for item in published.occurrences[0].selected_owners] == ["tool", "victim"]
    assert source == before
    assert {item.source.value for item in published.occurrences} == {"c0.participants.enable"}


def test_inline_extra_and_family_references_are_isolated_and_keep_identity():
    source = _source()
    source["participant_bindings"] = [
        {"name": "victims", "participants": {"victim": {"actors": ["a", "b"]}}}
    ]
    source["actions"][0]["use_participants"] = ["victims"]
    source["actions"][0]["participants"] = {"other": {"actors": ["c"]}}
    before = deepcopy(source)
    expanded = _expand(source)
    assert source == before
    assert "participant_bindings" not in expanded
    assert [a["source_key"] for a in expanded["actions"]] == [
        "sample.attack-a", "sample.attack-b", "sample.attack-c"
    ]
    expanded["actions"][0]["participants"]["victim"]["actors"].clear()
    assert expanded["actions"][1]["participants"]["victim"]["actors"] == ["a", "b"]
    assert expanded["actions"][1]["participants"]["other"] == {"actors": ["c"]}


@pytest.mark.parametrize("fault", [
    "unknown", "repeated_use", "duplicate_name", "alias_overlap", "inline_overlap",
    "foreign_actor", "repeated_actor", "foreign_kind", "recursive", "empty", "target",
])
def test_malformed_reuse_rejects_without_changing_source(fault):
    source = _source()
    source["participant_bindings"] = [
        {"name": "victims", "participants": {"victim": {"actors": ["a", "b"]}}}
    ]
    action = source["actions"][0]
    action["use_participants"] = ["victims"]
    group = source["participant_bindings"][0]
    if fault == "unknown":
        action["use_participants"] = ["absent"]
    elif fault == "repeated_use":
        action["use_participants"] *= 2
    elif fault == "duplicate_name":
        source["participant_bindings"].append(deepcopy(group))
    elif fault == "alias_overlap":
        source["participant_bindings"].append({**deepcopy(group), "name": "other"})
        action["use_participants"].append("other")
    elif fault == "inline_overlap":
        action["participants"] = deepcopy(group["participants"])
    elif fault == "foreign_actor":
        group["participants"]["victim"] = {"actors": ["absent"]}
    elif fault == "repeated_actor":
        group["participants"]["victim"] = {"actors": ["a", "a"]}
    elif fault == "foreign_kind":
        group["participants"]["victim"] = {"kind": "absent"}
    elif fault == "recursive":
        group["use_participants"] = ["victims"]
    elif fault == "empty":
        group["participants"] = {}
    else:
        action["target"] = {"kind": "tool"}
    before = deepcopy(source)
    with pytest.raises(C0LawError):
        _expand(source)
    assert source == before


@pytest.mark.parametrize("fault", ["wrong_actor_type", "wrong_kind_type", "extra_alias"])
def test_shared_mapping_cannot_bypass_the_selected_ports(fault):
    lib, ports, source, _ = _shared()
    if fault == "wrong_actor_type":
        person = deepcopy(next(record for record in lib["records"] if record["name"] == "Person"))
        person["name"] = "OtherPerson"
        lib["records"].append(person)
        next(owner for owner in lib["owners"] if owner["symbol"] == "b")["state"] = "OtherPerson"
    elif fault == "wrong_kind_type":
        tool = deepcopy(next(record for record in lib["records"] if record["name"] == "Tool"))
        tool["name"] = "OtherTool"
        lib["records"].append(tool)
        lib["object_kinds"].append({
            "symbol": "other_tool", "sort": "EXAMPLE.OTHER_TOOL@1", "state": "OtherTool",
            "version": "other-tool-v1", "max_instances": 4,
        })
        source["object_kinds"].append({"kind": "other_tool", "sort": "EXAMPLE.OTHER_TOOL@1"})
        source["participant_bindings"][0]["participants"]["tool"] = {"kind": "other_tool"}
    else:
        source["participant_bindings"][1]["participants"]["other"] = {"actors": ["a"]}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_bundle_preserves_definition_and_use_file_origins(tmp_path):
    lib, ports, source, assets = _shared()
    groups = source.pop("participant_bindings")
    manifest = {
        "schema": "c0.source_bundle.v1", "source_schema": source.pop("schema"),
        "lib": "lib.yaml", "ports": "ports.yaml", "assets": "assets.yaml",
        "source_parts": ["use.yaml", "groups.yaml"],
    }
    for name, data in {
        "lib.yaml": lib, "ports.yaml": ports, "assets.yaml": assets,
        "use.yaml": source, "groups.yaml": {"participant_bindings": groups},
        "world.yaml": manifest,
    }.items():
        (tmp_path / name).write_text(yaml.safe_dump(data, sort_keys=False))
    bundle = read_source_bundle(tmp_path / "world.yaml")
    program = compile_source_bundle(bundle)
    action = dict(program.actions)["enable"]
    frames = action.value.guard_ir.expression.provenance
    selections = [frame for frame in frames if frame.kind == "participant_binding"]
    assert [frame.name for frame in selections] == ["tools", "people"]
    assert all(frame.span.file.endswith("groups.yaml") for frame in selections)
    assert any(frame.kind == "source_binding" and frame.span.file.endswith("use.yaml")
               for frame in frames)
    session = program.start(assets)
    foreign = program.start(assets).offers("maker")[0]
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("maker", "enable", dict(foreign.payload))
    assert session.author_snapshot() == before
    offer = session.offers("maker")[0]
    assert isinstance(session.submit("maker", "enable", dict(offer.payload)), K0Published)


def test_expander_keeps_unreferenced_declarations_checked():
    source = _source()
    source["participant_bindings"] = [
        {"name": "unused", "participants": {"victim": {"actors": ["absent"]}}}
    ]
    with pytest.raises(C0LawError):
        expand_participant_bindings(source, OWNERS)
