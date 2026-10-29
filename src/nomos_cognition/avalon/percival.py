"""Percival-local joint identity model, separately scoped from red-side weights."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .model import FEATURES, features, normalize
from .observations import ASSIGNMENTS, compatible


@dataclass(frozen=True)
class PercivalModel:
    weights: tuple[float, ...]
    temperature: float = 1.0

    def __post_init__(self):
        if (
            len(self.weights) != len(FEATURES)
            or any(type(w) not in (int, float) or not math.isfinite(w) for w in self.weights)
            or type(self.temperature) not in (int, float)
            or not math.isfinite(self.temperature)
            or self.temperature <= 0
        ):
            raise ValueError("Percival model needs exact finite features and positive temperature")

    def predict(self, observed):
        if (
            observed.own_role != "percival"
            or observed.pair is None
            or observed.observer in observed.pair
            or observed.known_evil
        ):
            raise ValueError("Percival model requires its own acquired candidate pair")
        assignments = tuple(a for a in ASSIGNMENTS if compatible(observed, a))
        return normalize(
            assignments,
            tuple(
                math.fsum(w * x for w, x in zip(self.weights, features(observed, a), strict=True))
                / self.temperature
                for a in assignments
            ),
        )

    def data(self):
        return {
            "schema": "nomos.avalon.percival-joint-linear.v1",
            "features": list(FEATURES),
            "weights": list(self.weights),
            "temperature": self.temperature,
        }

    @classmethod
    def from_data(cls, data):
        if set(data) != {"schema", "features", "weights", "temperature"} or (
            data["schema"] != "nomos.avalon.percival-joint-linear.v1"
            or data["features"] != list(FEATURES)
        ):
            raise ValueError("foreign Percival artifact contract")
        return cls(tuple(data["weights"]), data["temperature"])

    @classmethod
    def load(cls, path):
        return cls.from_data(json.loads(Path(path).read_text(encoding="utf-8")))
