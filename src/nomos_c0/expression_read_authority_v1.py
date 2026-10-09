"""Recheck typed expression reads under checked lexical scopes."""

from collections.abc import Mapping
from typing import get_args

from .author_contract_v1 import C0LawError
from .composable_value_v1 import _field_type, _nonnull, _tuple_item
from .expression_ir_v1 import C0Expression
from .variant_types_v1 import variant_cases


def check_expression_reads(expression, ports, roots):
    budget = [8192]

    def walk(value, allowed, locals, types, depth=0):
        if type(value) is C0Expression:
            budget[0] -= 1
            if budget[0] < 0 or depth > 64:
                raise C0LawError("expression exceeds its finite read-check bound")
            if value.stage != "admission":
                raise C0LawError("expression is unavailable before admission")
            if value.operation in ("ref", "empty_like"):
                path = value.operand
                root = path.split(".", 1)[0] if type(path) is str else None
                if value.operation == "empty_like" and root in locals:
                    raise C0LawError("empty collection needs a declared input path")
                projected = (
                    path if value.operation == "empty_like" else reference_path(value, locals)
                )
                if (root not in locals and root not in allowed) or (
                    projected is not None and projected not in ports.readable_paths
                ):
                    raise C0LawError("expression crosses its exact read authority")
                carrier = types[root]
                for part in path.split(".")[1:]:
                    carrier = _field_type(_nonnull(carrier) or carrier, part, ports)
                if value.operation == "empty_like":
                    _tuple_item(carrier)
                    if value.result_type != carrier:
                        raise C0LawError("empty collection differs from its declared type")
                return
            row = value.operand
            if value.operation == "call":
                walk(row["args"], allowed, locals, types, depth + 1)
                parameters = {
                    name: reference_path(row["args"][name], locals)
                    for name, _ in row["definition"].parameters
                }
                walk(
                    row["body"],
                    frozenset(),
                    parameters,
                    dict(row["definition"].parameters),
                    depth + 1,
                )
                return
            if value.operation == "let":
                walk(row["value"], allowed, locals, types, depth + 1)
                walk(
                    row["in"],
                    allowed,
                    local_scope(row["name"], allowed, locals, reference_path(row["value"], locals)),
                    {**types, row["name"]: row["value"].result_type},
                    depth + 1,
                )
                return
            if value.operation == "collection_query":
                walk(row["collection"], allowed, locals, types, depth + 1)
                walk(row["right_collection"], allowed, locals, types, depth + 1)
                scope = local_scope(row["as"], allowed, locals)
                scope = local_scope(row["right_as"], allowed, scope)
                local_types = {
                    **types,
                    row["as"]: _tuple_item(row["collection"].result_type),
                    row["right_as"]: _tuple_item(row["right_collection"].result_type),
                }
                left_key = _field_type(local_types[row["as"]], row["key"], ports)
                right_key = _field_type(local_types[row["right_as"]], row["right_key"], ports)
                if left_key != right_key:
                    raise C0LawError("query keys differ from their checked row types")
                walk(row["where"], allowed, scope, local_types, depth + 1)
                return
            if value.operation == "update_matching":
                walk(row["collection"], allowed, locals, types, depth + 1)
                walk(row["matching"], allowed, locals, types, depth + 1)
                scope = local_scope(row["as"], allowed, locals)
                local_types = {**types, row["as"]: _tuple_item(row["collection"].result_type)}
                _field_type(local_types[row["as"]], row["key"], ports)
                walk(row["set"], allowed, scope, local_types, depth + 1)
                return
            if value.operation == "insert_missing":
                walk(row["collection"], allowed, locals, types, depth + 1)
                walk(row["candidates"], allowed, locals, types, depth + 1)
                _field_type(_tuple_item(row["collection"].result_type), row["key"], ports)
                return
            if value.operation == "participant_query":
                walk(row["collection"], allowed, locals, types, depth + 1)
                walk(row["right_keys"], allowed, locals, types, depth + 1)
                scope = local_scope(row["as"], allowed, locals)
                local_types = {**types, row["as"]: get_args(row["collection"].result_type)[0]}
                walk(row["predicates"], allowed, scope, local_types, depth + 1)
                key_type = _field_type(local_types[row["as"]], row["key"], ports)
                if any(key.result_type != key_type for key in row["right_keys"]):
                    raise C0LawError("query key differs from its checked row type")
                return
            if value.operation == "unique_by":
                walk(row["collection"], allowed, locals, types, depth + 1)
                scope = local_scope(row["as"], allowed, locals)
                local_types = {**types, row["as"]: _tuple_item(row["collection"].result_type)}
                walk(row["keys"], allowed, scope, local_types, depth + 1)
                return
            if value.operation in {
                "none_matching",
                "exists",
                "exactly_one",
                "count_matching",
                "collect_matching",
            }:
                walk(row["collection"], allowed, locals, types, depth + 1)
                scope = local_scope(row["as"], allowed, locals)
                local_types = {**types, row["as"]: get_args(row["collection"].result_type)[0]}
                walk(row["where"], allowed, scope, local_types, depth + 1)
                if value.operation == "collect_matching":
                    walk(row["value"], allowed, scope, local_types, depth + 1)
                return
            if value.operation == "match":
                walk(row["value"], allowed, locals, types, depth + 1)
                cases = variant_cases(row["value"].result_type)
                for case, arm in row["cases"].items():
                    walk(
                        arm["then"],
                        allowed,
                        local_scope(arm["as"], allowed, locals),
                        {**types, arm["as"]: cases[case]},
                        depth + 1,
                    )
                return
            walk(row, allowed, locals, types, depth + 1)
        elif isinstance(value, Mapping):
            for child in value.values():
                walk(child, allowed, locals, types, depth)
        elif type(value) is tuple:
            for child in value:
                walk(child, allowed, locals, types, depth)

    def reference_path(value, locals):
        if type(value) is not C0Expression or value.operation != "ref":
            return None
        if type(value.operand) is not str:
            raise C0LawError("reference is malformed")
        root, separator, suffix = value.operand.partition(".")
        if root not in locals:
            return value.operand
        origin = locals[root]
        return None if origin is None else origin + separator + suffix

    def local_scope(name, allowed, locals, origin=None):
        if type(name) is not str or not name or name in allowed or name in locals:
            raise C0LawError("expression has a shadowing local alias")
        return {**locals, name: origin}

    walk(expression, roots, {}, dict(ports.roots))
