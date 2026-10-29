"""Explicit goal preferences, independent of policy parameters and world authority."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GoalPreference:
    weights: tuple[tuple[str, float], ...]

    def __post_init__(self):
        if (
            type(self.weights) is not tuple
            or not self.weights
            or any(type(item) is not tuple or len(item) != 2 for item in self.weights)
        ):
            raise ValueError("preferences need immutable named weights")
        names = [name for name, _ in self.weights]
        if any(type(name) is not str or not name.isidentifier() for name in names):
            raise ValueError("preference axes need distinct identifiers")
        values = [value for _, value in self.weights]
        if len(set(names)) != len(names) or any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in values
        ):
            raise ValueError("preference weights must be finite and nonnegative")
        if not math.isclose(sum(values), 1, abs_tol=1e-9, rel_tol=0):
            raise ValueError("preference weights must sum to one")

    def vector(self, axes):
        if len(set(axes)) != len(axes) or set(axes) != dict(self.weights).keys():
            raise ValueError("preference axes differ from the policy contract")
        return tuple(dict(self.weights)[axis] for axis in axes)

    def data(self):
        return {"schema": "nomos.goal-preference.v1", "weights": dict(self.weights)}

    @classmethod
    def from_data(cls, data):
        if (
            type(data) is not dict
            or set(data) != {"schema", "weights"}
            or data["schema"] != "nomos.goal-preference.v1"
            or type(data["weights"]) is not dict
        ):
            raise ValueError("unknown goal preference contract")
        return cls(tuple(sorted(data["weights"].items())))
