"""Direct field comparison preserves the symbolic-tree check without cached proofs."""

from dataclasses import replace

import pytest
from test_nominal_signatures_v1 import source

from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.nominal_signatures_v1 import C0NominalFieldType


def test_direct_comparison_matches_constructed_tree_for_every_component():
    checked = nominal.check_nominal_lib(source())
    names = {carrier: name for name, carrier in checked.record_layout.records}
    specs = [field.value for row in checked.record_layout._fields for field in row]
    specs += [
        nominal._TypeSpec("bool", bool),
        nominal._TypeSpec("enum", str, choices=("first", "second")),
        nominal._TypeSpec("variant", checked.record("Item")),
    ]
    for spec in specs:
        expected = nominal._symbolic_field(spec, names)
        alternatives = [
            expected,
            replace(expected, kind="foreign"),
            replace(expected, record="Foreign"),
            replace(expected, minimum=expected.minimum + 1),
            replace(expected, maximum=expected.maximum + 1),
            replace(expected, choices=("foreign",)),
            replace(expected, item=None if expected.item else C0NominalFieldType("bool")),
        ]
        if expected.item is not None:
            alternatives.append(replace(expected, item=replace(expected.item, maximum=999)))
        for field in alternatives:
            assert nominal._realizes_field(spec, field, names) == (expected == field)
        assert not nominal._realizes_field(spec, None, names)


@pytest.mark.parametrize("change", ["name", "range", "nested", "count", "container"])
def test_next_layout_check_rejects_changed_signature_after_success(change):
    checked = nominal.check_nominal_lib(source())
    layout = checked.record_layout
    layout.check(checked.signatures)
    signature = checked.signatures.record("Box" if change == "nested" else "Item")
    fields = list(signature.fields)
    if change == "name":
        fields[0] = replace(fields[0], name="different")
    elif change == "range":
        fields[1] = replace(fields[1], value=replace(fields[1].value, maximum=999))
    elif change == "nested":
        value = fields[1].value
        fields[1] = replace(
            fields[1], value=replace(value, item=replace(value.item, record="Other"))
        )
    elif change == "count":
        fields.pop()
    object.__setattr__(signature, "fields", fields if change == "container" else tuple(fields))
    with pytest.raises(C0LawError, match="fields do not realize"):
        layout.check(checked.signatures)


def test_check_does_not_rebuild_symbolic_fields(monkeypatch):
    checked = nominal.check_nominal_lib(source())

    def forbidden(*args):
        raise AssertionError("layout checking must not rebuild symbolic field trees")

    monkeypatch.setattr(nominal, "_symbolic_field", forbidden)
    checked.record_layout.check(checked.signatures)
    checked.record_layout.check(checked.signatures)
