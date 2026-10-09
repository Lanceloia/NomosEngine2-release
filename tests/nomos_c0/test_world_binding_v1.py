"""One checked world runs under distinct layouts without repeating the frontend."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest
from nomos_kernel import K0CausalLawKey, K0EventTypeKey, K0OwnerKey, K0SourceSpecKey
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryProfile,
    _K0InMemorySession,
    _K0OwnerState,
)
from nomos_kernel._coordinates import _K0FixedTime, _K0TemporalAdvanceRequest, _K0TemporalInterval
from nomos_kernel._dynamic_owner_abi import _K0OpeningIndividual
from nomos_kernel._event_jump_abi import _K0PeriodicDueOpening
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend
from test_object_action_formation_v1 import _author_world

from nomos_c0 import composable_value_v1 as values
from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.nominal_owner_layout_v1 import bind_nominal_owners
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_start_v1 import _opening
from nomos_c0.world_binding_v1 import bind_world

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _documents(name):
    suffix = "json" if name == "parcel_delivery_v0" else "yaml"
    documents = tuple(
        read_author_document(ROOT / f"{name}.{part}.{suffix}").to_data()
        for part in ("lib", "ports", "source")
    )
    return documents


def _compile(lib, ports, source):
    checked = check_nominal_lib(lib)
    return compile_owner_graph(check_graph_ports(ports, checked), source)


def _parcel(*, false_law=None, shared=False, fixed=False):
    lib, ports, source = _documents("parcel_delivery_v0")
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    if false_law:
        law = next(item for item in source["lawdefs"] if item["name"] == false_law)
        value = law["body"]["value" if law["family"] == "action" else "law"]
        value["guard"] = {"all": [value["guard"], False]}
    if shared:
        del source["ontology"]
        first = next(item for item in source["events"] if item["name"] == "manifest")
        first["shared_result"] = "manifest"
        second = deepcopy(first)
        del second["trigger_event"]
        second.update(
            name="manifest_again",
            trigger_action="confirm",
            causal_key="c0.parcel.manifest_again.causes",
        )
        source["events"].append(second)
        next(item for item in source["lawdefs"] if item["name"] == "event.manifest")["body"]["law"][
            "guard"
        ] = True
    if fixed:
        lib["records"].append(
            {
                "name": "Marker",
                "fields": [{"name": "value", "type": {"str": [1, 24]}}],
                "invariant": None,
            }
        )
        lib["object_kinds"] = [
            {
                "symbol": "marker",
                "sort": "TEST.MARKER@1",
                "state": "Marker",
                "version": "v1",
                "max_instances": 2,
            }
        ]
        due = ports["due_events"][0]
        due["fixed_individual_roots"] = [
            {"name": "marker_view", "kind": "marker", "binding": "fixed_unique_opening"}
        ]
        due["value"]["read"].append("marker_view.value")
        source["object_kinds"] = [{"kind": "marker", "sort": "TEST.MARKER@1"}]
        law = next(item for item in source["lawdefs"] if item["name"] == "event.arrive")["body"][
            "law"
        ]
        law["guard"] = {
            "all": [law["guard"], {"eq": [{"ref": "marker_view.value"}, {"const": "ready"}]}]
        }
        assets["opening_objects"] = [{"kind": "marker", "state": {"value": "ready"}}]
    return _compile(lib, ports, source), assets


def _layout(program, *, fresh=True, rekey_sources=True):
    original = program.world_layout
    records = (
        bind_nominal_records(program.world_ir.signatures)
        if fresh
        else original.owners.record_layout
    )
    owners = bind_nominal_owners(
        program.world_ir.signatures,
        records,
        {
            item.symbol: K0OwnerKey("c0.rebound." + item.symbol)
            for item in program.world_ir.signatures.owners
        },
    )
    changes = {"owners": owners}
    if rekey_sources:
        for field, carrier in (
            ("sources", K0SourceSpecKey),
            ("classifications", K0EventTypeKey),
            ("causal_keys", K0CausalLawKey),
        ):
            changes[field] = tuple(
                (name, carrier(f"c0.rebound.{field}.{index}"))
                for index, (name, _) in enumerate(getattr(original, field))
            )
    return replace(original, **changes)


def _runtime(bound, assets):
    specs = [action.build_spec() for _, action in bound.actions]
    laws, emitted = [], set()
    for _, event in bound.events:
        spec, law = event.build()
        if spec.key not in emitted:
            specs.append(spec)
            emitted.add(spec.key)
        laws.append(law)
    if bound.temporal_binding:
        specs.extend(bound.temporal_binding.due_specs)
    declarations = sorted(bound.layout.owners.owners, key=lambda item: item.owner.key)
    kinds = {item.symbol: item.k0_kind for item in bound.layout.owners.object_kinds}
    profile = _K0InMemoryProfile(
        tuple(item.owner for item in declarations),
        tuple(specs),
        tuple(laws),
        max(1 + len(laws), len(bound.dues)),
        len(laws),
        temporal_policy=None if bound.temporal_binding is None else bound.temporal_binding.policy,
        dynamic_owner_kinds=tuple(kinds[name] for name in bound.ir.selected_kinds),
    )
    return _K0InMemorySession.create(
        profile,
        tuple(
            _K0OwnerState(
                item.owner.key, _opening(item.owner.state_type, assets["opening"][item.symbol])
            )
            for item in declarations
        ),
        initial_time=_K0FixedTime(assets["time"]) if bound.temporal_binding else None,
        opening_individuals=tuple(
            _K0OpeningIndividual(raw["kind"], _opening(kinds[raw["kind"]].state_type, raw["state"]))
            for raw in assets.get("opening_objects", [])
        ),
        opening_periodic_dues=tuple(
            _K0PeriodicDueOpening(
                dict(bound.temporal_binding.periodic_names)[raw["plan"]],
                _K0FixedTime(raw["first_at"]),
            )
            for raw in assets.get("periodic_due_openings", [])
        ),
    )


def _submit(bound, runtime, name, *payload):
    action = dict(bound.actions)[name]
    return runtime.settle(
        _K0InMemoryActionAttempt(action.source_key, action.payload_type(*payload))
    )


def _advance(runtime, at=2):
    return runtime.advance(
        _K0TemporalAdvanceRequest(_K0TemporalInterval(runtime.read_time(), _K0FixedTime(at)))
    )


def _snapshot(bound, runtime):
    return {
        item.symbol: asdict(runtime.read_owner(item.owner.key).view)
        for item in bound.layout.owners.owners
    }


def _forbid_checks(monkeypatch):
    monkeypatch.setattr(nominal, "check_nominal_lib", forbid_frontend)
    monkeypatch.setattr(nominal, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)


@pytest.mark.parametrize("fresh", [False, True])
def test_same_checked_world_runs_action_event_actor_due_under_two_layouts(monkeypatch, fresh):
    program, assets = _parcel()
    assert_symbolic(program.world_ir)
    assert "c0.parcel.dispatch" not in repr(program.world_ir)
    with pytest.raises(FrozenInstanceError):
        program.world_ir.selected_kinds = ()
    other = _layout(program, fresh=fresh, rekey_sources=False)
    _forbid_checks(monkeypatch)
    outcomes = []
    for layout in (program.world_layout, other):
        bound = bind_world(program.world_ir, layout)
        runtime = _runtime(bound, assets)
        assert isinstance(_submit(bound, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
        records = runtime.occurrence_history()
        departure = next(
            item for item in records if item.source == dict(bound.events)["depart"].source_key
        )
        notice = next(
            item for item in records if item.source == dict(bound.events)["notice"].ports.source_key
        )
        assert notice.formation_basis.predecessor == departure.occurrence
        assert notice.semantic_envelope.trigger == departure.occurrence
        _advance(runtime)
        arrival = runtime.occurrence_history()[-1]
        assert arrival.source == dict(bound.dues)["arrive"].ports.source_key
        assert arrival.formation_basis.key.formation == records[0].occurrence
        assert isinstance(_submit(bound, runtime, "confirm", "Niko", "P-1", "dock"), K0Published)
        state = _snapshot(bound, runtime)
        assert state["scene"]["parcel"]["status"] == "arrived"
        assert state["receiver"]["receipt"]["arrival"] == asdict(arrival.occurrence)
        assert state["receiver"]["notice"]["departure"] == asdict(departure.occurrence)
        outcomes.append((state, runtime.occurrence_history()))
    assert outcomes[0][0] == outcomes[1][0]
    assert [item.source for item in outcomes[0][1]] == [item.source for item in outcomes[1][1]]
    assert (
        other.owners.owner("scene").owner.key
        != program.world_layout.owners.owner("scene").owner.key
    )
    assert (
        other.owners.record_layout.record("Scene")
        is not program.world_layout.owners.record_layout.record("Scene")
    ) == fresh


def test_new_occurrence_addresses_keep_one_shared_body_and_each_actual_predecessor(monkeypatch):
    program, assets = _parcel(shared=True)
    layout = _layout(program)
    _forbid_checks(monkeypatch)
    bound = bind_world(program.world_ir, layout)
    first, second = (dict(bound.events)[name] for name in ("manifest", "manifest_again"))
    assert first.ir == second.ir and first.edge != second.edge
    assert first.value.guard_ir.expression.provenance[0].name == "manifest"
    assert second.value.guard_ir.expression.provenance[0].name == "manifest_again"
    runtime = _runtime(bound, assets)
    assert sum(spec.key == first.source_key for spec in runtime._profile.source_specs) == 1
    assert isinstance(_submit(bound, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
    _advance(runtime)
    published = _submit(bound, runtime, "confirm", "Niko", "P-1", "dock")
    assert isinstance(published, K0Published)
    shared = [item for item in runtime.occurrence_history() if item.source == first.source_key]
    assert len(shared) == 2
    assert shared[0].source != dict(program.events)["manifest"].source_key
    by_ref = {item.occurrence: item for item in runtime.occurrence_history()}
    assert (
        by_ref[shared[0].formation_basis.predecessor].source
        == dict(bound.events)["depart"].source_key
    )
    assert (
        by_ref[shared[1].formation_basis.predecessor].source
        == dict(bound.actions)["confirm"].source_key
    )


@pytest.mark.parametrize("formation", ["submit", "after_occurrence", "due"])
def test_rebound_world_preserves_rejection_no_formation_and_atomic_fatal_boundary(formation):
    program, assets = _parcel(
        false_law={
            "submit": "action.dispatch",
            "after_occurrence": "event.depart",
            "due": "event.arrive",
        }[formation]
    )
    bound = bind_world(program.world_ir, _layout(program))
    runtime = _runtime(bound, assets)
    before = _snapshot(bound, runtime)
    result = _submit(bound, runtime, "dispatch", "Mira", "P-1", "dock")
    if formation == "submit":
        assert isinstance(result, K0NotAdmitted)
        assert _snapshot(bound, runtime) == before and runtime.occurrence_history() == ()
    elif formation == "after_occurrence":
        assert isinstance(result, K0Published) and len(runtime.occurrence_history()) == 1
        assert _snapshot(bound, runtime)["scene"] == before["scene"]
        assert _snapshot(bound, runtime)["receiver"] == before["receiver"]
    else:
        before, history, pending = (
            _snapshot(bound, runtime),
            runtime.occurrence_history(),
            runtime._pending_due,
        )
        with pytest.raises(K0SettlementDefect):
            _advance(runtime)
        assert (_snapshot(bound, runtime), runtime.occurrence_history(), runtime._pending_due) == (
            before,
            history,
            pending,
        )
        assert runtime.read_time().ordinal == 0
        with pytest.raises(K0SettlementDefect):
            _advance(runtime)


@pytest.mark.parametrize("column", ["sources", "classifications", "causal_keys"])
@pytest.mark.parametrize("fault", ["missing", "alias", "native"])
def test_world_layout_rejects_missing_aliased_and_unqualified_occurrence_addresses(column, fault):
    program, _ = _parcel()
    rows = list(getattr(program.world_layout, column))
    if fault == "missing":
        rows.pop()
    elif fault == "alias":
        rows[1] = (rows[1][0], rows[0][1])
    else:
        rows[0] = (rows[0][0], rows[0][1].value)
    with pytest.raises(C0LawError, match="keys"):
        bind_world(program.world_ir, replace(program.world_layout, **{column: tuple(rows)}))


def test_world_layout_rejects_another_nominal_signature_even_if_declarations_are_equal():
    program, _ = _parcel()
    foreign, _ = _parcel()
    with pytest.raises(C0LawError, match="signatures"):
        bind_world(
            program.world_ir, replace(program.world_layout, owners=foreign.world_layout.owners)
        )


def test_opening_and_formed_objects_share_the_rebound_generic_law_and_sort(monkeypatch):
    lib, ports, source = _documents("object_target_v1")
    assets = read_author_document(ROOT / "object_target_v1.assets.yaml").to_data()
    program = _compile(lib, ports, source)
    layout = _layout(program)
    _forbid_checks(monkeypatch)
    bound = bind_world(program.world_ir, layout)
    runtime = _runtime(bound, assets)
    old = runtime.individuals()[0]
    assert isinstance(_submit(bound, runtime, "make", "Mira"), K0Published)
    new = runtime.individuals()[-1]
    assert new.individual.family == "fine_tool" and old.individual.family == "tool"
    assert new.formed_by == runtime.occurrence_history()[-1].occurrence
    inspect = dict(bound.actions)["inspect"]
    for binding in (old, new):
        assert isinstance(
            _submit(bound, runtime, "inspect", "Mira", binding.individual), K0Published
        )
        occurrence = runtime.occurrence_history()[-1]
        assert occurrence.source == inspect.source_key
        assert occurrence.selected_owners[0].selector == binding.individual
        assert occurrence.selected_owners[0].owner == binding.owner
        assert runtime.read_individual(binding.individual).view.ready is False
    before = runtime.occurrence_history()
    assert isinstance(_submit(bound, runtime, "inspect", "Mira", new.individual), K0NotAdmitted)
    foreign = _runtime(bound, assets).individuals()[0]
    assert isinstance(_submit(bound, runtime, "inspect", "Mira", foreign.individual), K0NotAdmitted)
    assert runtime.occurrence_history() == before


def test_closed_actor_and_individual_participants_keep_exact_current_owner_bindings():
    lib, ports, source = _documents("multi_participant_v0")
    program = _compile(lib, ports, source)
    bound = bind_world(program.world_ir, _layout(program))
    runtime = _runtime(
        bound, read_author_document(ROOT / "multi_participant_v0.assets.yaml").to_data()
    )
    tool = runtime.individuals()[0]
    assert isinstance(_submit(bound, runtime, "enable", "maker", tool.individual, "a"), K0Published)
    state = _snapshot(bound, runtime)
    assert state["a"]["enabled"] and not state["b"]["enabled"]
    selected = runtime.occurrence_history()[-1].selected_owners
    assert selected[1].owner == bound.layout.owners.owner("a").owner.key
    before = _snapshot(bound, runtime), runtime.occurrence_history()
    assert isinstance(
        _submit(bound, runtime, "enable", "maker", tool.individual, "b"), K0NotAdmitted
    )
    assert isinstance(
        _submit(bound, runtime, "enable", "maker", tool.individual, "maker"), K0NotAdmitted
    )
    assert (_snapshot(bound, runtime), runtime.occurrence_history()) == before


def test_fixed_due_reads_the_real_rebound_individual_and_retains_its_ref(monkeypatch):
    program, assets = _parcel(fixed=True)
    layout = _layout(program)
    _forbid_checks(monkeypatch)
    bound = bind_world(program.world_ir, layout)
    runtime = _runtime(bound, assets)
    marker = runtime.individuals()[0].individual
    assert isinstance(_submit(bound, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
    _advance(runtime)
    due = runtime.occurrence_history()[-1]
    assert due.participants.fixed_individuals == (("marker_view", marker),)
    assert due.semantic_envelope.fixed_individuals == (("marker_view", marker),)
    assert due.selected_owners[0].selector == marker


def test_formation_and_schedule_stay_atomic_effects_of_the_same_rebound_action():
    lib, ports, source, assets = _author_world()
    program = _compile(lib, ports, source)
    bound = bind_world(program.world_ir, _layout(program))
    runtime = _runtime(bound, assets)
    assert isinstance(_submit(bound, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
    action = runtime.occurrence_history()[0]
    assert runtime.individuals()[-1].formed_by == action.occurrence
    assert runtime._pending_due[0].key.formation == action.occurrence
    assert runtime._pending_due[0].source == dict(bound.dues)["arrive"].ports.source_key


def test_production_profile_rules_and_temporal_specs_consume_bound_world():
    program, _ = _parcel()
    assert program.world_ir is program.world_layout.world
    rebound = bind_world(program.world_ir, program.world_layout)
    assert (program.actions, program.events, program.due_laws, program.temporal_ir) == (
        rebound.actions,
        rebound.events,
        rebound.dues,
        rebound.temporal_ir,
    )
    sources = {spec.key: spec for spec in program.profile.source_specs}
    for _, action in program.actions:
        assert sources[action.source_key].rule.program is action
    for _, event in program.events:
        assert sources[event.ports.source_key].rule.program is event
    for _, due in program.due_laws:
        assert sources[due.ports.source_key].rule.program is due
    assert program.profile.temporal_policy == rebound.temporal_binding.policy


def test_shared_classification_still_filters_each_exact_predecessor_after_rebinding():
    lib, ports, source = _documents("parcel_delivery_v0")
    del source["ontology"]
    first, second = (source["events"][index] for index in (0, 2))
    second["event_type"] = first["event_type"]
    program = _compile(lib, ports, source)
    bound = bind_world(program.world_ir, _layout(program))
    events = dict(bound.events)
    assert events["depart"].event_type == events["manifest"].event_type
    runtime = _runtime(
        bound, read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    )
    assert isinstance(_submit(bound, runtime, "dispatch", "Mira", "P-1", "dock"), K0Published)
    records = runtime.occurrence_history()
    assert len(records) == 4
    departure = next(item for item in records if item.source == events["depart"].source_key)
    manifest = next(item for item in records if item.source == events["manifest"].source_key)
    assert manifest.formation_basis.predecessor == departure.occurrence


def test_periodic_due_rebinds_two_static_owners_time_and_each_periodic_origin(monkeypatch):
    lib, ports, source = _documents("parcel_delivery_v0")
    del source["ontology"]
    ports["actions"][0]["schedule"] = None
    for output in ("subject", "delay"):
        del source["lawdefs"][0]["body"]["value"]["outputs"][output]
    del source["actions"][0]["schedule"]
    due = ports["due_events"][0]
    due["owner_roots"] = ["receiver"]
    due["value"] = {
        "read": ["receiver.name", "due.subject", "time.ordinal"],
        "fields": {},
        "write_paths": ["scene.signal", "receiver.notice"],
        "outputs": {
            "signal": "scene.signal",
            "notice": {"target": "receiver.notice", "type": "Notice"},
        },
        "construct": ["Notice"],
        "collections": {},
    }
    law = next(item for item in source["lawdefs"] if item["name"] == "event.arrive")
    law["body"]["law"] = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {
            "all": [
                {"eq": [{"ref": "receiver.name"}, {"const": "Niko"}]},
                {"eq": [{"ref": "due.subject"}, {"const": "clock"}]},
                {"lt": [{"const": 0}, {"ref": "time.ordinal"}]},
            ]
        },
        "outputs": {
            "signal": {"const": "flagged"},
            "notice": {
                "record": {
                    "type": "Notice",
                    "fields": {
                        "departure": {"ref": "occurrence"},
                        "notification": {"ref": "occurrence"},
                    },
                }
            },
        },
    }
    source["temporal"] = {
        "mechanism": "action_value_event_jump",
        "order": ["arrive"],
        "max_pending": 1,
        "periodic": [
            {
                "name": "clock",
                "due": "arrive",
                "interval": 2,
                "max_occurrences": 2,
                "subject": "clock",
            }
        ],
    }
    source["game_form"] = {
        "mode": "action_value_event_jump",
        "seats": [
            {"seat": seat, "tempo": {"const": 1}, "eligible": True, "costs": {entry: {"const": 1}}}
            for seat, entry in (("sender", "dispatch"), ("receiver", "confirm"))
        ],
        "end_at": 8,
        "max_same_time_actions": 8,
    }
    program = _compile(lib, ports, source)
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    assets["periodic_due_openings"] = [{"plan": "clock", "first_at": 1}]
    layout = _layout(program)
    _forbid_checks(monkeypatch)
    states = []
    for selected in (program.world_layout, layout):
        bound = bind_world(program.world_ir, selected)
        runtime = _runtime(bound, assets)
        _advance(runtime, 1)
        assert len(runtime.occurrence_history()) == 1
        _advance(runtime, 3)
        history = runtime.occurrence_history()
        assert len(history) == 2 and not runtime._pending_due
        for index, occurrence in enumerate(history):
            assert occurrence.semantic_envelope.periodic_ordinal == index
            assert occurrence.semantic_envelope.periodic_plan == "c0.owner_graph.periodic.clock.v1"
            assert occurrence.semantic_envelope.formation is None
            assert occurrence.source == dict(bound.dues)["arrive"].ports.source_key
        state = _snapshot(bound, runtime)
        assert state["scene"]["signal"] == "flagged"
        assert state["receiver"]["notice"]["notification"] == asdict(history[-1].occurrence)
        states.append(state)
    assert states[0] == states[1]


def test_world_due_rejects_an_owner_with_the_wrong_nominal_record():
    program, _ = _parcel()
    world = program.world_ir
    transitions = tuple(
        replace(item, owners=(("scene", "receiver"),)) if item.kind == "due" else item
        for item in world.transitions
    )
    world = replace(world, transitions=transitions)
    with pytest.raises(C0LawError, match="nominal declarations"):
        bind_world(world, replace(program.world_layout, world=world))


def test_world_binding_rejects_a_declared_but_unselected_formation_kind():
    lib, ports, source = _documents("object_target_v1")
    program = _compile(lib, ports, source)
    world = replace(program.world_ir, selected_kinds=("tool",))
    with pytest.raises(C0LawError, match="unselected"):
        bind_world(world, replace(program.world_layout, world=world))


@pytest.mark.parametrize("fault", ["range", "invariant"])
def test_two_layouts_keep_nominal_validation_and_atomic_rollback_in_real_rules(fault):
    lib, ports, source = _documents("parcel_delivery_v0")
    law = next(item for item in source["lawdefs"] if item["name"] == "event.depart")
    changes = law["body"]["law"]["outputs"]["parcel"]["copy"]["changes"]
    if fault == "range":
        changes["status"] = {"const": "unlisted"}
    else:
        changes["depart_ref"] = None
    program = _compile(lib, ports, source)
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    for layout in (program.world_layout, _layout(program)):
        bound = bind_world(program.world_ir, layout)
        runtime = _runtime(bound, assets)
        before = _snapshot(bound, runtime)
        with pytest.raises(K0SettlementDefect):
            _submit(bound, runtime, "dispatch", "Mira", "P-1", "dock")
        assert _snapshot(bound, runtime) == before
        assert runtime.occurrence_history() == () and not runtime._pending_due


def test_world_binding_does_not_widen_the_checked_field_write_permission():
    program, _ = _parcel()
    world = replace(
        program.world_ir,
        transitions=tuple(
            replace(item, effects=(("scene", "routes", "signal"),))
            if item.symbol == "manifest"
            else item
            for item in program.world_ir.transitions
        ),
    )
    with pytest.raises(C0LawError, match="write port"):
        bind_world(world, replace(program.world_layout, world=world))
