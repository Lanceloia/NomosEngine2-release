"""Typed disclosure definitions and publication-time delivery declarations."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier, parse_expression
from .expressions import compile_value_expression


@dataclass(frozen=True)
class DisclosurePlan:
    name: str
    parameters: tuple
    sample: str
    recipients: object
    value: object
    assurances: tuple = ()
    constraints: tuple = ()


@dataclass(frozen=True)
class DeliveryPlan:
    label: str
    definition: DisclosurePlan
    arguments: tuple
    variable: str | None = None
    pool: object | None = None

    def expressions(self):
        return (() if self.pool is None else (self.pool,)) + self.arguments


def compile_disclosures(
    table, declarations, entities, pure, context=None, *, facts=None, constraints=()
):
    from .assurances import compile_assurances
    from .constraints import compile_constraint_assurances
    from .frontend import row

    if not isinstance(declarations, dict):
        raise C0LawError("disclosures require named definitions")
    result = []
    for name, declaration in declarations.items():
        if not _identifier(name):
            raise C0LawError("invalid disclosure name")
        row(
            declaration,
            {"parameters", "sample", "to", "returns", "value", "access"},
            {"assure", "assure_constraints"},
            path="disclosures." + name,
        )
        if declaration["sample"] not in ("before", "after") or declaration["access"] != "acquired":
            raise C0LawError("disclosure needs before/after sampling and acquired access")
        parameters = declaration["parameters"]
        if not isinstance(parameters, dict):
            raise C0LawError("disclosure needs typed parameters")

        def expression(field, returns):
            path = f"disclosures.{name}.{field}"
            return compile_value_expression(
                declaration[field],
                table,
                parameters,
                returns=returns,
                library=pure,
                entities=entities,
                context="world",
                path=path,
                span=None if context is None else context.locate(path),
            )

        recipients = expression("to", None)
        kind = recipients.result
        if (
            kind.kind != "set"
            or kind.element.kind != "ref"
            or dict(entities.entities)[kind.element.sort].kind != "person"
        ):
            raise C0LawError("disclosure recipients must be a finite Person reference set")
        result.append(
            (
                name,
                DisclosurePlan(
                    name,
                    tuple(parameters.items()),
                    declaration["sample"],
                    recipients,
                    expression("value", declaration["returns"]),
                    compile_assurances(
                        declaration.get("assure", {}),
                        {} if facts is None else facts,
                        table,
                        pure,
                        entities,
                        declaration["returns"],
                        "disclosures." + name + ".assure",
                    ),
                    compile_constraint_assurances(
                        declaration.get("assure_constraints", {}),
                        constraints,
                        table,
                        pure,
                        entities,
                        declaration["returns"],
                        "disclosures." + name + ".assure_constraints",
                    ),
                ),
            )
        )
    return tuple(result)


def compile_deliveries(declarations, compiler, path):
    if not isinstance(declarations, dict):
        raise C0LawError("deliver requires unique named calls")
    result = []
    for label, text in declarations.items():
        if not _identifier(label):
            raise C0LawError("invalid delivery label")
        location = path + ".deliver." + label
        variable, pool, bound = None, None, compiler
        if type(text) is dict:
            from .effects import EffectCompiler
            from .expressions import _INTRINSICS
            from .frontend import row

            row(text, {"for", "in", "value"}, path=location)
            variable = text["for"]
            reserved = (
                set(compiler.bindings)
                | set(dict(compiler.table.definitions))
                | set(dict(compiler.library.definitions))
                | set(dict(compiler.entities.relations))
                | set(dict(compiler.local_views))
                | _INTRINSICS
            )
            if not _identifier(variable) or variable in reserved:
                raise C0LawError(location + ": delivery binder conflicts with lexical scope")
            pool = compiler.expression(
                text["in"],
                None,
                location + ".in",
                context="actor" if compiler.actor is not None else "world",
            )
            if pool.result.kind not in ("set", "sequence"):
                raise C0LawError(location + ": delivery pool needs a finite typed collection")
            bound = EffectCompiler(
                compiler.table,
                {**compiler.bindings, variable: pool.result.element.name},
                library=compiler.library,
                entities=compiler.entities,
                actor=compiler.actor,
                path=compiler.path,
                context=compiler.context,
                local_views=compiler.local_views,
                disclosures=compiler.disclosures.items(),
                actor_bindings={**compiler.actor_bindings, variable: pool.result.element.name},
                shared_context=compiler.shared_context,
            )
            text = text["value"]
        syntax = parse_expression(text, path=location)
        if syntax.operation != "call" or syntax.children[0].operation != "name":
            raise C0LawError("delivery needs a named disclosure call")
        definition = compiler.disclosures.get(syntax.children[0].value)
        if definition is None or len(syntax.children) - 1 != len(definition.parameters):
            raise C0LawError("unknown disclosure or wrong argument count")
        arguments = tuple(
            bound.expression(
                text[arg.start : arg.end],
                kind,
                f"{path}.deliver.{label}.{name}",
                context="actor" if compiler.actor is not None else "world",
            )
            for arg, (name, kind) in zip(syntax.children[1:], definition.parameters, strict=True)
        )
        if any(arg.summary.owner_reads for arg in arguments):
            raise C0LawError(
                "delivery arguments must be data; sample entity reads in disclosure body"
            )
        result.append(DeliveryPlan(label, definition, arguments, variable, pool))
    return tuple(result)
