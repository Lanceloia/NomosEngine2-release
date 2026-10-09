"""Due Object reads use current bindings, sealed identities and no write authority."""

from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from authored_counter_v1 import _record, _value, action_value_documents
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_abi import _K0CapabilityRef
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect
from test_nominal_signatures_v1 import assert_symbolic
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.world_binding_v1 import bind_world


def ref(name):
    return {"ref": name}


def initial():
    return {
        "record": {
            "type": "Artifact",
            "fields": {"holder": None, "site": {"const": "home"}, "secret": 99},
        }
    }


def documents(*, opening=5):
    lib, ports, source, assets = action_value_documents()
    text = {"str": [1, 64]}
    lib["records"] += [
        _record(
            "Artifact", {"holder": {"optional": text}, "site": text, "secret": {"int": [0, 100]}}
        ),
        _record(
            "ArtifactEntry",
            {"individual": "individual_ref", "holder": {"optional": text}, "site": text},
        ),
        _record("ArtifactDomain", {"members": {"tuple": {"item": "ArtifactEntry", "max": 8}}}),
        _record("TransferAttempt", {"actor": text, "item": "individual_ref"}),
    ]
    lib["records"][0]["fields"] += [
        {"name": "observed", "type": {"tuple": {"item": "ArtifactEntry", "max": 8}}},
        {"name": "observed_count", "type": {"int": [0, 8]}},
    ]
    lib["object_kinds"] = [
        {
            "symbol": name,
            "sort": f"TEST.{name.upper()}@1",
            "state": "Artifact",
            "version": "1",
            "max_instances": 8,
        }
        for name in ("artifact", "other")
    ]
    source["object_kinds"] = [
        {"kind": row["symbol"], "sort": row["sort"]} for row in lib["object_kinds"]
    ]
    assets["opening"]["scene"].update(observed=[], observed_count=0)
    assets["opening_objects"] = [
        {"kind": "artifact", "state": {"holder": None, "site": "home", "secret": index}}
        for index in range(opening)
    ] + [{"kind": "other", "state": {"holder": None, "site": "home", "secret": 10}}]
    ports["actions"][0]["value"].update(outputs={"newborn": "Artifact"}, construct=["Artifact"])
    source["actions"][0]["form"] = {"kind": "artifact", "initial_output": "newborn"}
    source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"] = initial()
    plain = deepcopy(source["lawdefs"][0])
    plain["name"] = "count_plain"
    del plain["body"]["value"]["outputs"]["newborn"]
    source["lawdefs"].append(plain)
    source["actions"][1]["law"]["ref"] = "count_plain"
    source["game_form"]["seats"][1]["eligible"] = False
    source["game_form"]["seats"][0]["costs"]["count_0"] = 10
    assets["action_value_openings"][0]["debt"] = 0
    domain = {
        "name": "items",
        "kind": "artifact",
        "wrapper": "ArtifactDomain",
        "members_field": "members",
        "record": "ArtifactEntry",
        "identity_field": "individual",
        "fields": {"holder": "holder", "site": "site"},
    }
    due = ports["due_events"][0]
    due["read_object_domains"] = [domain]
    due["value"] = _value(
        ["due.subject", "time.ordinal", "items.members"],
        ["scene.observed", "scene.observed_count"],
        {"observed": "scene.observed", "count": "scene.observed_count"},
    )
    due["value"]["fields"] = {"ArtifactEntry": ["individual", "holder", "site"]}
    law = source["lawdefs"][1]["body"]["law"]
    law["guard"] = "due.subject == 'clock'"
    law["outputs"] = {
        "observed": {
            "collect_matching": {
                "collection": ref("items.members"),
                "as": "item",
                "where": True,
                "value": ref("item"),
            }
        },
        "count": {
            "count_matching": {"collection": ref("items.members"), "as": "item", "where": True}
        },
    }
    ports["actions"].append(
        {
            "symbol": "transfer",
            "actor": "actor_0",
            "payload": "TransferAttempt",
            "envelope": "Envelope",
            "actor_identity_field": "name",
            "payload_actor_field": "actor",
            "participants": [
                {
                    "name": "item",
                    "selector": "individual",
                    "state": "Artifact",
                    "payload_field": "item",
                    "write": True,
                }
            ],
            "effects": {"scene": {}, "actor": {}, "item": {"holder": "holder", "site": "site"}},
            "envelope_fields": {"action": "action"},
            "schedule": None,
            "value": _value(["actor.name", "item.site"], ["item.holder", "item.site"]),
        }
    )
    source["lawdefs"].append(
        {
            "name": "transfer",
            "family": "action",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": "item.site == 'home'",
                    "outputs": {
                        "holder": ref("actor.name"),
                        "site": {"const": "transit"},
                        "action": ref("occurrence"),
                    },
                }
            },
        }
    )
    source["actions"].append(
        {
            "name": "transfer",
            "template": "transfer",
            "actor": "actor_0",
            "source_key": "test.transfer",
            "event_type": "test.transfer.action",
            "law": {"ref": "transfer", "args": {}},
            "participants": {"item": {"kind": "artifact"}},
        }
    )
    source["seats"][0]["entries"].append("transfer")
    source["seats"][0]["offers"].append(
        {
            "entry": "transfer",
            "label": [{"const": "Transfer"}],
            "payload": {"item": ref("item_ref")},
            "for_each_participants": {"item": {"kind": "artifact", "read": ["item.site"]}},
            "visible_when": "item.site == 'home'",
            "when": True,
        }
    )
    source["game_form"]["seats"][0]["costs"]["transfer"] = 1
    return lib, ports, source, assets


