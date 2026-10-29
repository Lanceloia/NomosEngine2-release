"""Construct compiler-owned AST templates and literal constants."""

import ast


def statements(text):
    """Parse compiler-owned templates only; author data enters through Constant nodes."""
    return ast.parse(text).body


def constant(value):
    if type(value) is tuple:
        return ast.Tuple(elts=[constant(item) for item in value], ctx=ast.Load())
    return ast.Constant(value=value)
