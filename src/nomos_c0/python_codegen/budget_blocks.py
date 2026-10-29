"""Fold visits across proven total local copies, never across execution boundaries."""

import ast
from dataclasses import dataclass

from .syntax import constant

_BLOCK_LIMIT = 32


@dataclass(frozen=True)
class BudgetBlock:
    source: str
    base: str | None
    sites: tuple[tuple[int, int], ...]

    def statement(self):
        return ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="_budget", ctx=ast.Load()),
                    attr="visit_block",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Name(id=self.source, ctx=ast.Load()),
                    constant(self.sites),
                    constant(max(depth for _, depth in self.sites)),
                    constant(0) if self.base is None else ast.Name(id=self.base, ctx=ast.Load()),
                ],
                keywords=[],
            )
        )


def _integer(node):
    return isinstance(node, ast.Constant) and type(node.value) is int


def _visit(statement):
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return None
    call = statement.value
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "_budget"
        and call.func.attr == "visit"
        and len(call.args) == 3
        and not call.keywords
    ):
        return None
    source, offset, depth = call.args
    if not isinstance(source, ast.Name) or not _integer(offset):
        return None
    if _integer(depth):
        base, relative = None, depth.value
    elif (
        isinstance(depth, ast.BinOp)
        and isinstance(depth.op, ast.Add)
        and isinstance(depth.left, ast.Name)
        and depth.left.id == "_depth"
        and _integer(depth.right)
    ):
        base, relative = "_depth", depth.right.value
    else:
        return None
    return source.id, base, (offset.value, relative)


def _targets(target):
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_targets(item) for item in target.elts))
    return set()


def _copy(statement, bound):
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id not in {"_budget", "_depth"}
        and not statement.targets[0].id.startswith("_SOURCE_")
        and (
            isinstance(statement.value, ast.Constant)
            or isinstance(statement.value, ast.Name)
            and statement.value.id in bound
        )
    )


def _nested(statement, bound, plans):
    if isinstance(statement, ast.If):
        left = _block(statement.body, bound, plans)
        right = _block(statement.orelse, bound, plans)
        return left & right
    if isinstance(statement, (ast.For, ast.While)):
        inside = bound | (_targets(statement.target) if isinstance(statement, ast.For) else set())
        _block(statement.body, inside, plans)
        _block(statement.orelse, bound, plans)
    elif isinstance(statement, ast.Try):
        _block(statement.body, bound, plans)
        _block(statement.orelse, bound, plans)
        _block(statement.finalbody, bound, plans)
        for handler in statement.handlers:
            _block(handler.body, bound | ({handler.name} if handler.name else set()), plans)
    elif isinstance(statement, ast.Match):
        for case in statement.cases:
            _block(case.body, bound, plans)
    return bound


def _block(body, initial, plans):
    bound, output, pending, sites = set(initial), [], [], []
    source = base = None

    def flush():
        if len(sites) > 1:
            plan = BudgetBlock(source, base, tuple(sites))
            output.append(plan.statement())
            output.extend(statement for statement in pending if _visit(statement) is None)
            plans.append(plan)
        else:
            output.extend(pending)
        pending.clear()
        sites.clear()

    for statement in body:
        visit = _visit(statement)
        if visit is not None:
            current_source, current_base, site = visit
            if sites and (
                current_source != source or current_base != base or len(sites) == _BLOCK_LIMIT
            ):
                flush()
            source, base = current_source, current_base
            pending.append(statement)
            sites.append(site)
            continue
        if sites and _copy(statement, bound):
            pending.append(statement)
        else:
            flush()
            bound = _nested(statement, bound, plans)
            output.append(statement)
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                bound.update(_targets(target))
    flush()
    body[:] = output
    return bound


def fold_budget_blocks(function):
    """Mutate one generated function and return its static block plans."""
    bound = {arg.arg for arg in (*function.args.posonlyargs, *function.args.args)}
    bound.update(arg.arg for arg in function.args.kwonlyargs)
    plans = []
    _block(function.body, bound, plans)
    return tuple(plans)
