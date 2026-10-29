"""Scalarize a compiler-owned expression budget, synchronizing every escape boundary."""

import ast
from copy import copy, deepcopy
from dataclasses import dataclass

from .syntax import statements

_STEPS = "_nomos_budget_steps"
_STEP_LIMIT = "_nomos_budget_step_limit"
_DEPTH_LIMIT = "_nomos_budget_depth_limit"


@dataclass(frozen=True)
class LocalBudgetResult:
    visits: int = 0
    boundaries: int = 0
    reason: str = "unselected"


def _name(node, name):
    return isinstance(node, ast.Name) and node.id == name


def _attribute(node, name, field):
    return isinstance(node, ast.Attribute) and _name(node.value, name) and node.attr == field


def _query(call):
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id.startswith("_query_")
        and call.args
        and _name(call.args[0], "_budget")
    )


def _order(call):
    return (
        isinstance(call, ast.Call)
        and _name(call.func, "_ordered_members")
        and len(call.args) == 2
        and _name(call.args[0], "_budget")
        and not call.keywords
    )


def _method(call):
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and _name(call.func.value, "_budget")
        and call.func.attr in {"visit", "visit_block"}
    )


def _cache_method(call):
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and _name(call.func.value, "_budget")
        and call.func.attr in {"lookup_work", "replay_source"}
    )


def _region(function):
    if any(arg.arg == "_budget" for arg in function.args.args):
        return 0
    for index, statement in enumerate(function.body):
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and _name(statement.targets[0], "_budget")
            and isinstance(statement.value, ast.Call)
            and _name(statement.value.func, "ExpressionBudget")
        ):
            start = index + 1
            if start < len(function.body):
                setup = function.body[start]
                if (
                    isinstance(setup, ast.Assign)
                    and len(setup.targets) == 1
                    and _attribute(setup.targets[0], "_budget", "query_values")
                    and _name(setup.value, "query_values")
                ):
                    start += 1
            return start
    return None


def _scan(function, body):
    """Collect full-function collisions and region-local ownership facts once."""
    roots = {id(node) for node in body}
    # Only the function header and prefix are outside the selected region.
    if any(
        _name(node, _STEPS)
        for child in ast.iter_child_nodes(function)
        if id(child) not in roots
        for node in ast.walk(child)
    ):
        return (), {}, True, 0, False, ()
    parents, nodes = {}, []
    ancestry = []
    visits, has_loop = 0, False
    pending = [(node, None) for node in body]
    while pending:
        node, ancestor = pending.pop()
        if _name(node, _STEPS):
            return (), {}, True, 0, False, ()
        index = len(nodes)
        nodes.append(node)
        ancestry.append(ancestor)
        visits += bool(isinstance(node, ast.Call) and _method(node))
        has_loop |= isinstance(node, ast.For)
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
            pending.append((child, index))
    return nodes, parents, False, visits, has_loop, ancestry


def _owned(nodes, parents):
    """Every budget reference must have a compiler-controlled nonescaping use."""
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Delete)):
            return False
        if not _name(node, "_budget"):
            continue
        parent = parents[id(node)]
        if isinstance(parent, ast.Attribute) and parent.value is node:
            if parent.attr == "steps" and not isinstance(parent.ctx, ast.Del):
                continue
            if parent.attr == "query_values" and isinstance(parent.ctx, ast.Load):
                continue
            outer = parents.get(id(parent))
            if (
                parent.attr in {"limits", "source_limits"}
                and isinstance(outer, ast.Attribute)
                and outer.value is parent
                and outer.attr in {"steps", "depth"}
                and isinstance(outer.ctx, ast.Load)
            ):
                continue
            call = parents.get(id(parent))
            owner = parents.get(id(call))
            if (
                (_method(call) or _cache_method(call))
                and call.func is parent
                and isinstance(owner, ast.Expr)
                and owner.value is call
                and not call.keywords
                and len(call.args)
                == (1 if _cache_method(call) else 3 if parent.attr == "visit" else 4)
            ):
                continue
        if (_query(parent) or _order(parent)) and parent.args[0] is node:
            owner = parents.get(id(parent))
            if isinstance(owner, ast.Assign) and owner.value is parent:
                continue
        return False
    return True


def _integer(node):
    return isinstance(node, ast.Constant) and type(node.value) is int


def _depth(node):
    return (
        _integer(node)
        or _name(node, "_depth")
        or (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
            and _name(node.left, "_depth")
            and _integer(node.right)
        )
    )


def _budget_paths(nodes, ancestry):
    """Select rewrite ancestors after the full region has passed ownership checks."""
    paths, seen = set(), set()
    for index, node in enumerate(nodes):
        if not _name(node, "_budget"):
            continue
        # Track occurrences, not only object identities: valid ASTs can share a
        # child between several parent paths, and all those paths need rewriting.
        while index is not None and index not in seen:
            seen.add(index)
            paths.add(id(nodes[index]))
            index = ancestry[index]
    return paths


