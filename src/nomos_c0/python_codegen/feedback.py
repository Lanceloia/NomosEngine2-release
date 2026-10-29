"""Emit data-only interpretation functions and exact receipt bindings."""

from hashlib import sha256


def _projection_key(expression):
    summary = expression.summary
    identity = (
        expression.read_key,
        expression.result.type_id,
        expression.limits,
        expression.inputs,
        summary.context,
        summary.owner_reads,
        summary.reference_domains,
        tuple((query.definition, query.offset, query.arguments) for query in summary.dependencies),
    )
    return sha256(repr(identity).encode()).hexdigest()


def definitions(emitter, index, profile):
    rules = []
    for ordinal, plan in enumerate(profile.feedback):
        prefix = f"_feedback_{index}_{ordinal}"
        ports = []
        for number, receipt in enumerate(plan.receipts):
            function = prefix + f"_match_{number}"
            lines = ["values = []"]
            for key, kind, expression in receipt.matches:
                value = emitter.expression(expression, reads="reads", limits="limits")
                lines.extend(
                    [
                        f"value = {value}",
                        f"_VALIDATORS[{kind!r}](value, ValueBudget(limits, reads.references), ())",
                        f"values.append(({key!r}, Term({kind!r}, _TERM_CODECS[{kind!r}][0], "
                        f"_TERM_CODECS[{kind!r}][1](value))))",
                    ]
                )
            lines.append("return tuple(values)")
            emitter.function(function, "environment, reads, limits", lines)
            predicate = "None"
            if receipt.predicate is not None:
                predicate = prefix + f"_accept_{number}"
                emitter.function(
                    predicate,
                    "environment, reads, limits",
                    [
                        "return "
                        + emitter.expression(receipt.predicate, reads="reads", limits="limits")
                    ],
                )
            relation = "None"
            if receipt.relation is not None:
                selected = receipt.relation
                kind = selected.key.result.name
                for label, checked in (("key", selected.key), ("link", selected.link)):
                    name = prefix + f"_relation_{number}_{label}"
                    value = emitter.expression(checked, reads="reads", limits="limits")
                    nullable = (
                        ["if value is None: return None"]
                        if checked.result.kind == "optional"
                        else []
                    )
                    emitter.function(
                        name,
                        "environment, reads, limits",
                        [
                            f"value = {value}",
                            *nullable,
                            f"_VALIDATORS[{kind!r}](value, "
                            "ValueBudget(limits, reads.references), ())",
                            f"return Term({kind!r}, _TERM_CODECS[{kind!r}][0], "
                            f"_TERM_CODECS[{kind!r}][1](value))",
                        ],
                    )
                roots = prefix + f"_relation_{number}_roots"
                value = emitter.expression(selected.roots, reads="reads", limits="limits")
                emitter.function(
                    roots,
                    "environment, reads, limits",
                    [
                        f"values = {value}",
                        "terms = []",
                        "for value in values:",
                        f"    _VALIDATORS[{kind!r}](value, "
                        "ValueBudget(limits, reads.references), ())",
                        f"    terms.append(Term({kind!r}, _TERM_CODECS[{kind!r}][0], "
                        f"_TERM_CODECS[{kind!r}][1](value)))",
                        "return tuple(terms)",
                    ],
                )
                projection = _projection_key(selected.key), _projection_key(selected.link)
                relation = (
                    f"FeedbackRelation({prefix + f'_relation_{number}_key'}, "
                    f"{prefix + f'_relation_{number}_link'}, {roots}, "
                    f"{selected.depth!r}, {projection!r})"
                )
            ports.append(
                f"FeedbackPort({receipt.name!r}, {receipt.kind!r}, {receipt.channel!r}, "
                f"{receipt.source!r}, {receipt.type_name!r}, {function}, "
                f"{receipt.collection_type!r}, {receipt.item!r}, {receipt.until!r}, {predicate}, "
                f"{receipt.boundary!r}, {relation})"
            )
        when = emitter.expression(plan.when, reads="reads", limits="limits")
        values = ", ".join(
            f"({axis!r}, {emitter.expression(expr, reads='reads', limits='limits')})"
            for axis, expr in plan.outcomes
        )
        emitter.function(
            prefix,
            "environment, reads, limits",
            [
                f"if not {when}: return None",
                f"return ({values},)",
            ],
        )
        rules.append(
            f"FeedbackRule({plan.name!r}, {plan.ability!r}, {plan.inputs!r}, "
            f"({', '.join(ports)},), {prefix}, {plan.personal!r})"
        )
    return "(" + ", ".join(rules) + ("," if rules else "") + ")"
