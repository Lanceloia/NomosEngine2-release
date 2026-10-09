"""Finite authored Actor formation uses one checked Program and real K0 identities."""

from copy import deepcopy

import pytest
from authored_counter_v1 import _record, _value, action_value_documents
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError


def documents(*, opening=(), controller=None, path="action"):
    lib, ports, source, assets = action_value_documents()
    lib["records"] += [
        _record("Sprite", {"count": {"int": [0, 100]}, "awake": "bool"}),
        _record("SelfAttempt", {"actor": "actor_ref"}),
    ]
    lib["actor_kinds"] = [
        {
            "symbol": "sprite",
            "state": "Sprite",
            "version": "1",
            "max_instances": 4,
            "seat_read": ["count", "awake"],
        }
    ]
    ports["actions"].append(
        {
            "symbol": "step",
            "actor": {"self": "sprite"},
            "payload": "SelfAttempt",
            "envelope": "Envelope",
            "actor_identity_field": None,
            "payload_actor_field": "actor",
            "effects": {"scene": {}, "actor": {"count": "count"}},
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": _value(["actor.count", "actor.awake"], ["actor.count"]),
        }
    )
    source["lawdefs"].append(
        {
            "name": "step",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "actor.awake and actor.count < 2",
                    "outputs": {
                        "count": {"add": [{"ref": "actor.count"}, 1]},
                        "action": {"ref": "occurrence"},
                    },
                }
            },
        }
    )
    source["actions"].append(
        {
            "name": "step",
            "template": "step",
            "actor": {"self": "sprite"},
            "source_key": "c0.test.sprite.step",
            "event_type": "c0.test.sprite.step.action",
            "law": {"ref": "step", "args": {}},
        }
    )
    source["actor_templates"] = [
        {
            "kind": "sprite",
            "entries": ["step"],
            "read": ["actor.count", "actor.awake"],
            "offers": [
                {
                    "entry": "step",
                    "label": "Step",
                    "when": "actor.awake and actor.count < 2",
                    "payload": {},
                }
            ],
            "tempo": 1,
            "eligible": "actor.awake and actor.count < 2",
            "costs": {"step": 3},
            "first_debt": 2,
            "tie_priority": 2,
            "controller": controller or {"mode": "human_prompt"},
        }
    ]
    source["game_form"]["seats"][1]["eligible"] = False
    assets["action_value_openings"][0]["debt"] = 0
    assets["opening_actors"] = list(opening)
    product = {"kind": "sprite", "cardinality": "one", "initial_output": "newborn"}
    initial = {"record": {"type": "Sprite", "fields": {"count": 0, "awake": True}}}
    if path == "action":
        ports["actions"][0]["value"].update(
            outputs={"newborn": "Sprite"},
            construct=["Sprite"],
        )
        source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"] = initial
        source["actions"][0]["actor_product"] = product
        # The other fixed Action does not consume the formation output.
        source["actions"][1]["law"] = {"ref": "count_plain", "args": {"step": 1}}
        plain = deepcopy(source["lawdefs"][0])
        plain["name"] = "count_plain"
        del plain["body"]["value"]["outputs"]["newborn"]
        source["lawdefs"].append(plain)
    elif path == "due":
        ports["due_events"][0]["value"].update(
            outputs={"signal": "scene.signal", "newborn": "Sprite"},
            construct=["Sprite"],
        )
        source["lawdefs"][1]["body"]["law"]["outputs"]["newborn"] = initial
        source["due_events"][0]["actor_product"] = product
        source["game_form"]["seats"][0]["eligible"] = False
    else:
        ports["events"].append(
            {
                "symbol": "birth",
                "form": "direct_scene",
                "actor": None,
                "actor_identity_field": None,
                "value": _value(["scene.marker"], [], {"newborn": "Sprite"}, ["Sprite"]),
            }
        )
        source["lawdefs"].append(
            {
                "name": "birth",
                "family": "direct_event",
                "formals": {},
                "body": {
                    "law": {
                        "schema": "c0.value.v1",
                        "bindings": [],
                        "guard": True,
                        "outputs": {"newborn": initial},
                    }
                },
            }
        )
        source["events"].append(
            {
                "name": "birth",
                "template": "birth",
                "trigger_action": "count_0",
                "source_key": "c0.test.sprite.birth",
                "event_type": "c0.test.sprite.birth.event",
                "causal_key": "c0.test.sprite.birth.law",
                "actor_product": product,
                "law": {"ref": "birth", "args": {}},
            }
        )
    return lib, ports, source, assets


def submit_first(session):
    offer = session.form_frame("seat_0").offers[0]
    return session.submit("seat_0", offer.entry, dict(offer.payload))


