"""Authored world termination: explicit boundary, typed result and frozen audience."""

import hashlib
import json
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expressions import compile_value_expression


@dataclass(frozen=True)
class TerminalPlan:
    name: str
    context: object
    when: object
    boundary: str
    pending: str
    value: object
    to: object
    fingerprint: str


def compile_terminal(
    name, declaration, binding, contexts, table, entities, pure, context, world_name
):
    from .frontend import row

    path = "terminals." + binding["definition"]
    row(binding, {"definition", "context"}, path="use." + name)
    row(declaration, {"context", "when", "stop", "returns", "value", "to", "access"}, path=path)
    row(declaration["stop"], {"boundary", "pending"}, path=path + ".stop")
    boundary, pending = declaration["stop"]["boundary"], declaration["stop"]["pending"]
    if (boundary, pending) not in (("action", "freeze"), ("processes", "complete_existing")):
        raise C0LawError(f"UnsupportedFeature: {path}.stop: unsupported boundary/pending pair")
    if declaration["access"] != "public_status":
        raise C0LawError(f"UnsupportedFeature: {path}.access: explicit public_status required")
    selected = next((p for p in contexts if p.name == binding["context"]), None)
    if selected is None or selected.definition != declaration["context"]:
        raise C0LawError(f"{path}: exact declared context binding required")
    from .context_state import context_types

    bindings = context_types(selected)

    def expression(key, returns):
        return compile_value_expression(
            declaration[key],
            table,
            bindings,
            returns=returns,
            library=pure,
            entities=entities,
            context="world",
            path=path + "." + key,
            span=None if context is None else context.locate(path + "." + key),
        )

    when, value, to = (
        expression("when", "Bool"),
        expression("value", declaration["returns"]),
        expression("to", None),
    )
    if (
        to.result.kind != "set"
        or to.result.element.kind != "ref"
        or dict(entities.entities)[to.result.element.sort].kind != "person"
    ):
        raise C0LawError(f"{path}.to: Person Set required")
    fingerprint = hashlib.sha256(
        json.dumps(
            [world_name, name, declaration, binding, entities.fingerprint], sort_keys=True
        ).encode()
    ).hexdigest()
    return TerminalPlan(
        name,
        selected,
        when,
        boundary,
        pending,
        value,
        to,
        fingerprint,
    )
