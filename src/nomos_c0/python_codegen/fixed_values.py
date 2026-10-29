"""Generate typed fixed-value construction without depending on world assembly state."""

from nomos_c0.author_contract_v1 import C0LawError


def fixed_value(
    table, parameter, *, references="session.references", limits="session.limits.value"
):
    from nomos_c0.author_abilities.projections import OpeningDomain

    if type(parameter.node) is OpeningDomain:
        return (
            f"_VALIDATORS[{parameter.type_name!r}](frozenset(ref for ref in "
            f"{references}.symbols.values() if {references}.accepts("
            f"{parameter.node.sort!r}, ref.sort)), "
            f"ValueBudget({limits}, {references}), ())"
        )
    plan = table[parameter.type_name]

    def wire(node, kind):
        from nomos_c0.author_abilities.literal_values import (
            CollectionLiteral,
            RecordLiteral,
            ScalarLiteral,
            SymbolLiteral,
        )

        if type(node) is ScalarLiteral:
            return node.value
        if kind.kind == "optional":
            return wire(node, kind.element)
        if type(node) is SymbolLiteral:
            return {node.kind: node.symbol}
        if type(node) is CollectionLiteral:
            return [wire(child, kind.element) for child in node.values]
        if type(node) is RecordLiteral:
            if kind.kind == "variant":
                tag, case = next(
                    (tag, case) for tag, case in kind.cases if case.name == node.type_name
                )
                return {"tag": tag, "fields": wire(node, case)}
            children = dict(node.values)
            return {name: wire(children[name], child) for name, child in kind.fields}
        raise C0LawError(
            "Python world generation does not yet support fixed parameter construction"
        )

    return (
        f"_DECODERS[{parameter.type_name!r}]({wire(parameter.node, plan)!r}, "
        f"ValueBudget({limits}, {references}), ())"
    )
