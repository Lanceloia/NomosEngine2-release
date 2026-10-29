"""Compile finite selection into dedicated Python loops and short-circuit branches."""

import ast

from .iteration_order import ordered_pool
from .syntax import constant, statements
from .uniform_quantifier import emit as uniform_quantifier
from .uniform_quantifier import selected as uniform_selected


def filtered_count(emitter, node, body, name, depth, **scope):
    """Count a proven input subset without building or revalidating a collection."""
    source = scope["source"]
    logical_depth = f"_depth + {depth + 1}" if scope["nested"] else str(depth + 1)
    body.extend(
        statements(f"_budget.visit({emitter.source_name(source)}, {node.offset}, {logical_depth})")
    )
    pool = emitter.emit(node.children[0], body, depth + 2, **scope)
    plan = emitter.latest_plan(node, scope["environment"], source)
    if plan is not None:
        from .grouped_latest import grouped_latest

        return grouped_latest(
            emitter,
            node,
            plan,
            body,
            name,
            pool,
            depth + 1,
            source=source,
            nested=scope["nested"],
            count=True,
            normal=lambda block: _filtered_count_loop(
                emitter, node, block, name, pool, depth, scope
            ),
        )
    return _filtered_count_loop(emitter, node, body, name, pool, depth, scope)


def _filtered_count_loop(emitter, node, body, name, pool, depth, scope):
    item = name + "_item"
    body.append(emitter.assign(name, constant(0)))
    members = ordered_pool(node.children[0], pool, body, name)
    loop = ast.For(target=ast.Name(id=item, ctx=ast.Store()), iter=members, body=[], orelse=[])
    value = emitter.bound_expression(
        node.children[1], node.operand, item, loop.body, depth + 1, validated=True, **scope
    )
    loop.body.append(ast.If(test=value, body=statements(f"{name} += 1"), orelse=[]))
    body.append(loop)
    return ast.Name(id=name, ctx=ast.Load())


def quantifier(emitter, node, body, name, pool, depth, **scope):
    if uniform_selected(emitter, node, scope["environment"]):
        return uniform_quantifier(emitter, node, body, name, pool, depth, **scope)
    failure, count, item = name + "_failure", name + "_count", name + "_item"
    body.extend(statements(f"{failure} = None\n{count} = 0\n{name} = False"))
    members = ordered_pool(node.children[0], pool, body, name)
    loop = ast.For(target=ast.Name(id=item, ctx=ast.Store()), iter=members, body=[], orelse=[])
    guarded = statements("try:\n    pass\nexcept ExpressionError as error:\n    pass")[0]
    guarded.body = []
    value = emitter.bound_expression(
        node.children[1],
        node.operand,
        item,
        guarded.body,
        depth,
        validated=emitter.proofs.validated_argument(
            node.children[0], node.children[0].value_type, scope["environment"]
        ),
        **scope,
    )
    guarded.handlers[0].body = statements(
        "if error.diagnostic.code != 'InvalidValue':\n    raise\n"
        "key = (error.diagnostic.path, error.diagnostic.offset, error.diagnostic.actual)\n"
        f"if {failure} is None or key < ({failure}.diagnostic.path, "
        f"{failure}.diagnostic.offset, {failure}.diagnostic.actual):\n"
        f"    {failure} = error\ncontinue"
    )
    loop.body.append(guarded)
    decisive = statements(f"{name} = False\nbreak")
    if node.operation == "exactly_one":
        yes = statements(f"{count} += 1\nif {count} == 2:\n    pass")
        yes[-1].body = decisive
        loop.body.append(ast.If(test=value, body=yes, orelse=[]))
    else:
        if node.operation == "exists":
            decisive[0].value = constant(True)
        loop.body.append(
            ast.If(
                test=value
                if node.operation == "exists"
                else ast.UnaryOp(op=ast.Not(), operand=value),
                body=decisive,
                orelse=[],
            )
        )
    result = f"{count} == 1" if node.operation == "exactly_one" else str(node.operation == "forall")
    loop.orelse = statements(f"if {failure} is not None:\n    raise {failure}\n{name} = {result}")
    body.append(loop)
    return ast.Name(id=name, ctx=ast.Load())


def ranking(emitter, node, body, name, pool, depth, **scope):
    item, key, best_key, found, tied = (
        name + suffix for suffix in ("_item", "_key", "_best_key", "_found", "_tied")
    )
    origin = emitter.source_name(scope["source"])
    body.extend(statements(f"{name} = None\n{best_key} = None\n{found} = False\n{tied} = False"))
    members = ordered_pool(node.children[0], pool, body, name)
    loop = ast.For(target=ast.Name(id=item, ctx=ast.Store()), iter=members, body=[], orelse=[])
    keys = [
        emitter.bound_expression(
            child,
            parameter,
            item,
            loop.body,
            depth,
            validated=emitter.proofs.validated_argument(
                node.children[0], node.children[0].value_type, scope["environment"]
            ),
            **scope,
        )
        for child, parameter in zip(node.children[1:], node.operand, strict=True)
    ]
    loop.body.append(emitter.assign(key, ast.Tuple(elts=keys, ctx=ast.Load())))
    compare = "<" if node.operation == "min_by" else ">"
    loop.body.extend(
        statements(
            f"if not {found} or {key} {compare} {best_key}:\n"
            f"    {found}, {name}, {best_key}, {tied} = True, {item}, {key}, False\n"
            f"elif {node.children[0].value_type.kind == 'set'} and {key} == {best_key} "
            f"and {item} != {name}:\n"
            f"    {tied} = True"
        )
    )
    body.append(loop)
    body.extend(
        statements(
            f"if {tied}:\n"
            f"    {origin}.fail('AmbiguousSelection', {node.offset}, "
            "'unique best Set element or explicit distinguishing tie key', "
            "'multiple equally ranked elements')"
        )
    )
    return ast.Name(id=name, ctx=ast.Load())


