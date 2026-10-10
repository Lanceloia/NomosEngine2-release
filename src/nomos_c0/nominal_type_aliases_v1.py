"""Transparent Lib field-type aliases, expanded before nominal fingerprinting."""

from __future__ import annotations

import keyword
from copy import deepcopy

from .author_contract_v1 import C0LawError

BUILTIN_TYPE_NAMES = frozenset({
    "bool", "int", "str", "enum", "optional", "tuple", "none",
    "occurrence_ref", "individual_ref", "actor_ref",
})


def expand_type_aliases(row: dict[str, object]) -> dict[str, object]:
    aliases = row.get("type_aliases", {})
    if type(aliases) is not dict or len(aliases) > 64:
        raise C0LawError("Lib type_aliases must be a finite map of at most 64 declarations")
    records = row["records"]
    if type(records) is not list:
        raise C0LawError("Lib needs finite record declarations")
    record_names = {item.get("name") for item in records
                    if type(item) is dict and type(item.get("name")) is str}
    for name in aliases:
        if (type(name) is not str or not name.isascii() or not name.isidentifier()
                or keyword.iskeyword(name) or name.startswith("_") or len(name) > 64):
            raise C0LawError("Lib type alias must have a finite public identifier")
        if name in BUILTIN_TYPE_NAMES or name in record_names:
            raise C0LawError(f"Lib type alias collides with a declared or built-in type: {name}")
    resolved = {}

    def expand(raw, stack=(), depth=0):
        if depth > 12:
            raise C0LawError("Lib type alias nesting is too deep")
        if type(raw) is str:
            if raw in aliases:
                if raw in stack:
                    chain = " -> ".join((*stack, raw))
                    raise C0LawError(f"Lib type aliases are recursive: {chain}")
                if raw not in resolved:
                    resolved[raw] = expand(aliases[raw], (*stack, raw), depth)
                return deepcopy(resolved[raw])
            if raw not in record_names and raw not in BUILTIN_TYPE_NAMES:
                raise C0LawError(f"Lib type alias references an unknown type: {raw}")
            return raw
        if type(raw) is not dict or len(raw) != 1:
            raise C0LawError("Lib type alias expression is malformed")
        kind, argument = next(iter(raw.items()))
        if kind == "optional":
            return {kind: expand(argument, stack, depth + 1)}
        if kind == "tuple":
            if type(argument) is not dict or set(argument) != {"item", "max"}:
                raise C0LawError("Lib type alias collection needs item and max")
            return {kind: {"item": expand(argument["item"], stack, depth + 1),
                           "max": argument["max"]}}
        # Existing nominal validation owns scalar ranges, enums and value semantics.
        return deepcopy(raw)

    for name in aliases:
        expand(name)
    expanded_records = []
    for record in records:
        if type(record) is not dict or type(record.get("fields")) is not list:
            raise C0LawError("Lib nominal declaration needs a field list")
        fields = []
        for field in record["fields"]:
            if type(field) is not dict or "type" not in field:
                raise C0LawError("Lib record field needs a type")
            fields.append({**field, "type": expand(field["type"])})
        expanded = {**record, "fields": fields}
        if "variants" in record:
            if type(record["variants"]) is not dict:
                raise C0LawError("Lib variant needs a case map")
            expanded["variants"] = {
                name: expand(value) for name, value in record["variants"].items()
            }
        expanded_records.append(expanded)
    return {**row, "records": expanded_records, "type_aliases": resolved}
