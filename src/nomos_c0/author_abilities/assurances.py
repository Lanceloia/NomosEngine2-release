"""World-checked claims travel with native reports, never as a trust flag."""

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expressions import compile_pure_values, compile_value_expression


@dataclass(frozen=True)
class AssurancePlan:
    fact: str
    predicate: object
    arguments: tuple


def compile_fact_library(table, queries, facts, entities, context=None, *, constraints=None):
    from .constraints import constraint_declarations
    from .frontend import row

    if not isinstance(queries, Mapping) or not isinstance(facts, Mapping):
        raise C0LawError("queries and facts require named definitions")
    constraints = {} if constraints is None else constraints
    constraint_pure = constraint_declarations(
        constraints,
        reserved=set(dict(table.definitions)) | set(queries) | set(facts) | set(constraints),
    )
    if set(queries) & set(facts) or (set(queries) | set(facts)) & set(constraint_pure):
        raise C0LawError("fact, query and constraint names must be disjoint")
    declarations = dict(queries)
    for name, definition in facts.items():
        row(definition, {"parameters", "holds"}, path="facts." + str(name))
        declarations[name] = {
            "parameters": definition["parameters"],
            "returns": "Bool",
            "expression": definition["holds"],
        }
    declarations.update(constraint_pure)
    return compile_pure_values(
        table,
        declarations,
        entities=entities,
        context=context,
        definition_paths={
            **{name: "facts." + name + ".holds" for name in facts},
            **{name: "constraints." + name + ".holds" for name in constraints},
        },
    )


def compile_content_arguments(arguments, parameters, table, pure, entities, content_type, path):
    if not isinstance(arguments, Mapping) or set(arguments) != set(parameters):
        raise C0LawError(path + ": assurance needs exact named arguments")
    compiled = []
    for key, type_name in parameters.items():
        expr = compile_value_expression(
            arguments[key],
            table,
            {"content": content_type},
            returns=type_name,
            library=pure,
            entities=entities,
            context="world",
            path=path + "." + key,
        )
        if expr.summary.owner_reads or expr.summary.reference_domains:
            raise C0LawError(path + ": assurance arguments can only read delivered content")
        compiled.append((key, expr))
    return tuple(compiled)


def compile_assurances(declaration, facts, table, pure, entities, content_type, path):
    if not isinstance(declaration, Mapping):
        raise C0LawError(path + ": assure requires named facts and named content arguments")
    plans = []
    for name, arguments in declaration.items():
        if name not in facts or not isinstance(arguments, Mapping):
            raise C0LawError(path + ": assurance must select a declared fact")
        parameters = facts[name]["parameters"]
        compiled = compile_content_arguments(
            arguments, parameters, table, pure, entities, content_type, path + "." + name
        )
        predicate = compile_value_expression(
            name + "(" + ", ".join(parameters) + ")",
            table,
            parameters,
            returns="Bool",
            library=pure,
            entities=entities,
            context="world",
            path=path + "." + name,
        )
        plans.append(AssurancePlan(name, predicate, compiled))
    return tuple(plans)
