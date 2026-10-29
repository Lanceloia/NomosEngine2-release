"""Inline bounded scalar-validator blocks within generated nominal validators."""

import ast
from copy import deepcopy


def inline_scalar_checks(body, values):
    functions = {node.name: node for node in body if isinstance(node, ast.FunctionDef)}
    leaves = {}
    for plan in values.plans.values():
        if plan.kind in {"bool", "unit", "int", "enum"}:
            name = values.validator(plan)
            # Keep an immutable template: parents and leaves may be interleaved.
            leaves[name] = deepcopy(functions[name].body[1:-1]), plan.name
    counts = []
    for function in functions.values():
        if not function.name.startswith("_check_") or function.name in leaves:
            continue
        transformer = _Inline(leaves)
        transformer.visit(function)
        if transformer.count:
            counts.append((function.name, transformer.count))
    return counts


def inline_shape_checks(body, values):
    functions = {node.name: node for node in body if isinstance(node, ast.FunctionDef)}
    leaves = {
        values.shape(plan): (deepcopy(functions[values.shape(plan)].body), plan.name)
        for plan in values.shapes.values()
        if plan.kind in {"bool", "unit", "int", "text", "enum", "ref"}
    }
    counts = []
    for function in functions.values():
        if not function.name.startswith("_shape_") or function.name in leaves:
            continue
        transformer = _Inline(leaves, capture_value=True)
        transformer.visit(function)
        if transformer.count:
            counts.append((function.name, transformer.count))
    return counts


class _Inline(ast.NodeTransformer):
    def __init__(self, leaves, *, capture_value=False):
        self.leaves = leaves
        self.capture_value = capture_value
        self.count = 0
        self.remaining = 1024

    def visit_Expr(self, node):
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in self.leaves
            and not call.keywords
            and len(call.args) == 3
            and (
                isinstance(call.args[0], ast.Name)
                or self.capture_value
                and isinstance(call.args[0], ast.Attribute)
                and isinstance(call.args[0].value, ast.Name)
            )
            and isinstance(call.args[1], ast.Name)
            and call.args[1].id == "budget"
            and isinstance(call.args[2], (ast.Name, ast.Tuple))
            and all(
                isinstance(part, (ast.Name, ast.Load, ast.Tuple, ast.Starred, ast.Constant))
                for part in ast.walk(call.args[2])
            )
        ):
            return node
        template, definition = self.leaves[call.func.id]
        cost = sum(1 for statement in template for _ in ast.walk(statement))
        if self.capture_value:
            cost += sum(1 for arg in (call.args[0], call.args[2]) for _ in ast.walk(arg)) + 6
        if cost > self.remaining:
            return node
        self.remaining -= cost
        prefix = "_nomos_shape_check" if self.capture_value else "_nomos_scalar_check"
        path_name = f"{prefix}_{self.count}_path"
        value_name = f"{prefix}_{self.count}_value"
        self.count += 1
        path = ast.Name(id=path_name, ctx=ast.Load())
        replacements = {
            "value": ast.Name(id=value_name, ctx=ast.Load())
            if self.capture_value
            else call.args[0],
            "budget": call.args[1],
            "path": path,
            "definition": ast.Constant(value=definition),
        }
        substitute = _Substitute(replacements)
        # Shape leaves ignore value, but its field access must still precede
        # path evaluation and the budget failure, exactly as a real argument.
        return [
            *(
                [
                    ast.Assign(
                        targets=[ast.Name(id=value_name, ctx=ast.Store())],
                        value=deepcopy(call.args[0]),
                    )
                ]
                if self.capture_value
                else []
            ),
            ast.Assign(
                targets=[ast.Name(id=path_name, ctx=ast.Store())],
                value=deepcopy(call.args[2]),
            ),
            *(substitute.visit(deepcopy(statement)) for statement in template),
        ]


class _Substitute(ast.NodeTransformer):
    def __init__(self, replacements):
        self.replacements = replacements

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.replacements:
            return deepcopy(self.replacements[node.id])
        return node
