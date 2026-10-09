"""Ports charge canonical declaration size, not generated JSON formatting spaces."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_world_binding_v1 import _documents

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import parse_author_document
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib

LIMIT = 262144


@pytest.fixture
def bounded_capacity(monkeypatch):
    monkeypatch.setattr(
        "nomos_c0.declarative_graph_ports_v0.COMPILE_BUDGET",
        replace(COMPILE_BUDGET, ports_canonical_bytes=LIMIT),
    )


def declarations():
    lib, ports, _ = _documents("parcel_delivery_v0")
    template = deepcopy(ports["actions"][-1])
    while len(json.dumps(ports, sort_keys=True)) <= LIMIT:
        ports["actions"].append(
            dict(deepcopy(template), symbol=f"confirm_copy_{len(ports['actions'])}")
        )
    assert len(ports["actions"]) <= 512
    return check_nominal_lib(lib), ports, template


def canonical(ports):
    return json.dumps(ports, sort_keys=True, separators=(",", ":"))


def test_structured_and_minified_ports_accept_the_same_canonical_declaration(bounded_capacity):
    checked, ports, _ = declarations()
    encoded = canonical(ports)
    assert len(encoded) <= LIMIT < len(json.dumps(ports, sort_keys=True))
    before = deepcopy(ports)
    structured = check_graph_ports(ports, checked)
    parsed = check_graph_ports(encoded, checked)
    assert len(structured.actions) == len(parsed.actions) == len(ports["actions"])
    assert (
        structured.actions[-1].symbol == parsed.actions[-1].symbol == ports["actions"][-1]["symbol"]
    )
    assert ports == before


def test_canonical_overflow_remains_a_size_error_without_mutating_input(bounded_capacity):
    checked, ports, template = declarations()
    while len(canonical(ports)) <= LIMIT:
        ports["actions"].append(
            dict(deepcopy(template), symbol=f"confirm_copy_{len(ports['actions'])}")
        )
    assert len(ports["actions"]) <= 512
    before = deepcopy(ports)
    with pytest.raises(C0CompileLimitError) as failure:
        check_graph_ports(ports, checked)
    assert failure.value.resource == "ports_canonical_bytes"
    assert failure.value.actual == len(canonical(ports))
    assert failure.value.limit == LIMIT
    assert ports == before
    with pytest.raises(C0CompileLimitError, match="ports_canonical_bytes"):
        check_graph_ports(canonical(ports), checked)


def test_raw_port_bytes_have_a_separate_preparse_bound():
    lib, _, _ = _documents("parcel_delivery_v0")
    with pytest.raises(C0CompileLimitError) as failure:
        check_graph_ports(" " * (COMPILE_BUDGET.ports_source_bytes + 1), check_nominal_lib(lib))
    assert failure.value.resource == "ports_source_bytes"
    assert failure.value.stage == "Ports parse"


def test_default_capacity_accepts_larger_valid_declarations_in_all_input_forms():
    checked, ports, template = declarations()
    while len(ports["actions"]) < 500:
        ports["actions"].append(
            dict(deepcopy(template), symbol=f"confirm_copy_{len(ports['actions'])}")
        )
    encoded = canonical(ports)
    assert LIMIT < len(encoded) < COMPILE_BUDGET.ports_canonical_bytes
    document = parse_author_document(encoded, file="ports.json", format="json")
    for source in (ports, encoded, document):
        assert len(check_graph_ports(source, checked).actions) == 500


def test_default_canonical_bound_is_checked_before_semantic_expansion():
    checked, ports, template = declarations()
    while len(canonical(ports)) <= COMPILE_BUDGET.ports_canonical_bytes:
        ports["actions"].append(
            dict(deepcopy(template), symbol=f"confirm_copy_{len(ports['actions'])}")
        )
    # This oversized input is not claimed to fit the independent Action-count bound.
    with pytest.raises(C0CompileLimitError) as failure:
        check_graph_ports(ports, checked)
    assert failure.value.resource == "ports_canonical_bytes"
    assert failure.value.limit == COMPILE_BUDGET.ports_canonical_bytes
    assert failure.value.actual == len(canonical(ports))


def test_unencodable_raw_text_is_a_format_error():
    lib, _, _ = _documents("parcel_delivery_v0")
    with pytest.raises(C0LawError, match="not valid UTF-8"):
        check_graph_ports("\ud800", check_nominal_lib(lib))


def test_non_json_data_is_still_rejected_as_data_not_as_capacity():
    lib, ports, _ = _documents("parcel_delivery_v0")
    ports["actions"][0]["symbol"] = object()
    with pytest.raises(C0LawError, match="Lib ports are not finite JSON data"):
        check_graph_ports(ports, check_nominal_lib(lib))
