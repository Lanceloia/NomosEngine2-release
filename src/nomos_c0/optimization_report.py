"""Optional author-located compilation reports; not part of generated execution."""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionAnalysis:
    function: str
    source: str
    mode: str
    facts: object


@dataclass(frozen=True)
class OptimizationRemark:
    status: str
    optimization: str
    function: str
    source: str
    offsets: tuple
    reason: str
    detail: str
    file: str | None = None
    anchor_line: int | None = None
    anchor_column: int | None = None
    expression_line: int = 1
    expression_column: int = 1


class OptimizationReport:
    def __init__(self):
        self.functions = []
        self.remarks = []
        self.generated_value_checks = []
        self.generated_scalar_checks = []
        self.generated_shape_checks = []
        self._started = False

    def begin(self):
        if self._started:
            raise ValueError("use a fresh optimization report for each compilation")
        self._started = True

    def analyze(self, function, source, mode, facts):
        self.functions.append(FunctionAnalysis(function, source.path, mode, facts))

    def remark(self, status, optimization, function, source, offsets, reason, detail):
        if status not in {"Passed", "Missed", "Analysis"}:
            raise ValueError("unknown optimization remark status")
        span = source.span
        offsets = tuple(offsets)
        prefix = source.text[: offsets[0]] if offsets else ""
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1]) + 1
        self.remarks.append(
            OptimizationRemark(
                status,
                optimization,
                function,
                source.path,
                offsets,
                reason,
                detail,
                None if span is None else span.file,
                None if span is None else span.line,
                None if span is None else span.column,
                line,
                column,
            )
        )

    def render(self):
        """Render Markdown with source paths as the primary navigation."""
        counts = Counter(remark.status for remark in self.remarks)
        lines = [
            "# C0 Optimization Report",
            "",
            f"Functions analyzed: {len(self.functions)}. "
            f"Passed: {counts['Passed']}. Missed: {counts['Missed']}.",
            "",
            "Scope: grouped/indexed collections, lazy pure-query sharing/inlining, "
            "record parameters, native scalar proofs, local copies and budget lowering. "
            "Missed reports a local decision, not a failed compilation.",
            "",
            "Body facts assume checked inputs; intrinsic failures, logical steps, "
            "value budgets and read permissions are distinct conditions. "
            "Entry and final result checks are outside these body facts. "
            "Unknown step bounds are not infinite loops. Record-parameter escape analysis "
            "does not prove world-entity lifetime or whole-program escape properties.",
            "",
        ]
        if self.generated_value_checks:
            lines.extend(
                [
                    "Generated nominal boundaries: "
                    f"{len(self.generated_value_checks)} functions with "
                    f"{sum(count for _, count in self.generated_value_checks)} "
                    "inlined ValueBudget visits. Node/depth limits and diagnostics remain; "
                    "these are generated boundaries, not additional authored source locations.",
                    "",
                ]
            )
        if self.generated_scalar_checks:
            lines.extend(
                [
                    "Generated scalar blocks: "
                    f"{sum(count for _, count in self.generated_scalar_checks)} "
                    "inlined leaf calls; all nominal checks and logical nodes remain.",
                    "",
                ]
            )
        if self.generated_shape_checks:
            lines.extend(
                [
                    "Generated structural leaf blocks: "
                    f"{sum(count for _, count in self.generated_shape_checks)} "
                    "inlined shape calls; field evaluation and every structural node remain.",
                    "",
                ]
            )
        by_function = {}
        for remark in self.remarks:
            by_function.setdefault(remark.function, []).append(remark)
        for function in self.functions:
            remarks = by_function.get(function.function, ())
            if not remarks:
                continue
            facts = function.facts
            steps = "unknown" if facts.step_bound is None else str(facts.step_bound)
            lines.extend(
                [
                    f"## {function.source} ({function.function})",
                    "",
                    f"Mode: {function.mode}. Inputs: {', '.join(facts.inputs) or 'none'}. "
                    f"Views: {', '.join(facts.local_views) or 'none'}.",
                    "",
                    f"Reads: {', '.join(facts.external_reads) or 'none'}. "
                    f"Possible intrinsic failures: {', '.join(facts.failures) or 'none'}.",
                    "",
                    f"Body depth <= {facts.depth_bound}; logical visits <= {steps}. "
                    f"Iteration-dependent: {facts.iteration_dependent}. "
                    f"May materialize values: {facts.may_materialize_values}. "
                    f"Value-budget-sensitive: {facts.value_budget_sensitive}.",
                    "",
                ]
            )
            for remark in remarks:
                offsets = ", ".join(str(offset) for offset in remark.offsets)
                # Escape authored text so identifiers cannot alter the report structure.
                detail = remark.detail.replace("\\", "\\\\").replace("`", "\\`")
                detail = " ".join(detail.splitlines())
                lines.append(
                    f"- **{remark.status}** `{remark.optimization}` at offsets {offsets}: "
                    f"{remark.reason}. {detail}"
                    + (
                        f" YAML scalar anchor: {remark.file}:"
                        f"{remark.anchor_line}:{remark.anchor_column}; "
                        f"decoded expression: {remark.expression_line}:"
                        f"{remark.expression_column}."
                        if remark.file is not None
                        else ""
                    )
                )
            lines.append("")
        return "\n".join(lines) + "\n"
