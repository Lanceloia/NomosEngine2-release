"""Typed local pattern plans and pure expression adapters for derivation relations."""

from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError
from nomos_cognition.reasoning import Limits, Pattern, Premise, Rule, order_rules

from .expression_syntax import ExpressionLimits, _identifier, parse_expression
from .expressions import compile_value_expression
from .frontend import row


@dataclass(frozen=True)
class Derivation:
    rule: Rule
    constants: tuple
    each: tuple
    where: object
    conclusion: object
    polarity: str
    variables: tuple


def compile_derivations(program, model, actor, parameters, *, path, steps, context):
    table = program.table
    declaration = model.get("derive", {})
    if type(declaration) is not dict:
        raise C0LawError("derive requires named relations")
    limits = model.get("inference_limits", {})
    row(
        limits, set(), {"work", "arguments", "edges", "wire_bytes"}, path=path + ".inference_limits"
    )
    try:
        limits = Limits(**limits)
    except ValueError as error:
        raise C0LawError(str(error)) from error
    result = []
    for name, body in declaration.items():
        if not _identifier(name) or name == "base":
            raise C0LawError("derive needs valid nonreserved relation names")
        location = path + ".derive." + name
        row(body, {"variables", "premises", "conclude"}, {"each", "where"}, path=location)
        variables = body["variables"]
        if type(variables) is not dict or any(
            not _identifier(v)
            or v in {actor, "prior", *parameters}
            or type(t) is not str
            or t not in dict(table.definitions)
            for v, t in variables.items()
        ):
            raise C0LawError("derive variables require distinct declared nominal types")
        fixed = {actor: model["actor"][actor], **parameters}
        available = dict(fixed)
        bound, constants, premises = set(), [], []

        def expression(text, returns, environment):
            compiled = compile_value_expression(
                text,
                table,
                environment,
                returns=returns,
                library=program.queries,
                entities=program.entities,
                actor=actor,
                context="actor",
                path=location,
                span=None if context is None else context.locate(location),
                limits=ExpressionLimits(steps=steps),
            )
            if compiled.summary.owner_reads or compiled.summary.reference_domains:
                raise C0LawError("derive expressions may only read supplied local values")
            needed = {read.root for read in compiled.summary.reads}
            return replace(compiled, inputs=tuple(i for i in compiled.inputs if i[0] in needed))

        def wrapper(text, operations, arity):
            syntax = parse_expression(text, path=location, limits=ExpressionLimits(steps=steps))
            if (
                syntax.operation != "call"
                or len(syntax.children) != arity + 1
                or syntax.children[0].operation != "name"
                or syntax.children[0].value not in operations
            ):
                raise C0LawError("derive requires explicit literal polarity, not boolean negation")
            return syntax.children[0].value, syntax.children[1:]

        def pattern(syntax, expected, text):
            if syntax.operation == "name" and syntax.value in variables:
                if table[variables[syntax.value]].type_id != expected.type_id:
                    raise C0LawError("derive variable has an incompatible nominal type")
                bound.add(syntax.value)
                return Pattern(expected.name, expected.type_id.signature, "variable", syntax.value)
            if syntax.operation == "call":
                function, *arguments = syntax.children
                selected, tag = None, None
                if (
                    expected.kind == "record"
                    and function.operation == "name"
                    and function.value in dict(table.definitions)
                    and table[function.value].type_id == expected.type_id
                ):
                    selected = expected
                elif (
                    expected.kind == "variant"
                    and function.operation == "field"
                    and function.children[0].operation == "name"
                    and function.children[0].value in dict(table.definitions)
                    and table[function.children[0].value].type_id == expected.type_id
                ):
                    tag = function.value
                    selected = dict(expected.cases).get(tag)
                if selected is not None:
                    fields = dict(selected.fields)
                    supplied = {
                        argument.value: argument
                        for argument in arguments
                        if argument.operation == "keyword"
                    }
                    if len(supplied) != len(arguments) or set(supplied) != set(fields):
                        raise C0LawError("derive patterns require exact named constructor fields")
                    children = tuple(
                        pattern(supplied[field].children[0], kind, text)
                        for field, kind in selected.fields
                    )
                    record = Pattern(
                        selected.name, selected.type_id.signature, "tuple", None, children
                    )
                    return (
                        record
                        if tag is None
                        else Pattern(
                            expected.name,
                            expected.type_id.signature,
                            "case",
                            tag,
                            (record,),
                        )
                    )
            constant = expression(text[syntax.start : syntax.end], expected.name, fixed)
            constants.append(constant)
            return Pattern(
                expected.name, expected.type_id.signature, "constant", len(constants) - 1
            )

        texts = body["premises"]
        if type(texts) is not list or not texts:
            raise C0LawError("derive needs a nonempty premise list")
        for text in texts:
            polarity, (source, proposition) = wrapper(text, {"supports", "opposes"}, 2)
            if source.operation != "name" or source.value not in {"base", *declaration}:
                raise C0LawError("derive premise selects an unknown relation")
            premises.append(
                Premise(
                    source.value,
                    "support" if polarity == "supports" else "opposition",
                    pattern(proposition, table[model["propositions"]], text),
                )
            )
        if bound != set(variables):
            raise C0LawError(
                "derive has unbound variables: " + ", ".join(sorted(set(variables) - bound))
            )
        available.update(variables)
        each_rows, each = body.get("each", {}), []
        if type(each_rows) is not dict:
            raise C0LawError("derive each requires named finite collections")
        for variable, text in each_rows.items():
            if not _identifier(variable) or variable in {*available, "prior"}:
                raise C0LawError("derive each variable aliases its environment")
            compiled = expression(text, None, available)
            if compiled.result.kind not in ("set", "sequence"):
                raise C0LawError("derive each requires a finite typed collection")
            each.append((variable, compiled))
            available[variable] = compiled.result.element.name
        polarity, (conclusion,) = wrapper(body["conclude"], {"support", "opposition"}, 1)
        result.append(
            Derivation(
                Rule(name, tuple(premises)),
                tuple(constants),
                tuple(each),
                expression(body.get("where", "True"), "Bool", available),
                expression(
                    body["conclude"][conclusion.start : conclusion.end],
                    model["propositions"],
                    available,
                ),
                polarity,
                tuple((v, table[available[v]].name) for v in (*variables, *each_rows)),
            )
        )
    try:
        ordered = order_rules(tuple(r.rule for r in result))
    except (ValueError, RecursionError) as error:
        raise C0LawError(str(error)) from error
    by_name = {r.rule.name: r for r in result}
    return tuple(by_name[r.name] for r in ordered), limits
