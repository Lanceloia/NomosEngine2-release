"""Reference key dispatch preserves post-read metadata and full uniqueness checks."""

from dataclasses import replace

import pytest
from test_count_predicate_v1 import Inventory, Item, _compile
from test_invariant_execution_v1 import rewrite

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.expression_ir_v1 import closed_value_type


@pytest.fixture
def reference():
    compiled = _compile("exists(item for item in inventory.items if item.value > 0)")
    return compiled.guard_ir.expression.operand["collection"], compiled._admission_ports


def _read(node, ports, items):
    roots = {"inventory": Inventory(items, "same")}
    return values._eval_reference(node, roots, ports.roots, ports)


@pytest.mark.parametrize("keyed", [False, True])
def test_ref_skips_generic_key_dispatch_without_skipping_current_values(
    monkeypatch, reference, keyed
):
    node, ports = reference

    def generic(*args):
        pytest.fail("unchanged ref called generic collection-key dispatch")

    monkeypatch.setattr(values, "_collection_key", generic)
    with rewrite(ports, collection_keys={"inventory.items": "key"} if keyed else {}):
        for items in ((), (Item("a", 1),), (Item("b", 2),)):
            assert _read(node, ports, items) is items


def test_full_uniqueness_checks_later_rows_before_predicate_short_circuit(reference):
    node, ports = reference
    items = (Item("first", 1), Item("same", 2), Item("same", 3))
    with pytest.raises(values.C0ValueStateError, match="collection key is not unique"):
        _read(node, ports, items)


@pytest.mark.parametrize("mutation", ["ports", "operand", "type"])
def test_ref_uses_key_and_result_type_after_read(monkeypatch, reference, mutation):
    node, ports = reference
    original = values._read_reference
    order = []

    class Keys(dict):
        def get(self, key, default=None):
            order.append(("key", key))
            return super().get(key, default)

    def read(parts, context, env, actual_ports):
        result = original(parts, context, env, actual_ports)
        if parts == ("inventory", "items"):
            order.append("read")
            if mutation == "ports":
                object.__setattr__(
                    actual_ports, "collection_keys", Keys({"inventory.items": "key"})
                )
            elif mutation == "operand":
                object.__setattr__(node, "operand", "changed.items")
            else:
                object.__setattr__(node, "value_type", closed_value_type(int))
        return result

    monkeypatch.setattr(values, "_read_reference", read)
    keys = Keys({"changed.items" if mutation == "operand" else "inventory.items": "key"})
    with rewrite(ports, collection_keys={} if mutation == "ports" else keys):
        with rewrite(node, operand=node.operand, value_type=node.value_type):
            error = C0LawError if mutation == "type" else values.C0ValueStateError
            message = "homogeneous typed tuple" if mutation == "type" else "key is not unique"
            with pytest.raises(error, match=message):
                _read(node, ports, (Item("same", 1), Item("same", 2)))
    path = "changed.items" if mutation == "operand" else "inventory.items"
    assert order[:2] == ["read", ("key", path)]


@pytest.mark.parametrize("operation", ["append", "replace_unique", "const"])
def test_changed_operation_uses_original_dispatch_after_read(monkeypatch, reference, operation):
    node, ports = reference
    original_read = values._read_reference
    original_key = values._collection_key
    order = []
    if operation == "append":
        operand = (replace(node),)
    elif operation == "replace_unique":
        operand = {"collection": {"ref": "inventory.items"}}
    else:
        operand = True

    def read(parts, context, env, actual_ports):
        result = original_read(parts, context, env, actual_ports)
        if parts == ("inventory", "items"):
            order.append("read")
            object.__setattr__(node, "operation", operation)
            # append delegates to a separate unchanged ref, not itself.
            object.__setattr__(node, "operand", operand)
        return result

    def key(actual, actual_ports):
        order.append(("dispatch", actual.operation))
        return original_key(actual, actual_ports)

    monkeypatch.setattr(values, "_read_reference", read)
    monkeypatch.setattr(values, "_collection_key", key)
    items = (Item("same", 1), Item("same", 2))
    with rewrite(node, operation=node.operation, operand=node.operand):
        if operation == "const":
            assert _read(node, ports, items) is items
        else:
            with pytest.raises(values.C0ValueStateError, match="key is not unique"):
                _read(node, ports, items)
    assert order[:2] == ["read", ("dispatch", operation)]


def test_invalid_current_key_keeps_getter_then_permission_error(monkeypatch, reference):
    node, ports = reference
    order = []

    def getter(item):
        order.append("getter")
        return "same"

    monkeypatch.setattr(Item, "missing", property(getter), raising=False)
    with rewrite(ports, collection_keys={"inventory.items": "missing"}):
        with pytest.raises(C0LawError, match="declared read port"):
            _read(node, ports, (Item("a", 1),))
    assert order == ["getter"]


def test_read_failure_does_not_lookup_key(monkeypatch, reference):
    node, ports = reference

    class Keys(dict):
        def get(self, *args):
            pytest.fail("key lookup preceded the failing read")

    with rewrite(ports, collection_keys=Keys()):
        with pytest.raises(C0LawError, match="declared read port"):
            with rewrite(ports, readable_fields={}):
                _read(node, ports, (Item("a", 1),))
