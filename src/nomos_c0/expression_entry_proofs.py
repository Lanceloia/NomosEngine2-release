"""Compile-time exact input contracts for private generated expression callers."""

from dataclasses import dataclass

from nomos_c0.author_abilities.expressions import CheckedValueExpression
from nomos_c0.author_abilities.value_types import TypeId
from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class ExpressionEntryProof:
    expression: CheckedValueExpression
    bindings: tuple[tuple[str, TypeId], ...]

    def checked_names(self, expression):
        if self.expression is not expression or expression.summary.context != "actor":
            raise C0LawError("expression input proof requires its exact Actor expression")
        expected = {
            name: expression.table[spec.type_name].type_id for name, spec in expression.inputs
        }
        if (
            type(self.bindings) is not tuple
            or any(type(row) is not tuple or len(row) != 2 for row in self.bindings)
            or any(
                type(name) is not str or type(kind) is not TypeId for name, kind in self.bindings
            )
            or len(dict(self.bindings)) != len(self.bindings)
            or any(expected.get(name) != kind for name, kind in self.bindings)
        ):
            raise C0LawError("expression input proof requires exact named input type identities")
        return frozenset(name for name, _ in self.bindings)
