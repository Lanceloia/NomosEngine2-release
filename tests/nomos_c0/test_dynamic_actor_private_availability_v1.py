"""Actual self Actors use private static selectors and checked readonly availability."""

from copy import deepcopy
from dataclasses import replace

import pytest
from authored_counter_v1 import _record, _value
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_actor_formation_v1 import documents as birth_documents
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.program_runtime_v1 import _ProjectionReads


def documents(*, automated=False):
    lib, ports, source, assets = birth_documents()
    sprite = next(row for row in lib["records"] if row["name"] == "Sprite")
    sprite["fields"] += [
        {"name": "site", "type": {"int": [0, 100]}},
        {"name": "sighting", "type": {"optional": {"int": [0, 100]}}},
    ]
    lib["actor_kinds"][0]["seat_read"] += ["site", "sighting"]
    initial = source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"]["record"]["fields"]
    initial.update(site=0, sighting=None)
    assets["opening"]["actor_1"]["name"] = "actor_1"
    source["game_form"]["seats"][0]["eligible"] = "actor.count < 2"
    source["game_form"]["seats"][1]["eligible"] = True
    source["game_form"]["end_at"] = 80
    assets["action_value_openings"][1]["debt"] = 42
    lib["records"].append(
        _record("ObserveAttempt", {"actor": "actor_ref", "anchor": {"str": [1, 64]}})
    )
    ports["actions"] = ports["actions"][:2]
    source["actions"] = source["actions"][:2]
    for entry in ("observe", "signal"):
        read = [
            "actor.awake",
            "actor.site",
            "actor.sighting",
            "actor.count",
            "anchor.count",
            "payload.anchor",
        ]
        effect = {"sighting": "sighting"} if entry == "observe" else {"count": "count"}
        ports["actions"].append(
            {
                "symbol": entry,
                "actor": {"self": "sprite"},
                "payload": "ObserveAttempt",
                "envelope": "Envelope",
                "actor_identity_field": None,
                "payload_actor_field": "actor",
                "participants": [
                    {
                        "name": "anchor",
                        "selector": "closed_domain",
                        "state": "Actor",
                        "payload_field": "anchor",
                        "write": False,
                    }
                ],
                "effects": {"scene": {}, "actor": effect, "anchor": {}},
                "envelope_fields": {"action": "action"},
                "schedule": None,
                "value": _value(read, [f"actor.{field}" for field in effect]),
            }
        )
        outputs = (
            {
                "sighting": {
                    "if": {
                        "when": "actor.site == anchor.count",
                        "then": {"ref": "anchor.count"},
                        "else": None,
                    }
                }
            }
            if entry == "observe"
            else {"count": {"add": [{"ref": "actor.count"}, 1]}}
        )
        source["lawdefs"].append(
            {
                "name": entry,
                "family": "action",
                "formals": {},
                "body": {
                    "value": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": "actor.awake"
                        if entry == "observe"
                        else (
                            "actor.awake and actor.sighting == actor.site "
                            "and actor.site == anchor.count"
                        ),
                        "outputs": {**outputs, "action": {"ref": "occurrence"}},
                    }
                },
            }
        )
        source["actions"].append(
            {
                "name": entry,
                "template": entry,
                "actor": {"self": "sprite"},
                "source_key": f"c0.neutral.{entry}",
                "event_type": f"c0.neutral.{entry}.action",
                "law": {"ref": entry, "args": {}},
                "participants": {"anchor": {"actors": ["actor_1"]}},
            }
        )
    ports["candidate_inputs"] = [
        {
            "symbol": "signal_available",
            "action": "signal",
            "read": ["actor.site", "actor.sighting", "anchor.count", "payload.anchor"],
            "fields": {},
        }
    ]
    template = source["actor_templates"][0]
    template.update(
        entries=["observe", "signal"],
        read=["actor.count", "actor.awake", "actor.site", "actor.sighting"],
        offers=[
            {
                "entry": entry,
                "label": entry.title(),
                "when": "actor.awake" if entry == "observe" else "actor.sighting == actor.site",
                "payload": {},
                "for_each_participants": {"anchor": {"fixed_actor": "actor_1", "private": True}},
                **(
                    {
                        "availability": {
                            "ref": "signal_available",
                            "when": "actor.site == anchor.count and payload.anchor == 'actor_1'",
                        }
                    }
                    if entry == "signal"
                    else {}
                ),
            }
            for entry in ("observe", "signal")
        ],
        eligible="actor.awake",
        costs={"observe": 3, "signal": 3},
        first_debt=20,
    )
    if automated:
        template["controller"] = {
            "mode": "finite_appraisal",
            "profile": {
                "name": "scout",
                "seat": "sprite",
                "fallback_entry": "observe",
                "tie_order": ["signal", "observe"],
                "rules": [
                    {"entry": "signal", "mode": "score", "value": 10},
                    {"entry": "observe", "mode": "default"},
                ],
            },
        }
    return lib, ports, source, assets


