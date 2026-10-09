"""Data-only graph ports form the C0/K0 boundary without package Python wiring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef, K0SourceSpecKey
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.examples.parcel_delivery_v0 import ROOT, main
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _ports() -> dict[str, object]:
    return json.loads((ROOT / "parcel_delivery_v0.ports.json").read_text(encoding="utf-8"))


def _compile(ports: dict[str, object]) -> None:
    nominal = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    graph = check_graph_ports(ports, nominal)
    compile_owner_graph(
        graph, (ROOT / "parcel_delivery_v0.source.json").read_text(encoding="utf-8")
    )


def test_declared_action_event_and_due_ports_compile_one_world() -> None:
    _compile(_ports())


def test_tuple_output_accepts_declared_occurrence_refs_only() -> None:
    nominal = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    ports = _ports()
    ports["actions"][0]["value"]["outputs"]["contributions"] = {"tuple": "occurrence_ref"}
    graph = check_graph_ports(ports, nominal)
    assert (
        graph.actions[0].ports.value_ports.outputs["contributions"] == tuple[K0OccurrenceRef, ...]
    )

    ports["actions"][0]["value"]["outputs"]["contributions"] = {"tuple": "unknown"}
    with pytest.raises(C0LawError, match="tuple output"):
        check_graph_ports(ports, nominal)


def test_due_ports_can_name_an_additional_static_owner_root() -> None:
    ports = _ports()
    due = ports["due_events"][0]
    due["owner_roots"] = ["receiver"]
    due["value"]["read"].append("receiver.name")
    _compile(ports)

    duplicate = json.loads(json.dumps(ports))
    duplicate["due_events"][0]["owner_roots"].append("receiver")
    with pytest.raises(C0LawError, match="owner roots"):
        _compile(duplicate)


def test_due_event_binds_exactly_one_opening_object_and_retains_its_ref() -> None:
    nominal = json.loads((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    nominal["records"].append(
        {
            "name": "Marker",
            "fields": [{"name": "value", "type": {"str": [1, 24]}}],
            "invariant": None,
        }
    )
    nominal["object_kinds"] = [
        {
            "symbol": "marker",
            "sort": "TEST.MARKER@1",
            "state": "Marker",
            "version": "marker-v1",
            "max_instances": 2,
        }
    ]
    checked = check_nominal_lib(nominal)
    ports = _ports()
    due = ports["due_events"][0]
    due["fixed_individual_roots"] = [
        {"name": "marker_view", "kind": "marker", "binding": "fixed_unique_opening"}
    ]
    due["value"]["read"].append("marker_view.value")
    graph = check_graph_ports(ports, checked)
    source = json.loads((ROOT / "parcel_delivery_v0.source.json").read_text(encoding="utf-8"))
    source["object_kinds"] = [{"kind": "marker", "sort": "TEST.MARKER@1"}]
    due_law = next(item for item in source["lawdefs"] if item["name"] == "event.arrive")
    due_law["body"]["law"]["guard"] = {
        "all": [
            due_law["body"]["law"]["guard"],
            {"eq": [{"ref": "marker_view.value"}, {"const": "ready"}]},
        ]
    }
    program = compile_owner_graph(graph, source)
    assets = json.loads((ROOT / "parcel_delivery_v0.a.assets.json").read_text(encoding="utf-8"))
    assets["opening_objects"] = [{"kind": "marker", "state": {"value": "ready"}}]
    session = program.start(assets)
    individual = session._runtime.individuals()[0].individual
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    session.defer_form("sender")
    session.defer_form("receiver")
    session.continue_form("sender")
    due_occurrence = next(
        item
        for item in session._runtime.occurrence_history()
        if item.source == K0SourceSpecKey("c0.parcel.arrive.due")
    )
    assert due_occurrence.participants.fixed_individuals == (("marker_view", individual),)
    assert due_occurrence.semantic_envelope.fixed_individuals == (("marker_view", individual),)
    assert due_occurrence.selected_owners[0].selector == individual

    missing = json.loads(json.dumps(assets))
    missing["opening_objects"] = []
    with pytest.raises(C0BindingError, match="opening owner state is not admitted"):
        program.start(missing)
    duplicate = json.loads(json.dumps(assets))
    duplicate["opening_objects"].append({"kind": "marker", "state": {"value": "ready"}})
    with pytest.raises(C0BindingError, match="opening owner state is not admitted"):
        program.start(duplicate)


@pytest.mark.parametrize(
    "change",
    (
        "unknown_actor",
        "unknown_payload",
        "unknown_read_field",
        "unbounded_scene_symbol",
        "bad_event_form",
    ),
)
def test_bad_port_declaration_is_finitely_rejected(change: str) -> None:
    ports = _ports()
    if change == "unknown_actor":
        ports["actions"][0]["actor"] = "foreigner"
    elif change == "unknown_payload":
        ports["actions"][0]["payload"] = "MissingRecord"
    elif change == "unknown_read_field":
        ports["actions"][0]["value"]["read"].append("scene.parcel.missing")
    elif change == "unbounded_scene_symbol":
        ports["scene_owner"] = "x" * 263000
    else:
        ports["events"][0]["form"] = "unknown_form"
    with pytest.raises(C0LawError):
        _compile(ports)


def test_template_identity_is_source_only_not_an_inert_lib_knob() -> None:
    ports = _ports()
    ports["actions"][0]["source_key"] = "foreign.key"
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        _compile(ports)


def test_source_can_bind_a_new_action_identity_without_port_edit() -> None:
    nominal = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    graph = check_graph_ports(_ports(), nominal)
    source = json.loads((ROOT / "parcel_delivery_v0.source.json").read_text(encoding="utf-8"))
    source["actions"][0]["source_key"] = "c0.parcel.alternate.dispatch"
    program = compile_owner_graph(graph, source)
    assets = (ROOT / "parcel_delivery_v0.a.assets.json").read_text(encoding="utf-8")
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    assert session._runtime.occurrence_history()[0].source == K0SourceSpecKey(
        "c0.parcel.alternate.dispatch"
    )


def test_builtin_port_types_cannot_be_shadowed_by_records() -> None:
    nominal = json.loads((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    nominal["records"].append(
        {
            "name": "time",
            "fields": [{"name": "ordinal", "type": {"int": [0, 10]}}],
            "invariant": None,
        }
    )
    checked = check_nominal_lib(nominal)
    with pytest.raises(C0LawError, match="collides"):
        check_graph_ports(_ports(), checked)


def test_scene_owner_symbol_is_an_explicit_lib_binding() -> None:
    nominal = json.loads((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    nominal["owners"][0]["symbol"] = "world"
    checked = check_nominal_lib(nominal)
    ports = _ports()
    ports["scene_owner"] = "world"
    graph = check_graph_ports(ports, checked)
    assert graph.actions[0].ports.scene_owner is checked.owner("world").owner


@pytest.mark.parametrize("change", ("drop_read", "drop_write", "wrong_output", "wrong_actor_field"))
def test_source_law_cannot_escape_declared_port_boundary(change: str) -> None:
    ports = _ports()
    if change == "drop_read":
        ports["actions"][0]["value"]["read"].remove("scene.parcel.status")
    elif change == "drop_write":
        ports["events"][0]["value"]["write_paths"].remove("scene.parcel.status")
    elif change == "wrong_output":
        ports["actions"][0]["value"]["outputs"]["delay"] = "str"
    else:
        ports["actions"][0]["actor_identity_field"] = "missing"
    with pytest.raises(C0LawError):
        _compile(ports)


def test_bad_explicit_ports_file_has_no_python_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ports = _ports()
    ports["events"][0]["form"] = "unknown_form"
    path = tmp_path / "broken.ports.json"
    path.write_text(json.dumps(ports), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["parcel_delivery_v0", "--ports", str(path)])
    with pytest.raises(SystemExit) as outcome:
        main()
    assert outcome.value.code == 2
    assert "Cannot build parcel world:" in capsys.readouterr().err
