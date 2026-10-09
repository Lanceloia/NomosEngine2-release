"""One authored Object Law targets compatible opening and formed sorts."""

from __future__ import annotations

from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def _world():
    lib, ports, source, assets = (
        read_author_document(ROOT / f"object_target_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )
    return lib, ports, source, assets


def _compile(lib, ports, source):
    checked = check_nominal_lib(lib)
    return compile_owner_graph(check_graph_ports(ports, checked), source)


def _inspect(session, label: str) -> None:
    offer = next(item for item in session.offers("actor") if item.label == label)
    assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)


def test_one_source_law_reaches_opening_base_and_formed_specialization() -> None:
    lib, ports, source, assets = _world()
    assert sum(law["name"] == "action.inspect_consume" for law in lib["lawdefs"]) == 1
    assert source["operation_bindings"] == [
        {
            "receiver_sort": "EXAMPLE.TOOL@1",
            "operation": "inspect_v1",
            "using": "consuming_inspection",
        }
    ]
    assert sum(action["name"] == "inspect" for action in source["actions"]) == 1
    program = _compile(lib, ports, source)
    action = dict(program.actions)["inspect"]
    assert action.build_spec().participant_ports[0].families == ("fine_tool", "tool")
    assert tuple(kind.family for kind in program.profile.dynamic_owner_kinds) == tuple(
        port.family for port in program.object_plan.ports
    )
    session = program.start(assets)
    assert [item.label for item in session.offers("actor")] == ["Make a tool", "Inspect old"]
    _inspect(session, "Inspect old")
    assert isinstance(session.submit("actor", "make", {}), K0Published)
    opening, hidden, formed = session.author_object_instances()
    assert opening.sort != formed.sort
    assert opening.owner != formed.owner
    assert formed.formed_by is not None
    assert hidden.current_state.ready is True
    _inspect(session, "Inspect new")
    assert [item.current_state.ready for item in session.author_object_instances()] == [
        False,
        True,
        False,
    ]
    inspected = [
        item for item in session._runtime.occurrence_history() if item.source == action.source_key
    ]
    assert len(inspected) == 2
    assert [item.participants.target for item in inspected] == [
        opening.individual,
        formed.individual,
    ]
    assert [item.participants.target.family for item in inspected] == ["tool", "fine_tool"]


def test_source_binding_switch_changes_k0_result_for_both_sorts() -> None:
    lib, ports, source, assets = _world()
    source["operation_bindings"][0]["using"] = "preserving_inspection"
    session = _compile(lib, ports, source).start(assets)
    _inspect(session, "Inspect old")
    assert isinstance(session.submit("actor", "make", {}), K0Published)
    _inspect(session, "Inspect new")
    assert [item.current_state.ready for item in session.author_object_instances()] == [
        True,
        True,
        True,
    ]


@pytest.mark.parametrize(
    "fault",
    (
        "missing_binding",
        "foreign_implementation",
        "wrong_sort",
        "duplicate_binding",
        "direct_law",
        "null_operation",
        "wrong_offer",
    ),
)
def test_operation_binding_failures_reject_before_start(fault: str) -> None:
    lib, ports, source, _ = _world()
    if fault == "missing_binding":
        source["operation_bindings"] = []
    elif fault == "foreign_implementation":
        source["operation_bindings"][0]["using"] = "not_in_lib"
    elif fault == "wrong_sort":
        source["operation_bindings"][0]["receiver_sort"] = "EXAMPLE.FINE_TOOL@1"
    elif fault == "duplicate_binding":
        source["operation_bindings"].append(dict(source["operation_bindings"][0]))
    elif fault == "direct_law":
        source["actions"][1]["law"] = {"ref": "action.inspect_consume", "args": {}}
        del source["actions"][1]["operation"]
    elif fault == "null_operation":
        source["actions"][1]["operation"] = None
    else:
        source["seats"][0]["offers"][1]["operation"] = "foreign"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_operation_implementation_cannot_expand_declared_read_ports() -> None:
    lib, ports, source, _ = _world()
    law = next(item for item in lib["lawdefs"] if item["name"] == "action.inspect_consume")
    law["body"]["value"]["guard"]["all"].append({"ref": "target.secret"})
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_unselected_operation_implementation_also_obeys_ports() -> None:
    lib, ports, source, _ = _world()
    law = next(item for item in lib["lawdefs"] if item["name"] == "action.inspect_preserve")
    law["body"]["value"]["guard"]["all"].append({"ref": "target.secret"})
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(lib, ports, source)


@pytest.mark.parametrize(
    "fault", ("foreign_law", "foreign_unselected_law", "wrong_receiver", "wrong_template")
)
def test_lib_operation_must_match_declared_ports_and_law(fault: str) -> None:
    lib, ports, source, _ = _world()
    operation = ports["operations"][0]
    if fault == "foreign_law":
        operation["implementations"][0]["law"] = "action.absent"
    elif fault == "foreign_unselected_law":
        operation["implementations"][1]["law"] = "action.absent"
    elif fault == "wrong_receiver":
        operation["receiver_sort"] = "EXAMPLE.FINE_TOOL@1"
    else:
        operation["action_template"] = "make"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_unrelated_sort_is_neither_offered_nor_admitted() -> None:
    lib, ports, source, assets = _world()
    lib["object_kinds"].append(
        {
            "symbol": "stone",
            "sort": "EXAMPLE.STONE@1",
            "state": "Tool",
            "version": "stone-v1",
            "max_instances": 2,
        }
    )
    source["object_kinds"].append({"kind": "stone", "sort": "EXAMPLE.STONE@1"})
    assets["opening_objects"].append(
        {"kind": "stone", "state": {"label": "stone", "ready": True, "visible": True}}
    )
    session = _compile(lib, ports, source).start(assets)
    stone = next(
        item for item in session.author_object_instances() if item.individual.family == "stone"
    )
    assert "Inspect stone" not in [item.label for item in session.offers("actor")]
    with pytest.raises(C0BindingError, match="current seat offer"):
        session.submit("actor", "inspect", {"target": stone.individual})
    action = dict(session.program.actions)["inspect"]
    actor = session._runtime.read_owner(action.actor_owner.key).view
    before = session._runtime.occurrence_history()
    assert isinstance(
        session._runtime.settle(
            _K0InMemoryActionAttempt(
                action.source_key, action.payload_type(actor.name, stone.individual)
            )
        ),
        K0NotAdmitted,
    )
    assert session._runtime.occurrence_history() == before
    assert session.author_object_instances()[-1].current_state.ready is True


def test_unselected_specialization_cannot_be_formed_or_targeted() -> None:
    lib, ports, source, assets = _world()
    source["object_kinds"] = [
        item for item in source["object_kinds"] if item["kind"] != "fine_tool"
    ]
    with pytest.raises(C0LawError, match="unselected Object kind"):
        _compile(lib, ports, source)

    source["actions"][0]["form"]["kind"] = "tool"
    program = _compile(lib, ports, source)
    assert dict(program.actions)["inspect"].build_spec().participant_ports[0].families == ("tool",)
    session = program.start(assets)
    assert [item.label for item in session.offers("actor")] == ["Make a tool", "Inspect old"]


def test_selected_descendant_can_specialize_through_unselected_intermediate_sort() -> None:
    lib, ports, source, assets = _world()
    lib["object_kinds"].append(
        {
            "symbol": "intermediate_tool",
            "sort": "EXAMPLE.INTERMEDIATE_TOOL@1",
            "state": "Tool",
            "version": "intermediate-v1",
            "max_instances": 2,
            "specializes": ["EXAMPLE.TOOL@1"],
        }
    )
    fine = next(item for item in lib["object_kinds"] if item["symbol"] == "fine_tool")
    fine["specializes"] = ["EXAMPLE.INTERMEDIATE_TOOL@1"]
    program = _compile(lib, ports, source)
    assert dict(program.actions)["inspect"].build_spec().participant_ports[0].families == (
        "fine_tool",
        "tool",
    )
    session = program.start(assets)
    assert isinstance(session.submit("actor", "make", {}), K0Published)
    _inspect(session, "Inspect new")


@pytest.mark.parametrize("fault", ("foreign_parent", "cycle", "duplicate", "wrong_state"))
def test_invalid_specialization_or_state_is_rejected_before_start(fault: str) -> None:
    lib, ports, source, _ = _world()
    child = next(item for item in lib["object_kinds"] if item["symbol"] == "fine_tool")
    if fault == "foreign_parent":
        child["specializes"] = ["EXAMPLE.UNKNOWN@1"]
    elif fault == "cycle":
        base = next(item for item in lib["object_kinds"] if item["symbol"] == "tool")
        base["specializes"] = ["EXAMPLE.FINE_TOOL@1"]
    elif fault == "duplicate":
        child["specializes"].append("EXAMPLE.TOOL@1")
    else:
        lib["records"].append(
            {
                "name": "OtherTool",
                "fields": [
                    {"name": "label", "type": {"str": [1, 64]}},
                    {"name": "ready", "type": "bool"},
                    {"name": "visible", "type": "bool"},
                ],
                "invariant": None,
            }
        )
        child["state"] = "OtherTool"
        source["actions"][0]["form"]["kind"] = "tool"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