def born_session(program, assets):
    session = program.start(assets)
    for _ in range(2):
        offer = session.offers("seat_0")[0]
        assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
        if len(session._runtime.actors()) < 2:
            session.continue_form("seat_0")
    session._runtime.continue_action_value()
    assert session._runtime.action_opportunity().seat == session._runtime.actors()[0].seat
    return session


def settle_offer(session, binding, entry):
    offer = next(row for row in session.offers(binding.seat) if row.entry == entry)
    attempt = session._dynamic_attempt(binding, offer, _ProjectionReads(session._runtime))
    return session._runtime.settle(
        _K0InMemoryActionAttempt(dict(session.program.actions)[entry].source_key, attempt)
    )


def test_real_observe_motion_filters_stale_signal_and_paid_observe_clears_only_self():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session = born_session(program, assets)
    left, right = session._runtime.actors()
    assert left.formed_by is not None and right.formed_by is not None
    assert left.actor != right.actor and left.owner != right.owner
    before = session.author_snapshot()
    assert [offer.entry for offer in session.offers(left.seat)] == ["observe"]
    assert session.author_snapshot() == before
    assert isinstance(settle_offer(session, left, "observe"), K0Published)
    assert session._runtime.read_actor(left.actor).view.sighting == 0
    assert session._runtime.read_actor(right.actor).view.sighting is None
    assert [offer.entry for offer in session.offers(left.seat)] == ["observe", "signal"]
    signal = next(row for row in session.offers(left.seat) if row.entry == "signal")
    session.continue_form(left.seat)
    assert session._runtime.action_opportunity().seat == "seat_1"
    action = dict(program.actions)["count_1"]
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key, action.payload_type(actor="actor_1", target="actor_1")
            )
        ),
        K0Published,
    )
    session.continue_form("seat_1")
    assert session._runtime.action_opportunity().seat == left.seat
    assert session._runtime.read_actor(left.actor).view.sighting == 0
    assert [offer.entry for offer in session.offers(left.seat)] == ["observe"]
    before = session.author_snapshot()
    for _ in range(2):
        assert session.offers(left.seat) == session.offers(left.seat)
    assert session.author_snapshot() == before
    assert isinstance(settle_offer(session, left, "observe"), K0Published)
    assert session._runtime.read_actor(left.actor).view.sighting is None
    assert session._runtime.read_actor(right.actor).view.sighting is None
    assert dict(signal.payload) == {}
    records = session._runtime.occurrence_history()
    actual = next(row for row in records if row.source.value == "c0.neutral.observe")
    assert actual.participants.actor == left.actor
    assert actual.selected_owners[0].selector == "actor_1"
    assert actual.selected_owners[0].owner != left.owner
    assert (
        next(row for row in session._runtime.action_value_state() if row.seat == left.seat).debt
        >= 3
    )


def move_anchor(session, binding):
    session.continue_form(binding.seat)
    assert session._runtime.action_opportunity().seat == "seat_1"
    assert isinstance(session.submit("seat_1", "count_1", {"target": "actor_1"}), K0Published)
    session._runtime.continue_action_value()
    assert session._runtime.action_opportunity().seat == binding.seat


def test_independent_bind_uses_new_nominal_carriers_without_frontend(monkeypatch):
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    layouts = program.world_layout, _layout(program)
    assert layouts[0].owners.record_layout is not layouts[1].owners.record_layout
    _block_frontend(monkeypatch)
    for layout in layouts:
        session = born_session(bind_program(program.program_ir, layout), deepcopy(assets))
        left, right = session._runtime.actors()
        assert dict(session.offers(left.seat)[0].payload) == {}
        assert isinstance(session.submit(left.seat, "observe", {}), K0Published)
        assert session._runtime.read_actor(left.actor).view.sighting == 0
        assert session._runtime.read_actor(right.actor).view.sighting is None
        move_anchor(session, left)
        assert [offer.entry for offer in session.offers(left.seat)] == ["observe"]
        with pytest.raises(C0BindingError, match="current seat offer"):
            session.submit(left.seat, "signal", {})