def scene(session):
    return dict(session.author_snapshot().owners)["scene"]


def submit(session, entry):
    offer = next(row for row in session.offers("seat_0") if row.entry == entry)
    assert isinstance(session.submit("seat_0", entry, dict(offer.payload)), K0Published)


def advance(session):
    session.continue_form("seat_0")
    return next(
        row for row in session._runtime.occurrence_history() if row.source.value == "c0.graph.pulse"
    )


def precursor_documents():
    lib, ports, source, assets = documents()
    ports["due_events"].insert(
        0,
        {
            "symbol": "before",
            "value": _value(["due.subject"], ["scene.signal"], {"signal": "scene.signal"}),
            "read_object_domains": deepcopy(ports["due_events"][0]["read_object_domains"]),
        },
    )
    source["lawdefs"].append(
        {
            "name": "before",
            "family": "due_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"signal": {"const": "born"}},
                }
            },
        }
    )
    before = deepcopy(source["due_events"][0])
    before.update(
        name="before",
        template="before",
        source_key="test.before",
        event_type="test.before.event",
        law={"ref": "before", "args": {}},
    )
    source["due_events"].insert(0, before)
    ports["events"].append(
        {
            "symbol": "produce",
            "form": "direct_scene",
            "actor": None,
            "actor_identity_field": None,
            "value": _value(["scene.signal"], [], {"newborn": "Artifact"}, ["Artifact"]),
        }
    )
    source["lawdefs"].append(
        {
            "name": "produce",
            "family": "direct_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {"newborn": initial()},
                }
            },
        }
    )
    source["events"].append(
        {
            "name": "produce",
            "template": "produce",
            "trigger_event": "before",
            "source_key": "test.produce",
            "event_type": "test.produce.event",
            "causal_key": "test.produce.law",
            "law": {"ref": "produce", "args": {}},
            "object_product": {"kind": "artifact", "initial_output": "newborn"},
        }
    )
    source["temporal"]["order"] = ["before", "pulse"]
    source["temporal"]["max_pending"] = 2
    source["temporal"]["periodic"].insert(
        0,
        {
            "name": "beforeclock",
            "due": "before",
            "interval": 5,
            "max_occurrences": 1,
            "subject": "clock",
        },
    )
    assets["periodic_due_openings"].insert(0, {"plan": "beforeclock", "first_at": 5})
    source["game_form"]["seats"][0]["eligible"] = False
    return lib, ports, source, assets


