"""Public finite constraints checked against a private producer realization."""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from nomos_c0.author_contract_v1 import C0LawError

from .expressions import compile_value_expression


@dataclass(frozen=True)
class ConstraintDefinition:
    name: str
    parameters: tuple
    variables: tuple
    holds: object
    formula: str
    realization: tuple
    signature: str
    local: object | None = None


@dataclass(frozen=True)
class ConstraintAssurance:
    definition: ConstraintDefinition
    arguments: tuple


def constraint_declarations(declarations, *, reserved=()):
    """Enter pure formulas into the same acyclic, typed definition library."""
    from .local_constraints import constraint_formula

    if not isinstance(declarations, Mapping):
        raise C0LawError("constraints require named definitions")
    pure = {}
    for name, definition in declarations.items():
        path = "constraints." + str(name)
        formula = constraint_formula(definition, path, reserved=reserved)
        parameters, variables = definition["parameters"], definition["variables"]
        if (
            not isinstance(parameters, Mapping)
            or not isinstance(variables, Mapping)
            or not variables
            or set(parameters) & set(variables)
            or not isinstance(definition["realize"], Mapping)
            or set(definition["realize"]) != set(variables)
        ):
            raise C0LawError(path + ": distinct parameters/variables and exact realize required")
        if any(type(kind) is not str for kind in (*parameters.values(), *variables.values())):
            raise C0LawError(path + ": finite inputs must select nominal value types")
        pure[name] = {
            "parameters": {**parameters, **variables},
            "returns": "Bool",
            "expression": formula,
        }
    return pure


def compile_constraints(table, declarations, pure, entities):
    from .local_constraints import compile_local_constraint

    result = []
    for name, definition in declarations.items():
        path = "constraints." + name
        parameters, variables = definition["parameters"], definition["variables"]
        local = compile_local_constraint(definition, table, pure, entities, path)
        holds = compile_value_expression(
            name + "(" + ", ".join((*parameters, *variables)) + ")",
            table,
            {**parameters, **variables},
            returns="Bool",
            library=pure,
            entities=entities,
            context="world",
            path=path + ".holds",
        )
        if holds.summary.owner_reads or holds.summary.reference_domains:
            raise C0LawError(path + ": public constraint formula must be pure finite values")
        realization = tuple(
            (
                variable,
                compile_value_expression(
                    definition["realize"][variable],
                    table,
                    parameters,
                    returns=kind,
                    library=pure,
                    entities=entities,
                    context="world",
                    path=path + ".realize." + variable,
                ),
            )
            for variable, kind in variables.items()
        )
        identity = (holds.read_key, tuple((n, e.read_key) for n, e in realization))
        if local is not None:
            identity = (*identity, local.relation, local.check.read_key)
        signature = sha256(repr(identity).encode()).hexdigest()
        result.append(
            (
                name,
                ConstraintDefinition(
                    name,
                    tuple(parameters.items()),
                    tuple((n, k, table[k].type_id.signature) for n, k in variables.items()),
                    holds,
                    dict(pure.definitions)[name].source.text,
                    realization,
                    signature,
                    local,
                ),
            )
        )
    return tuple(result)


def compile_constraint_assurances(declaration, definitions, table, pure, entities, content, path):
    from .assurances import compile_content_arguments

    if not isinstance(declaration, Mapping):
        raise C0LawError(path + ": requires named constraints with content arguments")
    definitions = dict(definitions)
    result = []
    for name, arguments in declaration.items():
        if name not in definitions:
            raise C0LawError(path + ": unknown public constraint")
        definition = definitions[name]
        result.append(
            ConstraintAssurance(
                definition,
                compile_content_arguments(
                    arguments,
                    dict(definition.parameters),
                    table,
                    pure,
                    entities,
                    content,
                    path + "." + name,
                ),
            )
        )
    return tuple(result)
