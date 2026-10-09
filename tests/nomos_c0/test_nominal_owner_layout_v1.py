"""Owner storage keys and carriers realize, rather than define, nominal contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from nomos_kernel import K0OccurrenceRef, K0OwnerKey, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._owner_abi import _K0OccurrenceContribution
from nomos_kernel._owner_state_runtime import _isolate_candidate_owner_state
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend, source

from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.checked_value_binding_v1 import C0ValueBackend
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import bind_nominal_records, check_nominal_lib
from nomos_c0.nominal_owner_layout_v1 import C0NominalOwnerLayout, bind_nominal_owners
from nomos_c0.owner_graph_v1 import compile_owner_graph


def _lib():
    row = source()
    row["owners"].append(
        {
            "symbol": "other",
            "key": "c0.symbols.other",
            "version": "v1",
            "state": "Other",
            "identity_field": "name",
            "seat_read": ["name", "amount"],
            "write": "replace_one",
        }
    )
    row["object_kinds"] = [
        {
            "symbol": "item",
            "sort": "EXAMPLE.ITEM@1",
            "state": "Item",
            "version": "item-v1",
            "max_instances": 2,
        },
        {
            "symbol": "special_item",
            "sort": "EXAMPLE.SPECIAL_ITEM@1",
            "state": "Item",
            "version": "item-v1",
            "max_instances": 3,
            "specializes": ["EXAMPLE.ITEM@1"],
        },
    ]
    return row


def _keys(checked, prefix="c0.rebound."):
    return {item.symbol: K0OwnerKey(prefix + item.symbol) for item in checked.signatures.owners}


def test_owner_and_kind_declarations_are_immutable_carrier_free_and_key_independent():
    checked = check_nominal_lib(_lib())
    assert_symbolic(checked.signatures)
    assert checked.signatures.owners[0].state == "Box"
    assert checked.signatures.object_kinds[1].specializes == ("EXAMPLE.ITEM@1",)
    assert "c0.symbols.box" not in repr(checked.signatures)
    with pytest.raises(FrozenInstanceError):
        checked.signatures.owners[0].state = "Other"
    edited = _lib()
    edited["owners"][0]["key"] = "c0.second.box"
    other = check_nominal_lib(edited)
    assert checked.signatures == other.signatures
    assert checked.owner("box").owner.owner_version == other.owner("box").owner.owner_version
    assert checked.object_kinds[0].k0_kind.factory.owner_version == (
        other.object_kinds[0].k0_kind.factory.owner_version
    )
    assert checked.owner("box").owner.key != other.owner("box").owner.key


def test_candidate_isolation_copies_nested_records_and_refs_without_persistence(monkeypatch):
    checked = check_nominal_lib(_lib())
    item_type = checked.record_layout.record("Item")
    box_type = checked.record_layout.record("Box")
    item = item_type("x", 3, K0OccurrenceRef(4))
    before = box_type(item, (item,))
    owner = checked.owner("box").owner
    wire = owner.encode_state(before)

    def forbid_codec(*args):
        pytest.fail("candidate isolation used the persistence codec")

    with monkeypatch.context() as patch:
        patch.setattr(type(owner), "encode_state", forbid_codec)
        patch.setattr(type(owner), "decode_state", forbid_codec)
        isolated = _isolate_candidate_owner_state(owner, before)
    assert type(isolated) is box_type and isolated == before and isolated is not before
    assert isolated.item is not item and isolated.items[0] is not item
    assert isolated.items is not before.items
    assert isolated.item.origin == item.origin and isolated.item.origin is not item.origin
    assert owner.encode_state(isolated) == wire
    assert owner.preserved_occurrences(isolated) == owner.preserved_occurrences(before)
    object.__setattr__(isolated.item, "amount", 5)
    assert item.amount == 3 and isolated.items[0].amount == 3
    with pytest.raises(K0ProfileError, match="invariant"):
        owner.validate_state(isolated)
    owner.validate_state(before)


@pytest.mark.parametrize("fault", ["foreign", "nested_invariant", "mutable_collection"])
def test_candidate_isolation_rejects_bad_state_before_copying(fault):
    checked = check_nominal_lib(_lib())
    item = checked.record_layout.record("Item")("x", 3, None)
    box_type = checked.record_layout.record("Box")
    state = box_type(item, (item,))
    if fault == "foreign":
        state = checked.record_layout.record("Other")("x", 3, None)
    elif fault == "nested_invariant":
        state = box_type(replace(item, amount=5), (item,))
    else:
        state = box_type(item, [item])
    with pytest.raises(K0ProfileError):
        _isolate_candidate_owner_state(checked.owner("box").owner, state)


@pytest.mark.parametrize("fault", ["nested_field_as_scalar", "empty_nested_fields"])
def test_sealed_carrier_field_metadata_cannot_weaken_kernel_isolation(fault):
    checked = check_nominal_lib(_lib())
    item_type = checked.record_layout.record("Item")
    box_type = checked.record_layout.record("Box")
    item = item_type("x", 3, K0OccurrenceRef(4))
    state = box_type(item, (item,))
    owner = checked.owner("box").owner
    with pytest.raises(TypeError, match="read-only"):
        if fault == "nested_field_as_scalar":
            box_type.__nomos_fields__ = tuple(
                replace(field, value=nominal._TypeSpec("str", str))
                if field.name == "item"
                else field
                for field in box_type.__nomos_fields__
            )
        else:
            item_type.__nomos_fields__ = ()
    checked.record_layout.check(checked.signatures)
    isolated = _isolate_candidate_owner_state(owner, state)
    assert isolated == state and isolated.item is not item and isolated.items[0] is not item
    object.__setattr__(isolated.item, "amount", 5)
    assert item.amount == 3 and isolated.items[0].amount == 3
    owner.validate_state(state)
    with pytest.raises(K0ProfileError, match="invariant"):
        owner.validate_state(isolated)


def test_candidate_isolation_copies_opaque_handles_without_allocating_new_identities():
    declaration = _lib()
    declaration["records"][0]["fields"].extend(
        [
            {"name": "object", "type": {"optional": "individual_ref"}},
            {"name": "actor", "type": {"optional": "actor_ref"}},
        ]
    )
    checked = check_nominal_lib(declaration)
    individual = _K0IndividualRef("local", 3, "item")
    actor = _K0ActorRef("local", 2, "person")
    item = checked.record_layout.record("Item")("x", 3, None, individual, actor)
    state = checked.record_layout.record("Box")(item, ())
    owner = checked.owner("box").owner
    isolated = _isolate_candidate_owner_state(owner, state)
    assert type(isolated.item.object) is _K0IndividualRef
    assert type(isolated.item.actor) is _K0ActorRef
    assert isolated.item.object == individual and isolated.item.object is not individual
    assert isolated.item.actor == actor and isolated.item.actor is not actor
    assert owner.encode_state(isolated) == owner.encode_state(state)


def test_nominal_backend_has_no_second_isolation_plan_or_callback():
    checked = check_nominal_lib(_lib())
    assert not hasattr(nominal, "_IsolationPlan")
    assert not hasattr(nominal, "_isolate_value")
    assert not hasattr(checked.record_layout, "_isolation_plans")
    assert not hasattr(checked.owner("box").owner, "isolate_candidate_state")
    assert not hasattr(checked.object_kinds[0].k0_kind.factory, "isolation_plan")


@pytest.mark.parametrize("fresh_carrier", [False, True])
def test_one_signature_generates_two_key_layouts_with_same_owner_behavior(
    monkeypatch, fresh_carrier
):
    checked = check_nominal_lib(_lib())
    monkeypatch.setattr(nominal, "check_nominal_lib", forbid_frontend)
    monkeypatch.setattr(nominal, "compile_value_program", forbid_frontend)
    records = bind_nominal_records(checked.signatures) if fresh_carrier else checked.record_layout
    other = bind_nominal_owners(checked.signatures, records, _keys(checked))
    outcomes = []
    for layout in (checked.owner_layout, other):
        layout.check(checked.signatures)
        item = layout.record_layout.record("Item")("x", 3, K0OccurrenceRef(4))
        before = layout.record_layout.record("Box")(item, ())
        after = layout.record_layout.record("Box")(item, (item,))
        owner = layout.owner("box").owner
        contribution = layout.contribution_type(owner.key, after)
        batch = (_K0OccurrenceContribution(K0OccurrenceRef(5), contribution, ()),)
        assert owner.apply_contributions(before, batch) is after
        assert owner.decode_state(owner.encode_state(after)) == after
        outcomes.append((owner.encode_state(after), owner.preserved_occurrences(after)))
        with pytest.raises(K0ProfileError, match="one contribution"):
            owner.apply_contributions(before, batch + batch)
        with pytest.raises(K0ProfileError, match="foreign owner or state"):
            layout.contribution_type(layout.owner("other").owner.key, after).validate_for_k0()
        with pytest.raises(K0ProfileError, match="foreign owner or state"):
            layout.contribution_type(owner.key, item).validate_for_k0()
        for kind in layout.object_kinds:
            dynamic = kind.k0_kind.factory.build(K0OwnerKey("c0.dynamic." + kind.symbol))
            dynamic.validate_state(item)
            isolated = _isolate_candidate_owner_state(dynamic, item)
            assert isolated == item and isolated is not item
            update = dynamic.contribution_type(dynamic.key, item)
            dynamic.validate_contribution(update)
            assert dynamic.decode_state(dynamic.encode_state(item)) == item
            assert dynamic.preserved_occurrences(item) == (K0OccurrenceRef(4),)
            with pytest.raises(K0ProfileError, match="invariant"):
                dynamic.validate_state(type(item)("x", 5, None))
    assert outcomes[0] == outcomes[1]
    assert other.owner("box").owner.key != checked.owner("box").owner.key
    assert other.owner("box").owner.state_type is records.record("Box")
    assert other.object_kinds[1].k0_kind.max_instances == 3
    assert other.object_kinds[1].sort != other.object_kinds[0].sort


@pytest.mark.parametrize("fault", ["missing", "extra", "aliased", "native_key", "signature"])
def test_owner_binding_rejects_incomplete_aliased_or_foreign_layout(fault):
    checked = check_nominal_lib(_lib())
    keys = _keys(checked)
    signatures = checked.signatures
    if fault == "missing":
        del keys["box"]
    elif fault == "extra":
        keys["foreign"] = K0OwnerKey("c0.foreign")
    elif fault == "aliased":
        keys["other"] = keys["box"]
    elif fault == "native_key":
        keys["box"] = "c0.box"
    else:
        signatures = check_nominal_lib(_lib()).signatures
    with pytest.raises(C0LawError):
        bind_nominal_owners(signatures, checked.record_layout, keys)


def test_owner_layout_has_no_native_self_report_constructor():
    checked = check_nominal_lib(_lib())
    with pytest.raises(C0LawError, match="generated"):
        C0NominalOwnerLayout()
    with pytest.raises(C0LawError, match="generated"):
        replace(checked.owner_layout, owners=())
    with pytest.raises(C0LawError, match="same generated"):
        C0ValueBackend(bind_nominal_records(checked.signatures), checked.owner_layout)


@pytest.mark.parametrize("fault", ["contribution_validator", "contribution_annotation", "factory"])
def test_production_check_rejects_weakened_generated_owner_or_object_contribution(fault):
    checked = check_nominal_lib(_lib())
    with pytest.raises(TypeError, match="read-only"):
        if fault == "contribution_validator":
            checked.contribution_type.validate_for_k0 = lambda value: None
        elif fault == "contribution_annotation":
            checked.contribution_type.__annotations__["state"] = object
        else:
            checked.object_kinds[0].k0_kind.factory.contribution_type.validate_for_k0 = (
                lambda value: None
            )
    checked.check_record_layout()


@pytest.mark.parametrize("part", ["owners", "object_kinds", "contribution_type"])
def test_checked_lib_cannot_substitute_foreign_generated_bindings(part):
    first, foreign = check_nominal_lib(_lib()), check_nominal_lib(_lib())
    replaced = replace(first, **{part: getattr(foreign, part)})
    with pytest.raises(C0LawError, match="substituted"):
        replaced.check_record_layout()


def test_generated_layout_checks_resolved_annotations_without_reparsing(monkeypatch):
    checked = check_nominal_lib(_lib())
    monkeypatch.setattr(nominal, "get_type_hints", forbid_frontend)
    checked.record_layout.check(checked.signatures)
    carrier = checked.record_layout.record("Item")
    for changed in (object, "str"):
        with pytest.raises(TypeError, match="read-only"):
            carrier.__annotations__["name"] = changed
    checked.record_layout.check(checked.signatures)


def test_owner_template_key_prefix_is_layout_not_nominal_version():
    row = _lib()
    row["owners"][1]["template"] = row["owners"][1].pop("symbol")
    row["owners"][1]["key_prefix"] = row["owners"][1].pop("key") + "."
    domains = [{"name": "actors", "owner_template": "other", "owners": ["a", "b"]}]
    first = check_nominal_lib(row, domains)
    row["owners"][1]["key_prefix"] = "c0.second."
    second = check_nominal_lib(row, domains)
    assert first.signatures == second.signatures
    assert first.owner("a").owner.key != second.owner("a").owner.key
    assert first.owner("a").owner.owner_version == second.owner("a").owner.owner_version


def test_validation_pure_body_changes_wire_version_but_unused_pure_body_does_not():
    row = _lib()
    row["pure_definitions"].insert(
        0,
        {
            "name": "limit",
            "parameters": {},
            "result": "int",
            "stage": "admission",
            "body": 4,
        },
    )
    row["pure_definitions"][1]["body"]["le"][1] = {"call": {"ref": "limit", "args": {}}}
    first = check_nominal_lib(row)
    row["pure_definitions"].append(
        {"name": "unused", "parameters": {}, "result": "int", "stage": "admission", "body": 1}
    )
    unchanged = check_nominal_lib(row)
    assert first.owner("box").owner.owner_version == unchanged.owner("box").owner.owner_version
    row["pure_definitions"][0]["body"] = 3
    changed = check_nominal_lib(row)
    assert first.owner("box").owner.owner_version != changed.owner("box").owner.owner_version
    assert first.object_kinds[0].k0_kind.factory.owner_version != (
        changed.object_kinds[0].k0_kind.factory.owner_version
    )
    state = first.record("Box")(first.record("Item")("x", 4, None), ())
    with pytest.raises(K0ProfileError, match="version"):
        changed.owner("box").owner.decode_state(first.owner("box").owner.encode_state(state))


def test_production_profile_uses_generated_owner_and_object_factory_layout():
    root = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
    lib, ports, source = (
        read_author_document(root / f"object_target_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source")
    )
    checked = check_nominal_lib(lib)
    graph = check_graph_ports(ports, checked)
    program = compile_owner_graph(graph, source)
    assert graph.value_backend.owner_layout is checked.owner_layout
    assert {owner.key: owner for owner in program.profile.owners} == {
        item.owner.key: item.owner for item in checked.owner_layout.owners
    }
    assert {kind.family: kind.factory for kind in program.profile.dynamic_owner_kinds} == {
        item.symbol: item.k0_kind.factory for item in checked.owner_layout.object_kinds
    }
    foreign = check_nominal_lib(lib)
    with pytest.raises(C0LawError, match="substituted"):
        compile_owner_graph(replace(graph, owners=foreign.owners), source)
    with pytest.raises(C0LawError, match="substituted"):
        compile_owner_graph(replace(graph, object_kinds=foreign.object_kinds), source)
    with pytest.raises(C0LawError, match="omitted"):
        compile_owner_graph(
            replace(graph, value_backend=C0ValueBackend(checked.record_layout)), source
        )
