"""Permutation-equivariant conditional linear scores and consistent joint probabilities."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .observations import ASSIGNMENTS, EVIL, ROLES, compatible

FEATURES = tuple(
    [f"quest/evil={evil}/fails={fails}" for evil in range(3) for fails in range(3)]
    + [f"proposal/{role}/evil={evil}" for role in ROLES for evil in range(3)]
    + [
        f"vote/{role}/evil={evil}/yes={yes}"
        for role in ROLES
        for evil in range(3)
        for yes in (False, True)
    ]
    + [f"claim/{role}/as={claimed}" for role in ROLES for claimed in ROLES]
    + [
        f"advice/{role}/evil={evil}/yes={yes}"
        for role in ROLES
        for evil in range(3)
        for yes in (False, True)
    ]
    + [
        f"proposal/{role}/merlin={merlin}/morgana={morgana}"
        for role in ROLES
        for merlin in (False, True)
        for morgana in (False, True)
    ]
    + [
        f"{source}/{role}/merlin={merlin}/morgana={morgana}/yes={yes}"
        for source in ("vote", "advice")
        for role in ROLES
        for merlin in (False, True)
        for morgana in (False, True)
        for yes in (False, True)
    ]
)
POSITIONS = {name: index for index, name in enumerate(FEATURES)}


def features(observation, assignment):
    values = [0.0] * len(FEATURES)

    def add(name):
        values[POSITIONS[name]] += 1.0

    def evil(team):
        return sum(assignment[p] in EVIL for p in team)

    def pair(team):
        return (
            f"merlin={assignment.index('merlin') in team}/"
            f"morgana={assignment.index('morgana') in team}"
        )

    for row in observation.quests:
        add(f"quest/evil={evil(row.team)}/fails={row.fails}")
    for row in observation.proposals:
        add(f"proposal/{assignment[row.leader]}/evil={evil(row.team)}")
        add(f"proposal/{assignment[row.leader]}/{pair(row.team)}")
    for row in observation.ballots:
        for person, role in enumerate(assignment):
            add(f"vote/{role}/evil={evil(row.team)}/yes={person in row.approve}")
            add(f"vote/{role}/{pair(row.team)}/yes={person in row.approve}")
    for row in observation.claims:
        add(f"claim/{assignment[row.speaker]}/as={row.role}")
    for row in observation.advice:
        add(f"advice/{assignment[row.speaker]}/evil={evil(row.team)}/yes={row.approve}")
        add(f"advice/{assignment[row.speaker]}/{pair(row.team)}/yes={row.approve}")
    return tuple(values)


@dataclass(frozen=True)
class Belief:
    assignments: tuple
    probabilities: tuple[float, ...]

    def __post_init__(self):
        if (
            not self.assignments
            or len(set(self.assignments)) != len(self.assignments)
            or any(a not in ASSIGNMENTS for a in self.assignments)
            or len(self.probabilities) != len(self.assignments)
            or any(
                type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                for p in self.probabilities
            )
            or not math.isclose(math.fsum(self.probabilities), 1, abs_tol=1e-12)
        ):
            raise ValueError("belief needs a finite normalized joint distribution")

    def marginal(self, person, role):
        if type(person) is not int or not 0 <= person < 5 or role not in ROLES:
            raise ValueError("unknown belief subject or role")
        return min(
            1.0,
            math.fsum(
                p
                for a, p in zip(self.assignments, self.probabilities, strict=True)
                if a[person] == role
            ),
        )

    def all_good(self, members):
        if len(set(members)) != len(members) or any(
            type(p) is not int or not 0 <= p < 5 for p in members
        ):
            raise ValueError("team needs distinct known public seats")
        # Valid normalized beliefs can sum slightly above one through roundoff.
        return min(
            1.0,
            math.fsum(
                p
                for a, p in zip(self.assignments, self.probabilities, strict=True)
                if all(a[person] not in EVIL for person in members)
            ),
        )


def normalize(assignments, scores):
    if (
        not assignments
        or len(assignments) != len(scores)
        or any(type(score) not in (int, float) or not math.isfinite(score) for score in scores)
    ):
        raise ValueError("no compatible hypotheses or invalid scores")
    maximum = max(scores)
    masses = tuple(math.exp(score - maximum) for score in scores)
    total = math.fsum(masses)
    return Belief(tuple(assignments), tuple(mass / total for mass in masses))


def prior(observation, *, opening_only=False):
    assignments = tuple(
        a for a in ASSIGNMENTS if compatible(observation, a, opening_only=opening_only)
    )
    return normalize(assignments, (0.0,) * len(assignments))


@dataclass(frozen=True)
class Model:
    weights: tuple[float, ...]
    temperature: float = 1.0

    def __post_init__(self):
        if (
            len(self.weights) != len(FEATURES)
            or any(type(w) not in (int, float) or not math.isfinite(w) for w in self.weights)
            or type(self.temperature) not in (int, float)
            or not (math.isfinite(self.temperature) and self.temperature > 0)
        ):
            raise ValueError("model needs exact finite features and a positive temperature")

    def predict(self, observation):
        if observation.own_role not in EVIL:
            raise ValueError("this trained model selects only assassin and morgana observers")
        assignments = tuple(a for a in ASSIGNMENTS if compatible(observation, a))
        return normalize(
            assignments,
            tuple(
                math.fsum(
                    w * x for w, x in zip(self.weights, features(observation, a), strict=True)
                )
                / self.temperature
                for a in assignments
            ),
        )

    def data(self):
        return {
            "schema": "nomos.avalon.red-merlin-linear.v1",
            "features": list(FEATURES),
            "weights": list(self.weights),
            "temperature": self.temperature,
        }

    @classmethod
    def from_data(cls, data):
        if set(data) != {"schema", "features", "weights", "temperature"} or (
            data["schema"] != "nomos.avalon.red-merlin-linear.v1"
            or data["features"] != list(FEATURES)
        ):
            raise ValueError("model artifact has a foreign feature contract")
        return cls(tuple(data["weights"]), data["temperature"])

    @classmethod
    def load(cls, path):
        return cls.from_data(json.loads(Path(path).read_text(encoding="utf-8")))
