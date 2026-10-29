"""Compilation-scoped facts for checked expressions, never a runtime evaluator."""

from dataclasses import dataclass

from .author_abilities.expressions import NORMALIZED_OPERATIONS
from .integer_ranges import IntegerRanges

_ITERATIONS = frozenset(
    {
        "filter",
        "map",
        "sum",
        "sum_by",
        "exists",
        "exactly_one",
        "forall",
        "min_by",
        "max_by",
        "latest_by",
    }
)
_MATERIALIZES = frozenset(
    {
        "construct",
        "collection",
        "known",
        "filter",
        "latest_by",
        "map",
        "distinct",
        "union",
        "difference",
        "append",
        "concat",
        "take",
        "drop",
        "local_view",
    }
)


@dataclass(frozen=True)
class ExpressionFacts:
    inputs: tuple
    local_views: tuple
    owner_reads: tuple
    reference_domains: tuple
    external_reads: tuple
    queries: tuple
    failures: tuple
    depth_bound: int
    step_bound: int | None
    iteration_dependent: bool
    may_materialize_values: bool
    value_budget_sensitive: bool

    @property
    def body_total_with_checked_inputs(self):
        """Intrinsic failures only; logical and value budgets remain separate conditions."""
        return not self.failures


class ExpressionAnalysis:
    def __init__(self):
        self._facts = {}
        self.integer_ranges = IntegerRanges()

    def facts(self, node):
        key = id(node)
        if key not in self._facts:
            # Retain nodes for this compilation so identity keys cannot be recycled.
            self._facts[key] = node, self._analyze(node)
        return self._facts[key][1]

    def scalar_result_with_checked_inputs(self, node, expected):
        """Prove a result-only check total; callers must retain all input checks.

        Native operators on checked values preserve exact scalar carriers. External
        reads are excluded because their declared types alone are not value proofs.
        A fresh scalar ValueBudget always fits: it checks one node at path ().
        """
        if node.value_type.kind != expected.kind:
            return False
        if expected.kind == "int":
            if expected.minimum is not None or expected.maximum is not None:
                return False
        elif expected.kind not in {"bool", "unit"}:
            return False
        return not self.facts(node).external_reads

    def bounded_integer_result_with_checked_inputs(self, node, expected):
        """Infer bounds, not operand validity; the caller must establish provenance."""
        if (
            expected.kind != "int"
            or (expected.minimum is None and expected.maximum is None)
            or self.facts(node).external_reads
        ):
            return False
        interval = self.integer_ranges.range(node)
        return interval is not None and interval.fits(expected)

    def _analyze(self, node):
        operation = node.operation
        children = tuple(self.facts(child) for child in node.children)
        query = self.facts(node.operand.body) if operation == "pure_call" else None
        dependencies = (*children, *((query,) if query is not None else ()))

        def joined(attribute, own=()):
            return tuple(
                sorted(set(own).union(*(getattr(facts, attribute) for facts in dependencies)))
            )

        reads, failures = set(), set()
        if operation == "local_view":
            reads.add("local_information")
            failures.add("missing_local_information")
        if operation in {"entity_field", "relation"}:
            reads.update(("owner_snapshot", "reference_domain"))
            failures.add("information_or_identity_check")
        if operation == "known":
            reads.add("reference_domain")
        if operation in {"//", "%"}:
            divisor = node.children[1].value_type
            if not (
                divisor.minimum is not None
                and divisor.minimum > 0
                or divisor.maximum is not None
                and divisor.maximum < 0
            ):
                failures.add("zero_divisor")
        if operation in {"construct", "collection", "known", "pure_call", "append"}:
            failures.add("value_check")
        if operation in {"at", "index_of"}:
            failures.add("sequence_selection")
        if operation in {"take", "drop"}:
            count = node.children[1].value_type
            if count.minimum is None or count.minimum < 0:
                failures.add("negative_prefix")
        if operation in {"min_by", "max_by"} and node.children[0].value_type.kind == "set":
            failures.add("ambiguous_selection")
        if operation not in NORMALIZED_OPERATIONS:
            reads.add("unknown_effects")
            failures.add("unknown_operation")

        depth = max((1 + facts.depth_bound for facts in dependencies), default=1)
        step_bound = None
        if operation not in _ITERATIONS and operation in NORMALIZED_OPERATIONS:
            bounds = [facts.step_bound for facts in dependencies]
            if all(bound is not None for bound in bounds):
                if operation == "if":
                    step_bound = 1 + bounds[0] + max(bounds[1:])
                elif operation == "match":
                    step_bound = 1 + bounds[0] + max(bounds[1:], default=0)
                else:
                    step_bound = 1 + sum(bounds)
        return ExpressionFacts(
            tuple(sorted({read.root for read in node.reads})),
            joined("local_views", (node.operand,) if operation == "local_view" else ()),
            node.owner_reads,
            node.reference_domains,
            joined("external_reads", reads),
            joined("queries", (node.operand.name,) if operation == "pure_call" else ()),
            joined("failures", failures),
            depth,
            step_bound,
            operation in _ITERATIONS or any(f.iteration_dependent for f in dependencies),
            operation in _MATERIALIZES
            or operation not in NORMALIZED_OPERATIONS
            or any(f.may_materialize_values for f in dependencies),
            operation in _MATERIALIZES
            or operation in {"pure_call", "local_view"}
            or operation not in NORMALIZED_OPERATIONS
            or any(f.value_budget_sensitive for f in dependencies),
        )