class _LocalBudget(ast.NodeTransformer):
    def __init__(self, paths):
        self.paths = paths
        self.visits = self.boundaries = 0

    def visit(self, node):
        # Every rewrite below contains a literal _budget name. Selection limits
        # copying and transformation, never the preceding full safety scan.
        if id(node) not in self.paths:
            return node
        # Copy only rewrite paths. Clone their lists too: NodeTransformer edits
        # lists in place, and an unselected pass must leave the input untouched.
        node = copy(node)
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                setattr(node, field, list(value))
        return super().visit(node)

    def visit_Attribute(self, node):
        if _attribute(node, "_budget", "steps"):
            return ast.Name(id=_STEPS, ctx=node.ctx)
        if isinstance(node.value, ast.Attribute) and _attribute(node.value, "_budget", "limits"):
            return ast.Name(id=_STEP_LIMIT if node.attr == "steps" else _DEPTH_LIMIT, ctx=node.ctx)
        return self.generic_visit(node)

    def synchronize(self, statement):
        self.boundaries += 1
        before = statements(f"_budget.steps = {_STEPS}")
        guard = ast.Try(
            body=[statement],
            handlers=[],
            orelse=[],
            finalbody=statements(f"{_STEPS} = _budget.steps\n{_STEP_LIMIT} = _budget.limits.steps"),
        )
        return [*before, guard]

    def visit_Assign(self, node):
        query = _query(node.value) or _order(node.value)
        node = self.generic_visit(node)
        return self.synchronize(node) if query else node

    def visit_Expr(self, node):
        if _cache_method(node.value):
            return self.synchronize(self.generic_visit(node))
        if not _method(node.value):
            return self.generic_visit(node)
        call = node.value
        if call.func.attr == "visit":
            source, offset, depth = call.args
            if not isinstance(source, ast.Name) or not _integer(offset) or not _depth(depth):
                return self.synchronize(node)
            self.visits += 1
            result = statements(
                f"{_STEPS} += 1\n"
                f"if {_STEPS} > {_STEP_LIMIT} or 0 > {_DEPTH_LIMIT}:\n"
                "    None.fail('ExpressionBudget', 0, 'bounded evaluation', 'step/depth limit')"
            )
            result[-1].test.values[1].left = deepcopy(depth)
            failure = result[-1].body[0].value
            failure.func.value, failure.args[1] = deepcopy(source), deepcopy(offset)
            return result
        source, sites, maximum, base = call.args
        try:
            positions = ast.literal_eval(sites)
        except (ValueError, TypeError):
            return self.synchronize(node)
        if not (
            isinstance(source, ast.Name)
            and type(positions) is tuple
            and positions
            and all(
                type(p) is tuple and len(p) == 2 and all(type(v) is int for v in p)
                for p in positions
            )
            and _integer(maximum)
            and maximum.value == max(depth for _, depth in positions)
            and _depth(base)
        ):
            return self.synchronize(node)
        self.visits += 1
        fast = statements(
            f"if {_STEPS} + {len(positions)} <= {_STEP_LIMIT} and 0 <= {_DEPTH_LIMIT}:\n"
            f"    {_STEPS} += {len(positions)}\n"
            "else:\n    pass"
        )[0]
        fast.test.values[1].left = ast.BinOp(
            left=deepcopy(base), op=ast.Add(), right=deepcopy(maximum)
        )
        fast.orelse = self.synchronize(node)
        return fast


def scalarize_budget(function):
    """Select a whole generated function or leave its AST completely unchanged."""
    start = _region(function)
    if start is None:
        return LocalBudgetResult(reason="no-owned-budget")
    body = function.body[start:]
    nodes, parents, collision, visits, has_loop, ancestry = _scan(function, body)
    if collision:
        return LocalBudgetResult(reason="no-owned-budget")
    if not _owned(nodes, parents):
        return LocalBudgetResult(reason="budget-escape-or-unknown-use")
    if visits < 4 and not has_loop:
        return LocalBudgetResult(reason="small-straight-line-function")
    block = ast.Try(body=body, handlers=[], orelse=[], finalbody=[])
    transform = _LocalBudget(_budget_paths(nodes, ancestry) | {id(block)})
    block = transform.visit(block)
    if not transform.visits:
        return LocalBudgetResult(reason="no-static-visits")
    block.finalbody = statements(f"_budget.steps = {_STEPS}")
    function.body[start:] = [
        *statements(
            f"{_STEPS} = _budget.steps\n"
            f"{_STEP_LIMIT} = _budget.limits.steps\n"
            f"{_DEPTH_LIMIT} = _budget.limits.depth"
        ),
        block,
    ]
    return LocalBudgetResult(transform.visits, transform.boundaries, "owned-local-counter")