@pytest.mark.parametrize("fail_later", [False, True])
def test_same_boundary_causal_birth_is_read_by_later_due_or_wholly_rolled_back(fail_later):
    lib, ports, source, assets = precursor_documents()
    if fail_later:
        source["lawdefs"][1]["body"]["law"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    before = (
        session.author_snapshot(),
        session.author_object_instances(),
        session._runtime._time,
        session._runtime.action_value_state(),
    )
    if fail_later:
        with pytest.raises(K0SettlementDefect):
            advance(session)
        assert (
            session.author_snapshot(),
            session.author_object_instances(),
            session._runtime._time,
            session._runtime.action_value_state(),
        ) == before
        assert session._runtime._fatal
    else:
        event = advance(session)
        assert scene(session).observed_count == 6
        born = session.author_object_instances()[-1]
        history = session._runtime.occurrence_history()
        assert [row.source.value for row in history] == [
            "test.before",
            "test.produce",
            "c0.graph.pulse",
        ]
        assert born.formed_by == history[1].occurrence
        assert born.predecessor == history[0].occurrence
        assert len(history[0].participants.objects) == 5
        assert event.participants.objects[-1] == ("items", born.individual)


def test_five_opening_and_real_birth_use_current_exact_refs_without_object_writes():
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    submit(session, "count_0")
    before = session.author_object_instances()
    event = advance(session)
    actual = tuple(row for row in before if row.individual.family == "artifact")
    assert len(actual) == scene(session).observed_count == 6
    assert tuple(row.individual for row in scene(session).observed) == tuple(
        r.individual for r in actual
    )
    assert event.participants.objects == tuple(("items", row.individual) for row in actual)
    assert event.semantic_envelope.objects == event.participants.objects
    assert event.participants.fixed_individuals == () and event.participants.actors == ()
    assert session.author_object_instances() == before
    assert not any(
        "items" in path or "observed" in path for path, _ in session.read("seat_0").fields
    )


def test_due_reads_a_real_preceding_transfer_and_preserves_other_objects():
    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    submit(session, "transfer")
    session.continue_form("seat_0")
    submit(session, "count_0")
    before = session.author_object_instances()
    advance(session)
    changed = [entry for entry in scene(session).observed if entry.holder is not None]
    assert len(changed) == 1
    assert changed[0].holder == "person_0" and changed[0].site == "transit"
    assert session.author_object_instances() == before


def test_empty_domain_does_not_suppress_the_required_due():
    lib, ports, source, assets = documents(opening=0)
    source["game_form"]["seats"][0]["eligible"] = False
    session = _compile(lib, ports, source).start(assets)
    event = advance(session)
    assert scene(session).observed == () and scene(session).observed_count == 0
    assert event.participants.objects == event.semantic_envelope.objects == ()


def test_domain_and_fixed_singleton_of_same_family_keep_separate_actual_refs():
    lib, ports, source, assets = documents(opening=1)
    source["game_form"]["seats"][0]["eligible"] = False
    ports["due_events"][0]["fixed_individual_roots"] = [
        {"name": "fixed", "kind": "artifact", "binding": "fixed_unique_opening"}
    ]
    ports["due_events"][0]["value"]["read"].append("fixed.site")
    source["lawdefs"][1]["body"]["law"]["guard"] = "fixed.site == 'home'"
    session = _compile(lib, ports, source).start(assets)
    event = advance(session)
    ref = session.author_object_instances()[0].individual
    assert event.participants.fixed_individuals == (("fixed", ref),)
    assert event.participants.objects == (("items", ref),)
    assert event.semantic_envelope.objects == (("items", ref),)


def test_multiple_families_are_sealed_in_domain_name_then_actual_ordinal_order():
    lib, ports, source, assets = documents()
    source["game_form"]["seats"][0]["eligible"] = False
    other = deepcopy(ports["due_events"][0]["read_object_domains"][0])
    other.update(name="a_other", kind="other")
    ports["due_events"][0]["read_object_domains"].append(other)
    session = _compile(lib, ports, source).start(assets)
    event = advance(session)
    objects = session.author_object_instances()
    expected = (("a_other", objects[-1].individual),) + tuple(
        ("items", row.individual) for row in objects[:-1]
    )
    assert event.participants.objects == event.semantic_envelope.objects == expected
    assert scene(session).observed_count == 5


@pytest.mark.parametrize(
    "mutation",
    [
        "kind",
        "record",
        "identity",
        "mapping",
        "constraint",
        "capacity",
        "duplicate",
        "reserved",
        "write",
        "unselected",
        "hidden",
    ],
)
def test_invalid_domain_authority_or_nominal_projection_fails_compile(mutation):
    lib, ports, source, _ = documents()
    domain = ports["due_events"][0]["read_object_domains"][0]
    if mutation == "kind":
        domain["kind"] = "absent"
    elif mutation == "record":
        domain["record"] = "Artifact"
    elif mutation == "identity":
        next(r for r in lib["records"] if r["name"] == "ArtifactEntry")["fields"][0]["type"] = (
            "actor_ref"
        )
    elif mutation == "mapping":
        domain["fields"]["site"] = "absent"
    elif mutation == "constraint":
        next(r for r in lib["records"] if r["name"] == "ArtifactEntry")["fields"][2]["type"] = {
            "str": [1, 32]
        }
    elif mutation == "capacity":
        next(r for r in lib["records"] if r["name"] == "ArtifactDomain")["fields"][0]["type"][
            "tuple"
        ]["max"] = 1
    elif mutation == "duplicate":
        ports["due_events"][0]["read_object_domains"] *= 2
    elif mutation == "reserved":
        domain["name"] = "scene"
    elif mutation == "write":
        ports["due_events"][0]["value"]["outputs"]["count"] = "items.site"
    elif mutation == "unselected":
        source["object_kinds"] = source["object_kinds"][1:]
    else:
        source["lawdefs"][1]["body"]["law"]["outputs"]["count"]["count_matching"]["where"] = (
            "item.secret == 0"
        )
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_read_field_authority_is_not_granted_by_the_domain_mapping():
    lib, ports, source, _ = documents()
    ports["due_events"][0]["value"]["fields"]["ArtifactEntry"].remove("holder")
    with pytest.raises(C0LawError, match="read port"):
        _compile(lib, ports, source)


def test_failed_due_rolls_back_current_objects_time_history_and_debts():
    lib, ports, source, assets = documents()
    source["lawdefs"][1]["body"]["law"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    submit(session, "count_0")
    before = (
        session.author_snapshot(),
        session.author_object_instances(),
        session._runtime.occurrence_history(),
        session._runtime.action_value_state(),
        session._runtime._time,
    )
    with pytest.raises(K0SettlementDefect):
        advance(session)
    assert (
        session.author_snapshot(),
        session.author_object_instances(),
        session._runtime.occurrence_history(),
        session._runtime.action_value_state(),
        session._runtime._time,
    ) == before
    assert session._runtime._fatal


def test_independent_ir_bind_reconstructs_the_complete_domain_and_runs(monkeypatch):
    from nomos_c0 import graph_frontend_v1

    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    assert_symbolic(program.world_ir)

    def forbidden(*args, **kwargs):
        raise AssertionError("Bind must not parse or infer author input")

    monkeypatch.setattr(graph_frontend_v1, "check_owner_graph", forbidden)
    for layout in (program.world_layout, _layout(program)):
        rebound = bind_program(program.program_ir, layout)
        session = rebound.start(deepcopy(assets))
        submit(session, "count_0")
        session.continue_form("seat_0")
        symbol = next(
            row.occurrence for row in program.world_ir.transitions if row.symbol == "pulse"
        )
        key = dict(layout.sources)[symbol]
        event = next(row for row in session._runtime.occurrence_history() if row.source == key)
        assert scene(session).observed_count == 6
        assert event.participants.objects == tuple(
            ("items", row.individual) for row in scene(session).observed
        )


@pytest.mark.parametrize("fault", ["kind", "field", "identity", "capacity", "alias", "write"])
def test_independent_bind_rejects_forged_domain(fault):
    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    event = next(row for row in program.world_ir.transitions if row.kind == "due")
    domain = event.object_reads[0]
    if fault == "write":
        changed = replace(event, effects=(("items", "site", "count"),))
    else:
        patch = {
            "kind": {"kind": "missing"},
            "field": {"fields": (("holder", "holder"), ("site", "secret"))},
            "identity": {"identity_field": "site"},
            "capacity": {"wrapper": "ArtifactEntry"},
            "alias": {"name": "scene"},
        }[fault]
        changed = replace(event, object_reads=(replace(domain, **patch),))
    with pytest.raises(C0LawError):
        world = replace(
            program.world_ir,
            transitions=tuple(
                changed if row is event else row for row in program.world_ir.transitions
            ),
        )
        bind_world(world, replace(program.world_layout, world=world))


@dataclass(frozen=True)
class ForgedDueProjector:
    original: object
    fault: str
    capability_ref: _K0CapabilityRef

    def project_due(self, pending, time, owner_views):
        projection = self.original.project_due(pending, time, owner_views)
        views = projection.evidence.object_views
        if self.fault == "scope":
            view = replace(
                views[0], individual_ref=replace(views[0].individual_ref, scope="foreign")
            )
        elif self.fault == "owner":
            view = replace(views[0], owner=views[1].owner)
            # A permutation is structurally valid, but is not the actual binding.
            views = (view, replace(views[1], owner=views[0].owner), *views[2:])
        else:
            return replace(projection, participants=replace(projection.participants, objects=()))
        if self.fault == "scope":
            views = (view, *views[1:])
        return replace(
            projection,
            evidence=replace(projection.evidence, object_views=views),
            participants=replace(
                projection.participants,
                objects=tuple((row.participant, row.individual_ref) for row in views),
            ),
        )


@dataclass(frozen=True)
class ForgedDueEvaluation:
    original: object
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input):
        evaluation = self.original.evaluate(rule_input)
        return replace(evaluation, envelope=replace(evaluation.envelope, objects=()))


@pytest.mark.parametrize("fault", ["scope", "owner", "participants", "envelope"])
def test_kernel_rejects_forged_object_basis_and_publication_atomically(fault):
    lib, ports, source, assets = documents()
    source["game_form"]["seats"][0]["eligible"] = False
    program = _compile(lib, ports, source)
    specs = []
    for spec in program.profile.source_specs:
        if spec.read_object_domains:
            if fault == "envelope":
                spec = replace(
                    spec,
                    rule=ForgedDueEvaluation(spec.rule, _K0CapabilityRef("test.forged.evaluation")),
                )
            else:
                spec = replace(
                    spec,
                    due_projector=ForgedDueProjector(
                        spec.due_projector, fault, _K0CapabilityRef("test.forged.projector")
                    ),
                )
        specs.append(spec)
    # Inject a hostile native capability to test K0, not an author Program rebind.
    object.__setattr__(program, "profile", replace(program.profile, source_specs=tuple(specs)))
    session = program.start(assets)
    before = (session.author_snapshot(), session.author_object_instances())
    with pytest.raises(K0SettlementDefect) as failure:
        advance(session)
    assert isinstance(failure.value.__cause__, K0ProfileError)
    assert "Object domain" in str(failure.value.__cause__)
    assert (session.author_snapshot(), session.author_object_instances()) == before
    assert session._runtime._fatal


def test_kernel_domain_is_due_only_and_rejects_unselected_family():
    from nomos_kernel._dynamic_owner_abi import _K0ReadObjectDomainPort

    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    action = next(
        spec for spec in program.profile.source_specs if spec.admission_capability is not None
    )
    with pytest.raises(K0ProfileError):
        replace(action, read_object_domains=(_K0ReadObjectDomainPort("items", "artifact"),))
    due = next(spec for spec in program.profile.source_specs if spec.read_object_domains)
    bad = replace(due, read_object_domains=(_K0ReadObjectDomainPort("items", "missing"),))
    with pytest.raises(K0ProfileError):
        replace(
            program.profile,
            source_specs=tuple(
                bad if spec is due else spec for spec in program.profile.source_specs
            ),
        )


@dataclass(frozen=True)
class ObjectWritingDueRule:
    original: object
    contribution_type: type
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input):
        evaluation = self.original.evaluate(rule_input)
        view = rule_input.evidence.object_views[0]
        contribution = self.contribution_type(view.owner, replace(view.view, site="stolen"))
        return replace(
            evaluation,
            result=replace(
                evaluation.result,
                contributions=(*evaluation.result.contributions, contribution),
            ),
        )


