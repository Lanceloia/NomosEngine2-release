"""Pure seeded epsilon-greedy selection over complete, ordered legal candidates."""

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from json import dumps
from random import Random

from .appraisal import Decision


@dataclass(frozen=True)
class EpsilonGreedy:
    rate: Fraction
    seed: int

    def __post_init__(self):
        if type(self.rate) is not Fraction or not 0 <= self.rate <= 1:
            raise ValueError("exploration rate requires a Fraction between zero and one")
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise ValueError("exploration seed requires an unsigned 64-bit integer")


@dataclass(frozen=True)
class ExplorationDecision:
    policy: EpsilonGreedy
    visit: int
    step: int
    baseline: str
    selected: str
    ordered_keys: tuple[str, ...]
    gate: int | None
    index: int | None
    probability: Fraction

    @property
    def explored(self):
        return self.index is not None


def select(decision, baseline, ordered_keys, policy, *, visit, step):
    """Preserve estimates; choose a behavior action with an explicit probability."""
    if (
        type(decision) is not Decision
        or decision.status not in ("selected", "tie")
        or decision.assessment.status != "complete"
    ):
        raise ValueError("exploration requires a complete selectable decision")
    if type(policy) is not EpsilonGreedy:
        raise ValueError("exploration requires an EpsilonGreedy policy")
    if any(type(n) is not int or n < 0 for n in (visit, step)):
        raise ValueError("exploration visit and step require nonnegative integers")
    scores = {s.candidate: s.total for s in decision.scores}
    if (
        type(ordered_keys) is not tuple
        or not ordered_keys
        or any(type(k) is not str for k in ordered_keys)
        or len(set(ordered_keys)) != len(ordered_keys)
        or len(scores) != len(decision.scores)
        or set(ordered_keys) != set(scores)
        or set(scores) != {e.candidate.key for e in decision.assessment.estimates}
        or baseline not in scores
        or scores[baseline] != max(scores.values())
    ):
        raise ValueError("exploration requires every candidate exactly once and a best baseline")
    selected, gate, index = baseline, None, None
    if policy.rate:
        # No Session identity, candidate ticket or world RNG enters this random stream.
        payload = dumps(("nomos.epsilon-greedy.v1", policy.seed, visit, step)).encode()
        random = Random(int.from_bytes(sha256(payload).digest(), "big"))
        gate = random.randrange(policy.rate.denominator)
        if gate < policy.rate.numerator:
            index = random.randrange(len(ordered_keys))
            selected = ordered_keys[index]
    probability = policy.rate / len(ordered_keys)
    if selected == baseline:
        probability += 1 - policy.rate
    return ExplorationDecision(
        policy, visit, step, baseline, selected, ordered_keys, gate, index, probability
    )
