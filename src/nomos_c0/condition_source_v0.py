"""Lower compact author expressions to the existing typed value operations."""

from __future__ import annotations

import ast

from .author_contract_v1 import C0LawError
from .participant_expression_v1 import lexical_names, substitute

_BINARY = frozenset({"eq", "le", "lt", "add", "sub", "mul", "ceil_div", "append"})
_UNARY = frozenset({"is_none", "not_none", "not", "die_next_seed"})


def _predicate(source: str, path: str) -> dict:
    if not source or len(source) > 4096:
        raise C0LawError(f"{path}: predicate text is empty or too large")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise C0LawError(f"{path}: invalid predicate syntax") from error

    def lower(node, depth=0):
        if depth > 64:
            raise C0LawError(f"{path}: predicate is too deep")
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, bool, type(None)):
            return {"const": node.value}
        if isinstance(node, (ast.Name, ast.Attribute)):
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                return {"ref": ".".join([current.id, *reversed(parts)])}
        if isinstance(node, ast.BoolOp):
            op = "all" if isinstance(node.op, ast.And) else "any"
            return {op: [lower(item, depth + 1) for item in node.values]}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return {"not": lower(node.operand, depth + 1)}
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
            operation = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul"}[type(node.op)]
            return {operation: [lower(node.left, depth + 1), lower(node.right, depth + 1)]}
        if isinstance(node, ast.IfExp):
            return {
                "if": {
                    "when": lower(node.test, depth + 1),
                    "then": lower(node.body, depth + 1),
                    "else": lower(node.orelse, depth + 1),
                }
            }
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"count", "exists", "exactly_one"}
        ):
            operation = node.func.id
            if (
                len(node.args) != 1
                or node.keywords
                or not isinstance(node.args[0], ast.GeneratorExp)
            ):
                raise C0LawError(f"{path}: {operation} needs one filtered finite collection")
            query = node.args[0]
            if len(query.generators) != 1:
                raise C0LawError(f"{path}: {operation} does not support multiple generators")
            binding = query.generators[0]
            if (
                binding.is_async
                or not isinstance(binding.target, ast.Name)
                or not binding.target.id.isascii()
                or binding.target.id.startswith("_")
                or not isinstance(query.elt, ast.Name)
                or query.elt.id != binding.target.id
                or not isinstance(binding.iter, (ast.Name, ast.Attribute))
                or len(binding.ifs) != 1
            ):
                raise C0LawError(
                    f"{path}: {operation} needs 'item for item in collection if predicate'"
                )
            return {
                "count_matching" if operation == "count" else operation: {
                    "collection": lower(binding.iter, depth + 1),
                    "as": binding.target.id,
                    "where": lower(binding.ifs[0], depth + 1),
                }
            }
        if isinstance(node, ast.Compare):
            comparisons = []
            left = node.left
            for op, right in zip(node.ops, node.comparators, strict=True):
                a, b = lower(left, depth + 1), lower(right, depth + 1)
                if isinstance(op, (ast.Is, ast.IsNot)) and b == {"const": None}:
                    item = {"is_none" if isinstance(op, ast.Is) else "not_none": a}
                elif isinstance(op, (ast.Eq, ast.NotEq)):
                    item = {"eq": [a, b]}
                    if isinstance(op, ast.NotEq):
                        item = {"not": item}
                elif isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                    pair = [b, a] if isinstance(op, (ast.Gt, ast.GtE)) else [a, b]
                    item = {"lt" if isinstance(op, (ast.Lt, ast.Gt)) else "le": pair}
                else:
                    raise C0LawError(f"{path}: unsupported predicate comparison")
                comparisons.append(item)
                left = right
            return comparisons[0] if len(comparisons) == 1 else {"all": comparisons}
        raise C0LawError(f"{path}: unsupported predicate operation {type(node).__name__}")

    return lower(tree.body)


