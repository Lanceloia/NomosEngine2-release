"""Compile-time value proofs and their lexical lifetime, separate from AST emission."""

from contextlib import contextmanager

_OPERAND_OPERATIONS = frozenset(
    {
        "+",
        "-",
        "*",
        "//",
        "%",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "in",
        "not in",
        "is",
        "is not",
        "if",
        "and",
        "or",
        "not",
        "unary",
        "size",
        "contains",
        "index_of",
    }
)


class ValueProofs:
    def __init__(self, types, analysis, table):
        self.types = types
        self.analysis = analysis
        self.table = table
        self.bindings = set()
        self.local_views = set()

    def reset(self, bindings=()):
        """Start a generated function; no proof survives from its predecessor."""
        self.bindings = set(bindings)
        self.local_views = set()

    @contextmanager
    def branch(self):
        """Inherit dominating reads, but do not export a selected branch's reads."""
        previous = self.local_views
        self.local_views = set(previous)
        try:
            yield
        finally:
            self.local_views = previous

    @contextmanager
    def bound(self, binding, *, validated):
        previous = self.bindings
        if validated:
            self.bindings = previous | {binding}
        try:
            with self.branch():
                yield
        finally:
            self.bindings = previous

    @contextmanager
    def call(self, bindings):
        """An inlined callee receives checked formals, not its caller's local reads."""
        previous = self.bindings, self.local_views
        self.reset(bindings)
        try:
            yield
        finally:
            self.bindings, self.local_views = previous

    def validated_argument(self, node, plan, environment, *, bindings=None):
        # Equal types alone are insufficient: the actual value needs a checked origin.
        if not self.types.equivalent_validation(node.value_type, plan):
            return False
        while node.operation == "field":
            node = node.children[0]
        if node.operation in {"if", "match"}:
            return self.branch_argument_proven(node, environment, bindings=bindings)
        if node.operation in {"pure_call", "construct", "collection", "known", "latest_by"}:
            return True
        if node.operation == "local_view":
            return (node.operand, node.value_type.type_id) in self.local_views
        if self.proven_subset(node, environment, bindings=bindings):
            return True
        if node.operation in {"map", "distinct", "union", "concat", "append"}:
            return self.produced_collection_proven(node, environment, bindings=bindings)
        if node.operation == "at":
            pool = node.children[0]
            return self.validated_argument(pool, pool.value_type, environment, bindings=bindings)
        bindings = self.bindings if bindings is None else bindings
        return node.operation == "variable" and environment[node.operand] in bindings

    def produced_collection_proven(self, node, environment, *, bindings=None):
        bindings = self.bindings if bindings is None else bindings
        pool = node.children[0]
        pool_proven = self.validated_argument(pool, pool.value_type, environment, bindings=bindings)
        if node.operation == "map":
            binder = object()
            local = {**environment, node.operand: binder}
            checked = bindings | {binder} if pool_proven else bindings
            child, plan = node.children[1], node.value_type.element
            return self.validated_argument(child, plan, local, bindings=checked) or (
                self.checked_operands(child, local, bindings=checked)
                and (
                    self.analysis.scalar_result_with_checked_inputs(child, plan)
                    or self.analysis.bounded_integer_result_with_checked_inputs(child, plan)
                )
            )
        if not pool_proven or not self.types.equivalent_validation(
            pool.value_type.element, node.value_type.element
        ):
            return False
        if node.operation == "distinct":
            return True
        if node.operation == "append":
            inserted_check = self.table.expression_type(node.value_type.element)
            return self.types.equivalent_validation(inserted_check, node.value_type.element)
        other = node.children[1]
        return self.types.equivalent_validation(
            other.value_type.element, node.value_type.element
        ) and self.validated_argument(other, other.value_type, environment, bindings=bindings)

    def branch_argument_proven(self, node, environment, *, bindings=None):
        bindings = self.bindings if bindings is None else bindings
        if node.operation == "if":
            return all(
                self.validated_argument(child, node.value_type, environment, bindings=bindings)
                for child in node.children[1:]
            )
        subject, *branches = node.children
        if not self.validated_argument(subject, subject.value_type, environment, bindings=bindings):
            return False
        for (_, parameter, _), child in zip(node.operand, branches, strict=True):
            binder = object()
            if not self.validated_argument(
                child,
                node.value_type,
                environment if parameter is None else {**environment, parameter: binder},
                bindings=bindings if parameter is None else bindings | {binder},
            ):
                return False
        return True

    def proven_subset(self, node, environment, *, bindings=None):
        if node.operation not in {"filter", "take", "drop", "difference"}:
            return False
        pool = node.children[0]
        return self.types.equivalent_validation(
            node.value_type, pool.value_type
        ) and self.validated_argument(pool, pool.value_type, environment, bindings=bindings)

    def checked_operands(self, node, environment, *, bindings=None):
        if self.validated_argument(node, node.value_type, environment, bindings=bindings):
            return True
        if node.operation == "literal":
            return True
        bindings = self.bindings if bindings is None else bindings
        if node.operation in {
            "sum_by",
            "exists",
            "exactly_one",
            "forall",
            "map",
            "filter",
            "min_by",
            "max_by",
            "latest_by",
        }:
            pool, *expressions = node.children
            if not self.validated_argument(pool, pool.value_type, environment, bindings=bindings):
                return False
            parameters = (
                node.operand
                if node.operation in {"min_by", "max_by", "latest_by"}
                else (node.operand,)
            )
            for parameter, expression in zip(parameters, expressions, strict=True):
                binder = object()
                if not self.checked_operands(
                    expression, {**environment, parameter: binder}, bindings=bindings | {binder}
                ):
                    return False
            return True
        if node.operation == "match":
            subject, *branches = node.children
            if not self.validated_argument(
                subject, subject.value_type, environment, bindings=bindings
            ):
                return False
            for (_, parameter, _), expression in zip(node.operand, branches, strict=True):
                binder = object()
                if not self.checked_operands(
                    expression,
                    environment if parameter is None else {**environment, parameter: binder},
                    bindings=bindings if parameter is None else bindings | {binder},
                ):
                    return False
            return True
        if node.operation == "sum":
            pool = node.children[0]
            return self.validated_argument(pool, pool.value_type, environment, bindings=bindings)
        # A checked boundary is opaque; raw external reads are not.
        if node.operation not in _OPERAND_OPERATIONS:
            return False
        return all(
            self.checked_operands(child, environment, bindings=bindings) for child in node.children
        )

    def record_fields_proven(self, node, environment, *, bindings=None):
        return all(
            plan.kind in {"bool", "unit", "int", "text", "enum"}
            and (
                self.validated_argument(child, plan, environment, bindings=bindings)
                or self.checked_operands(child, environment, bindings=bindings)
                and self.analysis.scalar_result_with_checked_inputs(child, plan)
            )
            for (_, plan), child in zip(node.value_type.fields, node.children, strict=True)
        )

    def scalar_result_proven(self, node, plan, environment, *, bindings=None):
        return self.analysis.scalar_result_with_checked_inputs(node, plan) or (
            self.checked_operands(node, environment, bindings=bindings)
            and self.analysis.bounded_integer_result_with_checked_inputs(node, plan)
        )
