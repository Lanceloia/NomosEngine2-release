"""Compile-time scoring reuse preserves exact seat coverage and local authority."""

from copy import deepcopy

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_family_runtime_v1 import _family_world
from test_authored_law_origin_v1 import _compile as _compile_documents
from test_authored_law_origin_v1 import _document
from test_control_binding_v1 import _compile, _inputs

from nomos_c0.appraisal_definition_v1 import C0AppraisalDefinitions
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib


def _definition():
    return {
        "name": "response",
        "formals": {"score": "int"},
        "entries": ["fallback", "preferred"],
        "fallback_entry": "fallback",
        "tie_order": ["preferred", "fallback"],
        "rules": [
            {"entry": "fallback", "mode": "default"},
            {"entry": "preferred", "mode": "score", "value": {"arg": "score"}},
        ],
    }


def _binding():
    return {
        "name": "prefer_alt",
        "seat": "receiver",
        "definition": {"ref": "response", "args": {"score": 10}},
        "entries": {"fallback": "confirm", "preferred": "confirm_alt"},
    }


def _world():
    lib, ports, source, assets = _inputs()
    lib["appraisal_definitions"] = [_definition()]
    source["appraisal_profiles"] = [_binding()]
    return lib, ports, source, assets


def test_binding_reaches_compiled_control_and_real_k0_without_runtime_template_evaluation(
    monkeypatch,
):
    lib, ports, source, assets = _world()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    program = _compile(lib, ports, source)
    assert program.appraisal_profiles[0].fallback_entry == "confirm"
    assert program.appraisal_profiles[0].tie_order == ("confirm_alt", "confirm")
    monkeypatch.setattr(
        C0AppraisalDefinitions, "bind", lambda *a, **k: pytest.fail("Run rebound a template")
    )
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    session.submit("sender", offer.entry, dict(offer.payload))
    frame = session.continue_form("sender")
    assert frame.finished and frame.outcome == "delivered"
    assert session.appraisal_history()[0].proposal.chosen.entry == "confirm_alt"
    assert (
        session._runtime.occurrence_history()[-1].source
        == dict(program.actions)["confirm_alt"].source_key
    )


def test_only_changing_scalar_argument_changes_selection_not_world_permission():
    chosen = []
    for score in (0, 10):
        lib, ports, source, assets = _world()
        lib["appraisal_definitions"][0]["tie_order"] = ["fallback", "preferred"]
        source["appraisal_profiles"][0]["definition"]["args"]["score"] = score
        assets["controllers"] = [
            {"seat": "sender", "mode": "human_prompt"},
            {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
        ]
        program = _compile(lib, ports, source)
        session = program.start(assets)
        offer = session.form_frame("sender").offers[0]
        session.submit("sender", offer.entry, dict(offer.payload))
        session.continue_form("sender")
        proposal = session.appraisal_history()[0].proposal
        assert {candidate.offer.entry for candidate in proposal.candidates} == {
            "confirm",
            "confirm_alt",
        }
        chosen.append(proposal.chosen.entry)
        assert (
            session._runtime.occurrence_history()[-1].source
            == dict(program.actions)[proposal.chosen.entry].source_key
        )
    assert chosen == ["confirm", "confirm_alt"]


@pytest.mark.parametrize(
    "defect",
    ["missing_formal", "unused_formal", "duplicate", "bad_tie", "bad_fallback", "bad_slots"],
)
def test_definition_signature_rejects_unclosed_or_ambiguous_declarations(defect):
    lib, _, _, _ = _world()
    definition = lib["appraisal_definitions"][0]
    if defect == "missing_formal":
        definition["formals"] = {}
    elif defect == "unused_formal":
        definition["formals"]["unused"] = "str"
    elif defect == "duplicate":
        lib["appraisal_definitions"].append(deepcopy(definition))
    elif defect == "bad_tie":
        definition["tie_order"] = ["preferred", "preferred"]
    elif defect == "bad_fallback":
        definition["fallback_entry"] = "preferred"
    else:
        definition["entries"].append("fallback")
    with pytest.raises(C0LawError):
        check_nominal_lib(lib)


@pytest.mark.parametrize(
    "defect",
    [
        "unknown",
        "missing_arg",
        "extra_arg",
        "bool_arg",
        "negative_arg",
        "expression_arg",
        "missing_slot",
        "extra_slot",
        "aliased_slot",
        "foreign_action",
        "foreign_seat",
        "incomplete_seat",
        "extra_field",
        "duplicate_profile",
    ],
)
def test_binding_rejects_bad_arguments_action_maps_and_coverage(defect):
    lib, ports, source, _ = _world()
    binding = source["appraisal_profiles"][0]
    if defect == "unknown":
        binding["definition"]["ref"] = "absent"
    elif defect == "missing_arg":
        binding["definition"]["args"] = {}
    elif defect == "extra_arg":
        binding["definition"]["args"]["other"] = 1
    elif defect.endswith("_arg"):
        binding["definition"]["args"]["score"] = {
            "bool_arg": True,
            "negative_arg": -1,
            "expression_arg": {"ref": "actor.name"},
        }[defect]
    elif defect == "missing_slot":
        del binding["entries"]["preferred"]
    elif defect == "extra_slot":
        binding["entries"]["extra"] = "dispatch"
    elif defect == "aliased_slot":
        binding["entries"]["preferred"] = "confirm"
    elif defect == "foreign_action":
        binding["entries"]["preferred"] = "dispatch"
    elif defect == "foreign_seat":
        binding["seat"] = "sender"
    elif defect == "incomplete_seat":
        source["seats"][1]["entries"].append("dispatch")
    elif defect == "extra_field":
        binding["rules"] = []
    else:
        source["appraisal_profiles"].append(deepcopy(binding))
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "value", [{"ref": "scene.parcel.id"}, {"ref": "actor.secret"}, {"ref": "payload.absent"}, True]
)
def test_definition_cannot_bypass_actual_seat_read_permissions_or_score_type(value):
    lib, ports, source, _ = _world()
    definition = lib["appraisal_definitions"][0]
    definition["formals"] = {}
    definition["rules"][1]["value"] = value
    source["appraisal_profiles"][0]["definition"]["args"] = {}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def _family_inputs():
    lib, ports, source, assets = _family_world({"actor": {"from_trigger": "actor"}})
    alternate = deepcopy(source["actions"][0])
    alternate.update(family="alternate", source_prefix="test.alternate")
    source["actions"].append(alternate)
    seats = source["seats"][0]
    seats["names"] = {"maker": "First", "other": "Second"}
    seats["entries"].append("alternate")
    seats["offers"][0]["visible_when"] = {"all": [{"ref": "tool.visible"}, {"ref": "tool.ready"}]}
    extra_offer = deepcopy(seats["offers"][0])
    extra_offer["entry_family"] = "alternate"
    seats["offers"].append(extra_offer)
    source["temporal"] = {
        "mechanism": "action_value_event_jump",
        "order": [],
        "max_pending": 0,
        "periodic": [],
    }
    source["due_events"] = []
    source["game_form"] = {
        "mode": "action_value_event_jump",
        "end_at": None,
        "max_same_time_actions": 8,
        "seats": [
            {
                "seat": name,
                "tempo": 1,
                "eligible": True,
                "costs": {f"{entry}_{actor}": 1 for entry in ("enable", "alternate")},
            }
            for actor, name in seats["names"].items()
        ],
    }
    definition = _definition()
    definition["rules"][1]["value"] = {
        "if": {
            "when": {"eq": [{"ref": "actor.name"}, {"arg": "focus"}]},
            "then": {"arg": "score"},
            "else": 0,
        }
    }
    definition["formals"]["focus"] = "str"
    definition["tie_order"] = ["fallback", "preferred"]
    lib["appraisal_definitions"] = [definition]
    source["appraisal_profiles"] = [
        {
            "appraisal_family": "makers",
            "profiles": {"First": "first_policy", "Second": "second_policy"},
            "definition": {"ref": "response", "args": {"score": 10, "focus": "maker"}},
            "entries": {"fallback": "enable", "preferred": "alternate"},
        }
    ]
    assets["time"] = 0
    assets["opening"]["maker"]["known"] = [{"name": "a"}]
    assets["opening"]["other"]["known"] = [{"name": "b"}]
    assets["action_value_openings"] = [
        {"seat": name, "debt": 0, "tie_priority": index}
        for index, name in enumerate(seats["names"].values())
    ]
    assets["controllers"] = [
        {"seat": seat, "mode": "finite_appraisal", "profile": profile}
        for seat, profile in source["appraisal_profiles"][0]["profiles"].items()
    ]
    return lib, ports, source, assets


