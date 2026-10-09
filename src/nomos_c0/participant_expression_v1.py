"""Hygienic finite substitution; never look up world owners or evaluate Laws."""

from .author_contract_v1 import C0LawError


def lexical_names(value, *, declarations_only=False, depth=0):
    if depth > 128:
        raise C0LawError("participant expression is too deeply nested")
    names = set()
    if type(value) is dict:
        for operation, declaration in value.items():
            if not declarations_only and operation == "ref" and type(declaration) is str:
                names.add(declaration.split(".", 1)[0])
            if operation == "let" and type(declaration) is dict:
                if type(declaration.get("name")) is str:
                    names.add(declaration["name"])
            if not declarations_only and operation == "query" and type(declaration) is dict:
                for side in ("from", "join"):
                    source = declaration.get(side)
                    if type(source) is dict and type(source.get("as")) is str:
                        names.add(source["as"])
            if (
                operation
                in {
                    "collect_matching",
                    "count_matching",
                    "none_matching",
                    "exists",
                    "exactly_one",
                    "unique_by",
                    "update_matching",
                }
                and type(declaration) is dict
            ):
                if type(declaration.get("as")) is str:
                    names.add(declaration["as"])
            if operation == "match" and type(declaration) is dict:
                cases = declaration.get("cases", {})
                if type(cases) is dict:
                    names.update(
                        arm["as"]
                        for arm in cases.values()
                        if type(arm) is dict and type(arm.get("as")) is str
                    )
            names.update(
                lexical_names(declaration, declarations_only=declarations_only, depth=depth + 1)
            )
    elif type(value) is list:
        for child in value:
            names.update(lexical_names(child, declarations_only=declarations_only, depth=depth + 1))
    return names


def substitute(expression, replacements, *, budget, depth=0):
    budget[0] -= 1
    if budget[0] < 0 or depth > 64:
        raise C0LawError("participant expression exceeds its finite expansion bound")
    if type(expression) is dict:
        if set(expression) == {"ref"} and type(expression["ref"]) is str:
            root, separator, suffix = expression["ref"].partition(".")
            if root in replacements:
                return {"ref": replacements[root] + separator + suffix}
        return {
            key: substitute(child, replacements, budget=budget, depth=depth + 1)
            for key, child in expression.items()
        }
    if type(expression) is list:
        return [
            substitute(child, replacements, budget=budget, depth=depth + 1) for child in expression
        ]
    return expression