def lower_author_expression(
    source: object, *, path: str = "guard", participant_groups=(), reserved_names=()
) -> tuple[dict, dict[str, str]]:
    """Parse once; location metadata never participates in world evaluation."""
    locations: dict[str, str] = {}
    names: set[tuple[tuple[str, ...], str]] = set()
    groups = dict(participant_groups)
    reserved = set(reserved_names) | {"occurrence"}
    declared_locals = set()
    if groups:
        reserved.update(lexical_names(source))
        declared_locals = lexical_names(source, declarations_only=True)
    active_aliases = set()
    expansion_budget = [131072]
    serial = [0]

    def mark(value, internal, authored):
        locations[internal] = authored
        if type(value) is dict:
            for key, child in value.items():
                mark(child, f"{internal}.{key}", authored)
        elif type(value) is list:
            for index, child in enumerate(value):
                mark(child, f"{internal}[{index}]", authored)

    def fields(value, expected, authored):
        if type(value) is not dict or set(value) != expected:
            raise C0LawError(f"{authored}: expression has missing or unknown fields")
        return value

    def lower(value, internal, authored, scope=(), depth=0):
        if depth > 64:
            raise C0LawError(f"{authored}: value expression is too deep")
        locations[internal] = authored
        if type(value) is str:
            result = _predicate(value, authored)
            mark(result, internal, authored)
            return result
        if type(value) in (bool, int, type(None)):
            return {"const": value}
        if type(value) is not dict or len(value) != 1:
            raise C0LawError(f"{authored}: value expression must have one operation")
        op, body = next(iter(value.items()))
        if op == "insert_missing":
            declaration = fields(body, {"collection", "candidates", "key"}, authored)
            return {
                op: {
                    "collection": lower(
                        declaration["collection"],
                        internal + ".insert_missing.collection",
                        authored + ".collection",
                        scope,
                        depth + 1,
                    ),
                    "candidates": lower(
                        declaration["candidates"],
                        internal + ".insert_missing.candidates",
                        authored + ".candidates",
                        scope,
                        depth + 1,
                    ),
                    "key": declaration["key"],
                }
            }
        if op == "collect_participants":
            declaration = fields(body, {"group", "as", "where", "value"}, authored)
            group, alias = declaration["group"], declaration["as"]
            if type(group) is not str or group not in groups:
                raise C0LawError(f"{authored}: collection needs a selected participant group")
            if (
                type(alias) is not str
                or not alias.isascii()
                or not alias.isidentifier()
                or alias.startswith("_")
                or alias in active_aliases
                or alias in set(reserved_names)
                or alias in declared_locals
            ):
                raise C0LawError(
                    f"{authored}: participant collection alias is malformed or shadowed"
                )
            active_aliases.add(alias)
            try:
                predicate = lower(
                    declaration["where"], internal + ".where", authored + ".where", scope, depth + 1
                )
                value = lower(
                    declaration["value"], internal + ".value", authored + ".value", scope, depth + 1
                )
            finally:
                active_aliases.remove(alias)
            result = {
                "participant_collect": {
                    "predicates": [
                        substitute(predicate, {alias: member}, budget=expansion_budget)
                        for member in groups[group]
                    ],
                    "values": [
                        substitute(value, {alias: member}, budget=expansion_budget)
                        for member in groups[group]
                    ],
                }
            }
            mark(result, internal, authored)
            return result
        if op == "update_matching":
            declaration = fields(body, {"collection", "matching", "key", "as", "set"}, authored)
            changes = declaration["set"]
            if type(changes) is not dict or not changes:
                raise C0LawError(f"{authored}: update needs explicit fields")
            return {
                op: {
                    "collection": lower(
                        declaration["collection"],
                        internal + ".update_matching.collection",
                        authored + ".collection",
                        scope,
                        depth + 1,
                    ),
                    "matching": lower(
                        declaration["matching"],
                        internal + ".update_matching.matching",
                        authored + ".matching",
                        scope,
                        depth + 1,
                    ),
                    "key": declaration["key"],
                    "as": declaration["as"],
                    "set": {
                        name: lower(
                            child,
                            internal + ".update_matching.set." + str(name),
                            authored + ".set." + str(name),
                            scope,
                            depth + 1,
                        )
                        for name, child in changes.items()
                    },
                }
            }
        if op == "query":
            declaration = fields(body, {"from", "join", "where"}, authored)
            left = fields(declaration["from"], {"collection", "as", "key"}, authored + ".from")
            right_source = (
                "collection"
                if type(declaration["join"]) is dict and "collection" in declaration["join"]
                else "participants"
            )
            right = fields(declaration["join"], {right_source, "as", "key"}, authored + ".join")
            if right_source == "participants":
                group = right["participants"]
                if type(group) is not str or group not in groups:
                    raise C0LawError(f"{authored}: query needs a selected participant group")
            aliases = (left["as"], right["as"])
            for name in (*aliases, left["key"], right["key"]):
                if (
                    type(name) is not str
                    or not name.isascii()
                    or not name.isidentifier()
                    or name.startswith("_")
                ):
                    raise C0LawError(f"{authored}: query alias/key is malformed")
            if aliases[0] == aliases[1] or any(
                name in set(reserved_names) | active_aliases | declared_locals for name in aliases
            ):
                raise C0LawError(f"{authored}: query alias shadows an input or local binding")
            operation = "collection_query" if right_source == "collection" else "participant_query"
            collection = lower(
                left["collection"],
                internal + f".{operation}.collection",
                authored + ".from.collection",
                scope,
                depth + 1,
            )
            right_collection = None
            if right_source == "collection":
                right_collection = lower(
                    right["collection"],
                    internal + ".collection_query.right_collection",
                    authored + ".join.collection",
                    scope,
                    depth + 1,
                )
            active_aliases.update(aliases)
            try:
                predicate = lower(
                    declaration["where"], internal + ".where", authored + ".where", scope, depth + 1
                )
            finally:
                active_aliases.difference_update(aliases)
            if right_source == "collection":
                result = {
                    "collection_query": {
                        "collection": collection,
                        "as": left["as"],
                        "key": left["key"],
                        "right_collection": right_collection,
                        "right_as": right["as"],
                        "right_key": right["key"],
                        "where": predicate,
                    }
                }
                mark(result, internal, authored)
                return result
            result = {
                "participant_query": {
                    "collection": collection,
                    "as": left["as"],
                    "key": left["key"],
                    "right_keys": [
                        {"ref": member + "." + right["key"]} for member in groups[group]
                    ],
                    "predicates": [
                        substitute(predicate, {right["as"]: member}, budget=expansion_budget)
                        for member in groups[group]
                    ],
                }
            }
            mark(result, internal, authored)
            return result
        if op in {"any_participant", "all_participants", "fold_participants"}:
            fold = op == "fold_participants"
            declaration = fields(
                body,
                {"group", "as", "accumulator", "initial", "value"}
                if fold
                else {"group", "as", "where"},
                authored,
            )
            group = declaration["group"]
            if type(group) is not str or group not in groups:
                raise C0LawError(f"{authored}: unknown or unselected participant group")
            aliases = [declaration["as"]]
            if fold:
                aliases.append(declaration["accumulator"])
            if any(
                type(alias) is not str
                or not alias.isascii()
                or not alias.isidentifier()
                or alias.startswith("_")
                or alias in active_aliases
                for alias in aliases
            ) or len(set(aliases)) != len(aliases):
                raise C0LawError(f"{authored}: participant aliases are malformed or shadowed")
            key = "value" if fold else "where"
            # References to these aliases are expected; lexical declarations are not.
            template_raw = declaration[key]
            active_aliases.update(aliases)
            try:
                template = lower(
                    template_raw, f"{internal}.{key}", f"{authored}.{key}", scope, depth + 1
                )
            finally:
                active_aliases.difference_update(aliases)
            if any(alias in set(reserved_names) or alias in declared_locals for alias in aliases):
                raise C0LawError(f"{authored}: participant alias shadows an input or local binding")
            if not fold:
                operation = "any" if op == "any_participant" else "all"
                result = {
                    operation: [
                        substitute(template, {aliases[0]: member}, budget=expansion_budget)
                        for member in groups[group]
                    ]
                }
            else:
                initial = lower(
                    declaration["initial"],
                    f"{internal}.initial",
                    f"{authored}.initial",
                    scope,
                    depth + 1,
                )
                used = reserved | lexical_names(template) | lexical_names(initial) | set(aliases)

                def fresh():
                    while True:
                        current = f"participantFold{serial[0]}"
                        serial[0] += 1
                        if current not in used:
                            break
                    used.add(current)
                    return current

                previous = fresh()
                steps = [(previous, initial)]
                for member in groups[group]:
                    current = fresh()
                    step = substitute(
                        template,
                        {aliases[0]: member, aliases[1]: previous},
                        budget=expansion_budget,
                    )
                    steps.append((current, step))
                    previous = current
                result = {"ref": previous}
                for name, expression in reversed(steps):
                    result = {"let": {"name": name, "value": expression, "in": result}}
            mark(result, internal, authored)
            return result
        if op == "clause":
            raise C0LawError(f"{authored}: clause is internal IR; author conditions use require")
        if op == "require":
            if type(body) is not list or not body:
                raise C0LawError(f"{authored}: require needs a nonempty ordered condition list")
            items = []
            for index, entry in enumerate(body):
                if type(entry) is not dict or len(entry) != 1:
                    raise C0LawError(f"{authored}: each require entry needs exactly one name")
                name, condition = next(iter(entry.items()))
                if (
                    type(name) is not str
                    or not name.isascii()
                    or not name.isidentifier()
                    or name.startswith("_")
                ):
                    raise C0LawError(f"{authored}: clause name must be a public ASCII identifier")
                if (scope, name) in names:
                    raise C0LawError(f"{authored}: clause name repeats in the same scope: {name}")
                names.add((scope, name))
                location = f"{authored}.require.{name}"
                target = f"{internal}.all[{index}]"
                locations[target] = location
                test = lower(
                    condition, f"{target}.clause.test", location, (*scope, target), depth + 1
                )
                items.append({"clause": {"name": name, "test": test}})
            return {"all": items}
        if op in ("const", "ref"):
            return {op: body}
        if op == "call":
            declaration = fields(body, {"ref", "args"}, authored)
            if type(declaration["ref"]) is not str or type(declaration["args"]) is not dict:
                raise C0LawError(f"{authored}: pure call is malformed")
            return {
                "call": {
                    "ref": declaration["ref"],
                    "args": {
                        name: lower(
                            argument,
                            f"{internal}.call.args.{name}",
                            f"{authored}.call.args.{name}",
                            scope,
                            depth + 1,
                        )
                        for name, argument in declaration["args"].items()
                    },
                }
            }
        if op == "empty_like":
            if type(body) is not str:
                raise C0LawError(f"{authored}: empty collection needs a declared input path")
            return {"empty_like": body}
        if op in _BINARY or op in ("all", "any"):
            if type(body) is not list:
                raise C0LawError(f"{authored}: expression operands must be a list")
            return {
                op: [
                    lower(
                        child,
                        f"{internal}.{op}[{index}]",
                        f"{authored}.{op}[{index}]",
                        scope,
                        depth + 1,
                    )
                    for index, child in enumerate(body)
                ]
            }
        if op in _UNARY:
            return {op: lower(body, f"{internal}.{op}", f"{authored}.{op}", scope, depth + 1)}
        if op == "if":
            declaration = fields(body, {"when", "then", "else"}, authored)
            return {
                op: {
                    branch: lower(
                        child,
                        f"{internal}.if.{branch}",
                        f"{authored}.if.{branch}",
                        (*scope, f"{internal}.if.{branch}"),
                        depth + 1,
                    )
                    for branch, child in declaration.items()
                }
            }
        if op == "let":
            declaration = fields(body, {"name", "value", "in"}, authored)
            return {
                "let": {
                    "name": declaration["name"],
                    "value": lower(
                        declaration["value"],
                        f"{internal}.let.value",
                        f"{authored}.let.value",
                        scope,
                        depth + 1,
                    ),
                    "in": lower(
                        declaration["in"],
                        f"{internal}.let.in",
                        f"{authored}.let.in",
                        (*scope, f"{internal}.let.in"),
                        depth + 1,
                    ),
                }
            }
        if op == "is_case":
            declaration = fields(body, {"value", "case"}, authored)
            return {
                op: {
                    "case": declaration["case"],
                    "value": lower(
                        declaration["value"],
                        f"{internal}.{op}.value",
                        f"{authored}.{op}.value",
                        scope,
                        depth + 1,
                    ),
                }
            }
        if op == "match":
            declaration = fields(body, {"value", "cases"}, authored)
            if type(declaration["cases"]) is not dict:
                raise C0LawError(f"{authored}: match cases must be a mapping")
            cases = {}
            for case, raw in declaration["cases"].items():
                arm = fields(raw, {"as", "then"}, authored)
                location = f"{internal}.match.cases.{case}.then"
                cases[case] = {
                    "as": arm["as"],
                    "then": lower(
                        arm["then"],
                        location,
                        f"{authored}.match.cases.{case}.then",
                        (*scope, location),
                        depth + 1,
                    ),
                }
            return {
                op: {
                    "value": lower(
                        declaration["value"],
                        f"{internal}.match.value",
                        f"{authored}.match.value",
                        scope,
                        depth + 1,
                    ),
                    "cases": cases,
                }
            }
        if op == "unique_by":
            declaration = fields(body, {"collection", "as", "keys"}, authored)
            keys = declaration["keys"]
            if type(keys) is not list or not 1 <= len(keys) <= 8:
                raise C0LawError(f"{authored}: unique_by needs one to eight key expressions")
            return {
                op: {
                    "as": declaration["as"],
                    "collection": lower(
                        declaration["collection"],
                        f"{internal}.{op}.collection",
                        f"{authored}.{op}.collection",
                        scope,
                        depth + 1,
                    ),
                    "keys": [
                        lower(
                            key,
                            f"{internal}.{op}.keys[{index}]",
                            f"{authored}.{op}.keys[{index}]",
                            scope,
                            depth + 1,
                        )
                        for index, key in enumerate(keys)
                    ],
                }
            }
        if op in (
            "exists",
            "exactly_one",
            "none_matching",
            "count_matching",
            "collect_matching",
            "tuple_at",
            "die_roll",
            "replace_unique",
        ):
            expected = {
                "exists": {"collection", "as", "where"},
                "exactly_one": {"collection", "as", "where"},
                "none_matching": {"collection", "as", "where"},
                "count_matching": {"collection", "as", "where"},
                "collect_matching": {"collection", "as", "where", "value"},
                "tuple_at": {"collection", "index"},
                "die_roll": {"seed", "sides"},
                "replace_unique": {"collection", "old", "new", "key"},
            }[op]
            declaration = fields(body, expected, authored)
            return {
                op: {
                    key: child
                    if key in ("as", "key")
                    else lower(
                        child, f"{internal}.{op}.{key}", f"{authored}.{op}.{key}", scope, depth + 1
                    )
                    for key, child in declaration.items()
                }
            }
        if op in ("record", "variant", "copy"):
            container = "fields" if op in ("record", "variant") else "changes"
            declaration = fields(
                body,
                {"type", "case", "value", "fields"}
                if op == "variant"
                else {"type", "fields"}
                if op == "record"
                else {"from", "changes"},
                authored,
            )
            if type(declaration[container]) is not dict:
                raise C0LawError(f"{authored}: record fields must be a mapping")
            result = {
                container: {
                    key: lower(
                        child,
                        f"{internal}.{op}.{container}.{key}",
                        f"{authored}.{op}.{container}.{key}",
                        scope,
                        depth + 1,
                    )
                    for key, child in declaration[container].items()
                }
            }
            if op in ("record", "variant"):
                result["type"] = declaration["type"]
                if op == "variant":
                    result["case"] = declaration["case"]
                    result["value"] = lower(
                        declaration["value"],
                        f"{internal}.variant.value",
                        f"{authored}.variant.value",
                        scope,
                        depth + 1,
                    )
            else:
                result["from"] = lower(
                    declaration["from"],
                    f"{internal}.copy.from",
                    f"{authored}.copy.from",
                    scope,
                    depth + 1,
                )
            return {op: result}
        raise C0LawError(f"{authored}: value expression has an unknown operation: {op}")

    return lower(source, path, path), locations