def test_kernel_domain_read_does_not_authorize_object_contribution():
    lib, ports, source, assets = documents()
    source["game_form"]["seats"][0]["eligible"] = False
    program = _compile(lib, ports, source)
    specs = tuple(
        replace(
            spec,
            rule=ObjectWritingDueRule(
                spec.rule,
                program.object_kinds[0].k0_kind.factory.contribution_type,
                _K0CapabilityRef("test.unauthorized.object.write"),
            ),
        )
        if spec.read_object_domains
        else spec
        for spec in program.profile.source_specs
    )
    # Private fault injection remains necessary to verify K0 contribution isolation.
    object.__setattr__(program, "profile", replace(program.profile, source_specs=specs))
    session = program.start(assets)
    before = (session.author_snapshot(), session.author_object_instances())
    with pytest.raises(K0SettlementDefect) as failure:
        advance(session)
    assert isinstance(failure.value.__cause__, K0ProfileError)
    assert "contribution owners" in str(failure.value.__cause__)
    assert (session.author_snapshot(), session.author_object_instances()) == before


def test_object_metadata_requires_exclusive_exact_identity_and_participant():
    from nomos_kernel._actor_identity import _K0ActorRef
    from nomos_kernel._owner_abi import _K0OwnerView

    lib, ports, source, assets = documents()
    session = _compile(lib, ports, source).start(assets)
    item = session.author_object_instances()[0]
    actor = _K0ActorRef(item.individual.scope, item.individual.ordinal, "sprite")
    for participant, actor_ref, individual_ref in (
        (None, None, item.individual),
        ("items", actor, item.individual),
        ("items", None, actor),
    ):
        with pytest.raises(K0ProfileError):
            _K0OwnerView(item.owner, item.current_state, participant, actor_ref, individual_ref)


