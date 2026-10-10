"""Compact fields share the checked nominal layout and validation contract."""

from copy import deepcopy

import pytest

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.nominal_type_aliases_v1 import expand_type_aliases


def library(*, aliases=True):
    row = {
        "schema": "c0.nominal_lib.v1",
        "records": [{"name": "Scene", "fields": ["bool ready"], "invariant": None}],
        "owners": [{"symbol": "scene", "key": "compact.scene", "version": "v1",
                    "state": "Scene", "identity_field": None, "write": "replace_one",
                    "seat_read": ["ready"]}],
    }
    if aliases:
        row["type_aliases"] = {"Name": {"str": [1, 64]}}
        row["records"][0]["fields"].append("Name title")
    return row


@pytest.mark.parametrize("aliases", [False, True])
def test_compact_fields_preserve_layout_signatures_codec_and_input(aliases):
    source = library(aliases=aliases)
    before = deepcopy(source)
    expanded = expand_type_aliases(source)
    compact = check_nominal_lib(source)
    structured = check_nominal_lib(expanded)
    assert source == before
    assert compact.signatures == structured.signatures
    assert compact.owner("scene").owner.owner_version == (
        structured.owner("scene").owner.owner_version)
    values = (True, "title") if aliases else (True,)
    a, b = compact.record("Scene")(*values), structured.record("Scene")(*values)
    assert (compact.owner("scene").owner.encode_state(a)
            == structured.owner("scene").owner.encode_state(b))
    assert list(compact.record("Scene").__dataclass_fields__) == (
        ["ready", "title"] if aliases else ["ready"])


@pytest.mark.parametrize("field", [
    "", "bool", "bool ready extra", "bool ready;", "bool ready = true",
    "{str: [1, 64]} title", "bool _hidden", "bool réady", "bool ready\n",
    "bool\nready", "bool ready\nextra", 1, None,
])
def test_malformed_field_reports_record_and_position(field):
    source = library()
    source["records"][0]["fields"][1] = field
    with pytest.raises(C0LawError, match=r"record 'Scene' field\[1\]"):
        check_nominal_lib(source)


@pytest.mark.parametrize("field", ["Unknown title", "title Name", "bool class",
                                        "bool validate_for_k0", "bool ready"])
def test_named_fields_still_reject_unknown_types_invalid_names_and_duplicates(field):
    source = library()
    source["records"][0]["fields"][1] = field
    with pytest.raises(C0LawError):
        check_nominal_lib(source)


def test_compact_and_structured_fields_use_one_duplicate_check():
    source = library(aliases=False)
    source["records"][0]["fields"].append({"name": "ready", "type": "bool"})
    with pytest.raises(C0LawError, match="fields alias"):
        check_nominal_lib(source)


def test_spacing_and_forward_record_reference_do_not_create_another_type():
    source = library(aliases=False)
    source["records"][0]["fields"].append("  Payload\tdata  ")
    source["records"].append({"name": "Payload", "fields": ["bool present"],
                              "invariant": None})
    checked = check_nominal_lib(source)
    assert checked.record("Scene").__annotations__["data"] is checked.record("Payload")


def test_compact_variant_common_field_keeps_case_and_payload_checks():
    source = library(aliases=False)
    source["records"][0]["variants"] = {"pending": "none", "done": "Result"}
    source["records"].append({"name": "Result", "fields": ["bool ok"], "invariant": None})
    checked = check_nominal_lib(source)
    carrier = checked.record("Scene")
    assert list(carrier.__dataclass_fields__) == ["ready", "case", "done"]
    carrier(True, "pending", None).validate_for_k0()
    carrier(True, "done", checked.record("Result")(True)).validate_for_k0()
    with pytest.raises(ValueError):
        carrier(True, "pending", checked.record("Result")(True)).validate_for_k0()
