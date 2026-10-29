"""Expand explicitly referenced author defaults before semantic compilation."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

from .expression_syntax import ExpressionSource, _identifier

_LIB_FIELDS = {
    "abilities": {"context", "actor", "views"},
    "decision_groups": {"context", "actor", "views"},
    **{
        category: {"context"}
        for category in (
            "information",
            "projections",
            "reactions",
            "processes",
            "terminals",
            "activities",
            "periodic",
        )
    },
}


def _expand(document, fields, contexts, context, *, source=False):
    def fail(path, expected, actual):
        span = None if context is None else context.locate(path)
        ExpressionSource("", path, span).fail("AuthorScope", 0, expected, repr(actual))

    scopes = document.get("scopes", {})
    if not isinstance(scopes, Mapping):
        fail("scopes", "named explicit scopes", scopes)
    permitted = {"context", "views"} if source else {"context", "actor", "views"}
    for name, scope in scopes.items():
        path = f"scopes.{name}"
        if (
            not _identifier(name)
            or not isinstance(scope, Mapping)
            or not scope
            or set(scope) - permitted
        ):
            fail(path, "nonempty scope with only " + ", ".join(sorted(permitted)), scope)
        if "context" in scope and (
            not isinstance(contexts, Mapping)
            or type(scope["context"]) is not str
            or scope["context"] not in contexts
        ):
            fail(
                path + ".context",
                "declared context instance" if source else "declared context schema",
                scope["context"],
            )
        if "actor" in scope and (
            not isinstance(scope["actor"], Mapping)
            or len(scope["actor"]) != 1
            or any(not _identifier(k) or not _identifier(v) for k, v in scope["actor"].items())
        ):
            fail(path + ".actor", "one named actor and Ref type", scope["actor"])
        if "views" in scope and (
            not isinstance(scope["views"], Mapping)
            or any(not _identifier(alias) for alias in scope["views"])
            or source
            and any(type(v) is not str for v in scope["views"].values())
            or not source
            and any(not isinstance(v, Mapping) for v in scope["views"].values())
        ):
            fail(path + ".views", "named explicit view bindings/types", scope["views"])
    result = {key: value for key, value in document.items() if key != "scopes"}
    aliases = {} if context is None else dict(context.aliases)
    for category, allowed in fields.items():
        declarations = document.get(category, {})
        if not isinstance(declarations, Mapping):
            continue
        expanded = {}
        for name, declaration in declarations.items():
            if not isinstance(declaration, Mapping) or "scope" not in declaration:
                expanded[name] = declaration
                continue
            path, selected = f"{category}.{name}", declaration["scope"]
            if type(selected) is not str or selected not in scopes:
                fail(path + ".scope", "existing explicit scope name", selected)
            scope = scopes[selected]
            if set(scope) - allowed:
                fail(path + ".scope", f"scope fields supported by {category}", scope)
            row = {key: value for key, value in declaration.items() if key != "scope"}
            for key, value in scope.items():
                origin = f"scopes.{selected}.{key}"
                if key == "views":
                    local = row.get(key, {})
                    if not isinstance(local, Mapping) or set(local) & set(value):
                        fail(path + ".views", "local views disjoint from " + origin, local)
                    row[key] = {**deepcopy(value), **local}
                    inherited = [f"{origin}.{alias}" for alias in value]
                    logical = [f"{path}.views.{alias}" for alias in value]
                else:
                    if key in row and row[key] != value:
                        fail(path + "." + key, "same value as " + origin, row[key])
                    if key in row:
                        continue
                    row[key] = deepcopy(value)
                    inherited, logical = [origin], [path + "." + key]
                if context is not None:
                    for target, original in zip(logical, inherited, strict=True):
                        physical = context.indexed_path(original)
                        if physical is not None:
                            aliases[target] = physical
            expanded[name] = row
        if category in document:
            result[category] = expanded
    return result, None if context is None else replace(context, aliases=tuple(aliases.items()))


def expand_author_scopes(lib, source, context=None, source_context=None):
    """Lib scopes describe schemas; Source scopes choose instances and information ports."""
    lib, context = _expand(lib, _LIB_FIELDS, lib.get("contexts", {}), context)
    source, source_context = _expand(
        source,
        {"use": {"context", "views"}},
        source.get("contexts", {}),
        source_context,
        source=True,
    )
    return lib, source, context, source_context
