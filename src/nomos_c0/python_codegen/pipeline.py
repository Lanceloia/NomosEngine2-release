"""Ordered AST cleanup for compiler-owned code; no runtime pass dispatch."""

import ast
from dataclasses import dataclass

from .budget_blocks import fold_budget_blocks
from .limit_guards import elide_value_limit_guards
from .local_budget import scalarize_budget
from .local_copies import propagate_local_copies
from .scalar_checks import inline_scalar_checks, inline_shape_checks
from .value_budget import inline_value_budget_checks


@dataclass(frozen=True)
class PassContract:
    name: str
    requires: frozenset[str]
    establishes: str


MODULE_PASSES = (
    PassContract("value-budget", frozenset({"emitted-module"}), "nominal-budget-lowered"),
    PassContract("shape-leaves", frozenset({"nominal-budget-lowered"}), "shape-leaves-lowered"),
    PassContract("scalar-leaves", frozenset({"shape-leaves-lowered"}), "scalar-leaves-lowered"),
    PassContract("budget-blocks", frozenset({"scalar-leaves-lowered"}), "budget-blocks-folded"),
)
FUNCTION_PASSES = (
    PassContract("limit-guards", frozenset({"budget-blocks-folded"}), "limit-guards-pruned"),
    PassContract("local-copies", frozenset({"limit-guards-pruned"}), "local-copies-propagated"),
    PassContract("local-budget", frozenset({"local-copies-propagated"}), "local-budget-lowered"),
)


def validate_order(passes, available):
    """Reject a broken compiler pipeline before mutating any generated AST."""
    available = set(available)
    names = set()
    for item in passes:
        missing = item.requires - available
        if missing or item.name in names or item.establishes in available:
            raise ValueError(f"invalid compiler pass order at {item.name}: {sorted(missing)}")
        names.add(item.name)
        available.add(item.establishes)
    return frozenset(available)


class ModuleOptimizer:
    def __init__(self, types, sources, function_sources, report):
        self.types = types
        self.sources = sources
        self.function_sources = function_sources
        self.report = report

    def note(self, function, optimization, source, offsets, reason, detail):
        if self.report is not None:
            self.report.remark(
                "Passed", optimization, function.name, source, offsets, reason, detail
            )

    def value_budget(self, body):
        for function in body:
            if isinstance(function, ast.FunctionDef):
                checks = inline_value_budget_checks(function)
                if checks and self.report is not None:
                    self.report.generated_value_checks.append((function.name, checks))

    def shape_leaves(self, body):
        checks = inline_shape_checks(body, self.types)
        if self.report is not None:
            self.report.generated_shape_checks.extend(checks)

    def scalar_leaves(self, body):
        checks = inline_scalar_checks(body, self.types)
        if self.report is not None:
            self.report.generated_scalar_checks.extend(checks)

    def budget_blocks(self, body):
        for function in body:
            if not isinstance(function, ast.FunctionDef):
                continue
            for block in fold_budget_blocks(function):
                self.note(
                    function,
                    "budget-block",
                    self.sources[int(block.source.removeprefix("_SOURCE_"))],
                    tuple(offset for offset, _ in block.sites),
                    "total-local-straight-line",
                    f"Combine {len(block.sites)} visits; retain exact logical steps and "
                    "ordered failure diagnostics.",
                )

    def limit_guards(self, function):
        guards = elide_value_limit_guards(function)
        if guards:
            self.note(
                function,
                "value-limit-guard-dominance",
                self.function_sources[function.name],
                (),
                "unrebound-formal-and-prior-successful-intrinsic-guard",
                f"Omit {guards} repeated limit type guards; retain their first "
                "execution, branches, exceptions and every budget check.",
            )

    def local_copies(self, function):
        copies = propagate_local_copies(function)
        if copies.substitutions or copies.removed_assignments:
            self.note(
                function,
                "local-copy-propagation",
                self.function_sources[function.name],
                (),
                "definitely-bound-local-names",
                f"Replace {copies.substitutions} local loads and remove "
                f"{copies.removed_assignments} unused copy/literal assignments; "
                "keep producers, checks, control flow and logical budgets.",
            )

    def local_budget(self, function):
        budget = scalarize_budget(function)
        if budget.visits:
            self.note(
                function,
                "local-budget-counter",
                self.function_sources[function.name],
                (),
                budget.reason,
                f"Inline {budget.visits} budget sites with {budget.boundaries} "
                "synchronized call boundaries; retain logical costs and failure steps.",
            )

    def run(self, body):
        available = validate_order(MODULE_PASSES, {"emitted-module"})
        validate_order(FUNCTION_PASSES, available)
        # Resolve the entire fixed pipeline before the first mutation. Unknown passes
        # are compiler defects, never silently skipped optimizations.
        module_steps = tuple(getattr(self, p.name.replace("-", "_")) for p in MODULE_PASSES)
        function_steps = tuple(getattr(self, p.name.replace("-", "_")) for p in FUNCTION_PASSES)
        for step in module_steps:
            step(body)
        for function in body:
            if isinstance(function, ast.FunctionDef) and function.name in self.function_sources:
                for step in function_steps:
                    step(function)
