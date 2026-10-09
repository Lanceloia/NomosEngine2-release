"""Actor domain writes use checked member endpoints, not Source mappings."""

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_action_actor_domain_effects_v1 import documents as action_documents
from test_action_actor_domain_effects_v1 import settle
from test_actor_domain_due_v1 import domain_documents
from test_actor_formation_v1 import submit_first
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError


def documents(due):
    lib, ports, source, assets = domain_documents() if due else action_documents()
    collection = "due_events" if due else "actions"
    owner = source[collection][0 if due else -1]
    port = ports[collection][0 if due else -1]["actor_domains"][0]
    return lib, ports, source, assets, owner, port


@pytest.mark.parametrize("due", [False, True])
@pytest.mark.parametrize("mapping", [None, {}, {"count": "count"}])
def test_source_rejects_retired_domain_effect_even_when_matching(due, mapping):
    lib, ports, source, _, owner, _ = documents(due)
    owner["actor_domain_effects"][0]["effect"] = mapping
    with pytest.raises(C0LawError, match="missing or unknown"):
        _compile(lib, ports, source)


@pytest.mark.parametrize("due", [False, True])
def test_result_alias_changes_without_changing_member_destination(due):
    lib, ports, source, assets, owner, port = documents(due)
    port["value"]["outputs"] = {"after": "actor.count"}
    name = owner["actor_domain_effects"][0]["law"]["ref"]
    law = next(item for item in source["lawdefs"] if item["name"] == name)
    body = law["body"]["law" if due else "value"]
    body["outputs"]["after"] = body["outputs"].pop("count")
    session = _compile(lib, ports, source).start(assets)
    if due:
        submit_first(session)
        session.continue_form("seat_0")
    else:
        assert isinstance(settle(session, "count_0"), K0Published)
        assert isinstance(settle(session, "blast"), K0Published)
    assert [row.current_state.count for row in session.author_actor_instances()] == (
        [1, 1] if due else [3]
    )


@pytest.mark.parametrize("due", [False, True])
@pytest.mark.parametrize("fault", ["type_only", "permission", "duplicate", "wrong_owner"])
def test_member_destination_cannot_be_guessed_or_widen_permissions(due, fault):
    lib, ports, source, _, _, port = documents(due)
    value = port["value"]
    if fault == "type_only":
        value["outputs"]["count"] = "int"
    elif fault == "permission":
        value["write_paths"] = []
    elif fault == "duplicate":
        value["outputs"]["other"] = "actor.count"
    else:
        value["outputs"]["count"] = "scene.signal" if due else "initiator.count"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
