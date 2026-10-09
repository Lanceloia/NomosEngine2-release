"""A seat read projection observes current K0 state without publishing world writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph

EXAMPLES = Path(__file__).resolve().parents[2] / "src" / "nomos_c0" / "examples"


def _authored():
    stem = EXAMPLES / "object_target_v1"
    lib = deepcopy(read_author_document(stem.with_suffix(".lib.yaml")).to_data())
    ports = deepcopy(read_author_document(stem.with_suffix(".ports.yaml")).to_data())
    source = deepcopy(read_author_document(stem.with_suffix(".source.yaml")).to_data())
    assets = deepcopy(read_author_document(stem.with_suffix(".assets.yaml")).to_data())
    lib["records"].insert(
        1,
        {
            "name": "KnownLabel",
            "fields": [{"name": "label", "type": {"str": [1, 64]}}],
            "invariant": None,
        },
    )
    actor = next(item for item in lib["records"] if item["name"] == "Actor")
    actor["fields"].extend(
        [
            {"name": "focus_label", "type": {"str": [1, 64]}},
            {"name": "known_labels", "type": {"tuple": {"item": "KnownLabel", "max": 8}}},
        ]
    )
    ports["seat_read_projections"] = [
        {
            "symbol": "known_tool_condition",
            "actor": "actor",
            "collection_field": "known_labels",
            "current_field": "focus_label",
            "candidate_key": "label",
            "fixed_individual_root": {
                "name": "tool",
                "kind": "tool",
                "binding": "fixed_unique_opening",
            },
            "max_candidates": 8,
            "value": {
                "read": ["scene.title", "candidate.label", "tool.label", "tool.ready"],
                "fields": {"KnownLabel": ["label"]},
                "write_paths": [],
                "outputs": {"condition": "str"},
                "construct": [],
                "collections": {},
            },
        }
    ]
    source["lawdefs"].append(
        {
            "name": "view.known_tool_condition",
            "family": "seat_view",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": {
                        "eq": [{"ref": "scene.title"}, {"const": "Object target experiment"}]
                    },
                    "outputs": {
                        "condition": {
                            "if": {
                                "when": {
                                    "all": [
                                        {"eq": [{"ref": "candidate.label"}, {"ref": "tool.label"}]},
                                        {"ref": "tool.ready"},
                                    ]
                                },
                                "then": {"const": "ready"},
                                "else": {"const": "spent"},
                            }
                        }
                    },
                }
            },
        }
    )
    source["seats"][0]["read_projection"] = {
        "template": "known_tool_condition",
        "law": {"ref": "view.known_tool_condition", "args": {}},
    }
    assets["opening"]["actor"].update({"focus_label": "old", "known_labels": [{"label": "old"}]})
    assets["opening_objects"] = [assets["opening_objects"][0]]
    return lib, ports, source, assets


def _program(lib, ports, source):
    return compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def test_seat_read_follows_current_object_after_a_real_action() -> None:
    lib, ports, source, assets = _authored()
    session = _program(lib, ports, source).start(assets)
    expected = (("old", (("condition", "ready"),)),)
    before = session.author_snapshot()
    assert dict(session.read("actor").fields)["known_tool_condition"] == expected
    assert session.author_snapshot() == before
    assert "scene.title" not in dict(session.read("actor").fields)
    inspect = next(item for item in session.offers("actor") if item.entry == "inspect")
    assert isinstance(session.submit("actor", inspect.entry, dict(inspect.payload)), K0Published)
    assert dict(session.read("actor").fields)["known_tool_condition"] == (
        ("old", (("condition", "spent"),)),
    )


def test_seat_read_requires_its_unique_opening_object() -> None:
    lib, ports, source, assets = _authored()
    assets["opening_objects"] = []
    with pytest.raises(C0BindingError, match="one opening individual"):
        _program(lib, ports, source).start(assets)


def test_seat_read_rejects_repeated_local_candidates() -> None:
    lib, ports, source, assets = _authored()
    assets["opening"]["actor"]["known_labels"].append({"label": "old"})
    session = _program(lib, ports, source).start(assets)
    before = session.author_snapshot()
    with pytest.raises(C0BindingError, match="cannot evaluate current state"):
        session.read("actor")
    assert session.author_snapshot() == before


def test_seat_read_rejects_missing_current_local_candidate() -> None:
    lib, ports, source, assets = _authored()
    assets["opening"]["actor"]["focus_label"] = "unseen"
    session = _program(lib, ports, source).start(assets)
    with pytest.raises(C0BindingError, match="cannot evaluate current state"):
        session.read("actor")


def test_seat_read_rejects_wrong_actor_binding_at_compile() -> None:
    lib, ports, source, _ = _authored()
    ports["seat_read_projections"][0]["actor"] = "scene"
    with pytest.raises(C0LawError, match="unknown root"):
        _program(lib, ports, source)


def test_direct_library_rejects_malformed_seat_read_port() -> None:
    lib, ports, source, _ = _authored()
    library = check_graph_ports(ports, check_nominal_lib(lib))
    malformed = replace(
        library,
        seat_read_ports=(replace(library.seat_read_ports[0], candidate_key="missing"),),
    )
    with pytest.raises(C0LawError, match="closed port"):
        compile_owner_graph(malformed, source)
