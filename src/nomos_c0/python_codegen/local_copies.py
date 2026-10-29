"""Propagate definitely bound local names without moving their producers or checks."""

import ast
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

_TEMP = re.compile(r"_v[0-9]+(?:_[A-Za-z0-9_]+)?\Z")
_UNSUPPORTED = (
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.AnnAssign,
    ast.NamedExpr,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
    ast.TryStar,
    ast.Import,
    ast.ImportFrom,
)


@dataclass(frozen=True)
class LocalCopyResult:
    substitutions: int
    removed_assignments: int


def _targets(node):
    return {
        n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }


def _writes(node):
    # The whole-function guard rejects expression binders (walrus/comprehensions/
    # nested scopes) before this analysis. Only assignment targets can bind here.
    if isinstance(node, ast.Assign):
        return {name for target in node.targets for name in _targets(target)}
    if isinstance(node, ast.AugAssign):
        return _targets(node.target)
    if isinstance(node, (ast.Expr, ast.Return, ast.Raise, ast.Assert)):
        return set()
    return _bindings(node)[0]


def _bindings(node):
    # The whole-function guard already excludes expression binders and nested
    # scopes. Only Store targets, patterns and exception handlers bind here.
    names, cleared = set(), set()
    pending = [node]
    while pending:
        child = pending.pop()
        if isinstance(child, ast.Name):
            if isinstance(child.ctx, ast.Store):
                names.add(child.id)
            continue
        if isinstance(child, (ast.Tuple, ast.List, ast.Starred)) and isinstance(
            child.ctx, ast.Store
        ):
            pending.extend([child.value] if isinstance(child, ast.Starred) else child.elts)
            continue
        if isinstance(child, ast.expr):
            continue
        if isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name is not None:
            names.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest is not None:
            names.add(child.rest)
        elif isinstance(child, ast.ExceptHandler) and child.name is not None:
            names.add(child.name)
            cleared.add(child.name)
        pending.extend(ast.iter_child_nodes(child))
    return names, cleared


def _without(aliases, writes):
    # Values are already flattened to their current source binding.
    return {
        name: source
        for name, source in aliases.items()
        if name not in writes and source not in writes
    }


class _Propagation(ast.NodeTransformer):
    def __init__(self):
        self.aliases = {}
        self.substitutions = 0
        self.candidates = {}

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.aliases:
            self.substitutions += 1
            return ast.copy_location(ast.Name(id=self.aliases[node.id], ctx=ast.Load()), node)
        return node

    def rewrite(self, node, aliases):
        if not aliases:
            return node
        self.aliases = aliases
        return self.visit(node)

    def block(self, body, initial, incoming):
        bound, aliases = set(initial), dict(incoming)
        for statement in body:
            if isinstance(statement, ast.If):
                statement.test = self.rewrite(statement.test, aliases)
                left_bound, left = self.block(statement.body, bound, aliases)
                right_bound, right = self.block(statement.orelse, bound, aliases)
                bound = left_bound & right_bound
                aliases = {
                    name: source for name, source in left.items() if right.get(name) == source
                }
            elif isinstance(statement, (ast.For, ast.While)):
                writes, cleared = _bindings(statement)
                stable = _without(aliases, writes)
                # An except target is deleted on handler exit, including on an
                # earlier iteration. Only a for target is rebound every iteration.
                bound -= cleared
                if isinstance(statement, ast.For):
                    statement.iter = self.rewrite(statement.iter, aliases)
                    inside = bound | _targets(statement.target)
                else:
                    # Unlike a for iterable, this condition runs after body writes too.
                    statement.test = self.rewrite(statement.test, stable)
                    inside = bound
                self.block(statement.body, inside, stable)
                self.block(statement.orelse, bound, stable)
                aliases = stable
            elif isinstance(statement, ast.Try):
                # A handler may see any prefix of the try body, including no writes.
                writes, cleared = _bindings(statement)
                stable = _without(aliases, writes)
                normal_bound, normal = self.block(statement.body, bound, aliases)
                self.block(statement.orelse, normal_bound, normal)
                for handler in statement.handlers:
                    if handler.type is not None:
                        handler.type = self.rewrite(handler.type, stable)
                    self.block(
                        handler.body,
                        (bound - cleared) | ({handler.name} if handler.name else set()),
                        stable,
                    )
                self.block(statement.finalbody, bound - cleared, stable)
                bound -= cleared
                aliases = _without(stable, cleared)
            elif isinstance(statement, ast.Match):
                statement.subject = self.rewrite(statement.subject, aliases)
                writes, cleared = _bindings(statement)
                stable = _without(aliases, writes)
                for case in statement.cases:
                    captured = _writes(case.pattern)
                    # A failed guard can leave captures visible to the next case.
                    local = _without(stable, captured)
                    if case.guard is not None:
                        case.guard = self.rewrite(case.guard, local)
                    self.block(case.body, bound | captured, local)
                aliases = stable
                bound -= cleared
            else:
                if isinstance(statement, ast.Assign):
                    # RHS runs before target stores. A tuple/chained target may
                    # rebind a source before a later subscript/attribute uses it.
                    writes = _writes(statement)
                    statement.value = self.rewrite(statement.value, aliases)
                    target_aliases = _without(aliases, writes)
                    statement.targets = [
                        self.rewrite(target, target_aliases) for target in statement.targets
                    ]
                else:
                    self.rewrite(statement, aliases)
                    writes = _writes(statement)
                aliases = _without(aliases, writes)
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and _TEMP.fullmatch(statement.targets[0].id)
                ):
                    target, value = statement.targets[0].id, statement.value
                    if isinstance(value, ast.Name) and value.id in bound:
                        self.candidates[id(statement)] = statement
                        if target != value.id:
                            aliases[target] = value.id
                    elif isinstance(value, ast.Constant):
                        self.candidates[id(statement)] = statement
                bound |= writes
        return bound, aliases


