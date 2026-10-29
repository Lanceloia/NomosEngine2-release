"""A preference-conditioned network artifact; inference does not import torch."""

import math
from dataclasses import dataclass

from nomos_cognition.preferences import GoalPreference

from .neural_value import PUBLIC_FEATURES, SCALE, NeuralValue

AXES = ("task_progress", "protect_companions")
SCHEMA = "nomos.avalon.conditional-proposal.v1"


def preference(task):
    return GoalPreference(((AXES[0], task), (AXES[1], 1 - task)))


@dataclass(frozen=True)
class ConditionalValue:
    hidden: tuple
    biases: tuple
    output: tuple

    def __post_init__(self):
        if (
            type(self.hidden) is not tuple
            or type(self.biases) is not tuple
            or type(self.output) is not tuple
            or not 1 <= len(self.hidden) <= 32
            or len(self.biases) != len(self.hidden)
            or len(self.output) != len(self.hidden)
            or any(
                type(row) is not tuple or len(row) != len(PUBLIC_FEATURES) + 2
                for row in self.hidden
            )
        ):
            raise ValueError("invalid conditional network shape")
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 8
            for v in (*self.biases, *self.output, *(v for row in self.hidden for v in row))
        ):
            raise ValueError("conditional network parameters must be finite and bounded")

    def score(self, features, goals):
        if len(features) != len(PUBLIC_FEATURES) or any(
            type(v) is not int or v not in (0, 1) for v in features
        ):
            raise ValueError("features must match the binary local observation contract")
        if type(goals) is not GoalPreference:
            raise ValueError("a declared goal preference is required")
        z = goals.vector(AXES)
        value = 0.0
        for row, bias, weight in zip(self.hidden, self.biases, self.output):
            origin = bias + sum(w * x for w, x in zip(row[-2:], z))
            value += weight * (
                max(0, origin + sum(w * x for w, x in zip(row[:-2], features))) - max(0, origin)
            )
        return max(-1, min(1, value))

    def condition(self, goals):
        if type(goals) is not GoalPreference:
            raise ValueError("a declared goal preference is required")
        z = goals.vector(AXES)
        return NeuralValue(
            tuple(tuple(round(w * SCALE) for w in row[:-2]) for row in self.hidden),
            tuple(
                round((b + sum(w * x for w, x in zip(row[-2:], z))) * SCALE)
                for row, b in zip(self.hidden, self.biases)
            ),
            tuple(round(w * SCALE) for w in self.output),
            PUBLIC_FEATURES,
        )

    def data(self):
        return {
            "schema": SCHEMA,
            "features": list(PUBLIC_FEATURES),
            "axes": list(AXES),
            "hidden": [list(row) for row in self.hidden],
            "biases": list(self.biases),
            "output": list(self.output),
        }

    @classmethod
    def from_data(cls, data):
        if (
            type(data) is not dict
            or set(data) != {"schema", "features", "axes", "hidden", "biases", "output"}
            or data["schema"] != SCHEMA
            or data["features"] != list(PUBLIC_FEATURES)
            or data["axes"] != list(AXES)
        ):
            raise ValueError("unknown conditional network contract")
        return cls(
            tuple(tuple(row) for row in data["hidden"]),
            tuple(data["biases"]),
            tuple(data["output"]),
        )
