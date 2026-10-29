"""Validated fixed-point proposal value artifacts; deployment does not import torch."""

from dataclasses import dataclass

FEATURES = ("success_core", "public_support", "self_member", "last_rejected", "nearby_pass")
PUBLIC_FEATURES = (
    *FEATURES,
    "vote_disagreement",
    "failed_backer",
    "failed_proposer",
    "advice_for",
    "advice_against",
)
SCALE = 65536
SCHEMA = "nomos.avalon.proposal-mlp.v1"
PUBLIC_SCHEMA = "nomos.avalon.proposal-mlp.public.v2"
BALLOT_FEATURES = (
    "is_percival",
    "critical",
    "multiple_evil",
    "advice_opposes",
    "failed_overlap",
    "self_in_team",
    "rejections_present",
    "approves",
)
BALLOT_SCHEMA = "nomos.avalon.ballot-mlp.v1"
CONTRACTS = ((SCHEMA, FEATURES), (PUBLIC_SCHEMA, PUBLIC_FEATURES), (BALLOT_SCHEMA, BALLOT_FEATURES))


@dataclass(frozen=True)
class NeuralValue:
    hidden: tuple
    biases: tuple
    output: tuple
    feature_names: tuple = FEATURES

    def __post_init__(self):
        n = len(self.hidden)
        if not 1 <= n <= 32 or len(self.biases) != n or len(self.output) != n:
            raise ValueError("neural proposal artifact needs 1..32 exact hidden units")
        if self.feature_names not in tuple(names for _, names in CONTRACTS):
            raise ValueError("unknown neural proposal feature contract")
        if any(len(row) != len(self.feature_names) for row in self.hidden):
            raise ValueError("neural proposal weights differ from the feature contract")
        values = (*self.biases, *self.output, *(v for row in self.hidden for v in row))
        if any(type(v) is not int or abs(v) > 32 * SCALE for v in values):
            raise ValueError("neural proposal weights must be bounded fixed-point integers")

    def score(self, features):
        if len(features) != len(self.feature_names) or any(
            type(x) is not int or x not in (0, 1) for x in features
        ):
            raise ValueError("neural proposal inputs must match the binary local feature contract")
        total = sum(
            v * (max(0, sum(w * x for w, x in zip(row, features)) + b) - max(0, b))
            for row, b, v in zip(self.hidden, self.biases, self.output)
        )
        return max(-80000, min(80000, 80000 * total // (SCALE * SCALE)))

    def parameters(self, prefix="nv"):
        if prefix not in ("nv", "bv"):
            raise ValueError("unknown neural parameter namespace")
        return {
            **{
                f"{prefix}_w_{j}_{i}": w
                for j, row in enumerate(self.hidden)
                for i, w in enumerate(row)
            },
            **{f"{prefix}_b_{j}": v for j, v in enumerate(self.biases)},
            **{f"{prefix}_v_{j}": v for j, v in enumerate(self.output)},
        }

    def data(self):
        return {
            "schema": next(schema for schema, names in CONTRACTS if names == self.feature_names),
            "features": list(self.feature_names),
            "scale": SCALE,
            "hidden": [list(row) for row in self.hidden],
            "biases": list(self.biases),
            "output": list(self.output),
        }

    @classmethod
    def from_data(cls, data):
        if set(data) != {"schema", "features", "scale", "hidden", "biases", "output"} or (
            (data["schema"], data["features"])
            not in tuple((schema, list(names)) for schema, names in CONTRACTS)
            or type(data["scale"]) is not int
            or data["scale"] != SCALE
        ):
            raise ValueError("foreign neural proposal artifact schema")
        return cls(
            tuple(tuple(row) for row in data["hidden"]),
            tuple(data["biases"]),
            tuple(data["output"]),
            tuple(data["features"]),
        )
