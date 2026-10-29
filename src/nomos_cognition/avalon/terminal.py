"""Exact one-action assassination values from supplied local beliefs and legal targets.

This is a numerical leaf evaluator, not a world simulator or a belief updater.
The caller obtains targets from the runtime and commits choices through it.
"""

import math

from nomos_cognition.learning import DecisionFrame, LearningCandidate, LearningSchema, choose

from .model import Belief
from .observations import ASSIGNMENTS

SCHEMA = LearningSchema(
    "avalon.assassination.joint.v1",
    tuple("belief/" + "/".join(a) for a in ASSIGNMENTS),
    tuple(f"target/{i}" for i in range(5)),
    ("red_terminal",),
)


def frame(belief, targets, *, observer, episode, basis):
    """Encode a conditional joint distribution without supplying hidden truth."""
    if type(belief) is not Belief:
        raise ValueError("terminal evaluation requires a validated joint belief")
    if (
        type(targets) is not tuple
        or not targets
        or len(set(targets)) != len(targets)
        or any(type(t) is not int or not 0 <= t < 5 for t in targets)
    ):
        raise ValueError("terminal targets must be distinct runtime-supplied seats")
    masses = dict(zip(belief.assignments, belief.probabilities, strict=True))
    if not math.isclose(sum(belief.marginal(t, "merlin") for t in targets), 1, abs_tol=1e-10):
        raise ValueError("terminal targets omit possible Merlin assignments")
    return DecisionFrame(
        SCHEMA,
        observer,
        episode,
        basis,
        tuple(masses.get(a, 0.0) for a in ASSIGNMENTS),
        tuple(
            LearningCandidate(str(t), tuple(float(i == t) for i in range(5)), 0.0) for t in targets
        ),
    )


def probabilities(local_frame):
    if type(local_frame) is not DecisionFrame or local_frame.schema != SCHEMA:
        raise ValueError("foreign terminal frame")
    # Reuse the strict probability validator, including normalization and finiteness.
    belief = Belief(ASSIGNMENTS, local_frame.observation)
    values = []
    for candidate in local_frame.candidates:
        if candidate.features not in tuple(
            tuple(float(i == t) for i in range(5)) for t in range(5)
        ):
            raise ValueError("terminal candidate must name one target seat")
        seat = candidate.features.index(1.0)
        if candidate.key != str(seat):
            raise ValueError("terminal key differs from its seat")
        values.append(belief.marginal(seat, "merlin"))
    return tuple(values)


def decision(local_frame, scores=None, *, policy="avalon.terminal.exact.v1"):
    exact = probabilities(local_frame)
    values = exact if scores is None else scores
    if len(values) != len(exact) or any(not math.isfinite(v) for v in values):
        raise ValueError("terminal scores must match finite legal candidates")
    selected = max(
        (i for i, allowed in enumerate(local_frame.mask) if allowed),
        key=lambda i: (values[i], -int(local_frame.candidates[i].key)),
    )
    return choose(
        local_frame,
        tuple(float(i == selected) for i in range(len(values))),
        policy=policy,
        uniform=0.0,
        value=2 * values[selected] - 1,
    )
