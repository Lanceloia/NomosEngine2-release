"""Framework-independent learning values; neither observation nor execution authority."""

import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps
from typing import Any, cast


def _name(value: str) -> None:
    if type(value) is not str or not value:
        raise ValueError("learning names must be nonempty strings")


def _names(values: tuple[str, ...]) -> None:
    if (
        type(values) is not tuple
        or not values
        or any(type(v) is not str or not v for v in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("learning axes must be immutable, nonempty and distinct")
    for value in values:
        _name(value)


def _numbers(values: tuple[float, ...]) -> None:
    if type(values) is not tuple or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in values
    ):
        raise ValueError("learning vectors require immutable finite numbers")


def _digest(value: object) -> str:
    return sha256(
        dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _mapping(value: object, keys: tuple[str, ...]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("learning wire fields differ from the declared contract")
    return cast(dict[str, Any], value)


def _sequence(value: object) -> tuple[Any, ...]:
    if type(value) not in (tuple, list):
        raise ValueError("learning wire vectors require a sequence")
    return tuple(cast(tuple[Any, ...] | list[Any], value))


@dataclass(frozen=True)
class LearningSchema:
    name: str
    observations: tuple[str, ...]
    actions: tuple[str, ...]
    rewards: tuple[str, ...]

    def __post_init__(self) -> None:
        _name(self.name)
        for axes in (self.observations, self.actions, self.rewards):
            _names(axes)

    @property
    def signature(self) -> str:
        return _digest(("nomos.learning.schema.v1", asdict(self)))


@dataclass(frozen=True)
class LearningCandidate:
    key: str
    features: tuple[float, ...]
    prior: float
    priority: int = 0
    legal: bool = True

    def __post_init__(self) -> None:
        _name(self.key)
        _numbers(self.features)
        _numbers((self.prior,))
        if type(self.priority) is not int or type(self.legal) is not bool:
            raise ValueError("candidate priority and legality need exact types")


@dataclass(frozen=True)
class DecisionFrame:
    schema: LearningSchema
    observer: str
    episode: str
    basis: int
    observation: tuple[float, ...]
    candidates: tuple[LearningCandidate, ...]

    def __post_init__(self) -> None:
        if type(self.schema) is not LearningSchema:
            raise ValueError("learning frame requires an exact schema")
        _name(self.observer)
        _name(self.episode)
        if type(self.basis) is not int or self.basis < 0:
            raise ValueError("frame basis requires a nonnegative record position")
        _numbers(self.observation)
        if len(self.observation) != len(self.schema.observations):
            raise ValueError("observation width differs from schema")
        if (
            type(self.candidates) is not tuple
            or not self.candidates
            or any(type(c) is not LearningCandidate for c in self.candidates)
            or len({c.key for c in self.candidates}) != len(self.candidates)
            or any(len(c.features) != len(self.schema.actions) for c in self.candidates)
            or not any(c.legal for c in self.candidates)
        ):
            raise ValueError("frame requires distinct, shaped candidates and a legal action")

    @property
    def mask(self) -> tuple[bool, ...]:
        priority = max(c.priority for c in self.candidates if c.legal)
        return tuple(c.legal and c.priority == priority for c in self.candidates)

    @property
    def signature(self) -> str:
        return _digest(("nomos.learning.frame.v1", asdict(self)))

    def data(self) -> dict[str, object]:
        return {
            "schema": asdict(self.schema),
            "observer": self.observer,
            "episode": self.episode,
            "basis": self.basis,
            "observation": self.observation,
            "candidates": tuple(asdict(c) for c in self.candidates),
            "signature": self.signature,
        }

    @classmethod
    def from_data(cls, value: object) -> "DecisionFrame":
        data = _mapping(
            value,
            ("schema", "observer", "episode", "basis", "observation", "candidates", "signature"),
        )
        schema = _mapping(data["schema"], ("name", "observations", "actions", "rewards"))
        candidates = []
        for candidate in _sequence(data["candidates"]):
            row = _mapping(candidate, ("key", "features", "prior", "priority", "legal"))
            candidates.append(
                LearningCandidate(
                    row["key"],
                    _sequence(row["features"]),
                    row["prior"],
                    row["priority"],
                    row["legal"],
                )
            )
        frame = cls(
            LearningSchema(
                schema["name"],
                _sequence(schema["observations"]),
                _sequence(schema["actions"]),
                _sequence(schema["rewards"]),
            ),
            data["observer"],
            data["episode"],
            data["basis"],
            _sequence(data["observation"]),
            tuple(candidates),
        )
        if data["signature"] != frame.signature:
            raise ValueError("learning frame digest differs from decoded values")
        return frame


@dataclass(frozen=True)
class PolicyChoice:
    frame: str
    policy: str
    action: str
    probabilities: tuple[float, ...]
    log_probability: float
    value: float | None

    def __post_init__(self) -> None:
        for name in (self.frame, self.policy, self.action):
            _name(name)
        _numbers(self.probabilities)
        _numbers((self.log_probability,))
        if self.value is not None:
            _numbers((self.value,))


def choose(
    frame: DecisionFrame,
    probabilities: tuple[float, ...],
    *,
    policy: str,
    uniform: float,
    value: float | None = None,
) -> PolicyChoice:
    """Validate the entire distribution before sampling from already supplied local candidates."""
    if type(frame) is not DecisionFrame:
        raise ValueError("policy requires an exact learning frame")
    _numbers(probabilities)
    _numbers((uniform,))
    if (
        len(probabilities) != len(frame.candidates)
        or not 0 <= uniform < 1
        or any(
            not 0 <= p <= 1 or not allowed and p != 0
            for p, allowed in zip(probabilities, frame.mask)
        )
        or not math.isclose(math.fsum(probabilities), 1, abs_tol=1e-6, rel_tol=0)
    ):
        raise ValueError("policy requires a normalized distribution over allowed candidates")
    cumulative = 0.0
    selected = max(i for i, p in enumerate(probabilities) if p > 0)
    for i, probability in enumerate(probabilities):
        cumulative += probability
        if uniform < cumulative:
            selected = i
            break
    return PolicyChoice(
        frame.signature,
        policy,
        frame.candidates[selected].key,
        probabilities,
        math.log(probabilities[selected]),
        value,
    )


@dataclass(frozen=True)
class TrainingSample:
    """Decision-aligned outcome labels, not a one-step environment transition or TD reward."""

    frame: DecisionFrame
    choice: PolicyChoice
    feedback_basis: int
    rewards: tuple[float, ...]
    terminal_feedback: bool

    def __post_init__(self) -> None:
        if type(self.frame) is not DecisionFrame or type(self.choice) is not PolicyChoice:
            raise ValueError("sample requires an exact frame and choice")
        if self.choice.frame != self.frame.signature:
            raise ValueError("feedback belongs to a different decision frame")
        checked = choose(
            self.frame,
            self.choice.probabilities,
            policy=self.choice.policy,
            uniform=0,
            value=self.choice.value,
        )
        indexes = {c.key: i for i, c in enumerate(self.frame.candidates)}
        index = indexes.get(self.choice.action)
        if (
            index is None
            or self.choice.probabilities[index] <= 0
            or not math.isclose(
                self.choice.log_probability, math.log(checked.probabilities[index]), abs_tol=1e-6
            )
        ):
            raise ValueError("sample action and logged probability disagree")
        _numbers(self.rewards)
        if (
            len(self.rewards) != len(self.frame.schema.rewards)
            or type(self.terminal_feedback) is not bool
            or type(self.feedback_basis) is not int
            or self.feedback_basis <= self.frame.basis
        ):
            raise ValueError("feedback needs matching reward axes and a later basis")

    def data(self) -> dict[str, object]:
        return {
            "frame": self.frame.data(),
            "choice": asdict(self.choice),
            "feedback_basis": self.feedback_basis,
            "rewards": self.rewards,
            "terminal_feedback": self.terminal_feedback,
        }

    @classmethod
    def from_data(cls, value: object) -> "TrainingSample":
        data = _mapping(
            value, ("frame", "choice", "feedback_basis", "rewards", "terminal_feedback")
        )
        choice = _mapping(
            data["choice"],
            ("frame", "policy", "action", "probabilities", "log_probability", "value"),
        )
        return cls(
            DecisionFrame.from_data(data["frame"]),
            PolicyChoice(
                choice["frame"],
                choice["policy"],
                choice["action"],
                _sequence(choice["probabilities"]),
                choice["log_probability"],
                choice["value"],
            ),
            data["feedback_basis"],
            _sequence(data["rewards"]),
            data["terminal_feedback"],
        )


@dataclass(frozen=True)
class LearningBatch:
    schema: str
    observations: tuple[tuple[float, ...], ...]
    actions: tuple[tuple[tuple[float, ...], ...], ...]
    priors: tuple[tuple[float, ...], ...]
    masks: tuple[tuple[bool, ...], ...]
    keys: tuple[tuple[str | None, ...], ...]


def batch(frames: tuple[DecisionFrame, ...]) -> LearningBatch:
    """Pad variable candidate counts, never observations or incompatible schema axes."""
    if type(frames) is not tuple or not frames or any(type(f) is not DecisionFrame for f in frames):
        raise ValueError("batch requires nonempty exact frames")
    signature = frames[0].schema.signature
    if any(f.schema.signature != signature for f in frames):
        raise ValueError("batch cannot mix different schema orders or versions")
    width = max(len(f.candidates) for f in frames)
    actions, priors, masks, keys = [], [], [], []
    for frame in frames:
        padding = width - len(frame.candidates)
        actions.append(
            tuple(c.features for c in frame.candidates)
            + ((0.0,) * len(frame.schema.actions),) * padding
        )
        priors.append(tuple(c.prior for c in frame.candidates) + (0.0,) * padding)
        masks.append(frame.mask + (False,) * padding)
        keys.append(tuple(c.key for c in frame.candidates) + (None,) * padding)
    return LearningBatch(
        signature,
        tuple(f.observation for f in frames),
        tuple(actions),
        tuple(priors),
        tuple(masks),
        tuple(keys),
    )