def _dead_copies(function, candidates):
    if not candidates:
        return 0
    reads = Counter()
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            reads[node.id] += 1
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            reads[node.target.id] += 1
    by_target = defaultdict(list)
    for statement in candidates.values():
        by_target[statement.targets[0].id].append(statement)
    pending = deque(name for name in by_target if not reads[name])
    removed = set()
    while pending:
        for statement in by_target[pending.popleft()]:
            if id(statement) in removed:
                continue
            removed.add(id(statement))
            if isinstance(statement.value, ast.Name):
                source = statement.value.id
                reads[source] -= 1
                if not reads[source] and source in by_target:
                    pending.append(source)

    if not removed:
        return 0

    class Remove(ast.NodeTransformer):
        def visit_Assign(self, node):
            return None if id(node) in removed else node

        def generic_visit(self, node):
            # Removal only edits statement lists. Expression subtrees cannot
            # contain candidate Assign statements or bodies needing a Pass.
            if isinstance(node, ast.expr):
                return node
            had_finally = isinstance(node, ast.Try) and bool(node.finalbody)
            super().generic_visit(node)
            if had_finally and not node.finalbody:
                node.finalbody = [ast.Pass()]
            if (
                isinstance(
                    node, (ast.For, ast.While, ast.If, ast.Try, ast.ExceptHandler, ast.match_case)
                )
                and not node.body
            ):
                node.body = [ast.Pass()]
            return node

    Remove().visit(function)
    return len(removed)


def propagate_local_copies(function):
    """Optimize C0's private temporary names; unsupported Python scopes stay intact."""
    for node in ast.walk(function):
        if (
            isinstance(node, _UNSUPPORTED)
            or isinstance(node, ast.FunctionDef)
            and node is not function
            or isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"locals", "globals", "vars", "eval", "exec"}
        ):
            return LocalCopyResult(0, 0)
    bound = {
        arg.arg
        for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    }
    bound.update(arg.arg for arg in (function.args.vararg, function.args.kwarg) if arg is not None)
    propagation = _Propagation()
    propagation.block(function.body, bound, {})
    removed = _dead_copies(function, propagation.candidates)
    if not function.body:
        function.body.append(ast.Pass())
    return LocalCopyResult(propagation.substitutions, removed)
