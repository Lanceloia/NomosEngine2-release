"""Find non-escaping record arguments to bounded scalar query inlining."""

from dataclasses import dataclass


@dataclass(frozen=True, eq=False)
class VirtualRecord:
    """Compiler-only fields; never emitted as a Python runtime value."""

    fields: tuple


def can_project_record(argument, parameter, name, body, *, shared=False, forwarded=False):
    if shared or parameter.kind != "record" or argument.value_type.type_id != parameter.type_id:
        return False
    construct = argument
    if argument.operation == "pure_call":
        definition = argument.operand
        if definition.returns.type_id != parameter.type_id:
            return False
        construct = definition.body

        def wrapper_size(node):
            if node.operation not in {"construct", "literal", "variable", "field"}:
                return 25
            return 1 + sum(wrapper_size(child) for child in node.children)

        # Constructor wrappers only. In particular, do not inline owner reads
        # whose controller role belongs to the original query call.
        if wrapper_size(construct) > 24:
            return False
    if (
        construct.operation != "construct"
        or construct.value_type.type_id != parameter.type_id
        or construct.operand[0] is not None
        or len(parameter.fields) > (16 if forwarded else 8)
    ):
        return False

    def fields_only(node, parent=None):
        # Binder scopes need separate escape analysis; this slice has none.
        if node.operation in {
            "match",
            "filter",
            "map",
            "sum_by",
            "exists",
            "forall",
            "exactly_one",
        }:
            return False
        if node.operation == "variable" and node.operand == name:
            return parent is not None and parent.operation == "field"
        return all(fields_only(child, node) for child in node.children)

    return forwarded or fields_only(body)
