"""Expand deterministic Action/Event spelling before all semantic consumers."""

from collections.abc import Mapping

from nomos_c0.author_contract_v1 import C0LawError


def _unit_resolution(body, path, depth=0):
    if not isinstance(body, Mapping):
        raise C0LawError(path + ": explicit resolution object required")
    if depth > 64:
        raise C0LawError(path + ": bounded resolution required")
    keys = set(body)
    children = (
        ("then", "else")
        if keys == {"when", "then", "else"}
        else ("success", "failure")
        if keys == {"attempt", "success", "failure"}
        else ("then",)
        if keys == {"draw", "then"}
        else ()
    )
    if children:
        return {
            **body,
            **{key: _unit_resolution(body[key], path + "." + key, depth + 1) for key in children},
        }
    if "result" not in body and keys <= {"effects", "deliver", "form"}:
        return {**body, "result": "None"}
    return body


def normalize_action_defaults(lib):
    """Only ordinary abilities/reactions: explicit resolve, Unit results, empty capture."""
    result = dict(lib)
    for category in ("abilities", "reactions"):
        declarations = lib.get(category)
        if not isinstance(declarations, Mapping):
            continue
        normalized = {}
        for name, declaration in declarations.items():
            if not isinstance(declaration, Mapping):
                normalized[name] = declaration
                continue
            row = dict(declaration)
            if not isinstance(row.get("resolve"), Mapping):
                raise C0LawError(f"{category}.{name}.resolve: explicit resolution object required")
            row.setdefault("results", "Unit")
            if row["results"] == "Unit" and "resolve" in row:
                row["resolve"] = _unit_resolution(row["resolve"], f"{category}.{name}.resolve")
            if category == "reactions" and isinstance(row.get("on"), Mapping):
                row["on"] = dict(row["on"])
                row["on"].setdefault("bind", {})
            normalized[name] = row
        result[category] = normalized
    return result
