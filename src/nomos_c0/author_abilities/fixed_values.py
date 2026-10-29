"""Fold closed fixed expressions before emitting any world execution code."""

from nomos_c0.author_contract_v1 import C0LawError

from .constant_folding import fold_constant
from .constant_values import ConstantValues
from .literal_values import CollectionLiteral, RecordLiteral, ScalarLiteral, SymbolLiteral


def evaluate_fixed(expression, parameters, symbols):
    if (
        expression.summary.owner_reads
        or expression.summary.reference_domains
        or expression.actor is not None
    ):
        raise C0LawError("fixed expression cannot query owners, knowledge or a controller")
    values = ConstantValues(expression.table, symbols)

    def resolve(node):
        if type(node) is ScalarLiteral:
            return node.value
        if type(node) is SymbolLiteral:
            return node
        if type(node) is CollectionLiteral:
            children = tuple(resolve(child) for child in node.values)
            result = frozenset(children) if node.kind == "set" else children
            if len(result) != len(children):
                raise C0LawError("fixed set has duplicate values")
            return result
        if type(node) is RecordLiteral:
            return values.construct(
                node.type_name, {name: resolve(child) for name, child in node.values}
            ).value
        raise C0LawError("fixed expression has an undeclared literal node")

    selected = {parameter.name: parameter for parameter in parameters}
    environment = {
        name: resolve(selected[name].node) for name, _ in expression.inputs
    }
    return fold_constant(expression, values, environment)
