"""A current offer may carry a bounded, read-only Actor-local forecast."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_contract_v1 import C0LawError
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
            "name": "KnownTool",
            "fields": [
                {"name": "station", "type": {"str": [1, 64]}},
                {"name": "label", "type": {"str": [1, 64]}},
            ],
            "invariant": None,
        },
    )
    actor = next(item for item in lib["records"] if item["name"] == "Actor")
    actor["fields"].extend(
        [
            {"name": "station", "type": {"str": [1, 64]}},
            {"name": "known_tools", "type": {"tuple": {"item": "KnownTool", "max": 8}}},
        ]
    )
    attempt = next(item for item in lib["records"] if item["name"] == "InspectAttempt")
    attempt["fields"].append({"name": "choice", "type": {"str": [1, 64]}})
    ports["seat_offer_previews"] = [
        {
            "symbol": "inspect_condition",
            "actor": "actor",
            "action_template": "inspect",
            "collection_field": "known_tools",
            "current_field": "station",
            "candidate_origin_field": "station",
            "candidate_key": "label",
            "offer_payload_key": "choice",
            "fixed_individual_root": {
                "name": "tool",
                "kind": "tool",
                "binding": "fixed_unique_opening",
            },
            "max_candidates": 8,
            "value": {
                "read": ["actor.station", "candidate.station", "candidate.label", "tool.ready"],
                "fields": {"KnownTool": ["station", "label"]},
                "write_paths": [],
                "outputs": {"condition": "str"},
                "construct": [],
                "collections": {},
            },
        }
    ]
    source["lawdefs"].append(
        {
            "name": "view.tool_condition",
            "family": "seat_view",
            "formals": {},
            "body": {
                "value": {
                    "schema": "c0.value.v1",
                    "bindings": [],
                    "guard": {"eq": [{"ref": "actor.station"}, {"ref": "candidate.station"}]},
                    "outputs": {
                        "condition": {
                            "if": {
                                "when": {"ref": "tool.ready"},
                                "then": {"const": "ready"},
                                "else": {"const": "spent"},
                            }
                        }
                    },
                }
            },
        }
    )
    source["seats"][0]["offer_previews"] = [
        {
            "template": "inspect_condition",
            "entry": "inspect",
            "law": {"ref": "view.tool_condition", "args": {}},
        }
    ]
    inspect = next(item for item in source["seats"][0]["offers"] if item["entry"] == "inspect")
    inspect["payload"]["choice"] = {"ref": "target.label"}
    assets["opening"]["actor"].update(
        {"station": "bench", "known_tools": [{"station": "bench", "label": "old"}]}
    )
    assets["opening_objects"] = [assets["opening_objects"][0]]
    return lib, ports, source, assets


def _program(lib, ports, source):
    return compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def test_offer_preview_is_read_only_and_action_still_settles_through_k0() -> None:
    lib, ports, source, assets = _authored()
    session = _program(lib, ports, source).start(assets)
    before = session.author_snapshot()
    offer = next(item for item in session.offers("actor") if item.entry == "inspect")
    assert offer.preview == (("condition", "ready"),)
    assert session.author_snapshot() == before
    assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)
    assert session.author_object_instances()[0].current_state.ready is False
    assert not any(item.entry == "inspect" for item in session.offers("actor"))


def test_missing_local_preview_candidate_cannot_suppress_a_legal_action() -> None:
    lib, ports, source, assets = _authored()
    assets["opening"]["actor"]["known_tools"] = []
    session = _program(lib, ports, source).start(assets)
    before = session.author_snapshot()
    offers, faults = session._offer_projection("actor")
    inspect = next(item for item in offers if item.entry == "inspect")
    assert faults == () and inspect.preview == ()
    assert session.author_snapshot() == before
    assert isinstance(session.submit("actor", inspect.entry, dict(inspect.payload)), K0Published)


def test_offer_preview_rejects_foreign_action_binding_at_compile() -> None:
    lib, ports, source, _ = _authored()
    source["seats"][0]["offer_previews"][0]["entry"] = "make"
    with pytest.raises(C0LawError, match="offer preview"):
        _program(lib, ports, source)


def test_offer_preview_rejects_malformed_lib_and_direct_port() -> None:
    lib, ports, source, _ = _authored()
    ports["seat_offer_previews"][0]["action_template"] = []
    with pytest.raises(C0LawError, match="offer preview"):
        _program(lib, ports, source)
    ports["seat_offer_previews"][0]["action_template"] = "inspect"
    library = check_graph_ports(ports, check_nominal_lib(lib))
    malformed = replace(
        library,
        seat_offer_preview_ports=(
            replace(library.seat_offer_preview_ports[0], offer_payload_key="missing"),
        ),
    )
    with pytest.raises(C0LawError, match="closed port"):
        compile_owner_graph(malformed, source)


def test_offer_preview_key_must_be_in_the_visible_offer_payload() -> None:
    lib, ports, source, _ = _authored()
    ports["seat_offer_previews"][0]["offer_payload_key"] = "actor"
    with pytest.raises(C0LawError, match="key is absent from the current offer"):
        _program(lib, ports, source)


def test_new_same_kind_object_does_not_remove_existing_offers() -> None:
    lib, ports, source, assets = _authored()
    source["actions"][0]["form"]["kind"] = "tool"
    session = _program(lib, ports, source).start(assets)
    make = next(item for item in session.offers("actor") if item.entry == "make")
    assert isinstance(session.submit("actor", make.entry, dict(make.payload)), K0Published)
    inspect = tuple(item for item in session.offers("actor") if item.entry == "inspect")
    assert inspect
    assert any(dict(item.payload)["choice"] == "old" and item.preview for item in inspect)
    new = next(item for item in inspect if dict(item.payload)["choice"] == "new")
    assert new.preview == ()
    assert isinstance(session.submit("actor", new.entry, dict(new.payload)), K0Published)


def test_duplicate_local_preview_candidate_cannot_suppress_a_legal_action() -> None:
    lib, ports, source, assets = _authored()
    assets["opening"]["actor"]["known_tools"].append({"station": "bench", "label": "old"})
    session = _program(lib, ports, source).start(assets)
    before = session.author_snapshot()
    offers, faults = session._offer_projection("actor")
    inspect = next(item for item in offers if item.entry == "inspect")
    assert faults == () and inspect.preview == ()
    assert session.author_snapshot() == before
