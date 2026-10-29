"""Conservative native integer intervals assuming checked lexical inputs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IntegerRange:
    minimum: int | None = None
    maximum: int | None = None

    def fits(self, expected):
        return (
            expected.minimum is None
            or self.minimum is not None
            and self.minimum >= expected.minimum
        ) and (
            expected.maximum is None
            or self.maximum is not None
            and self.maximum <= expected.maximum
        )


class IntegerRanges:
    def __init__(self):
        self._ranges = {}

    def range(self, node):
        key = id(node)
        if key not in self._ranges:
            self._ranges[key] = node, self._analyze(node)
        return self._ranges[key][1]

    def _analyze(self, node):
        if node.value_type.kind != "int":
            return None
        operation = node.operation
        if operation == "literal":
            return IntegerRange(node.operand, node.operand) if type(node.operand) is int else None
        if operation in {"variable", "field", "at", "index_of"}:
            return IntegerRange(node.value_type.minimum, node.value_type.maximum)
        if operation == "pure_call":
            # A completed query expression has passed its caller-side return boundary.
            plan = node.operand.returns
            return IntegerRange(plan.minimum, plan.maximum)
        if operation in {"if", "match"}:
            ranges = [self.range(child) for child in node.children[1:]]
            if not ranges or any(value is None for value in ranges):
                return None
            lows, highs = [r.minimum for r in ranges], [r.maximum for r in ranges]
            return IntegerRange(
                None if None in lows else min(lows),
                None if None in highs else max(highs),
            )
        if operation == "size":
            pool = node.children[0]
            return IntegerRange(
                0, pool.value_type.maximum if pool.value_type.kind == "text" else None
            )
        if operation == "unary":
            value = self.range(node.children[0])
            if value is None or node.operand not in {"+", "-"}:
                return None
            if node.operand == "+":
                return value
            return IntegerRange(
                None if value.maximum is None else -value.maximum,
                None if value.minimum is None else -value.minimum,
            )
        if operation not in {"+", "-", "*", "//", "%"}:
            return None
        left, right = (self.range(child) for child in node.children)
        if left is None or right is None:
            return None
        a, b, c, d = left.minimum, left.maximum, right.minimum, right.maximum
        if operation == "+":
            return IntegerRange(
                None if None in (a, c) else a + c, None if None in (b, d) else b + d
            )
        if operation == "-":
            return IntegerRange(
                None if None in (a, d) else a - d, None if None in (b, c) else b - c
            )
        if operation == "%":
            if c is not None and c > 0:
                return IntegerRange(0, None if d is None else d - 1)
            if d is not None and d < 0:
                return IntegerRange(None if c is None else c + 1, 0)
            return None
        if None in (a, b, c, d):
            return None
        if operation == "*":
            values = [x * y for x in (a, b) for y in (c, d)]
        elif c > 0 or d < 0:
            values = [x // y for x in (a, b) for y in (c, d)]
        else:
            return None
        return IntegerRange(min(values), max(values))