@pytest.mark.parametrize("path", ["action", "event", "due"])
def test_authored_birth_allocates_real_owner_and_paid_self_action(path):
    lib, ports, source, assets = documents(path=path)
    program = _compile(lib, ports, source)
    session = program.start(assets)
    if path == "due":
        session.continue_form("seat_0")
    else:
        result = submit_first(session)
        assert isinstance(result, K0Published)
    (birth,) = session._runtime.actors()
    assert birth.formed_by is not None
    assert birth.born_at.ordinal == (5 if path == "due" else 0)
    assert session._runtime.read_actor(birth.actor).view.count == 0
    assert dict(session.read(birth.seat).fields) == {"actor.count": 0, "actor.awake": True}
    session.continue_form("seat_0")
    assert session._runtime.action_opportunity().seat == birth.seat
    assert session.time == birth.born_at.ordinal + 2
    (offer,) = session.form_frame(birth.seat).offers
    assert isinstance(session.submit(birth.seat, offer.entry, dict(offer.payload)), K0Published)
    assert session._runtime.read_actor(birth.actor).view.count == 1
    assert (
        next(item for item in session._runtime.action_value_state() if item.seat == birth.seat).debt
        == 3
    )
    actual = session._runtime.occurrence_history()[-1]
    assert actual.source.value == "c0.test.sprite.step"
    assert actual.participants.actor == birth.actor


def test_opening_and_two_births_share_one_template_not_other_owners():
    lib, ports, source, assets = documents(
        opening=[
            {
                "kind": "sprite",
                "state": {"count": 0, "awake": True},
                "debt": 1,
            }
        ]
    )
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    first, second = session._runtime.actors()
    assert first.formed_by is None and second.formed_by is not None
    assert first.actor != second.actor and first.owner != second.owner
    session.continue_form("seat_0")
    (offer,) = session.form_frame(first.seat).offers
    session.submit(first.seat, offer.entry, {})
    assert session._runtime.read_actor(first.actor).view.count == 1
    assert session._runtime.read_actor(second.actor).view.count == 0
    assert len(session.program.profile.source_specs) == len(session.program.actions) + 1


def test_unknown_kind_and_missing_controller_fail_before_start():
    lib, ports, source, _ = documents()
    for change in ({"controller": {}}, {"read": ["scene.signal"]}, {"first_debt": 0}):
        bad = deepcopy(source)
        bad["actor_templates"][0].update(change)
        with pytest.raises(C0LawError):
            _compile(lib, ports, bad)


def test_opening_cannot_forge_actor_identity_or_exceed_capacity():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    for row in (
        {"kind": "unknown", "state": {"count": 0, "awake": True}, "debt": 1},
        {"kind": "sprite", "state": {"count": -1, "awake": True}, "debt": 1},
    ):
        bad = deepcopy(assets)
        bad["opening_actors"] = [row]
        with pytest.raises(C0BindingError):
            program.start(bad)
    assets["opening_actors"] = [
        {"kind": "sprite", "state": {"count": 0, "awake": True}, "debt": 1},
    ] * 5
    with pytest.raises(C0BindingError):
        program.start(assets)


def test_wrong_or_foreign_self_ref_cannot_write_an_owner():
    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session, other = program.start(assets), program.start(assets)
    submit_first(session)
    submit_first(other)
    session.continue_form("seat_0")
    action = dict(program.actions)["step"]
    before = (session.author_snapshot(), session._runtime.occurrence_history())
    ref = other._runtime.actors()[0].actor
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(
            action.source_key,
            action.payload_type(actor=ref),
        )
    )
    assert isinstance(result, K0NotAdmitted)
    assert (session.author_snapshot(), session._runtime.occurrence_history()) == before


def test_capacity_failure_rolls_back_owner_identity_and_world_action():
    lib, ports, source, assets = documents(
        opening=[
            {
                "kind": "sprite",
                "state": {"count": 0, "awake": True},
                "debt": 2,
            }
        ]
        * 4
    )
    session = _compile(lib, ports, source).start(assets)
    before = (session.author_snapshot(), session._runtime.actors())
    with pytest.raises(K0SettlementDefect):
        submit_first(session)
    assert (session.author_snapshot(), session._runtime.actors()) == before
    assert session._runtime._fatal


def test_two_actual_births_have_distinct_owners_and_separate_mutations():
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    session.continue_form("seat_0")
    while session._runtime.action_opportunity().seat != "seat_0":
        binding = next(
            item
            for item in session._runtime.actors()
            if item.seat == session._runtime.action_opportunity().seat
        )
        (offer,) = session.form_frame(binding.seat).offers
        session.submit(binding.seat, offer.entry, {})
        session.continue_form("seat_0")
    submit_first(session)
    first, second = session.author_actor_instances()
    assert first.formed_by != second.formed_by and first.owner != second.owner
    assert first.current_state.count == 2 and second.current_state.count == 0