@pytest.mark.parametrize("injection", ["private", "self", "foreign_binding"])
def test_guessed_private_selector_and_cross_instance_self_are_rejected(injection):
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session = born_session(program, assets)
    left, right = session._runtime.actors()
    offer = session.offers(left.seat)[0]
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    if injection == "foreign_binding":
        other = born_session(program, assets)._runtime.actors()[0]
        with pytest.raises(C0BindingError, match="actual registered self"):
            session._dynamic_attempt(other, offer, _ProjectionReads(session._runtime))
    else:
        payload = {"anchor": "actor_1"} if injection == "private" else {"actor": right.actor}
        with pytest.raises(C0BindingError, match="current seat offer"):
            session.submit(left.seat, "observe", payload)
        with pytest.raises(C0BindingError, match="public payload partition"):
            session._dynamic_attempt(
                left,
                replace(offer, payload=tuple(payload.items())),
                _ProjectionReads(session._runtime),
            )
    assert session.author_snapshot() == before and session._runtime.occurrence_history() == history


def test_foreign_actual_ref_is_not_a_candidate_basis_or_world_action():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session = born_session(program, assets)
    other = born_session(program, assets)._runtime.actors()[0]
    action = dict(program.actions)["observe"]
    payload = action.payload_type(actor=other.actor, anchor="actor_1")
    left = session._runtime.actors()[0]
    before = session.author_snapshot()
    assert (
        session._selected_action_roots(
            action,
            session._runtime.read_actor(left.actor).view,
            payload,
            _ProjectionReads(session._runtime),
        )
        is None
    )
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload)), K0NotAdmitted
    )
    assert session.author_snapshot() == before


def test_world_guard_is_independent_of_positive_availability():
    lib, ports, source, assets = documents()
    offer = source["actor_templates"][0]["offers"][1]
    offer.update(when=True, availability={"ref": "signal_available", "when": True})
    next(row for row in source["lawdefs"] if row["name"] == "signal")["body"]["value"]["guard"] = (
        False
    )
    session = born_session(_compile(lib, ports, source), assets)
    left = session._runtime.actors()[0]
    assert [row.entry for row in session.offers(left.seat)] == ["observe", "signal"]
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    assert isinstance(session.submit(left.seat, "signal", {}), K0NotAdmitted)
    assert session.author_snapshot() == before and session._runtime.occurrence_history() == history


def test_same_entry_offers_keep_their_own_availability_before_deduplication():
    lib, ports, source, assets = documents()
    offers = source["actor_templates"][0]["offers"]
    offers[1]["when"] = True
    denied = deepcopy(offers[1])
    denied["availability"]["when"] = False
    allowed = deepcopy(denied)
    allowed["availability"]["when"] = True
    offers[1:] = [denied, allowed]
    session = born_session(_compile(lib, ports, source), assets)
    left = session._runtime.actors()[0]
    assert [row.entry for row in session.offers(left.seat)] == ["observe", "signal"]


def test_complete_private_and_scalar_payload_is_shared_by_filter_score_and_submission():
    lib, ports, source, assets = documents(automated=True)
    attempt = next(row for row in lib["records"] if row["name"] == "ObserveAttempt")
    attempt["fields"].append({"name": "allowed", "type": "bool"})
    for offer in source["actor_templates"][0]["offers"]:
        offer["payload"] = {"allowed": True}
    for port in ports["actions"][-2:]:
        port["value"]["read"].append("payload.allowed")
    ports["candidate_inputs"][0]["read"].append("payload.allowed")
    offer = source["actor_templates"][0]["offers"][1]
    offer["availability"]["when"] = "payload.allowed and payload.anchor == 'actor_1'"
    offer["when"] = True
    rule = source["actor_templates"][0]["controller"]["profile"]["rules"][0]
    rule["value"] = {
        "if": {"when": "payload.allowed and payload.anchor == 'actor_1'", "then": 10, "else": 0}
    }
    law = next(row for row in source["lawdefs"] if row["name"] == "signal")
    law["body"]["value"]["guard"] = "actor.awake and payload.allowed"
    session = born_session(_compile(lib, ports, source), assets)
    left = session._runtime.actors()[0]
    proposal = session.propose_appraisal(left.seat)
    assert dict(proposal.chosen.payload) == {"allowed": True}
    assert proposal.chosen.entry == "signal"
    assert isinstance(session.commit_appraisal(proposal), K0Published)
    assert session._runtime.occurrence_history()[-1].selected_owners[0].selector == "actor_1"
    assert session._runtime.read_actor(left.actor).view.count == 1


