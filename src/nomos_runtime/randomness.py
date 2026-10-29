"""Selected replayable streams, staged in the same transaction as world effects."""

from dataclasses import dataclass
from hashlib import sha256
from secrets import randbits
from types import MappingProxyType

MAX_SEED = (1 << 63) - 1
MAX_SIDES = 1000


class RandomBudgetExceeded(Exception):
    code = "RandomBudget"

    def __init__(self, path, message):
        self.path = path
        super().__init__(f"RandomBudget: {path}: {message}")


@dataclass(frozen=True)
class RandomKey:
    stream: str


@dataclass(frozen=True)
class RandomState:
    seed: int
    count: int = 0


@dataclass(frozen=True)
class DrawRecord:
    label: str
    ordinal: int
    seed: int
    sides: int
    value: int
    stream: str


def next_seed(seed):
    digest = sha256(b"nomos.c0.die.next.v1\0" + seed.to_bytes(8, "big")).digest()
    return int.from_bytes(digest[:8], "big") & MAX_SEED


def roll(seed, sides):
    limit = (1 << 64) - (1 << 64) % sides
    for counter in range(128):
        digest = sha256(
            b"nomos.c0.die.roll.v1\0"
            + seed.to_bytes(8, "big")
            + sides.to_bytes(2, "big")
            + counter.to_bytes(2, "big")
        ).digest()
        sample = int.from_bytes(digest[:8], "big")
        if sample < limit:
            return sample % sides + 1
    raise RandomBudgetExceeded("replayable_seed", "finite rejection sampling exhausted")


def opening_states(streams, assets):
    if not streams:
        return {}
    row = assets["random"]
    if type(row) is not dict or not {"seed"} <= set(row) <= {"seed", "streams"}:
        raise ValueError("Assets.random requires seed and declared stream seeds")
    others = row.get("streams", {})
    if type(others) is not dict or set(others) != set(streams) - {"main"}:
        raise ValueError("Assets.random.streams differs from selected stream declarations")
    seeds = {"main": row["seed"], **others}
    if any(
        seed != "fresh" and (type(seed) is not int or not 0 <= seed <= MAX_SEED)
        for seed in seeds.values()
    ):
        raise ValueError("Assets.random seed requires fresh or an integer in its domain")
    seeds = {name: randbits(63) if seed == "fresh" else seed for name, seed in seeds.items()}
    return {
        RandomKey(name): MappingProxyType({"state": RandomState(seeds[name])}) for name in streams
    }


class RandomCursor:
    def __init__(self, before, changes):
        self.before, self.changes = before, changes
        self.draws = []

    def sample(self, label, sides, stream):
        if type(sides) is not int or not 2 <= sides <= MAX_SIDES:
            raise ValueError("draw sides must be an integer between 2 and 1000")
        if type(stream) is not str or RandomKey(stream) not in self.before:
            raise ValueError("draw stream is outside the selected domain")
        key = RandomKey(stream)
        current = self.changes.get((key, "state"), self.before[key]["state"])
        value = roll(current.seed, sides)
        self.draws.append(DrawRecord(label, current.count + 1, current.seed, sides, value, stream))
        self.changes[key, "state"] = RandomState(next_seed(current.seed), current.count + 1)
        return value

    def shuffle(self, label, values, stream):
        if type(values) is not tuple:
            raise ValueError("shuffle requires an exact Sequence")
        if len(values) > MAX_SIDES:
            raise RandomBudgetExceeded(label, "shuffle exceeds its finite sequence capacity")
        result = list(values)
        for index in range(len(result) - 1, 0, -1):
            selected = self.sample(label, index + 1, stream) - 1
            result[index], result[selected] = result[selected], result[index]
        return tuple(result)