def test_finite_appraisal_runs_only_after_birth_debt_and_does_not_share_private_view():
    controller = {
        "mode": "finite_appraisal",
        "profile": {
            "name": "sprite-choice",
            "seat": "sprite",
            "fallback_entry": "step",
            "tie_order": ["step"],
            "rules": [{"entry": "step", "mode": "default"}],
        },
    }
    lib, ports, source, assets = documents(controller=controller)
    session = _compile(lib, ports, source).start(assets)
    submit_first(session)
    (birth,) = session._runtime.actors()
    assert session.appraisal_history() == ()
    assert not any("sprite" in field for field, _ in session.read("seat_0").fields)
    assert birth.seat not in session.human_seats()
    session.continue_form("seat_0")
    history = session.appraisal_history()
    assert [(item.proposal.time, item.proposal.seat) for item in history] == [
        (2, birth.seat),
        (5, birth.seat),
    ]
    assert session._runtime.read_actor(birth.actor).view.count == 2
    assert session._runtime.action_opportunity().seat == "seat_0"


def test_optional_product_still_publishes_second_required_due_without_second_birth():
    lib, ports, source, assets = documents(path="due")
    ports["due_events"][0]["value"]["outputs"]["newborn"] = {"optional": "Sprite"}
    value = source["lawdefs"][1]["body"]["law"]
    value["guard"] = True
    initial = value["outputs"]["newborn"]
    value["outputs"]["newborn"] = {
        "if": {
            "when": "scene.signal == 'quiet'",
            "then": initial,
            "else": {"const": None},
        }
    }
    ports["due_events"][0]["value"]["read"].append("scene.signal")
    source["due_events"][0]["actor_product"]["cardinality"] = "zero_or_one"
    source["temporal"]["periodic"][0]["max_occurrences"] = 2
    session = _compile(lib, ports, source).start(assets)
    while (
        len(
            [
                record
                for record in session._runtime.occurrence_history()
                if record.source.value == "c0.graph.pulse"
            ]
        )
        < 2
    ):
        session.continue_form("seat_0")
        opportunity = session._runtime.action_opportunity()
        if opportunity is not None:
            (offer,) = session.form_frame(opportunity.seat).offers
            session.submit(opportunity.seat, offer.entry, {})
    assert len(session.author_actor_instances()) == 1
    assert (
        len(
            [
                record
                for record in session._runtime.occurrence_history()
                if record.source.value == "c0.graph.pulse"
            ]
        )
        == 2
    )


def test_bind_and_run_do_not_reenter_author_frontend(monkeypatch):
    from nomos_c0 import declarative_graph_ports_v0, declarative_nominal_v0, graph_frontend_v1
    from nomos_c0.program_binding_v1 import bind_program

    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("Bind/Start/Run cannot parse author assets")

    monkeypatch.setattr(graph_frontend_v1, "check_owner_graph", forbidden)
    monkeypatch.setattr(declarative_graph_ports_v0, "check_graph_ports", forbidden)
    monkeypatch.setattr(declarative_nominal_v0, "check_nominal_lib", forbidden)
    rebound = bind_program(program.program_ir, program.world_layout)
    session = rebound.start(assets)
    submit_first(session)
    (birth,) = session._runtime.actors()
    session.continue_form("seat_0")
    (offer,) = session.form_frame(birth.seat).offers
    assert isinstance(session.submit(birth.seat, offer.entry, {}), K0Published)


@pytest.mark.parametrize("sibling", ["formation", "scene_write"])
def test_pure_formation_does_not_claim_a_scene_write(sibling):
    lib, ports, source, assets = documents(path="event")
    other_port = deepcopy(ports["events"][0])
    other_port["symbol"] = "sibling"
    other_law = deepcopy(source["lawdefs"][-1])
    other_law["name"] = "sibling"
    other_event = deepcopy(source["events"][0])
    other_event.update(
        name="sibling",
        template="sibling",
        source_key="c0.test.sprite.sibling",
        event_type="c0.test.sprite.sibling.event",
        causal_key="c0.test.sprite.sibling.law",
        law={"ref": "sibling", "args": {}},
    )
    if sibling == "scene_write":
        other_port["value"] = _value(["scene.marker"], ["scene.marker"], {"marker": "scene.marker"})
        other_law["body"]["law"]["outputs"] = {"marker": {"const": "marked"}}
        del other_event["actor_product"]
    ports["events"].append(other_port)
    source["lawdefs"].append(other_law)
    source["events"].append(other_event)
    session = _compile(lib, ports, source).start(assets)
    assert isinstance(submit_first(session), K0Published)
    assert len(session.author_actor_instances()) == (2 if sibling == "formation" else 1)
    if sibling == "scene_write":
        assert dict(session.author_snapshot().owners)["scene"].marker == "marked"
