"""Check locally observable scopes and opportunities for planning continuation."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expressions import compile_value_expression
from .frontend import row


@dataclass(frozen=True)
class ContinuationPlan:
    scope: object
    ready: object
    complete: object
    closed: object


def compile_continuation(program, document, bindings):
    row(document, {"scope", "ready", "complete", "closed"}, path="planning.continuation")
    scope = document["scope"]
    row(scope, {"type", "value"}, path="planning.continuation.scope")
    if type(scope["type"]) is not str or scope["type"] not in dict(program.table.definitions):
        raise C0LawError("planning continuation scope needs a named type")

    def expression(text, returns, name):
        checked = compile_value_expression(
            text,
            program.table,
            bindings,
            returns=returns,
            library=program.queries,
            entities=program.entities,
            context="actor",
            path="planning.continuation." + name,
        )
        if checked.summary.owner_reads or checked.summary.reference_domains:
            raise C0LawError("planning continuation accepts supplied local values only")
        return checked

    return ContinuationPlan(
        expression(scope["value"], scope["type"], "scope"),
        *(expression(document[name], "Bool", name) for name in ("ready", "complete", "closed")),
    )
