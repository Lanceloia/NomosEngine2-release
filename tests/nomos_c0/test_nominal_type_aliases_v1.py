"""Type aliases preserve existing field bounds, signatures and runtime validation."""

from copy import deepcopy
from dataclasses import fields

import pytest
from nomos_kernel import K0ProfileError

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.nominal_type_aliases_v1 import expand_type_aliases


def library():
    return {
        "schema": "c0.nominal_lib.v1",
        "type_aliases": {
            "Name": {"str": [1, 64]},
            "Count": {"int": [1, 1000000]},
            "OptionalName": {"optional": "Name"},
            "Items": {"tuple": {"item": "Name", "max": 3}},
            "Label": "Name",
            "Choice": {"enum": ["a", "b"]},
        },
        "records": [{"name": "Scene", "fields": [
            {"name": "label", "type": "Label"},
            {"name": "count", "type": "Count"},
            {"name": "target", "type": "OptionalName"},
            {"name": "items", "type": "Items"},
            {"name": "choice", "type": "Choice"},
        ], "invariant": None}],
        "owners": [{"symbol": "scene", "key": "alias.scene", "version": "v1",
                    "state": "Scene", "identity_field": None, "write": "replace_one",
                    "seat_read": ["label", "count"]}],
    }


def test_aliases_are_transparent_and_do_not_mutate_input_or_create_record_types():
    source = library()
    untouched = deepcopy(source)
    expanded = expand_type_aliases(source)
    del expanded["type_aliases"]
    aliased = check_nominal_lib(source)
    inline = check_nominal_lib(expanded)
    assert source == untouched
    assert [name for name, _ in aliased.records] == ["Scene"]
    assert [field.type for field in fields(aliased.record("Scene"))] == [
        field.type for field in fields(inline.record("Scene"))]
    assert aliased.signatures == inline.signatures
    assert aliased.owner("scene").owner.owner_version == inline.owner("scene").owner.owner_version
    a = aliased.record("Scene")("x", 1, None, ("y",), "a")
    b = inline.record("Scene")("x", 1, None, ("y",), "a")
    assert (aliased.owner("scene").owner.encode_state(a)
            == inline.owner("scene").owner.encode_state(b))
    renamed = library()
    renamed["type_aliases"]["Renamed"] = renamed["type_aliases"].pop("Name")
    renamed["type_aliases"]["Label"] = "Renamed"
    renamed["type_aliases"]["OptionalName"]["optional"] = "Renamed"
    renamed["type_aliases"]["Items"]["tuple"]["item"] = "Renamed"
    assert check_nominal_lib(renamed).signatures == aliased.signatures


@pytest.mark.parametrize("change", ["short", "long", "low", "high", "bool", "optional",
                                  "item", "size", "enum"])
def test_aliases_retain_every_current_value_check(change):
    checked = check_nominal_lib(library())
    values = ["x", 1, None, ("y",), "a"]
    if change in ("short", "long"):
        values[0] = "" if change == "short" else "x" * 65
    elif change in ("low", "high", "bool"):
        values[1] = {"low": 0, "high": 1000001, "bool": True}[change]
    elif change == "optional":
        values[2] = ""
    elif change == "item":
        values[3] = (1,)
    elif change == "size":
        values[3] = ("x",) * 4
    else:
        values[4] = "c"
    with pytest.raises(K0ProfileError):
        checked.record("Scene")(*values).validate_for_k0()


@pytest.mark.parametrize("change", ["unknown", "cycle", "builtin", "record", "keyword",
                                  "bad_range", "unused", "nested_optional", "unbounded"])
def test_invalid_aliases_reject_at_compile_including_unused_declarations(change):
    source = library()
    aliases = source["type_aliases"]
    if change == "unknown":
        aliases["Label"] = "Missing"
    elif change == "cycle":
        aliases["Name"] = "Label"
    elif change in ("builtin", "record", "keyword"):
        aliases[{"builtin": "int", "record": "Scene", "keyword": "class"}[change]] = "bool"
    elif change in ("bad_range", "unused"):
        aliases["Unused" if change == "unused" else "Count"] = {"int": [-1, 2]}
    elif change == "nested_optional":
        aliases["OptionalName"] = {"optional": {"optional": "Name"}}
    else:
        aliases["Items"] = {"tuple": {"item": "Name"}}
    with pytest.raises(C0LawError):
        check_nominal_lib(source)


def test_used_bound_edit_changes_wire_and_rejects_old_values_without_kernel_changes():
    original = check_nominal_lib(library())
    changed = library()
    changed["type_aliases"]["Count"] = {"int": [2, 1000000]}
    revised = check_nominal_lib(changed)
    state = original.record("Scene")("x", 1, None, (), "a")
    with pytest.raises(K0ProfileError):
        revised.record("Scene")("x", 1, None, (), "a").validate_for_k0()
    revised.record("Scene")("x", 2, None, (), "a").validate_for_k0()
    old_owner = original.owner("scene").owner
    new_owner = revised.owner("scene").owner
    assert old_owner.owner_version != new_owner.owner_version
    with pytest.raises(K0ProfileError, match="version"):
        new_owner.decode_state(old_owner.encode_state(state))


def test_variant_payload_and_record_reference_aliases_keep_nominal_identity():
    source = library()
    source["type_aliases"]["Payload"] = "Scene"
    source["records"].append({"name": "Result", "fields": [], "invariant": None,
                              "variants": {"empty": "none", "present": "Payload"}})
    checked = check_nominal_lib(source)
    result = checked.record("Result")
    assert result.__nomos_cases__ == (("empty", type(None)), ("present", checked.record("Scene")))


def test_alias_order_is_irrelevant_and_expanded_nesting_remains_bounded():
    source = library()
    checked = check_nominal_lib(source)
    source["type_aliases"] = dict(reversed(list(source["type_aliases"].items())))
    assert check_nominal_lib(source).signatures == checked.signatures
    nested = "Name"
    for _ in range(13):
        nested = {"tuple": {"item": nested, "max": 1}}
    source["type_aliases"]["TooDeep"] = nested
    with pytest.raises(C0LawError, match="nesting"):
        check_nominal_lib(source)


@pytest.mark.parametrize("declaration", [[], {f"T{i}": "bool" for i in range(65)}])
def test_alias_map_is_finite(declaration):
    source = library()
    source["type_aliases"] = declaration
    with pytest.raises(C0LawError, match="finite map"):
        check_nominal_lib(source)
