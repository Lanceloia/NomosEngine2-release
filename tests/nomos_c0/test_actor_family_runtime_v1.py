"""Typed instance families reach the ordinary backend and actual K0 owners."""

from copy import deepcopy

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _compile, _world

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError


def _family_world(recipient):
    lib, ports, source, assets = deepcopy(_world())
    person = next(row for row in lib["records"] if row["name"] == "Person")
    person["fields"].extend(
        {"name": name, "type": {"optional": "occurrence_ref"}}
        for name in ("notice_ref", "trigger_ref")
    )
    maker = deepcopy(next(row for row in lib["owners"] if row["symbol"] == "maker"))
    maker.update(symbol="other", key="c0.participants.other")
    lib["owners"].append(maker)
    source["owners"].append("other")
    assets["opening"]["other"] = dict(assets["opening"]["maker"], name="other")
    for owner in lib["owners"]:
        if owner["state"] == "Person":
            owner["seat_read"].extend(["notice_ref", "trigger_ref"])
            assets["opening"][owner["symbol"]].update(notice_ref=None, trigger_ref=None)
    lib["lawdefs"].append(
        {
            "name": "event.notice",
            "family": "direct_actor_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {
                        "notice_ref": {"ref": "occurrence"},
                        "trigger_ref": {"ref": "trigger.occurrence"},
                    },
                }
            },
        }
    )
    ports["events"] = [
        {
            "symbol": "notice",
            "form": "direct_actor",
            "actor": "maker",
            "actor_identity_field": "name",
            "value": {
                "read": ["trigger.occurrence"],
                "fields": {},
                "write_paths": ["actor.notice_ref", "actor.trigger_ref"],
                "outputs": {"notice_ref": "actor.notice_ref", "trigger_ref": "actor.trigger_ref"},
                "construct": [],
                "collections": {},
            },
        }
    ]
    source["actor_domains"] = [
        {"name": "makers", "actor_state": "Person", "owners": ["maker", "other"]},
        {"name": "recipients", "actor_state": "Person", "owners": ["a", "b"]},
    ]
    participants = source["actions"][0]["participants"]
    source["actions"] = [
        {
            "family": "enable",
            "template": "enable",
            "domain": "makers",
            "source_prefix": "test.enable",
            "law": {"ref": "action.enable", "args": {}},
            "participants": participants,
        }
    ]
    source["events"] = [
        {
            "family": "notice",
            "template": "notice",
            "for_action_family": "enable",
            "source_prefix": "test.notice",
            "share_result": True,
            "law": {"ref": "event.notice", "args": {}},
            **recipient,
        }
    ]
    offer = source["seats"][0]["offers"][0]
    del offer["entry"]
    offer["entry_family"] = "enable"
    source["seats"] = [
        {
            "seat_family": "makers",
            "names": {"maker": "maker", "other": "other"},
            "entries": ["enable"],
            "read": ["actor.name", "actor.known", "actor.notice_ref", "actor.trigger_ref"],
            "offers": [offer],
        }
    ]
    return lib, ports, source, assets


@pytest.mark.parametrize(
    "recipient, recipients, event_count",
    [
        ({"actor": "b"}, ("b",), 1),
        ({"actor_domain": "recipients"}, ("a", "b"), 2),
        ({"actor": {"from_trigger": "actor"}}, None, 1),
    ],
)
def test_family_actions_and_events_keep_real_participants_owners_and_precise_predecessors(
    recipient, recipients, event_count
):
    lib, ports, source, assets = _family_world(recipient)
    program = _compile(lib, ports, source)
    session = program.start(assets)
    for actor, label in (("maker", "Use one on a"), ("other", "Use two on b")):
        offer = next(item for item in session.offers(actor) if item.label == label)
        assert offer.entry == f"enable_{actor}"
        result = session.submit(actor, offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        assert len(result.occurrences) == 1 + event_count
        action, *events = result.occurrences
        assert action.source.value == f"test.enable-{actor}"
        assert [item.name for item in action.selected_owners] == ["tool", "victim"]
        owners = dict(session.author_snapshot().owners)
        expected = recipients or (actor,)
        assert {owners[name].notice_ref for name in expected} == {
            item.occurrence for item in events
        }
        assert all(owners[name].trigger_ref == action.occurrence for name in expected)
        assert all(item.formation_basis.predecessor == action.occurrence for item in events)
        assert all(item.semantic_envelope.trigger == action.occurrence for item in events)
        assert "b.notice_ref" not in dict(session.read(actor).fields)
        before = session.author_snapshot()
        with pytest.raises(C0BindingError, match="not a current seat offer"):
            session.submit(actor, offer.entry, dict(offer.payload))
        compiled = dict(program.actions)[offer.entry]
        assert isinstance(
            session._runtime.settle(
                _K0InMemoryActionAttempt(
                    compiled.source_key, compiled.payload_type(actor, **dict(offer.payload))
                )
            ),
            K0NotAdmitted,
        )
        assert session.author_snapshot() == before
    owners = dict(session.author_snapshot().owners)
    assert owners["a"].enabled and owners["b"].enabled
    assert not owners["maker"].enabled and not owners["other"].enabled
    if recipients:
        assert owners["maker"].notice_ref is None and owners["other"].notice_ref is None


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda lib, ports, source: source["actions"][0]["participants"]["victim"].update(
                actors=["foreign"]
            ),
            "participant",
        ),
        (
            lambda lib, ports, source: source["events"][0].update(actor="scene"),
            "recipient is foreign",
        ),
        (
            lambda lib, ports, source: ports["events"][0]["value"].update(write_paths=[]),
            "write",
        ),
        (
            lambda lib, ports, source: source["seats"][0]["offers"][0].update(unknown=True),
            "missing or unknown",
        ),
    ],
)
def test_expansion_does_not_bypass_ordinary_binding_and_offer_checks(change, message):
    lib, ports, source, _ = _family_world({"actor": "b"})
    change(lib, ports, source)
    with pytest.raises(C0LawError, match=message):
        _compile(lib, ports, source)


def test_family_binding_does_not_force_a_false_recipient_event():
    lib, ports, source, assets = _family_world({"actor_domain": "recipients"})
    lib["lawdefs"][-1]["body"]["law"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    offer = next(item for item in session.offers("maker") if item.label == "Use one on a")
    result = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published) and len(result.occurrences) == 1
    owners = dict(session.author_snapshot().owners)
    assert owners["a"].enabled
    assert all(owners[name].notice_ref is None for name in ("maker", "other", "a", "b"))


def test_two_families_without_a_proof_cannot_bypass_same_trigger_write_checks():
    lib, ports, source, assets = _family_world({"actor": "b"})
    other = deepcopy(source["events"][0])
    other.update(family="other_notice", source_prefix="test.other_notice")
    source["events"].append(other)
    with pytest.raises(C0LawError, match="same-trigger owner fanout.*proof"):
        _compile(lib, ports, source)
