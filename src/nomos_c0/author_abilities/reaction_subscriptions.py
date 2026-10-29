"""Compile explicit reaction selectors to existing definition/occurrence lists."""

from collections.abc import Mapping

from .expression_syntax import ExpressionSource


def expand_reaction_subscriptions(lib, source, context=None, source_context=None):
    """Return pure expanded declarations and a static, non-authoritative binding preview."""

    def location(index, path):
        span = None if index is None else index.locate(path)
        return path if span is None else f"{span.file}:{span.line}:{span.column} ({path})"

    def fail(index, path, expected, actual):
        span = None if index is None else index.locate(path)
        ExpressionSource("", path, span).fail("ReactionBinding", 0, expected, actual)

    reactions = lib.get("reactions", {})
    selections = source.get("use", {})
    if not isinstance(reactions, Mapping) or not isinstance(selections, Mapping):
        fail(context, "reactions", "named reactions and Source.use mappings", "malformed mapping")
    expanded = dict(reactions)
    for name, declaration in reactions.items():
        if not isinstance(declaration, Mapping) or not isinstance(declaration.get("on"), Mapping):
            continue
        allowed = declaration["on"].get("definition")
        if type(allowed) is not list or not any(isinstance(item, Mapping) for item in allowed):
            continue
        definitions = []
        for index, item in enumerate(allowed):
            path = f"reactions.{name}.on.definition[{index}]"
            if type(item) is str:
                definitions.append(item)
            elif (
                isinstance(item, Mapping)
                and set(item) == {"decision_group"}
                and type(item["decision_group"]) is str
                and item["decision_group"] in lib.get("decision_groups", {})
            ):
                definitions.extend(lib["decision_groups"][item["decision_group"]]["alternatives"])
            else:
                fail(
                    context, path, "definition name or existing decision_group selector", repr(item)
                )
        if len(definitions) != len(set(definitions)):
            fail(
                context,
                f"reactions.{name}.on.definition",
                "non-overlapping definitions",
                repr(definitions),
            )
        expanded[name] = {**declaration, "on": {**declaration["on"], "definition": definitions}}
    bindings, preview = dict(selections), []
    for name, binding in selections.items():
        if (
            not isinstance(binding, Mapping)
            or type(binding.get("definition")) is not str
            or binding["definition"] not in expanded
        ):
            continue
        definition = binding["definition"]
        declaration = expanded[definition]
        if not isinstance(declaration, Mapping) or not isinstance(declaration.get("on"), Mapping):
            continue
        allowed = declaration["on"].get("definition")
        allowed = [allowed] if type(allowed) is str else allowed
        after, mode = binding.get("after"), "explicit"
        path = f"use.{name}.after"
        if isinstance(after, Mapping):
            if set(after) != {"declared"} or after["declared"] is not True:
                fail(
                    source_context,
                    path,
                    "{declared: true} or explicit occurrence aliases",
                    repr(after),
                )
            mode = "declared"
            if (
                type(allowed) is not list
                or not allowed
                or any(type(item) is not str for item in allowed)
                or len(allowed) != len(set(allowed))
            ):
                fail(
                    context,
                    f"reactions.{definition}.on.definition",
                    "finite unique definitions",
                    repr(allowed),
                )
            shared = binding.get("context")
            schema = declaration.get("context")
            if schema is not None:
                contexts = source.get("contexts", {})
                actual = (
                    contexts.get(shared)
                    if isinstance(contexts, Mapping) and type(shared) is str
                    else None
                )
                if not isinstance(actual, Mapping) or actual.get("definition") != schema:
                    fail(
                        source_context, path, f"selected context instance of {schema}", repr(shared)
                    )
            elif "context" in binding:
                fail(source_context, path, "no context for this reaction", repr(shared))
            parents = []
            for target in allowed:
                if target not in lib.get("abilities", {}) and target not in reactions:
                    fail(
                        context,
                        f"reactions.{definition}.on.definition",
                        "ordinary ability/reaction definition",
                        target,
                    )
                candidates = [
                    alias
                    for alias, selected in selections.items()
                    if isinstance(selected, Mapping)
                    and selected.get("definition") == target
                    and selected.get("context") == shared
                ]
                if len(candidates) != 1:
                    all_matches = [
                        f"{alias} [context={selected.get('context')!r}] at "
                        + location(source_context, f"use.{alias}")
                        for alias, selected in selections.items()
                        if isinstance(selected, Mapping) and selected.get("definition") == target
                    ]
                    fail(
                        source_context,
                        path,
                        f"one selected {target} in context {shared!r}; "
                        "explicit after list for partial/multiple sources; "
                        + location(context, f"reactions.{definition}.on.definition"),
                        repr(all_matches),
                    )
                parents.append(candidates[0])
            after = parents
            bindings[name] = {**binding, "after": after}
        parents = [after] if type(after) is str else after if type(after) is list else []
        preview.append(
            {
                "reaction": name,
                "definition": definition,
                "context": binding.get("context"),
                "mode": mode,
                "allowed_definitions": allowed,
                "parents": [
                    {
                        "use": parent,
                        "definition": (
                            selections[parent].get("definition")
                            if isinstance(selections.get(parent), Mapping)
                            else None
                        ),
                    }
                    for parent in parents
                    if type(parent) is str
                ],
            }
        )
    return {**lib, "reactions": expanded}, {**source, "use": bindings}, tuple(preview)