def latest_by(emitter, node, body, name, pool, depth, **scope):
    """Compute each key/version once; preserve all strict maxima in input order."""
    item, rows, maxima, key, version, output = (
        name + suffix for suffix in ("_item", "_rows", "_maxima", "_key", "_version", "_output")
    )
    origin = emitter.source_name(scope["source"])
    logical_depth = f"_depth + {depth}" if scope["nested"] else str(depth)
    charge = f"_budget.visit({origin}, {node.offset}, {logical_depth})"
    if not emitter.proofs.validated_argument(
        node.children[0], node.children[0].value_type, scope["environment"]
    ):
        emitter.validate_result(
            node.children[0].value_type,
            pool,
            node.offset,
            body,
            origin=origin,
            reusable=True,
        )
    body.extend(statements(f"{rows} = []\n{maxima} = {{}}"))
    members = ordered_pool(node.children[0], pool, body, name)
    loop = ast.For(
        target=ast.Name(id=item, ctx=ast.Store()), iter=members, body=statements(charge), orelse=[]
    )
    for child, parameter, target in zip(
        node.children[1:], node.operand, (key, version), strict=True
    ):
        value = emitter.bound_expression(
            child,
            parameter,
            item,
            loop.body,
            depth,
            validated=True,
            **scope,
        )
        plan = child.value_type
        environment = {**scope["environment"], parameter: item}
        with emitter.proofs.bound(item, validated=True):
            if not emitter.proofs.validated_argument(child, plan, environment):
                if not emitter.scalar_result_proven(
                    child,
                    plan,
                    scope["source"],
                    child.offset,
                    loop.body,
                    environment=environment,
                ):
                    emitter.validate_result(plan, value, child.offset, loop.body, origin=origin)
        loop.body.append(emitter.assign(target, value))
    loop.body.extend(
        statements(
            f"{rows}.append(({item}, {key}, {version}))\n"
            f"if {key} not in {maxima} or {version} > {maxima}[{key}]:\n"
            f"    {maxima}[{key}] = {version}"
        )
    )
    body.append(loop)
    body.extend(
        statements(
            f"{output} = []\nfor {item}, {key}, {version} in {rows}:\n"
            f"    {charge}\n    if {version} == {maxima}[{key}]:\n"
            f"        {output}.append({item})\n{name} = tuple({output})"
        )
    )
    return ast.Name(id=name, ctx=ast.Load())


def collection_operation(emitter, node, children, body, name, source, *, subset_proven=False):
    operation = node.operation
    first, *remaining = children
    origin = emitter.source_name(source)
    if operation == "distinct":
        value = ast.Call(func=ast.Name(id="frozenset", ctx=ast.Load()), args=[first], keywords=[])
    elif operation in {"union", "difference", "concat"}:
        operator = {"union": ast.BitOr, "difference": ast.Sub, "concat": ast.Add}[operation]
        value = ast.BinOp(left=first, op=operator(), right=remaining[0])
    elif operation == "append":
        emitter.validate_result(
            emitter.checked.table.expression_type(node.value_type.element),
            remaining[0],
            node.offset,
            body,
            origin=origin,
        )
        value = ast.BinOp(left=first, op=ast.Add(), right=ast.Tuple(elts=remaining, ctx=ast.Load()))
    elif operation == "at":
        index = remaining[0]
        check = statements(
            "if not 0 <= 0 < len(()):\n"
            f"    {origin}.fail('InvalidValue', {node.offset}, "
            "'current sequence bounds', 'index out of bounds')"
        )[0]
        check.test.operand.comparators[0] = index
        check.test.operand.comparators[1].args[0] = first
        body.append(check)
        value = ast.Subscript(value=first, slice=index, ctx=ast.Load())
    elif operation in {"take", "drop"}:
        count = remaining[0]
        check = statements(
            "if 0 < 0:\n"
            f"    {origin}.fail('InvalidValue', {node.offset}, 'nonnegative prefix length', str(0))"
        )[0]
        check.test.left = count
        check.body[0].value.args[-1].args[0] = count
        body.append(check)
        value = ast.Subscript(
            value=first,
            slice=ast.Slice(
                lower=count if operation == "drop" else None,
                upper=count if operation == "take" else None,
            ),
            ctx=ast.Load(),
        )
    else:
        assert operation == "index_of"
        index, item = name + "_index", name + "_item"
        loop = statements(
            f"for {index}, {item} in enumerate(()):\n"
            f"    if {item} == None:\n        {name} = {index}\n        break\n"
            "else:\n"
            f"    {origin}.fail('MissingSequenceMember', {node.offset}, "
            "'member of the current sequence', 'absent')"
        )[0]
        loop.iter.args[0] = first
        loop.body[0].test.comparators[0] = remaining[0]
        body.append(loop)
        return ast.Name(id=name, ctx=ast.Load())
    body.append(emitter.assign(name, value))
    if operation not in {"at", "index_of"} and not subset_proven:
        emitter.validate_structure(node.value_type, name, node.offset, body, origin=origin)
    return ast.Name(id=name, ctx=ast.Load())
