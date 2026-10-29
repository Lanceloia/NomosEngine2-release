"""Bounded compile-time scalar and literal data validation."""

import json
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0BindingError


def validate_scalar(kind, value, *, minimum=0, maximum=0, choices=()):
    """Shared primitive checks; Python's bool/int relationship grants no coercion."""
    carrier = {"bool": bool, "unit": type(None), "int": int, "text": str, "enum": str}[kind]
    if type(value) is not carrier:
        raise ValueError("wrong scalar carrier")
    if kind == "int" and (
        minimum is not None and value < minimum or maximum is not None and value > maximum
    ):
        raise ValueError("integer outside declared bounds")
    if kind == "enum" and value not in choices:
        raise ValueError("value outside declared enum")
    if kind == "text" and (
        len(value) > maximum or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ValueError("text exceeds its scalar bound or contains a surrogate")


@dataclass(frozen=True)
class ValueDiagnostic:
    code: str
    stage: str
    definition: str
    path: tuple[str | int, ...]
    expected: str
    actual: str


class ValueBindingError(C0BindingError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        location = "".join(
            f"[{part}]" if type(part) is int else f".{part}" for part in diagnostic.path
        )
        super().__init__(
            f"{diagnostic.code}: {diagnostic.definition}{location}: "
            f"{diagnostic.expected}; {diagnostic.actual}"
        )


@dataclass(frozen=True)
class ValueLimits:
    depth: int = 64
    nodes: int = 32768
    items: int = 4096
    wire_bytes: int = 1048576

    def __post_init__(self):
        if any(
            type(value) is not int or value < 1
            for value in (self.depth, self.nodes, self.items, self.wire_bytes)
        ):
            raise C0BindingError("value budgets must be positive integers")


class _Budget:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = 0
        self.bytes = 0

    def check(self, plan, path):
        self.nodes += 1
        if self.nodes > self.limits.nodes or len(path) > self.limits.depth:
            _fail(plan, path, "ValueBudget", "bounded structure", "node/depth limit")

    def collection(self, plan, value, path):
        if len(value) > self.limits.items:
            _fail(plan, path, "ValueBudget", "bounded collection", "item limit")

    def wire(self, plan, size, path):
        self.bytes += size
        if self.bytes > self.limits.wire_bytes:
            _fail(plan, path, "ValueBudget", "bounded wire bytes", "byte limit")


def _fail(plan, path, code, expected, actual):
    raise ValueBindingError(ValueDiagnostic(code, "Compile", plan.name, path, expected, actual))


def _wire_atom_bytes(plan, value, path, budget):
    if type(value) is str:
        if len(value) > budget.limits.wire_bytes:
            _fail(plan, path, "ValueBudget", "bounded wire bytes", "byte limit")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            _fail(plan, path, "InvalidValue", "Unicode scalar text", "surrogate")
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        _fail(plan, path, "InvalidValue", "encodable plain wire atom", "encoding failed")


def _wire_check(plan, value, path, budget, stack=frozenset()):
    budget.check(plan, path)
    if value is None or type(value) in (bool, int, str):
        budget.wire(plan, _wire_atom_bytes(plan, value, path, budget), path)
        return
    if type(value) not in (dict, list) or id(value) in stack:
        _fail(plan, path, "InvalidValue", "acyclic plain wire data", type(value).__name__)
    budget.collection(plan, value, path)
    budget.wire(plan, 2 + max(0, len(value) - 1), path)
    stack = stack | {id(value)}
    for name, child in value.items() if type(value) is dict else enumerate(value):
        if type(value) is dict and type(name) is not str:
            _fail(plan, path, "InvalidValue", "text wire keys", type(name).__name__)
        if type(value) is dict:
            budget.wire(plan, _wire_atom_bytes(plan, name, path, budget) + 1, path)
        _wire_check(plan, child, (*path, name), budget, stack)