def test_dynamic_actor_recomputes_conditional_private_member_after_its_real_action():
    lib, ports, source, assets = documents()
    attempt = next(row for row in lib["records"] if row["name"] == "ObserveAttempt")
    field = next(row for row in attempt["fields"] if row["name"] == "anchor")
    field["type"] = {"optional": field["type"]}
    for port in ports["actions"][-2:]:
        port["participants"][0]["nullable"] = True
        port["value"]["read"].append("anchor")
    for offer in source["actor_templates"][0]["offers"]:
        offer["for_each_participants"]["anchor"]["when"] = "actor.count == 0"
    source["actor_templates"][0]["costs"]["observe"] = {
        "if": {"when": {"not_none": {"ref": "anchor"}}, "then": 3, "else": 4}
    }
    observe = next(row for row in source["lawdefs"] if row["name"] == "observe")
    observe["body"]["value"]["outputs"]["sighting"]["if"]["when"] = {
        "all": [{"not_none": {"ref": "anchor"}}, "actor.site == anchor.count"]
    }
    signal = next(row for row in source["lawdefs"] if row["name"] == "signal")
    signal["body"]["value"]["guard"] = {
        "all": [{"not_none": {"ref": "anchor"}}, signal["body"]["value"]["guard"]]
    }
    ports["candidate_inputs"][0]["read"].append("anchor")
    check = source["actor_templates"][0]["offers"][1]["availability"]
    check["when"] = {"all": [{"not_none": {"ref": "anchor"}}, check["when"]]}
    assets["action_value_openings"][1]["debt"] = 80
    session = born_session(_compile(lib, ports, source), assets)
    left = session._runtime.actors()[0]
    assert isinstance(settle_offer(session, left, "observe"), K0Published)
    session.continue_form(left.seat)
    while session._runtime.action_opportunity().seat != left.seat:
        opportunity = session._runtime.action_opportunity()
        other = next(row for row in session._runtime.actors() if row.seat == opportunity.seat)
        assert isinstance(settle_offer(session, other, "observe"), K0Published)
        session.continue_form(other.seat)
    assert isinstance(settle_offer(session, left, "signal"), K0Published)
    assert session._runtime.read_actor(left.actor).view.count == 1
    assert [offer.entry for offer in session.offers(left.seat)] == ["observe"]
    session.continue_form(left.seat)
    while session._runtime.action_opportunity().seat != left.seat:
        opportunity = session._runtime.action_opportunity()
        other = next(row for row in session._runtime.actors() if row.seat == opportunity.seat)
        assert isinstance(settle_offer(session, other, "observe"), K0Published)
        session.continue_form(other.seat)
    result = settle_offer(session, left, "observe")
    assert isinstance(result, K0Published)
    assert result.occurrences[0].selected_owners == ()
    assert session._runtime.read_actor(left.actor).view.sighting is None
    assert (
        next(row for row in session._runtime.action_value_state() if row.seat == left.seat).debt
        == 4
    )


def test_self_basis_is_reread_from_actual_ref_not_a_different_instances_same_carrier():
    lib, ports, source, assets = documents()
    session = born_session(_compile(lib, ports, source), assets)
    left, right = session._runtime.actors()
    assert isinstance(session.submit(left.seat, "observe", {}), K0Published)
    action = dict(session.program.actions)["signal"]
    payload = action.payload_type(actor=right.actor, anchor="actor_1")
    roots = session._selected_action_roots(
        action,
        session._runtime.read_actor(left.actor).view,
        payload,
        _ProjectionReads(session._runtime),
    )
    assert roots["actor"].sighting is None
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload)), K0NotAdmitted
    )


