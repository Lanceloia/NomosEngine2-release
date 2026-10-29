"""Nominal record paths and lexical pool identities shared by query planning."""

from dataclasses import dataclass

HASHABLE_SCALARS = frozenset({"bool", "int", "text", "enum", "ref", "unit"})


@dataclass(frozen=True)
class FieldProjection:
    fields: tuple
    type_id: object
    kind: str


def projection(node, binder):
    fields, current = [], node
    while current.operation == "field":
        record, name = current.operand
        if record.kind != "record":
            return None
        fields.append((record, name))
        current = current.children[0]
    if current.operation != "variable" or current.operand != binder:
        return None
    return FieldProjection(tuple(reversed(fields)), node.value_type.type_id, node.value_type.kind)


def same_projection(left, right):
    return (
        left is not None
        and right is not None
        and left.type_id == right.type_id
        and tuple((p.type_id, n) for p, n in left.fields)
        == tuple((p.type_id, n) for p, n in right.fields)
    )


def pool_binding(node):
    # Provenance may alias two lambda elements; actual lexical roots cannot.
    fields, current = [], node
    while current.operation == "field":
        record, name = current.operand
        if record.kind != "record":
            return None
        fields.append((record.type_id, name))
        current = current.children[0]
    if current.operation != "variable":
        return None
    return current.operand, tuple(reversed(fields)), node.value_type.type_id
