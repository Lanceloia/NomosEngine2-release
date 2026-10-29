"""Frame-owned reuse of completed pure construction expressions."""

from dataclasses import dataclass, field
from types import MappingProxyType

from .ordering import canonical


@dataclass(frozen=True, eq=False)
class PreparedMembers:
    values: tuple
    ranks: object = field(init=False, repr=False)

    def __post_init__(self):
        if type(self.values) is not tuple:
            raise ValueError("prepared members need an immutable ordered tuple")
        ranks = {value: index for index, value in enumerate(self.values)}
        if len(ranks) != len(self.values):
            raise ValueError("prepared members must be distinct")
        object.__setattr__(self, "ranks", MappingProxyType(ranks))

    @classmethod
    def prepare(cls, values, work):
        if type(values) is not frozenset:
            raise ValueError("member preparation requires a checked set")
        work.spend(max(1, 2 * len(values)))
        return cls(tuple(sorted(values, key=canonical)))


@dataclass(frozen=True, eq=False)
class ConstructionExpression:
    function: object
    inputs: tuple[str, ...]
    members: bool = False

    def __post_init__(self):
        if not callable(self.function):
            raise ValueError("construction expression needs a generated callable")
        if (
            type(self.inputs) is not tuple
            or any(type(name) is not str for name in self.inputs)
            or len(set(self.inputs)) != len(self.inputs)
        ):
            raise ValueError("construction expression inputs must be distinct names")
        if type(self.members) is not bool:
            raise ValueError("construction member preparation must be explicit boolean")


@dataclass(frozen=True)
class FramePreparation:
    requests: int
    reused: int
    completed: int
    member_domains: int


class ConstructionFrame:
    def __init__(self, reads, value_limits):
        self._reads, self._value_limits = reads, value_limits
        self._results = {}
        self._members = {}
        self._requests = self._reused = 0

    def preparation(self):
        return FramePreparation(
            self._requests, self._reused, len(self._results), len(self._members)
        )

    def evaluate(self, expression, scope, work):
        if type(expression) is not ConstructionExpression:
            raise ValueError("construction requires compiled expression dependencies")
        work.spend(1 + len(expression.inputs))
        self._requests += 1
        inputs = tuple(scope[name] for name in expression.inputs)
        key = expression, tuple(id(value) for value in inputs)
        cached = self._results.get(key)
        if cached is None:
            result = expression.function(self._reads, self._value_limits, scope, work)
            # Retain actual inputs: object-id reuse must never alias another scope.
            self._results[key] = inputs, result
        else:
            self._reused += 1
            result = cached[1]
        if expression.members:
            if key not in self._members:
                self._members[key] = PreparedMembers.prepare(result, work)
            return self._members[key]
        return result
