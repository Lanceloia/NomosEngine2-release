"""Small multi-file author contracts, without a long application replay."""

from copy import deepcopy

import pytest
import yaml
from authored_counter_v1 import _actor, counter_documents
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _fixture(root):
    lib, ports, source, assets = counter_documents(2, 2)
    second = deepcopy(source["lawdefs"][0])
    second["name"] = "count_other"
    source["lawdefs"].append(second)
    source["actions"][1]["law"] = {"ref": "count_other", "args": {"step": 2}}
    manifest = {
        "schema": "c0.source_bundle.v1",
        "source_schema": source["schema"],
        "lib": "model.lib.yaml",
        "ports": "capabilities.ports.yaml",
        "assets": "opening.assets.yaml",
        "source_parts": ["source/world.yaml", "source/rules.yaml", "source/abilities.yaml"],
    }
    world = {
        key: value
        for key, value in source.items()
        if key not in {"schema", "lawdefs", "actions", "seats"}
    }
    world["lawdefs"] = [source["lawdefs"][0]]
    _write(root / manifest["lib"], lib)
    _write(root / manifest["ports"], ports)
    _write(root / manifest["assets"], assets)
    _write(root / "source/world.yaml", world)
    _write(root / "source/rules.yaml", {"lawdefs": [second]})
    _write(root / "source/abilities.yaml", {"actions": source["actions"], "seats": source["seats"]})
    _write(root / "world.bundle.yaml", manifest)
    return root / "world.bundle.yaml", source, assets


def test_frozen_bundle_compiles_one_program_and_starts_independent_assets(tmp_path):
    path, source, assets = _fixture(tmp_path)
    bundle = read_source_bundle(path)
    assert bundle.source.to_data() == source
    for file in tmp_path.rglob("*.yaml"):
        file.unlink()
    program = compile_source_bundle(bundle)
    first = program.start(assets)
    changed = deepcopy(assets)
    changed["opening"]["actor_1"]["count"] = 10
    other = program.start(changed)
    assert isinstance(first.submit("seat_1", "count_1", {"target": "person_1"}), K0Published)
    assert _actor(first, 1).count == 2
    assert _actor(other, 1).count == 10
    assert _actor(first, 0).count == 0


def test_rebased_law_and_binding_keep_original_file_paths(tmp_path):
    path, _, _ = _fixture(tmp_path)
    bundle = read_source_bundle(path)
    span = bundle.source.context().locate("lawdefs[1].body.value.guard")
    assert span.file == str(tmp_path / "source/rules.yaml")
    assert span.path == ("lawdefs", 0, "body", "value", "guard")
    assert span == bundle.source.parts[1].spans[span.path]
    binding = bundle.source.context().locate("actions[1].law")
    assert binding.file.endswith("source/abilities.yaml")
    assert binding.path == ("actions", 1, "law")


def test_edited_rule_changes_real_admission_without_world_glue(tmp_path):
    path, _, assets = _fixture(tmp_path)
    rules_path = tmp_path / "source/rules.yaml"
    rules = yaml.safe_load(rules_path.read_text())
    rules["lawdefs"][0]["body"]["value"]["guard"] = "actor.count < 1"
    _write(rules_path, rules)
    session = compile_source_bundle(read_source_bundle(path)).start(assets)
    assert isinstance(session.submit("seat_1", "count_1", {"target": "person_1"}), K0Published)
    before = session.author_snapshot()
    assert isinstance(session.submit("seat_1", "count_1", {"target": "person_1"}), K0NotAdmitted)
    assert session.author_snapshot() == before
    report = session.author_guard_report("seat_1", session.offers("seat_1")[0])
    assert any(
        frame.span is not None and frame.span.file == str(rules_path)
        for condition in report.failures
        for frame in condition.provenance
    )


@pytest.mark.parametrize("section", ["lawdefs", "seats", "game_form"])
def test_duplicate_declarations_never_merge_even_if_equal(tmp_path, section):
    path, source, _ = _fixture(tmp_path)
    manifest = yaml.safe_load(path.read_text())
    manifest["source_parts"].append("duplicate.yaml")
    value = source[section] if section == "game_form" else [source[section][0]]
    _write(tmp_path / "duplicate.yaml", {section: value})
    _write(path, manifest)
    with pytest.raises(C0LawError, match="Duplicate Source") as failure:
        read_source_bundle(path)
    assert "duplicate.yaml" in str(failure.value) and "first at" in str(failure.value)


