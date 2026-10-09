"""Author Object sorts and opening instances reach one private K0 Session."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._dynamic_owner_abi import _K0DynamicOwnerKind
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.object_owner_binding_v1 import _bind_object_owner_plan
from nomos_c0.owner_graph_v1 import compile_owner_graph

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _json(name: str) -> dict[str, object]:
    return json.loads((ROOT / f"parcel_delivery_v0.{name}.json").read_text(encoding="utf-8"))


def _lib() -> dict[str, object]:
    lib = _json("lib")
    lib["records"].append(
        {
            "name": "Tool",
            "fields": [
                {"name": "label", "type": {"str": [1, 64]}},
                {"name": "ready", "type": "bool"},
            ],
            "invariant": None,
        }
    )
    lib["object_kinds"] = [
        {
            "symbol": "tool",
            "sort": "EXAMPLE.TOOL@1",
            "state": "Tool",
            "version": "tool-v1",
            "max_instances": 2,
        }
    ]
    return lib


def _source() -> dict[str, object]:
    source = _json("source")
    source["object_kinds"] = [{"kind": "tool", "sort": "EXAMPLE.TOOL@1"}]
    return source


def _assets() -> dict[str, object]:
    assets = _json("a.assets")
    assets["opening_objects"] = [
        {"kind": "tool", "state": {"label": "A", "ready": True}},
        {"kind": "tool", "state": {"label": "B", "ready": False}},
    ]
    return assets


def _program(lib: dict[str, object] | None = None, source: dict[str, object] | None = None):
    checked = check_nominal_lib(_lib() if lib is None else lib)
    graph = check_graph_ports(_json("ports"), checked)
    return compile_owner_graph(graph, _source() if source is None else source)


def test_source_object_sort_and_assets_open_two_distinct_individual_owners() -> None:
    program = _program()
    assert program.object_plan.ports[0].sort.identity.value == "EXAMPLE.TOOL@1"
    assert tuple(kind.family for kind in program.profile.dynamic_owner_kinds) == tuple(
        port.family for port in program.object_plan.ports
    )
    session = program.start(_assets())
    bindings = session._runtime.individuals()
    assert len(bindings) == 2
    assert bindings[0].owner != bindings[1].owner
    assert all(item.formed_by is None for item in bindings)
    assert [session._runtime.read_individual(item.individual).view.label for item in bindings] == [
        "A",
        "B",
    ]
    second = program.start(_assets())
    assert bindings[0].individual != second._runtime.individuals()[0].individual
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    assert session._runtime.individuals() == bindings
    assert session._runtime.read_individual(bindings[1].individual).view.label == "B"


@pytest.mark.parametrize(
    "fault", ("missing", "extra", "wrong_sort", "wrong_family", "wrong_state", "wrong_capacity")
)
def test_object_owner_plan_must_match_k0_kind_before_profile_assembly(fault: str) -> None:
    program = _program()
    plan = program.object_plan
    selected = program.object_kinds
    if fault == "missing":
        plan = None
    elif fault == "extra":
        selected = selected + selected
    else:
        port = plan.ports[0]
        changed = {
            "wrong_sort": {
                "sort": replace(port.sort, identity=replace(port.sort.identity, value="OTHER@1"))
            },
            "wrong_family": {"family": "other"},
            "wrong_state": {"state_record": "Other"},
            "wrong_capacity": {"max_instances": port.max_instances + 1},
        }[fault]
        plan = replace(plan, ports=(replace(port, **changed),))
    with pytest.raises(C0LawError, match="Object owner plan|selected Object kinds"):
        _bind_object_owner_plan(plan, selected)


@pytest.mark.parametrize("fault", ("wrong_sort", "duplicate", "foreign"))
def test_source_cannot_misbind_selected_object_sort(fault: str) -> None:
    source = _source()
    if fault == "wrong_sort":
        source["object_kinds"][0]["sort"] = "EXAMPLE.OTHER@1"
    elif fault == "duplicate":
        source["object_kinds"].append(source["object_kinds"][0].copy())
    else:
        source["object_kinds"][0]["kind"] = "foreign"
    with pytest.raises(C0LawError):
        _program(source=source)


def test_source_can_select_no_kind_from_a_larger_lib() -> None:
    source = _json("source")
    program = _program(source=source)
    assert program.object_kinds == ()
    assert program.object_plan is None
    assert program.start(_json("a.assets"))._runtime.individuals() == ()


def test_explicit_null_object_selection_is_not_omission() -> None:
    source = _json("source")
    source["object_kinds"] = None
    with pytest.raises(C0LawError):
        _program(source=source)


def test_direct_graph_cannot_claim_a_different_k0_owner_family() -> None:
    checked = check_nominal_lib(_lib())
    graph = check_graph_ports(_json("ports"), checked)
    item = graph.object_kinds[0]
    wrong = replace(item, k0_kind=replace(item.k0_kind, family="other"))
    assert type(wrong.k0_kind) is _K0DynamicOwnerKind
    with pytest.raises(C0LawError):
        compile_owner_graph(replace(graph, object_kinds=(wrong,)), _source())


def test_direct_graph_cannot_mix_same_named_states_from_two_lib_compilations() -> None:
    first = check_nominal_lib(_lib())
    second = check_nominal_lib(_lib())
    graph = check_graph_ports(_json("ports"), first)
    item = graph.object_kinds[0]
    assert item.k0_kind.state_type is not second.record("Tool")
    with pytest.raises(K0ProfileError, match="factory"):
        replace(item.k0_kind, state_type=second.record("Tool"))


def test_source_selects_a_proper_subset_of_lib_object_kinds() -> None:
    lib = _lib()
    lib["records"].append(
        {
            "name": "Token",
            "fields": [{"name": "mark", "type": {"str": [1, 64]}}],
            "invariant": None,
        }
    )
    lib["object_kinds"].append(
        {
            "symbol": "token",
            "sort": "EXAMPLE.TOKEN@1",
            "state": "Token",
            "version": "token-v1",
            "max_instances": 2,
        }
    )
    program = _program(lib=lib)
    assert tuple(item.symbol for item in program.object_kinds) == ("tool",)
    assert tuple(port.family for port in program.object_plan.ports) == ("tool",)
    assert len(program.start(_assets())._runtime.individuals()) == 2


def test_object_kind_does_not_become_a_static_owner_symbol() -> None:
    source = _source()
    source["owners"].append("tool")
    with pytest.raises(C0LawError):
        _program(source=source)


@pytest.mark.parametrize("fault", ("missing", "foreign", "malformed_state", "over_capacity"))
def test_assets_cannot_smuggle_or_overfill_opening_objects(fault: str) -> None:
    assets = _assets()
    if fault == "missing":
        del assets["opening_objects"]
    elif fault == "foreign":
        assets["opening_objects"][0]["kind"] = "foreign"
    elif fault == "malformed_state":
        assets["opening_objects"][0]["state"]["ready"] = "yes"
    else:
        assets["opening_objects"].append({"kind": "tool", "state": {"label": "C", "ready": True}})
    with pytest.raises(C0BindingError):
        _program().start(assets)


@pytest.mark.parametrize("fault", ("duplicate_sort", "unknown_state", "bad_capacity"))
def test_lib_rejects_invalid_object_kind_declarations(fault: str) -> None:
    lib = _lib()
    if fault == "duplicate_sort":
        duplicate = lib["object_kinds"][0].copy()
        duplicate["symbol"] = "other"
        lib["object_kinds"].append(duplicate)
    elif fault == "unknown_state":
        lib["object_kinds"][0]["state"] = "Absent"
    else:
        lib["object_kinds"][0]["max_instances"] = 0
    with pytest.raises(C0LawError):
        check_nominal_lib(lib)


def test_existing_source_and_assets_without_objects_remain_valid() -> None:
    checked = check_nominal_lib(_json("lib"))
    graph = check_graph_ports(_json("ports"), checked)
    session = compile_owner_graph(graph, _json("source")).start(_json("a.assets"))
    assert session._runtime.individuals() == ()
    foreign = _json("a.assets")
    foreign["opening_objects"] = []
    with pytest.raises(C0BindingError):
        compile_owner_graph(graph, _json("source")).start(foreign)
