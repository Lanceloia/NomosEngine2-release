"""Declared Lib records and owners retain exact K0 types and provenance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.compile_budget_v1 import COMPILE_BUDGET, C0CompileLimitError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.examples.parcel_delivery_v0 import main, open_session

LIB = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples/parcel_delivery_v0.lib.json"


def _source() -> dict[str, object]:
    return json.loads(LIB.read_text(encoding="utf-8"))


def test_declared_records_and_owner_codec_preserve_nested_occurrence_refs() -> None:
    checked = check_nominal_lib(_source())
    parcel = checked.record("Parcel")("P-1", "dock", "transit", K0OccurrenceRef(3), None)
    state = checked.record("Scene")(parcel, (), "none")
    owner = checked.owner("scene").owner
    owner.validate_state(state)
    assert owner.read_view(state) is state
    assert owner.preserved_occurrences(state) == (K0OccurrenceRef(3),)
    assert owner.decode_state(owner.encode_state(state)) == state
    assert type(owner.decode_state(owner.encode_state(state))) is checked.record("Scene")
    assert checked.record("Scene") is not checked.record("Sender")


def test_finite_record_capacity_accepts_64_fields_and_rejects_65() -> None:
    source = _source()
    scene = next(item for item in source["records"] if item["name"] == "Scene")
    original_fields = len(scene["fields"])
    for index in range(64 - original_fields):
        scene["fields"].append({"name": f"extra_{index}", "type": "bool"})
    checked = check_nominal_lib(source)
    assert len(checked.record("Scene").__dataclass_fields__) == 64

    scene["fields"].append({"name": "one_too_many", "type": "bool"})
    with pytest.raises(C0LawError, match="finite fields"):
        check_nominal_lib(source)


def test_nominal_record_budget_accepts_last_type_and_rejects_overflow() -> None:
    source = _source()
    for index in range(COMPILE_BUDGET.nominal_records - len(source["records"])):
        source["records"].append(
            {
                "name": f"Extra{index}",
                "fields": [{"name": "value", "type": "bool"}],
                "invariant": None,
            }
        )
    checked = check_nominal_lib(source)
    assert len(checked.records) == COMPILE_BUDGET.nominal_records
    last = checked.record(source["records"][-1]["name"])(True)
    last.validate_for_k0()
    source["records"].append(
        {"name": "Overflow", "fields": [{"name": "value", "type": "bool"}], "invariant": None}
    )
    with pytest.raises(C0CompileLimitError) as caught:
        check_nominal_lib(source)
    error = caught.value
    assert (error.resource, error.actual, error.limit, error.stage) == (
        "nominal_records",
        COMPILE_BUDGET.nominal_records + 1,
        COMPILE_BUDGET.nominal_records,
        "Lib declarations",
    )


def test_declared_invariant_and_field_bounds_reject_malformed_current_state() -> None:
    checked = check_nominal_lib(_source())
    parcel = checked.record("Parcel")
    route = checked.record("Route")
    with pytest.raises(K0ProfileError, match="invariant"):
        parcel("P-1", "dock", "transit", None, None).validate_for_k0()
    with pytest.raises(K0ProfileError, match="nominal value"):
        route("dock", 0).validate_for_k0()
    with pytest.raises(K0ProfileError, match="nominal value"):
        parcel("P-1", "dock", "foreign", None, None).validate_for_k0()


def test_declared_invariant_counts_fields_inside_a_nested_collection() -> None:
    source = _source()
    scene = next(item for item in source["records"] if item["name"] == "Scene")
    scene["invariant"] = {
        "eq": [
            {
                "count_matching": {
                    "collection": {"ref": "state.routes"},
                    "as": "route",
                    "where": {"le": [{"ref": "route.travel"}, {"const": 2}]},
                }
            },
            {"const": 1},
        ]
    }
    checked = check_nominal_lib(source)
    parcel = checked.record("Parcel")("P", "dock", "home", None, None)
    route = checked.record("Route")
    checked.record("Scene")(parcel, (route("dock", 2),), "none").validate_for_k0()
    with pytest.raises(K0ProfileError, match="invariant"):
        checked.record("Scene")(
            parcel, (route("dock", 2), route("tower", 1)), "none"
        ).validate_for_k0()


@pytest.mark.parametrize(
    "field_type",
    (
        {"bool": True},
        {"str": [0, 64]},
        {"int": [-1, 3]},
        {"enum": ["home", "home"]},
        {"optional": {"optional": "occurrence_ref"}},
        {"tuple": {"item": "occurrence_ref", "max": 0}},
        "MissingRecord",
        "occurrence_reference",
    ),
)
def test_declared_type_expressions_reject_nonclosed_shapes(field_type: object) -> None:
    source = _source()
    source["records"][0]["fields"][0]["type"] = field_type
    with pytest.raises(C0LawError):
        check_nominal_lib(source)


@pytest.mark.parametrize(
    "wire",
    (
        ("wrong-version", ()),
        (None, ()),
        (None, (("P-1", "dock", "transit", "not-a-ref", None), (), "none")),
        (None, (("P-1", "dock", "home", None, None), (), "foreign")),
    ),
)
def test_declared_owner_codec_finitely_rejects_bad_wire(wire: object) -> None:
    owner = check_nominal_lib(_source()).owner("scene").owner
    if wire[0] is None:
        wire = (owner.owner_version, wire[1])
    with pytest.raises(K0ProfileError):
        owner.decode_state(wire)


@pytest.mark.parametrize(
    "change",
    (
        "unknown_type",
        "recursive_type",
        "unbounded_collection",
        "bad_invariant",
        "bad_owner_state",
        "bad_seat_path",
        "unsupported_write_strategy",
        "empty_author_string",
        "untrimmed_owner_version",
        "reserved_record_name",
        "keyword_field",
        "oversized_dict_input",
    ),
)
def test_bad_author_lib_rejects_during_checklib(change: str) -> None:
    source = _source()
    if change == "unknown_type":
        source["records"][0]["fields"][0]["type"] = "Foreign"
    elif change == "recursive_type":
        source["records"][0]["fields"][0]["type"] = "Parcel"
    elif change == "unbounded_collection":
        source["records"][2]["fields"][1]["type"] = {"tuple": {"item": "Route"}}
    elif change == "bad_invariant":
        source["records"][0]["invariant"] = {"eq": [{"ref": "state.unseen"}, {"const": "home"}]}
    elif change == "bad_owner_state":
        source["owners"][0]["state"] = []
    elif change == "bad_seat_path":
        source["owners"][0]["seat_read"].append("parcel.unseen")
    elif change == "empty_author_string":
        source["records"][0]["fields"][0]["type"] = {"str": [0, 64]}
    elif change == "untrimmed_owner_version":
        source["owners"][0]["version"] = " parcel-scene-v1 "
    elif change == "reserved_record_name":
        source["records"][1]["name"] = "bool"
    elif change == "keyword_field":
        source["records"][0]["fields"][0]["name"] = "class"
    elif change == "oversized_dict_input":
        source["owners"][0]["version"] = "x" * 263000
    else:
        source["owners"][0]["write"] = "last_write_wins"
    with pytest.raises(C0LawError):
        check_nominal_lib(source)


def test_invalid_explicit_lib_is_a_finite_cli_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source()
    source["records"][0]["fields"][0]["name"] = "class"
    path = tmp_path / "invalid.lib.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["parcel_delivery_v0", "--lib", str(path)])
    with pytest.raises(SystemExit) as outcome:
        main()
    assert outcome.value.code == 2
    assert "Cannot build parcel world:" in capsys.readouterr().err


def test_editing_only_lib_changes_generated_type_constraint() -> None:
    original = _source()
    revised = _source()
    revised["records"][1]["fields"][1]["type"]["int"][0] = 3
    old_route = check_nominal_lib(original).record("Route")
    new_route = check_nominal_lib(revised).record("Route")
    old_route("dock", 2).validate_for_k0()
    with pytest.raises(K0ProfileError):
        new_route("dock", 2).validate_for_k0()
    new_route("dock", 3).validate_for_k0()


def test_edited_lib_changes_private_owner_wire_identity() -> None:
    original = _source()
    revised = _source()
    revised["records"][1]["fields"][1]["type"]["int"][0] = 3
    old = check_nominal_lib(original)
    new = check_nominal_lib(revised)
    state = old.record("Scene")(old.record("Parcel")("P-1", "dock", "home", None, None), (), "none")
    wire = old.owner("scene").owner.encode_state(state)
    assert old.owner("scene").owner.owner_version != new.owner("scene").owner.owner_version
    with pytest.raises(K0ProfileError, match="version"):
        new.owner("scene").owner.decode_state(wire)


def test_explicit_lib_edit_changes_same_source_start_without_python_edit(tmp_path: Path) -> None:
    revised = _source()
    revised["records"][1]["fields"][1]["type"]["int"][0] = 3
    path = tmp_path / "revised.lib.json"
    path.write_text(json.dumps(revised), encoding="utf-8")
    assets = LIB.parent
    with pytest.raises(C0BindingError):
        open_session(assets / "parcel_delivery_v0.a.assets.json", lib_path=path)
    session = open_session(assets / "parcel_delivery_v0.b.assets.json", lib_path=path)
    assert session.time == 0
    assert len(session.form_frame("sender").offers) == 1


def test_incompatible_declared_field_cannot_fall_back_to_python_ports(tmp_path: Path) -> None:
    revised = _source()
    revised["records"][2]["fields"][0]["name"] = "cargo"
    path = tmp_path / "wrong-port.lib.json"
    path.write_text(json.dumps(revised), encoding="utf-8")
    with pytest.raises(C0LawError):
        open_session(LIB.parent / "parcel_delivery_v0.a.assets.json", lib_path=path)
