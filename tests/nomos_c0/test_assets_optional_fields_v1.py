"""Only typed opening records default omitted optional fields to None."""

from copy import deepcopy

import pytest
from authored_counter_v1 import _owner, _record, build, counter_documents
from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_formation_v1 import documents as actor_documents
from test_object_start_v1 import _assets as object_assets
from test_object_start_v1 import _lib as object_lib
from test_object_start_v1 import _program as object_program
from test_variant_types_v1 import declaration as variant_declaration
from test_variant_types_v1 import program as variant_program

from nomos_c0 import program_start_v1
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_start_v1 import _opening_value, check_assets


@pytest.fixture(scope="module")
def carrier():
    lib = {
        "schema": "c0.nominal_lib.v1",
        "owners": [_owner("one", "Opening", ["name"])],
        "records": [
            _record(
                "Detail", {"number": {"int": [0, 9]}, "origin": {"optional": "occurrence_ref"}}
            ),
            _record(
                "Opening",
                {
                    "name": {"str": [1, 16]},
                    "enabled": "bool",
                    "count": {"int": [0, 9]},
                    "labels": {"tuple": {"item": {"str": [1, 16]}, "max": 4}},
                    "detail": "Detail",
                    "samples": {"tuple": {"item": "Detail", "max": 4}},
                    "note": {"optional": {"str": [1, 16]}},
                    "extra": {"optional": "Detail"},
                    "flag": {"optional": "bool"},
                    "quantity": {"optional": {"int": [0, 9]}},
                    "target": {"optional": "individual_ref"},
                    "speaker": {"optional": "actor_ref"},
                },
            ),
        ],
    }
    return check_nominal_lib(lib).record("Opening")


def opening():
    return {
        "name": "one",
        "enabled": False,
        "count": 0,
        "labels": [],
        "detail": {"number": 2},
        "samples": [{"number": 3}],
    }


def test_omitted_optionals_equal_explicit_null_recursively_without_mutating_input(carrier):
    sparse = opening()
    before = deepcopy(sparse)
    explicit = {
        **sparse,
        "note": None,
        "extra": None,
        "flag": None,
        "quantity": None,
        "target": None,
        "speaker": None,
        "detail": {"number": 2, "origin": None},
        "samples": [{"number": 3, "origin": None}],
    }
    result = _opening_value(carrier, sparse)
    assert result == _opening_value(carrier, explicit)
    result.validate_for_k0()
    assert result.note is result.extra is result.target is result.speaker is None
    assert result.detail.origin is result.samples[0].origin is None
    assert sparse == before
    supplied = _opening_value(
        carrier, {**sparse, "note": "kept", "extra": {"number": 4}, "flag": False, "quantity": 0}
    )
    assert supplied.note == "kept" and supplied.extra.number == 4 and supplied.extra.origin is None
    assert supplied.flag is False and supplied.quantity == 0


@pytest.mark.parametrize("name", ["name", "enabled", "count", "labels", "detail", "samples"])
def test_required_fields_never_receive_implicit_empty_or_zero_values(carrier, name):
    raw = opening()
    del raw[name]
    with pytest.raises(C0BindingError, match=f"missing required=.*{name}"):
        _opening_value(carrier, raw)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": None},
        {"notes": None},
        {"enabled": None},
        {"note": 1},
        {"target": 1},
        {"speaker": "one"},
        {"detail": {}},
        {"samples": [{}]},
        {"extra": {}},
        {1: None, "foreign": None},
    ],
)
def test_malformed_supplied_values_and_unknown_fields_still_reject(carrier, change):
    with pytest.raises(C0BindingError):
        _opening_value(carrier, {**opening(), **change})


def test_variant_optional_common_fields_and_payload_default_but_tags_remain_required():
    declaration = variant_declaration()
    declaration["records"][1]["fields"].append(
        {"name": "origin", "type": {"optional": "occurrence_ref"}}
    )
    lib = check_nominal_lib(declaration)
    raw = {
        "case": "success",
        "value": {"number": 3, "secret": "hidden"},
        "fields": {"request": "r"},
    }
    result = _opening_value(lib.record("Result"), raw)
    result.validate_for_k0()
    assert result.origin is result.success.origin is None
    explicit = deepcopy(raw)
    explicit["value"]["origin"] = None
    explicit["fields"]["origin"] = None
    assert result == _opening_value(lib.record("Result"), explicit)
    for invalid in (
        {**raw, "fields": {}},
        {**raw, "fields": {"request": "r", "origins": None}},
        {key: value for key, value in raw.items() if key != "case"},
        {key: value for key, value in raw.items() if key != "value"},
        {key: value for key, value in raw.items() if key != "fields"},
    ):
        with pytest.raises(C0BindingError):
            _opening_value(lib.record("Result"), invalid)


def test_sparse_start_preserves_checked_opening_and_real_k0_action():
    lib, ports, source, assets = counter_documents()
    program = compile_owner_graph(build(lib, ports), source)
    sparse = deepcopy(assets)
    del sparse["opening"]["scene"]["open_ref"]
    assert check_assets(program, sparse) == check_assets(program, assets)
    sessions = (program.start(sparse), program.start(assets))
    for session in sessions:
        offer = session.offers("seat_0")[0]
        assert isinstance(session.submit("seat_0", offer.entry, dict(offer.payload)), K0Published)
    assert sessions[0].read("seat_0") == sessions[1].read("seat_0")


def test_missing_optional_does_not_bypass_owner_invariant_or_allocate_session(monkeypatch):
    lib, ports, source, assets = counter_documents()
    lib["records"][0]["fields"].append({"name": "note", "type": {"optional": {"str": [1, 16]}}})
    lib["records"][0]["invariant"] = "state.note != None"
    program = compile_owner_graph(build(lib, ports), source)

    def forbid(*args, **kwargs):
        raise AssertionError("invalid opening allocated K0")

    monkeypatch.setattr(program_start_v1._K0InMemorySession, "create", forbid)
    with pytest.raises(C0BindingError, match="opening owner state is not admitted"):
        program.start(assets)


def test_opening_objects_and_dynamic_actors_share_the_same_optional_contract():
    lib = object_lib()
    lib["records"][-1]["fields"].append({"name": "origin", "type": {"optional": "occurrence_ref"}})
    objects = object_program(lib=lib).start(object_assets()).author_object_instances()
    assert len(objects) == 2 and all(row.current_state.origin is None for row in objects)

    lib, ports, source, assets = actor_documents(
        opening=[{"kind": "sprite", "state": {"count": 0, "awake": True}, "debt": 2}]
    )
    next(row for row in lib["records"] if row["name"] == "Sprite")["fields"].append(
        {"name": "note", "type": {"optional": {"str": [1, 16]}}}
    )
    # Runtime formation is intentionally unused: only this opening exercises defaulting.
    birth = source["lawdefs"][0]["body"]["value"]["outputs"]["newborn"]["record"]["fields"]
    birth["note"] = None
    session = compile_owner_graph(build(lib, ports), source).start(assets)
    actors = session.author_actor_instances()
    assert len(actors) == 1 and actors[0].current_state.note is None


def test_runtime_record_construction_still_requires_explicit_optional_fields():
    lib = check_nominal_lib(variant_declaration())
    with pytest.raises(C0LawError):
        variant_program(
            lib,
            {"record": {"type": "Ticket", "fields": {"number": 3, "secret": {"const": "hidden"}}}},
            output=lib.record("Ticket"),
        )
