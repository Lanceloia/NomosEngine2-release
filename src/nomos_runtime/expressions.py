"""Diagnostics and logical resource accounting, not an expression interpreter."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpan:
    file: str
    digest: str
    path: tuple
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class ExpressionDiagnostic:
    code: str
    stage: str
    path: str
    offset: int
    line: int
    column: int
    span: SourceSpan | None
    expected: str
    actual: str


class ExpressionError(Exception):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        file = diagnostic.path if diagnostic.span is None else diagnostic.span.file
        super().__init__(
            f"{diagnostic.code}: {file}:{diagnostic.line}:{diagnostic.column}: "
            f"{diagnostic.expected}; {diagnostic.actual}"
        )


@dataclass(frozen=True)
class Source:
    text: str
    path: str
    span: SourceSpan | None = None

    def fail(self, code, offset, expected, actual):
        prefix = self.text[:offset]
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1]) + 1
        if self.span is not None:
            column += self.span.column - 1 if line == 1 else 0
            line += self.span.line - 1
        raise ExpressionError(
            ExpressionDiagnostic(
                code, "Run", self.path, offset, line, column, self.span, expected, actual
            )
        )

    def value_failure(self, error, offset, expected="valid pure value"):
        code = error.diagnostic.code
        self.fail("ExpressionBudget" if code == "ValueBudget" else code, offset, expected, code)


@dataclass(frozen=True)
class ExpressionLimits:
    steps: int = 100000
    depth: int = 64

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in (self.steps, self.depth)):
            raise ValueError("expression budgets must be positive integers")


@dataclass(frozen=True)
class _WorkLimits:
    steps: int
    depth: int


class _ExpressionWork:
    def __init__(self, work, limits):
        self.work, self.source_limits = work, limits
        self.remaining = work.until - work.used
        self.replayed = self.lookups = 0
        if self.remaining < 1:
            work.interrupt()

    def limits(self):
        return _WorkLimits(
            min(self.source_limits.steps, self.remaining + self.replayed - self.lookups),
            self.source_limits.depth,
        )


class ExpressionBudget:
    def __init__(self, limits):
        if type(limits) is not ExpressionLimits:
            raise TypeError("generated expression needs ExpressionLimits")
        self.limits, self.steps = limits, 0
        self.query_values = None
        self.planning = None
        self._orders = None

    @property
    def source_limits(self):
        return self.limits if self.planning is None else self.planning.source_limits

    def plan_work(self, work):
        if self.planning is not None:
            raise ValueError("expression work is already configured")
        self.planning = _ExpressionWork(work, self.limits)
        self.limits = self.planning.limits()

    def lookup_work(self, amount):
        if type(amount) is not int or amount < 1:
            raise ValueError("query lookup work must be positive")
        if self.planning is not None:
            if self.steps > self.limits.steps:
                raise ValueError("failed expression cannot access query entries")
            if self.work_used() + amount > self.planning.remaining:
                self.planning.work.interrupt(amount)
            self.planning.lookups += amount
            self.limits = self.planning.limits()

    def replay_source(self, steps):
        if type(steps) is not int or steps < 0 or self.steps + steps > self.source_limits.steps:
            raise ValueError("query replay requires a proved source cost")
        self.steps += steps
        if self.planning is not None:
            self.planning.replayed += steps
            self.limits = self.planning.limits()

    def work_used(self):
        if self.planning is None:
            raise ValueError("expression work is not configured")
        used = min(self.steps, self.limits.steps) - self.planning.replayed + self.planning.lookups
        if not 0 <= used <= self.planning.remaining:
            raise ValueError("expression work accounting is inconsistent")
        return used

    def visit(self, source, offset, depth):
        self.steps += 1
        if self.steps > self.limits.steps or depth > self.limits.depth:
            source.fail("ExpressionBudget", offset, "bounded evaluation", "step/depth limit")

    def visit_block(self, source, sites, maximum, base=0):
        steps = self.steps + len(sites)
        if steps <= self.limits.steps and base + maximum <= self.limits.depth:
            self.steps = steps
        else:
            # Only the cold failure path walks the original diagnostic sites.
            for offset, depth in sites:
                self.visit(source, offset, base + depth)


@dataclass(frozen=True)
class ValueLimits:
    depth: int = 64
    nodes: int = 32768
    items: int = 4096
    wire_bytes: int = 1048576

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("value budgets must be positive integers")


@dataclass(frozen=True)
class ValueDiagnostic:
    code: str
    stage: str
    definition: str
    path: tuple
    expected: str
    actual: str


class ValueBindingError(Exception):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(
            f"{diagnostic.code}: {diagnostic.definition}{diagnostic.path}: "
            f"{diagnostic.expected}; {diagnostic.actual}"
        )


def fail_value(definition, path, code, expected, actual):
    raise ValueBindingError(ValueDiagnostic(code, "Bind", definition, path, expected, actual))


class ValueBudget:
    def __init__(self, limits, references=None, *, resolve_reference=None):
        if type(limits) is not ValueLimits:
            raise TypeError("generated value needs ValueLimits")
        self.limits, self.nodes = limits, 0
        self.references = references
        self.resolve_reference = resolve_reference

    def check(self, definition, path):
        self.nodes += 1
        if self.nodes > self.limits.nodes or len(path) > self.limits.depth:
            fail_value(definition, path, "ValueBudget", "bounded structure", "node/depth limit")

    def collection(self, definition, path, size):
        if size > self.limits.items:
            fail_value(definition, path, "ValueBudget", "bounded collection", "item limit")
