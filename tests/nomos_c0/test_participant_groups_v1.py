"""Finite participant signatures reuse checked ports, not runtime authority."""

from copy import deepcopy

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_multi_participant_action_v0 import _compile, _owners, _world

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.participant_group_v1 import expand_participant_groups


def grouped():
    lib, ports, source, assets = _world()
    original = deepcopy(ports)
    ports["participant_groups"] = [
        dict(
            name="recipients",
            members=["victim"],
            selector="closed_domain",
            state="Person",
            read=["enabled"],
            effects={"enabled": "enabled"},
        )
    ]
    action = ports["actions"][0]
    action["participant_groups"] = ["recipients"]
    action["participants"] = action["participants"][:1]
    del action["effects"]["victim"]
    action["value"]["read"].remove("victim.enabled")
    action["value"]["write_paths"].remove("victim.enabled")
    return lib, ports, source, assets, original


def test_expansion_preserves_signature_and_does_not_mutate_author_input():
    _, ports, _, _, original = grouped()
    before = deepcopy(ports)
    assert expand_participant_groups(ports) == original
    assert ports == before


def test_grouped_write_reaches_only_selected_actor_and_object():
    lib, ports, source, assets, _ = grouped()
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    outcome = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(outcome, K0Published)
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False
    assert [row.name for row in outcome.occurrences[0].selected_owners] == ["tool", "victim"]


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "duplicate",
        "collision",
        "target",
        "bad_read",
        "bad_state",
        "bad_effect",
        "missing_write_paths",
    ],
)
def test_invalid_groups_are_finite_compile_errors(fault):
    lib, ports, source, _, _ = grouped()
    action = ports["actions"][0]
    group = ports["participant_groups"][0]
    if fault == "unknown":
        action["participant_groups"] = ["absent"]
    elif fault == "duplicate":
        action["participant_groups"] *= 2
    elif fault == "collision":
        group["members"] = ["tool"]
    elif fault == "target":
        action["target"] = {}
    elif fault == "bad_read":
        group["read"] = ["absent"]
    elif fault == "bad_state":
        group["state"] = "Absent"
    elif fault == "bad_effect":
        group["effects"] = {"absent": "enabled"}
    elif fault == "missing_write_paths":
        del action["value"]["write_paths"]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_definition_can_be_reused_without_sharing_mutable_effects():
    _, ports, _, _, _ = grouped()
    ports["actions"].append(deepcopy(ports["actions"][0]))
    ports["actions"][1]["symbol"] = "another"
    expanded = expand_participant_groups(ports)
    expanded["actions"][0]["effects"]["victim"]["enabled"] = "changed"
    assert expanded["actions"][1]["effects"]["victim"] == {"enabled": "enabled"}


def test_readonly_group_does_not_grant_law_write_permission():
    lib, ports, source, _, _ = grouped()
    ports["participant_groups"][0]["effects"] = {}
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_multiple_members_expand_to_separate_exact_ports():
    _, ports, _, _, _ = grouped()
    ports["participant_groups"][0]["members"] = ["first", "second"]
    expanded = expand_participant_groups(ports)["actions"][0]
    assert [row["name"] for row in expanded["participants"]] == ["first", "second", "tool"]
    assert {"first.enabled", "second.enabled"} <= set(expanded["value"]["read"])
    assert expanded["effects"]["first"] == expanded["effects"]["second"]
    assert expanded["effects"]["first"] is not expanded["effects"]["second"]