def test_scoring_filters_before_proposal_and_one_bounded_auto_step_clears_sighting():
    lib, ports, source, assets = documents(automated=True)
    source["game_form"]["end_at"] = 24
    session = born_session(_compile(lib, ports, source), assets)
    left, right = session._runtime.actors()
    initial = session.propose_appraisal(left.seat)
    assert initial.chosen.entry == "observe"
    assert isinstance(session.commit_appraisal(initial), K0Published)
    move_anchor(session, left)
    before = session.author_snapshot()
    proposal = session.propose_appraisal(left.seat)
    assert proposal.chosen.entry == "observe"
    assert [row.offer.entry for row in proposal.candidates] == ["observe"]
    assert session.author_snapshot() == before
    with pytest.raises(C0BindingError, match="stale or foreign"):
        session.commit_appraisal(initial)
    session.continue_form("seat_1")
    assert session._runtime.read_actor(left.actor).view.sighting is None
    assert session._runtime.read_actor(right.actor).view.sighting is None
    assert len(session.appraisal_history()) == 2
    assert session.appraisal_history()[-1].proposal.chosen.entry == "observe"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "nonsingleton",
        "wrong_member",
        "wrong_role",
        "not_private",
        "payload",
        "public_when",
        "public_payload",
        "input_read",
        "input_type",
        "input_action",
    ],
)
def test_compile_rejects_private_binding_and_read_authority_faults(fault):
    lib, ports, source, _ = documents()
    offer = source["actor_templates"][0]["offers"][1]
    fixed = offer["for_each_participants"]["anchor"]
    if fault == "missing":
        offer.pop("for_each_participants")
    elif fault == "nonsingleton":
        source["actions"][-1]["participants"]["anchor"]["actors"].append("actor_0")
    elif fault == "wrong_member":
        fixed["fixed_actor"] = "actor_0"
    elif fault == "wrong_role":
        offer["for_each_participants"] = {"other": fixed}
    elif fault == "not_private":
        fixed["private"] = False
    elif fault == "payload":
        offer["payload"]["anchor"] = "actor_1"
    elif fault == "public_when":
        offer["when"] = "anchor.count == 0"
    elif fault == "public_payload":
        offer["payload"]["anchor"] = {"ref": "anchor.count"}
    elif fault == "input_read":
        ports["candidate_inputs"][0]["read"].append("anchor.name")
    elif fault == "input_type":
        offer["availability"]["when"] = "actor_1"
    else:
        ports["candidate_inputs"][0]["action"] = "observe"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault",
    [
        "private_member",
        "private_role",
        "public_partition",
        "check_entry",
        "check_index",
        "check_read",
        "check_root",
        "public_read",
    ],
)
def test_independent_bind_rechecks_private_partition_and_exact_availability(fault):
    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    template = program.program_ir.actor_templates[0]
    offer = template.offers[1]
    if fault == "private_member":
        offer = replace(
            offer, private_actor_fields=(replace(offer.private_actor_fields[0], member="actor_0"),)
        )
    elif fault == "private_role":
        offer = replace(
            offer,
            private_actor_fields=(replace(offer.private_actor_fields[0], payload_field="other"),),
        )
    elif fault == "public_partition":
        offer = replace(offer, private_actor_fields=())
    elif fault == "public_read":
        value = offer.value.value
        changed = replace(value.ports, readable_paths=(), admission_readable_paths=())
        offer = replace(offer, value=replace(offer.value, value=replace(value, ports=changed)))
    else:
        check = offer.candidate_check
        if fault == "check_entry":
            check = replace(check, entry="observe")
        elif fault == "check_index":
            check = replace(check, index=0)
        else:
            value = check.body.value
            if fault == "check_read":
                paths = tuple(path for path in value.ports.readable_paths if path != "anchor.count")
                changed = replace(value.ports, readable_paths=paths, admission_readable_paths=paths)
            else:
                roots = dict(value.ports.roots)
                roots["anchor"] = roots["actor"]
                changed = replace(value.ports, roots=tuple(roots.items()))
            check = replace(check, body=replace(check.body, value=replace(value, ports=changed)))
        offer = replace(offer, candidate_check=check)
    ir = replace(
        program.program_ir, actor_templates=(replace(template, offers=(template.offers[0], offer)),)
    )
    with pytest.raises(C0LawError):
        bind_program(ir, _layout(program))
