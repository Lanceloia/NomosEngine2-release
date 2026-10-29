"""Recognize constant arms of a query's direct nominal variant dispatch."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConstantVariantPlan:
    parameter: int
    cases: tuple


def plan_constant_variant(definition):
    body = definition.body
    if body.operation != "match" or definition.returns.kind not in {
        "bool",
        "int",
        "text",
        "enum",
        "unit",
    }:
        return None
    subject = body.children[0]
    if subject.operation != "variable" or subject.value_type.kind != "variant":
        return None
    parameters = [name for name, _ in definition.parameters]
    if subject.operand not in parameters:
        return None
    cases = tuple(
        (tag, branch.operand, branch.offset)
        for (tag, _, _), branch in zip(body.operand, body.children[1:], strict=True)
        if branch.operation == "literal"
    )
    return ConstantVariantPlan(parameters.index(subject.operand), cases) if cases else None
