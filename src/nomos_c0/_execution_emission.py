"""Shared compiler-only mechanics for checked Python execution plans."""

from __future__ import annotations

import ast


class FunctionEmission:
    def __init__(self, globals: dict[str, object] | None = None):
        self.namespace = dict(globals or {})
        self._names = set(self.namespace)
        self._serials: dict[str, int] = {}

    def fresh(self, prefix: str = "item") -> str:
        if not prefix.isascii() or not prefix.isidentifier():
            raise ValueError("generated local prefix must be an ASCII identifier")
        serial = self._serials.get(prefix, 0)
        while True:
            name = f"{prefix}_{serial}"
            serial += 1
            if name not in self._names and name not in self.namespace:
                self._serials[prefix] = serial
                self._names.add(name)
                return name

    def bind(self, value: object) -> str:
        name = self.fresh("constant")
        self.namespace[name] = value
        return name

    @staticmethod
    def statements(template: str) -> list[ast.stmt]:
        return ast.parse(template).body

    def compile(self, module: ast.Module, *, filename: str) -> dict[str, object]:
        # Only compiler-selected templates reach this boundary, never author text.
        exec(compile(ast.fix_missing_locations(module), filename, "exec"), self.namespace)
        return self.namespace