def test_family_scores_each_actual_actor_and_keeps_distinct_k0_sources():
    lib, ports, source, assets = _family_inputs()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    for seat, expected in (("First", "alternate_maker"), ("Second", "enable_other")):
        assert session._runtime.continue_action_value().seat == seat
        proposal = session.propose_appraisal(seat)
        assert proposal.chosen.entry == expected
        result = session.commit_appraisal(proposal)
        assert isinstance(result, K0Published)
        assert result.occurrences[0].source == dict(program.actions)[expected].source_key
        assert proposal.profile == ("first_policy" if seat == "First" else "second_policy")
    assert dict(session.author_snapshot().owners)["other"].notice_ref is not None
    assert dict(session.author_snapshot().owners)["maker"].notice_ref is None


@pytest.mark.parametrize("defect", ["domain", "seat", "profile", "action", "missing", "extra"])
def test_family_rejects_foreign_incomplete_or_aliased_bindings(defect):
    lib, ports, source, _ = _family_inputs()
    family = source["appraisal_profiles"][0]
    if defect == "domain":
        family["appraisal_family"] = "recipients"
    elif defect == "seat":
        family["profiles"] = {"maker": "first_policy", "Second": "second_policy"}
    elif defect == "profile":
        family["profiles"]["Second"] = "first_policy"
    elif defect == "action":
        family["entries"]["preferred"] = "missing"
    elif defect == "missing":
        del family["profiles"]["Second"]
    else:
        family["profiles"]["Foreign"] = "other_policy"
    with pytest.raises(C0LawError, match="appraisal family"):
        _compile(lib, ports, source)


def test_score_origins_include_definition_binding_entry_map_and_family_actor():
    lib, ports, source, _ = _family_inputs()
    documents = tuple(
        _document(raw, f"policy.{part}.yaml")
        for raw, part in zip((lib, ports, source), ("lib", "ports", "source"), strict=True)
    )
    program = _compile_documents(documents)
    for profile in program.appraisal_profiles:
        value = profile.rules[1].value
        expression = value._tree["outputs"]["score"]
        frames = expression.provenance
        by_kind = {frame.kind: frame for frame in frames}
        assert (
            by_kind["appraisal_rule"].span
            == documents[0].spans["appraisal_definitions", 0, "rules", 1, "value"]
        )
        assert (
            by_kind["appraisal_binding"].span
            == documents[2].spans["appraisal_profiles", 0, "definition"]
        )
        assert (
            by_kind["appraisal_entries"].span
            == documents[2].spans["appraisal_profiles", 0, "entries"]
        )
        assert dict(by_kind["actor_instance"].arguments)["seat"] == profile.seat
        assert (
            by_kind["appraisal_definition"].span == documents[0].spans["appraisal_definitions", 0]
        )
