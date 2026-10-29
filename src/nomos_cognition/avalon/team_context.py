"""Candidate summaries derived exclusively from an actor's encoded joint belief."""

import math

from nomos_cognition.learning import DecisionFrame

from . import decision, graded
from .observations import ASSIGNMENTS, EVIL, ROLES

FEATURES = tuple(f"evil_count/{i}" for i in range(3)) + tuple(f"role_in_team/{r}" for r in ROLES)
BELIEFS = tuple(decision.OBSERVATIONS.index("belief/" + "/".join(a)) for a in ASSIGNMENTS)
MEMBERS = tuple(decision.ACTIONS.index(f"member/{i}") for i in range(5))
PROPOSE = decision.ACTIONS.index("ability/propose")


def features(frame):
    """These are subjective event estimates, not world facts or a preference ordering."""
    if type(frame) is not DecisionFrame or frame.schema not in (decision.SCHEMA, graded.SCHEMA):
        raise ValueError("team context requires a supported actor-local frame")
    probabilities = tuple(frame.observation[i] for i in BELIEFS)
    if any(p < 0 for p in probabilities) or not math.isclose(
        math.fsum(probabilities), 1, abs_tol=1e-8
    ):
        raise ValueError("team context needs normalized encoded joint beliefs")
    result = []
    for candidate in frame.candidates:
        bits = tuple(candidate.features[i] for i in MEMBERS)
        if (
            candidate.features[PROPOSE] != 1
            or any(v not in (0, 1) for v in bits)
            or sum(bits) not in (2, 3)
        ):
            raise ValueError("team context requires five-player legal-size proposal features")
        members = tuple(i for i, bit in enumerate(bits) if bit)
        counts = tuple(sum(assignment[i] in EVIL for i in members) for assignment in ASSIGNMENTS)
        values = tuple(
            math.fsum(p for p, n in zip(probabilities, counts, strict=True) if n == k)
            for k in range(3)
        )
        values += tuple(
            math.fsum(
                p
                for assignment, p in zip(ASSIGNMENTS, probabilities, strict=True)
                if any(assignment[i] == role for i in members)
            )
            for role in ROLES
        )
        result.append(values)
    return tuple(result)
