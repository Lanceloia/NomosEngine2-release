"""Explicit value reads share a finite budget without enlarging owner authority."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.checked_value_binding_v1 import C0ValueBackend
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.composable_value_v1 import compile_value_program
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.value_symbols_v1 import bind_value_program


def _record(name, fields):
    return {"name": name, "fields": fields, "invariant": None}


def _field(name, annotation):
    return {"name": name, "type": annotation}


def _owner(symbol, record, seat_read=()):
    return {
        "symbol": symbol,
        "key": f"sample.read-budget.{symbol}",
        "version": "v1",
        "state": record,
        "identity_field": "name" if record != "Scene" else None,
        "seat_read": list(seat_read),
        "write": "replace_one",
    }


def _paths():
    return ["actor.name", "actor.total", "payload.actor"] + [
        f"r{owner}.f{field:02d}" for owner in range(8) for field in range(32)
    ]


def _documents(count):
    names = [f"reader_{index}" for index in range(8)]
    scalar = {"int": [0, 1000000]}
    text = {"str": [1, 32]}
    lib = {
        "schema": "c0.nominal_lib.v1",
        "records": [
            _record("Scene", [_field("ready", "bool")]),
            _record(
                "Accumulator",
                [
                    _field("name", text),
                    _field("total", scalar),
                    _field("action_ref", {"optional": "occurrence_ref"}),
                ],
            ),
            _record(
                "Sample",
                [_field("name", text)]
                + [_field(f"f{index:02d}", scalar) for index in range(32)]
                + [_field("secret", scalar)],
            ),
            _record(
                "Attempt",
                [_field("actor", text)] + [_field(f"r{index}", text) for index in range(8)],
            ),
            _record("Envelope", [_field("action", "occurrence_ref")]),
        ],
        "owners": [
            _owner("scene", "Scene"),
            _owner("accumulator", "Accumulator", ["name", "total", "action_ref"]),
            *[_owner(name, "Sample") for name in names],
        ],
    }
    ports = {
        "schema": "c0.graph_ports.v1",
        "scene_owner": "scene",
        "offer_provider": {"name": "finite_value", "version": "1", "limit": 16},
        "actions": [
            {
                "symbol": "accumulate",
                "actor": "accumulator",
                "payload": "Attempt",
                "envelope": "Envelope",
                "actor_identity_field": "name",
                "payload_actor_field": "actor",
                "participants": [
                    {
                        "name": f"r{index}",
                        "selector": "closed_domain",
                        "state": "Sample",
                        "payload_field": f"r{index}",
                        "write": False,
                    }
                    for index in range(8)
                ],
                "effects": {
                    "scene": [],
                    "actor": {"total": "total", "action_ref": "action_ref"},
                    **{f"r{index}": [] for index in range(8)},
                },
                "envelope_fields": ["action"],
                "schedule": None,
                "value": {
                    "read": _paths()[:count],
                    "fields": {},
                    "write_paths": ["actor.total", "actor.action_ref"],
                    "construct": [],
                    "collections": {},
                },
            }
        ],
        "events": [],
        "due_events": [],
    }
    return lib, ports


def _sum(paths):
    if not paths:
        return {"const": 0}
    if len(paths) == 1:
        return {"ref": paths[0]}
    middle = len(paths) // 2
    return {"add": [_sum(paths[:middle]), _sum(paths[middle:])]}


def _body(count):
    return {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {
            "all": [
                {"eq": [{"ref": "actor.name"}, {"ref": "payload.actor"}]},
                {"le": [0, _sum(_paths()[3:count])]},
            ]
        },
        "outputs": {
            "action": {"ref": "occurrence"},
            "action_ref": {"ref": "occurrence"},
            "total": {"add": [{"ref": "actor.total"}, _sum(_paths()[3:count])]},
        },
    }


def _direct(count=64):
    lib, ports = _documents(64)
    checked = check_nominal_lib(lib)
    value_ports = check_graph_ports(ports, checked).actions[0].ports.value_ports
    paths = frozenset(_paths()[:count])
    return checked, replace(value_ports, readable_paths=paths, admission_readable_paths=paths)


def _compile_value(count, ports):
    return compile_value_program(
        json.dumps(_body(count)),
        ports,
        state_outputs={"actor.total": "total", "actor.action_ref": "action_ref"},
    )


def _roots(layout):
    return {
        "scene": layout.record("Scene")(True),
        "actor": layout.record("Accumulator")("accumulator", 0, None),
        "payload": layout.record("Attempt")(
            "accumulator", *(f"reader_{index}" for index in range(8))
        ),
        **{
            f"r{owner}": layout.record("Sample")(
                f"reader_{owner}", *(owner * 32 + field + 1 for field in range(32)), 900000
            )
            for owner in range(8)
        },
    }


def _source(count):
    return {
        "schema": "c0.owner_graph.v6",
        "owners": ["scene", "accumulator", *(f"reader_{index}" for index in range(8))],
        "offer_provider": {"name": "finite_value", "version": "1"},
        "game_form": {"mode": "manual"},
        "actions": [
            {
                "name": "accumulate",
                "template": "accumulate",
                "actor": "accumulator",
                "source_key": "sample.read-budget.accumulate",
                "event_type": "sample.read-budget.accumulate.action",
                "law": {"ref": "action.accumulate", "args": {}},
                "participants": {
                    f"r{index}": {"actors": [f"reader_{index}"]} for index in range(8)
                },
            }
        ],
        "events": [],
        "seats": [
            {
                "name": "accumulator",
                "actor": "accumulator",
                "entries": ["accumulate"],
                "read": ["accumulator.name", "accumulator.total", "accumulator.action_ref"],
                "offers": [
                    {
                        "entry": "accumulate",
                        "label": "Accumulate samples",
                        "when": {"const": True},
                        "payload": {
                            f"r{index}": {"const": f"reader_{index}"} for index in range(8)
                        },
                    }
                ],
            }
        ],
        "lawdefs": [
            {
                "name": "action.accumulate",
                "family": "action",
                "formals": {},
                "body": {"value": _body(count)},
            }
        ],
    }


def _assets():
    return {
        "schema": "c0.owner_graph.assets.v1",
        "opening": {
            "scene": {"ready": True},
            "accumulator": {"name": "accumulator", "total": 0, "action_ref": None},
            **{
                f"reader_{owner}": {
                    "name": f"reader_{owner}",
                    **{f"f{field:02d}": owner * 32 + field + 1 for field in range(32)},
                    "secret": 900000,
                }
                for owner in range(8)
            },
        },
    }


def _wide_paths():
    return ["actor.name", "actor.total", "payload.actor"] + [
        f"r{owner}.f{outer:02d}.g{inner:02d}"
        for owner in range(8)
        for outer in range(32)
        for inner in range(32)
    ]


def _wide_documents(count):
    lib, ports = _documents(64)
    sample = lib["records"][2]
    for field in sample["fields"][1:-1]:
        field["type"] = "Leaf"
    lib["records"].append(
        _record("Leaf", [_field(f"g{index:02d}", {"int": [0, 1000000]}) for index in range(32)])
    )
    ports["actions"][0]["value"]["read"] = _wide_paths()[:count]
    return lib, ports


def _wide_direct(count=8192):
    lib, ports = _wide_documents(8192)
    checked = check_nominal_lib(lib)
    value_ports = check_graph_ports(ports, checked).actions[0].ports.value_ports
    paths = frozenset(_wide_paths()[:count])
    return checked, replace(value_ports, readable_paths=paths, admission_readable_paths=paths)


def _wide_body():
    body = _body(64)
    total = _sum([f"r{owner}.f00.g00" for owner in range(8)])
    body["guard"]["all"][1] = {"le": [0, total]}
    body["outputs"]["total"] = {"add": [{"ref": "actor.total"}, total]}
    return body


def _compile_wide_value(ports):
    return compile_value_program(
        json.dumps(_wide_body()),
        ports,
        state_outputs={"actor.total": "total", "actor.action_ref": "action_ref"},
    )


def _wide_assets():
    assets = _assets()
    for owner in range(8):
        for outer in range(32):
            assets["opening"][f"reader_{owner}"][f"f{outer:02d}"] = {
                f"g{inner:02d}": owner * 1024 + outer * 32 + inner + 1 for inner in range(32)
            }
    return assets


def _wide_roots(layout):
    assets = _wide_assets()["opening"]
    return {
        "scene": layout.record("Scene")(**assets["scene"]),
        "actor": layout.record("Accumulator")(**assets["accumulator"]),
        "payload": layout.record("Attempt")(
            "accumulator", *(f"reader_{index}" for index in range(8))
        ),
        **{
            f"r{owner}": layout.record("Sample")(
                f"reader_{owner}",
                *(
                    layout.record("Leaf")(**assets[f"reader_{owner}"][f"f{outer:02d}"])
                    for outer in range(32)
                ),
                900000,
            )
            for owner in range(8)
        },
    }


def _guard_documents(owner_count, nested_shapes=()):
    lib, ports = _documents(64)
    names = ["scene", "accumulator", *(f"reader_{index}" for index in range(owner_count - 2))]
    scalar = {"int": [0, 1000000]}
    fields = [_field("name", {"str": [1, 32]})] + [
        _field(f"f{index:02d}", scalar) for index in range(63 - len(nested_shapes))
    ]
    fields += [_field(f"detail{index}", f"Leaf{index}") for index in range(len(nested_shapes))]
    lib["records"] = [
        _record("State", fields),
        _record("Attempt", [_field("actor", {"str": [1, 32]})]),
        _record("Envelope", [_field("action", "occurrence_ref")]),
        *[
            _record(f"Leaf{index}", [_field(f"g{field:02d}", scalar) for field in range(size)])
            for index, size in enumerate(nested_shapes)
        ],
    ]
    lib["owners"] = [_owner(name, "State") for name in names]
    lib["owners"][0]["identity_field"] = None
    lib["owners"][1]["seat_read"] = ["name"]
    action = ports["actions"][0]
    action["participants"] = []
    action["effects"] = {"scene": [], "actor": {"f00": "value"}}
    action["value"] = {
        "read": ["actor.name", "payload.actor"],
        "fields": {},
        "write_paths": ["actor.f00"],
        "construct": [],
        "collections": {},
    }
    source = _source(64)
    source["owners"] = names
    source["actions"][0].pop("participants")
    source["seats"][0]["read"] = ["accumulator.name"]
    source["seats"][0]["offers"][0]["payload"] = {}
    source["lawdefs"][0]["body"]["value"] = {
        "schema": "c0.value.v1",
        "bindings": [],
        "guard": {"eq": [{"ref": "actor.name"}, {"ref": "payload.actor"}]},
        "outputs": {"action": {"ref": "occurrence"}, "value": {"const": 1}},
    }
    return lib, ports, source


def _guard_assets(lib):
    records = {record["name"]: record["fields"] for record in lib["records"]}

    def state(record, name):
        return {
            field["name"]: (
                name
                if field["name"] == "name"
                else state(field["type"], name)
                if type(field["type"]) is str
                else 0
            )
            for field in records[record]
        }

    return {
        "schema": "c0.owner_graph.assets.v1",
        "opening": {
            owner["symbol"]: state(owner["state"], owner["symbol"]) for owner in lib["owners"]
        },
    }


def _world_stop(source, when):
    source["due_events"] = []
    source["temporal"] = {
        "mechanism": "action_value_event_jump",
        "order": [],
        "max_pending": 0,
        "periodic": [],
    }
    source["game_form"] = {
        "mode": "action_value_event_jump",
        "seats": [
            {"seat": "accumulator", "tempo": 1, "eligible": True, "costs": {"accumulate": 1}}
        ],
        "end_at": 2,
        "max_same_time_actions": 2,
        "world_stops": [{"outcome": "stopped", "owners": source["owners"], "when": when}],
    }


def _add_one_guard_path(lib):
    records = {record["name"]: record for record in lib["records"]}
    state = deepcopy(records["State"])
    leaf = deepcopy(records[state["fields"][-1]["type"]])
    leaf["name"] = "OverflowLeaf"
    leaf["fields"].append(_field("extra", {"int": [0, 1000000]}))
    state["name"] = "OverflowState"
    state["fields"][-1]["type"] = "OverflowLeaf"
    lib["records"].extend([leaf, state])
    lib["owners"][0]["state"] = "OverflowState"


def _assert_limit(error, stage):
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "value_read_paths",
        8193,
        8192,
        stage,
    )


def _alter_ports(ir, **changes):
    return replace(ir, value=replace(ir.value, ports=replace(ir.value.ports, **changes)))


@pytest.mark.parametrize("count", [64, 65, 256, 8192])
def test_ports_accept_neutral_explicit_read_paths(count):
    lib, ports = _wide_documents(count) if count == 8192 else _documents(count)
    before = deepcopy((lib, ports))
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    assert len(graph.actions[0].ports.value_ports.readable_paths) == count
    assert graph.actions[0].ports.value_ports.admission_readable_paths == frozenset(
        ports["actions"][0]["value"]["read"]
    )
    assert (lib, ports) == before


def test_ports_reject_8193_before_ir_without_changing_input():
    lib, ports = _wide_documents(8193)
    before = deepcopy((lib, ports))
    with pytest.raises(C0CompileLimitError) as caught:
        check_graph_ports(ports, check_nominal_lib(lib))
    _assert_limit(caught.value, "Ports value readable paths")
    assert (lib, ports) == before


@pytest.mark.parametrize("count", [64, 65, 256, 8192])
def test_direct_compile_capture_and_independent_bind_share_read_budget(count, monkeypatch):
    checked, ports = _wide_direct(count) if count == 8192 else _direct(count)
    original = _compile_wide_value(ports) if count == 8192 else _compile_value(count, ports)
    ir = C0ValueBackend(checked.record_layout).capture(original)
    assert (
        ir.value.ports.readable_paths
        == ir.value.ports.admission_readable_paths
        == ports.readable_paths
    )

    def forbid_frontend(*args, **kwargs):
        pytest.fail("Bind must not rerun the expression frontend")

    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)
    layout = bind_nominal_records(checked.signatures)
    bound = C0ValueBackend(layout).bind(ir)
    roots = _wide_roots(layout) if count == 8192 else _roots(layout)
    before = dict(roots)
    result = bound.evaluate(roots, occurrence=K0OccurrenceRef(1))
    assert result == {
        "action": K0OccurrenceRef(1),
        "action_ref": K0OccurrenceRef(1),
        "total": sum(owner * 1024 + 1 for owner in range(8))
        if count == 8192
        else sum(range(1, count - 2)),
    }
    assert roots == before


@pytest.mark.parametrize("port", ["readable_paths", "admission_readable_paths"])
def test_direct_compile_rejects_8193_for_each_read_stage(port):
    _, ports = _wide_direct()
    ports = replace(ports, **{port: frozenset(_wide_paths()[:8193])})
    with pytest.raises(C0CompileLimitError) as caught:
        _compile_wide_value(ports)
    stage = "Value readable paths" if port == "readable_paths" else "Value admission readable paths"
    _assert_limit(caught.value, stage)


@pytest.mark.parametrize("port", ["readable_paths", "admission_readable_paths"])
def test_capture_rejects_a_frontend_value_with_forged_8193_path_ports(port):
    checked, ports = _wide_direct()
    original = _compile_wide_value(ports)
    forged = type(original)(
        original.guard_ir,
        original._tree,
        replace(ports, **{port: frozenset(_wide_paths()[:8193])}),
        original._admission_outputs,
        original._binding_types,
        original.effects,
    )
    with pytest.raises(C0CompileLimitError) as caught:
        C0ValueBackend(checked.record_layout).capture(forged)
    stage = "Value readable paths" if port == "readable_paths" else "Value admission readable paths"
    _assert_limit(caught.value, stage)


@pytest.mark.parametrize("port", ["readable_paths", "admission_readable_paths"])
@pytest.mark.parametrize("entry", ["backend", "direct"])
def test_bind_rejects_forged_8193_path_ir_without_recompiling(port, entry, monkeypatch):
    checked, ports = _wide_direct()
    ir = C0ValueBackend(checked.record_layout).capture(_compile_wide_value(ports))
    forged = _alter_ports(ir, **{port: frozenset(_wide_paths()[:8193])})

    def forbid_frontend(*args, **kwargs):
        pytest.fail("Bind must check its own ports")

    monkeypatch.setattr(values, "compile_value_program", forbid_frontend)
    monkeypatch.setattr(values, "_expr_type", forbid_frontend)
    layout = bind_nominal_records(checked.signatures)
    with pytest.raises(C0CompileLimitError) as caught:
        if entry == "backend":
            C0ValueBackend(layout).bind(forged)
        else:
            bind_value_program(forged.value, dict(layout.records))
    stage = "Value readable paths" if port == "readable_paths" else "Value admission readable paths"
    _assert_limit(caught.value, stage)


@pytest.mark.parametrize("count", [65, 256, 8192])
@pytest.mark.parametrize("entry", ["compile", "bind"])
def test_multi_owner_reads_write_only_one_owner_with_exact_occurrence(count, entry):
    lib, ports = _wide_documents(count) if count == 8192 else _documents(count)
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    source = _source(count)
    if count == 8192:
        source["lawdefs"][0]["body"]["value"] = _wide_body()
    if entry == "compile":
        program = compile_owner_graph(graph, source)
    else:
        ir, layout = check_owner_graph(graph, source)
        program = bind_program(ir, layout)
    session = program.start(_wide_assets() if count == 8192 else _assets())
    before = dict(session.author_snapshot().owners)
    offer = session.offers("accumulator")[0]
    result = session.submit("accumulator", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    after = dict(session.author_snapshot().owners)
    assert {name for name in before if before[name] != after[name]} == {"accumulator"}
    expected = (
        sum(owner * 1024 + 1 for owner in range(8)) if count == 8192 else sum(range(1, count - 2))
    )
    assert after["accumulator"].total == expected
    occurrence = session._runtime.occurrence_history()[0]
    assert occurrence.source.value == "sample.read-budget.accumulate"
    assert after["accumulator"].action_ref == occurrence.occurrence
    assert len(session._runtime.occurrence_history()) == 1
    assert all("reader_" not in path for path, _ in session.read("accumulator").fields)


@pytest.mark.parametrize("path", ["r0.secret", "r7.f31", "r0"])
@pytest.mark.parametrize("count", [65, 8192])
def test_more_read_capacity_does_not_grant_unlisted_fields_or_whole_owners(path, count):
    _, ports = _wide_direct() if count == 8192 else _direct(count)
    body = _wide_body() if count == 8192 else _body(count)
    body["guard"] = {"eq": [{"ref": path}, {"ref": path}]}
    with pytest.raises(C0LawError, match="declared read boundary"):
        compile_value_program(json.dumps(body), ports)


@pytest.mark.parametrize("fault", ["admission_path", "admission_field", "effect_field"])
@pytest.mark.parametrize("count", [65, 8192])
def test_bind_rechecks_admission_subset_and_field_grants(fault, count):
    checked, ports = _wide_direct() if count == 8192 else _direct(count)
    original = _compile_wide_value(ports) if count == 8192 else _compile_value(count, ports)
    ir = C0ValueBackend(checked.record_layout).capture(original)
    symbolic_ports = ir.value.ports
    unused = sorted(symbolic_ports.readable_paths)[-1]
    if fault == "admission_path":
        forged = _alter_ports(
            ir,
            admission_readable_paths=(symbolic_ports.admission_readable_paths - {unused})
            | {"r7.f31"},
        )
        message = "value read port is malformed"
    elif fault == "admission_field":
        fields = tuple(
            (carrier, names | {"secret"} if carrier.symbol == "Sample" else names)
            for carrier, names in symbolic_ports.admission_readable_fields
        )
        forged = _alter_ports(ir, admission_readable_fields=fields)
        message = "admission read port exceeds its effect port"
    else:
        paths = (symbolic_ports.readable_paths - {unused}) | {"r0.secret"}
        forged = _alter_ports(ir, readable_paths=paths, admission_readable_paths=paths)
        message = "field is not a declared read port"
    with pytest.raises(C0LawError, match=message):
        C0ValueBackend(bind_nominal_records(checked.signatures)).bind(forged)


def test_capture_and_bind_recheck_existing_frozen_tuple_projection():
    checked, ports = _direct(65)
    annotation = tuple[int, str]
    ports = replace(
        ports,
        tuple_fields={annotation: {"amount": 0}},
        admission_tuple_fields={annotation: {"amount": 0}},
    )
    backend = C0ValueBackend(checked.record_layout)
    ir = backend.capture(_compile_value(65, ports))
    rebound = C0ValueBackend(bind_nominal_records(checked.signatures)).bind(ir)
    assert rebound._ports.tuple_fields[annotation] == {"amount": 0}
    carrier, _ = ir.value.ports.tuple_fields[0]
    forged = _alter_ports(ir, tuple_fields=((carrier, (("amount", 2),)),))
    with pytest.raises(C0LawError, match="tuple projection is malformed"):
        backend.bind(forged)


@pytest.mark.parametrize("fault", ["fields", "participants", "write_paths", "outputs"])
def test_read_budget_does_not_enlarge_other_port_lists_or_record_fields(fault):
    lib, ports = _documents(256)
    action = ports["actions"][0]
    if fault == "fields":
        lib["records"][2]["fields"] = [_field(f"f{index}", "bool") for index in range(65)]
    elif fault == "participants":
        action["participants"] *= 9
    elif fault == "write_paths":
        action["value"]["write_paths"] = ["actor.total"] * 65
    else:
        action["value"]["outputs"] = {f"out{index}": "int" for index in range(65)}
    with pytest.raises(C0LawError, match="finite") as caught:
        check_graph_ports(ports, check_nominal_lib(lib))
    assert not isinstance(caught.value, C0CompileLimitError)
    assert COMPILE_BUDGET.value_read_paths == 8192


def test_constant_opening_guard_keeps_the_four_owner_260_path_regression():
    lib, ports, source = _guard_documents(4)
    assert len(lib["records"]) == 3 and len(lib["records"][0]["fields"]) == 64
    assert ports["actions"][0]["value"]["read"] == ["actor.name", "payload.actor"]
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    unguarded = compile_owner_graph(graph, source)
    source["opening_guard"] = {"const": True}
    before = deepcopy((lib, ports, source))
    guarded = compile_owner_graph(graph, source)
    assert len(guarded.opening_guard._ports.readable_paths) == 260
    assert (
        guarded.opening_guard._ports.readable_paths
        == guarded.opening_guard._ports.admission_readable_paths
    )
    assets = _guard_assets(lib)
    for program in (unguarded, guarded):
        session = program.start(assets)
        offer = session.offers("accumulator")[0]
        result = session.submit("accumulator", offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        assert dict(session.author_snapshot().owners)["accumulator"].f00 == 1
        history = session._runtime.occurrence_history()
        assert len(history) == 1 and history[0].source.value == "sample.read-budget.accumulate"
    assert (lib, ports, source) == before


@pytest.mark.parametrize("owner_count", [31, 64])
@pytest.mark.parametrize("nested_shapes", [(), (52,)])
def test_full_owner_opening_checks_keep_flat_and_nested_paths(owner_count, nested_shapes):
    lib, ports, source = _guard_documents(owner_count, nested_shapes)
    source["opening_guard"] = {"eq": [{"ref": "scene.f00"}, 0]}
    before = deepcopy((lib, ports, source))
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    ir, layout = check_owner_graph(graph, source)
    program = bind_program(ir, layout)
    assert len(program.opening_guard._ports.readable_paths) == owner_count * (
        65 + sum(nested_shapes)
    )
    assets = _guard_assets(lib)
    program.start(assets)
    assets["opening"]["scene"]["f00"] = 1
    with pytest.raises(C0BindingError, match="opening guard"):
        program.start(assets)
    assert (lib, ports, source) == before


@pytest.mark.parametrize("kind", ["opening", "world_stop"])
def test_full_owner_guards_share_8192_boundary_and_reject_8193(kind):
    owner_count, shapes = (64, (63,)) if kind == "opening" else (32, (64, 64, 63))
    lib, ports, source = _guard_documents(owner_count, shapes)
    if kind == "opening":
        source["opening_guard"] = {"const": True}
    else:
        _world_stop(source, {"const": True})
    graph = check_graph_ports(ports, check_nominal_lib(lib))
    program = compile_owner_graph(graph, source)
    predicate = (
        program.control_ir.opening
        if kind == "opening"
        else program.control_ir.world_stops[0].predicate
    )
    assert len(predicate.value.ports.readable_paths) == 8192
    assert predicate.value.ports.readable_paths == predicate.value.ports.admission_readable_paths
    assets = _guard_assets(lib)
    if kind == "world_stop":
        assets["time"] = 0
        assets["action_value_openings"] = [{"seat": "accumulator", "debt": 0, "tie_priority": 0}]
    session = program.start(assets)
    assert session._runtime.occurrence_history() == ()
    if kind == "world_stop":
        assert session.form_frame("accumulator").outcome == "stopped"
    _add_one_guard_path(lib)
    before = deepcopy((lib, ports, source))
    with pytest.raises(C0CompileLimitError) as caught:
        compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    _assert_limit(caught.value, "Value readable paths")
    assert (lib, ports, source) == before
