"""Typed shared-state schemas and lexical context bindings."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier


@dataclass(frozen=True)
class ContextSchema:
    fields: tuple
    public: tuple[str, ...]
    version: str


def compile_context_state(name, row, table, parameters):
    if row is None:
        return None
    if (
        not isinstance(row, Mapping)
        or set(row) != {"fields", "public"}
        or not isinstance(row["fields"], Mapping)
        or not row["fields"]
        or any(
            not _identifier(key)
            or key in parameters
            or type(kind) is not str
            or kind not in dict(table.definitions)
            for key, kind in row["fields"].items()
        )
        or type(row["public"]) is not list
        or any(type(key) is not str for key in row["public"])
        or len(row["public"]) != len(set(row["public"]))
        or not set(row["public"]) <= set(row["fields"])
    ):
        raise C0LawError("context state needs disjoint typed fields and exact public names")
    fields = tuple((key, table[kind]) for key, kind in row["fields"].items())
    version = hashlib.sha256(
        repr((name, tuple((key, plan.type_id.signature) for key, plan in fields))).encode()
    ).hexdigest()
    return ContextSchema(fields, tuple(row["public"]), version)


def context_types(plan, *, local=False):
    parameters = {
        item.name: item.type_name
        for item in plan.parameters
        if not local or item.name not in plan.world_parameters
    }
    if plan.state is not None:
        parameters.update(
            (name, kind.name)
            for name, kind in plan.state.fields
            if not local or name in plan.state.public
        )
    return parameters


def selected_context(declaration, binding, plans):
    if "context" not in declaration and "context" not in binding:
        return None
    plan = next((p for p in plans if p.name == binding.get("context")), None)
    if plan is None or plan.definition != declaration.get("context"):
        raise C0LawError("executable must bind its declared context")
    return plan