def test_actor_domain_effect_reads_outer_object_wrapper_under_independent_bind():
    from test_actor_formation_v1 import documents as actor_documents

    lib, ports, source, assets = documents()
    a_lib, a_ports, a_source, a_assets = actor_documents(
        opening=[{"kind": "sprite", "state": {"count": 0, "awake": False}, "debt": 20}] * 2
    )
    lib["records"] += a_lib["records"][-2:]
    lib["actor_kinds"] = a_lib["actor_kinds"]
    ports["actions"].append(a_ports["actions"][-1])
    source["actions"].append(a_source["actions"][-1])
    source["lawdefs"].append(next(row for row in a_source["lawdefs"] if row["name"] == "step"))
    source["actor_templates"] = a_source["actor_templates"]
    assets["opening_actors"] = a_assets["opening_actors"]
    value = _value(["items.members"], ["actor.count"], {"count": "actor.count"})
    ports["due_events"][0]["actor_domains"] = [
        {"name": "sprites", "kind": "sprite", "value": value}
    ]
    source["lawdefs"].append(
        {
            "name": "count_items",
            "family": "due_event",
            "formals": {},
            "body": {
                "law": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": True,
                    "outputs": {
                        "count": {
                            "count_matching": {
                                "collection": ref("items.members"),
                                "as": "item",
                                "where": True,
                            }
                        }
                    },
                }
            },
        }
    )
    source["due_events"][0]["actor_domain_effects"] = [
        {"name": "sprites", "law": {"ref": "count_items", "args": {}}}
    ]
    program = _compile(lib, ports, source)
    for selected in (program, bind_program(program.program_ir, _layout(program))):
        session = selected.start(assets)
        submit(session, "count_0")
        before = session.author_object_instances()
        session.continue_form("seat_0")
        assert [item.current_state.count for item in session.author_actor_instances()] == [6, 6]
        assert session.author_object_instances() == before