@pytest.mark.parametrize("change", ["repeat", "absolute", "unknown", "schema", "missing"])
def test_explicit_closed_manifest(tmp_path, change):
    path, _, _ = _fixture(tmp_path)
    manifest = yaml.safe_load(path.read_text())
    if change == "repeat":
        manifest["source_parts"].append("./source/world.yaml")
    elif change == "absolute":
        manifest["lib"] = str(tmp_path / "model.lib.yaml")
    elif change == "unknown":
        manifest["glob"] = "source/*.yaml"
    elif change == "schema":
        manifest["source_schema"] = "old"
    else:
        manifest["assets"] = "missing.yaml"
    _write(path, manifest)
    with pytest.raises(C0LawError):
        read_source_bundle(path)


@pytest.mark.parametrize(
    "fragment", [{"schema": "c0.owner_graph.v6"}, {"seats": {}}, {"script": []}]
)
def test_fragments_do_not_introduce_another_language(tmp_path, fragment):
    path, _, _ = _fixture(tmp_path)
    _write(tmp_path / "source/rules.yaml", fragment)
    with pytest.raises(C0LawError):
        read_source_bundle(path)


def test_bundle_budget_is_aggregate(tmp_path, monkeypatch):
    import nomos_c0.source_bundle_v1 as module

    path, _, _ = _fixture(tmp_path)
    sizes = [len(file.read_bytes()) for file in tmp_path.rglob("*.yaml")]
    monkeypatch.setattr(module, "_MAX_BYTES", max(sizes) + 1)
    with pytest.raises(C0LawError, match="aggregate"):
        read_source_bundle(path)


def test_bundle_terminal_uses_the_same_compiler(tmp_path, monkeypatch, capsys):
    from nomos_c0.owner_graph_play_v1 import main

    path, _, _ = _fixture(tmp_path)
    answers = iter(["1", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(["--bundle", str(path)]) == 0
    assert "count" in capsys.readouterr().out.lower()
    with pytest.raises(SystemExit):
        main(["other_example", "--bundle", str(path)])


def test_manifest_order_is_preserved_not_sorted(tmp_path):
    path, _, _ = _fixture(tmp_path)
    manifest = yaml.safe_load(path.read_text())
    manifest["source_parts"][:2] = reversed(manifest["source_parts"][:2])
    _write(path, manifest)
    bundle = read_source_bundle(path)
    assert [law["name"] for law in bundle.source.to_data()["lawdefs"]] == ["count_other", "count"]
    assert bundle.source.context().locate("lawdefs[0]").path == ("lawdefs", 0)
    compile_source_bundle(bundle)


def test_missing_rule_is_rejected_by_the_common_compiler(tmp_path):
    path, _, _ = _fixture(tmp_path)
    _write(tmp_path / "source/rules.yaml", {"lawdefs": []})
    with pytest.raises(C0LawError):
        compile_source_bundle(read_source_bundle(path))


def test_yaml_anchors_cannot_cross_file_boundaries(tmp_path):
    path, _, _ = _fixture(tmp_path)
    (tmp_path / "source/rules.yaml").write_text("lawdefs: *foreign\n", encoding="utf-8")
    with pytest.raises(C0LawError, match="source/rules.yaml"):
        read_source_bundle(path)


@pytest.mark.parametrize("member_binding", [False, True])
def test_output_family_expression_keeps_rebased_module_origin(tmp_path, member_binding):
    path, _, _ = _fixture(tmp_path)
    rules_path = tmp_path / "source/rules.yaml"
    rules = yaml.safe_load(rules_path.read_text())
    body = rules["lawdefs"][0]["body"]["value"]
    body["outputs"].pop("count")
    body["output_families"] = [
        {
            "name": "counter",
            "owners": ["actor"],
            "as": "person",
            "fields": {"count": {"add": [{"ref": "person.count"}, {"arg": "step"}]}},
        }
    ]
    if member_binding:
        body["output_families"][0]["bindings"] = {
            "after": {"add": [{"ref": "person.count"}, {"arg": "step"}]}
        }
        body["output_families"][0]["fields"]["count"] = "after"
    _write(rules_path, rules)
    program = compile_source_bundle(read_source_bundle(path))
    expression = dict(program.actions)["count_1"].value._tree["outputs"]["count"]
    frame = expression.provenance[-1]
    assert frame.span.file == str(rules_path)
    assert frame.span.path[:2] == ("lawdefs", 0)
    if member_binding:
        computation = dict(program.actions)["count_1"].value._tree["bindings"][-1]["let"]
        frame = next(
            frame for frame in computation.provenance if frame.kind == "output_member_binding"
        )
        assert frame.span.file == str(rules_path)
        assert dict(frame.arguments)["owner"] == "actor"
