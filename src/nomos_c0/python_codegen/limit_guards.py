"""Remove dominated intrinsic limit guards without moving the first check."""

import ast

_GUARD = ast.dump(
    ast.parse(
        "if type(value_limits) is not ValueLimits:\n"
        "    raise TypeError('generated value needs ValueLimits')"
    ).body[0]
)
_BINDINGS = frozenset({"value_limits", "type", "ValueLimits", "TypeError"})


class _Guards:
    def __init__(self):
        self.removed = 0

    def block(self, body, proven):
        output = []
        for statement in body:
            if (
                isinstance(statement, ast.If)
                and not statement.orelse
                and len(statement.body) == 1
                and isinstance(statement.body[0], ast.Raise)
                and ast.dump(statement) == _GUARD
            ):
                if proven:
                    self.removed += 1
                    continue
                proven = True
            elif isinstance(statement, ast.If):
                left = self.block(statement.body, proven)
                right = self.block(statement.orelse, proven)
                proven = left and right
                if not statement.body:
                    statement.body = [ast.Pass()]
            elif isinstance(statement, (ast.For, ast.While)):
                self.block(statement.body, proven)
                self.block(statement.orelse, proven)
                if not statement.body:
                    statement.body = [ast.Pass()]
                # The body may never execute, or may leave through break.
            elif isinstance(statement, ast.Try):
                had_finally = bool(statement.finalbody)
                normal = self.block(statement.body, proven)
                self.block(statement.orelse, normal)
                for handler in statement.handlers:
                    self.block(handler.body, proven)
                    if not handler.body:
                        handler.body = [ast.Pass()]
                self.block(statement.finalbody, proven)
                if had_finally and not statement.finalbody:
                    statement.finalbody = [ast.Pass()]
                if not statement.body:
                    statement.body = [ast.Pass()]
                # Exceptions can leave any prefix; do not export a new proof.
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    self.block(case.body, proven)
                    if not case.body:
                        case.body = [ast.Pass()]
            output.append(statement)
        body[:] = output
        return proven


def elide_value_limit_guards(function):
    """Recognize only compiler-owned exact guards on an unrebound formal argument."""
    if not isinstance(function, ast.FunctionDef):
        return 0
    arguments = function.args
    if "value_limits" not in {
        arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }:
        return 0
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                    ast.Global,
                    ast.Nonlocal,
                    ast.With,
                    ast.AsyncWith,
                    ast.TryStar,
                    ast.Import,
                    ast.ImportFrom,
                ),
            ):
                return 0
            if (
                isinstance(node, ast.Name)
                and node.id in _BINDINGS
                and not isinstance(node.ctx, ast.Load)
                or isinstance(node, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler))
                and node.name in _BINDINGS
                or isinstance(node, ast.MatchMapping)
                and node.rest in _BINDINGS
            ):
                return 0
    if any(
        arg.arg in _BINDINGS - {"value_limits"}
        for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    ) or (
        arguments.vararg is not None
        and arguments.vararg.arg in _BINDINGS
        or arguments.kwarg is not None
        and arguments.kwarg.arg in _BINDINGS
    ):
        return 0
    guards = _Guards()
    guards.block(function.body, False)
    return guards.removed
