"""Bounded inlining of checked scalar leaves and acyclic pure forwarding bodies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryInlineDecision:
    selected: bool
    reason: str
    size: int = 0


class QueryInlinePlan:
    def __init__(self, analysis):
        self.analysis = analysis
        self.remaining = 96

    def select(self, definition, *, shared=False):
        if shared:
            return QueryInlineDecision(False, "dominating-query-sharing")
        facts = self.analysis.facts(definition.body)
        if definition.returns.kind not in {"bool", "int", "text", "enum", "unit"}:
            return QueryInlineDecision(False, "non-scalar-result")
        if facts.external_reads or facts.may_materialize_values:
            return QueryInlineDecision(False, "external-or-materialized-body")
        forwarder = definition.body.operation == "pure_call" and all(
            not self.analysis.facts(argument).queries
            and not self.analysis.facts(argument).iteration_dependent
            for argument in definition.body.children
        )
        if not forwarder and (facts.queries or facts.iteration_dependent):
            return QueryInlineDecision(False, "non-leaf-body")

        def size_of(node):
            return 1 + sum(size_of(child) for child in node.children)

        size = size_of(definition.body)
        if size > 24:
            return QueryInlineDecision(False, "body-size-limit")
        if size > self.remaining:
            return QueryInlineDecision(False, "function-growth-limit", size)
        self.remaining -= size
        return QueryInlineDecision(
            True, "bounded-scalar-forwarder" if forwarder else "bounded-scalar-leaf", size
        )
