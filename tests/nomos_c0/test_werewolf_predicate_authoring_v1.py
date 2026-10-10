"""Author examples use boolean predicates without replacing real vote arithmetic."""

from pathlib import Path

import pytest

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.condition_source_v0 import lower_author_expression
from nomos_c0.nominal_type_aliases_v1 import BUILTIN_TYPE_NAMES, expand_type_aliases
from tools import release_rule_edit_demo

EXAMPLES = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


@pytest.mark.parametrize("filename", [
    "three_seat_werewolf_v0.source.yaml", "six_seat_werewolf_v0.source.yaml",
    "three_seat_werewolf_v0.lib.yaml",
])
def test_boolean_queries_do_not_use_numeric_counts_or_negated_absence(filename):
    document = read_author_document(EXAMPLES / filename).to_data()
    for node in nodes(document):
        assert not (isinstance(node.get("not"), dict) and "none_matching" in node["not"])
        operands = node.get("eq", [])
        if len(operands) == 2 and any(
            isinstance(item, dict) and "count_matching" in item for item in operands
        ):
            assert not any(item == {"const": 0} or item == {"const": 1} for item in operands)
        operands = node.get("lt", [])
        if len(operands) == 2:
            assert not (operands[0] == {"const": 0}
                        and isinstance(operands[1], dict) and "count_matching" in operands[1])


@pytest.mark.parametrize("filename", [
    "three_seat_werewolf_v0.source.yaml", "six_seat_werewolf_v0.source.yaml",
])
def test_opening_distinguishes_uniqueness_absence_and_actual_domain_size(filename):
    document = read_author_document(EXAMPLES / filename).to_data()
    actor_guard = document["opening_actor_guards"][0]["when"]["all"]
    assert "exactly_one" in actor_guard[0] and "exactly_one" in actor_guard[1]
    assert "none_matching" in actor_guard[2] and "none_matching" in actor_guard[3]
    counts = [node["count_matching"] for node in nodes(document["opening_guard"])
              if "count_matching" in node]
    assert {row["collection"]["ref"] for row in counts} == {"scene.players", "scene.roles"}
    assert all(row["where"] != {"eq": [{"ref": "player.alive"}, {"const": True}]}
               for row in counts)


def test_role_existence_and_numeric_vote_rules_remain_different_definitions():
    lib = read_author_document(EXAMPLES / "three_seat_werewolf_v0.lib.yaml").to_data()
    definitions = {row["name"]: row for row in lib["pure_definitions"]}
    assert definitions["town.has_living_role"]["result"] == "bool"
    assert "exists" in definitions["town.has_living_role"]["body"]
    for name in ("town.remaining_count", "town.living_role_count"):
        assert definitions[name]["result"] == "int"
        assert "count_matching" in definitions[name]["body"]
    laws = {row["name"]: row for row in lib["lawdefs"]}
    for name in ("event.resolve_day", "event.select_unanimous", "event.select_majority"):
        body = laws[name]["body"]["law"]
        guard = lower_author_expression(body["guard"])[0]
        assert any("count_matching" in node for node in nodes(guard))
    for name in ("event.resolve_day", "event.select_majority"):
        binding = laws[name]["body"]["law"]["bindings"][0]["where"]["all"][1]["let"]
        assert binding["name"] == "support"
        assert binding["value"].startswith("count(")
        assert "support * 2" in binding["in"]


def test_rule_capture_rejects_existing_destination_before_compile(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("existing capture must reject before compilation")

    monkeypatch.setattr(release_rule_edit_demo, "compile_owner_graph", forbidden)
    with pytest.raises(SystemExit) as failure:
        release_rule_edit_demo.main(["--record", str(tmp_path)])
    assert failure.value.code == 2


def test_shared_lib_field_types_are_declared_even_when_used_once():
    lib = read_author_document(EXAMPLES / "three_seat_werewolf_v0.lib.yaml").to_data()
    declared = BUILTIN_TYPE_NAMES | set(lib["type_aliases"]) | {
        record["name"] for record in lib["records"]
    }
    used = set()
    for record in lib["records"]:
        for field in record["fields"]:
            assert isinstance(field["type"], str), "declare domain field types before use"
            assert field["type"] in declared
            used.add(field["type"])
    assert set(lib["type_aliases"]) <= used
    assert lib["type_aliases"]["OptionalParticipant"] == {"optional": "ParticipantName"}


def test_single_use_domain_type_names_preserve_their_exact_constraints():
    lib = read_author_document(EXAMPLES / "three_seat_werewolf_v0.lib.yaml").to_data()
    expanded = expand_type_aliases(lib)
    fields = {(record["name"], field["name"]): field["type"]
              for record in expanded["records"] for field in record["fields"]}
    assert fields["Observation", "faction"] == {"enum": ["wolf", "town"]}
    assert fields["Scene", "phase"] == {"enum": ["day", "night", "finished"]}
    assert fields["Scene", "winner"] == {"enum": ["none", "wolf", "town"]}
    assert fields["NightChoice", "kind"] == {"enum": ["inspect", "pass"]}
    assert fields["Actor", "witch_notice"] == {"optional": "WitchNotice"}
    for record, field, item, limit in (
        ("Scene", "players", "Player", 64),
        ("Scene", "roles", "Assignment", 64),
        ("Actor", "votes", "OwnVote", 128),
        ("Actor", "observations", "Observation", 128),
        ("Actor", "choices", "NightChoice", 128),
        ("Actor", "attacks", "AttackChoice", 128),
        ("Actor", "witch_choices", "WitchChoice", 128),
    ):
        assert fields[record, field] == {"tuple": {"item": item, "max": limit}}
