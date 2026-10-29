"""Freeze the selected world's player-facing information before an actual decision."""

from dataclasses import asdict, dataclass
from itertools import permutations

ROLES = ("merlin", "percival", "servant", "morgana", "assassin")
EVIL = frozenset(("morgana", "assassin"))
ASSIGNMENTS = tuple(permutations(ROLES))


@dataclass(frozen=True)
class Proposal:
    epoch: int
    leader: int
    team: tuple[int, ...]


@dataclass(frozen=True)
class Ballot:
    epoch: int
    team: tuple[int, ...]
    approve: tuple[int, ...]


@dataclass(frozen=True)
class Quest:
    epoch: int
    team: tuple[int, ...]
    fails: int


@dataclass(frozen=True)
class Claim:
    speaker: int
    role: str


@dataclass(frozen=True)
class Advice:
    speaker: int
    team: tuple[int, ...]
    approve: bool


@dataclass(frozen=True)
class Observation:
    observer: int
    own_role: str
    known_evil: tuple[int, ...]
    pair: tuple[int, ...] | None
    proposals: tuple[Proposal, ...] = ()
    ballots: tuple[Ballot, ...] = ()
    quests: tuple[Quest, ...] = ()
    claims: tuple[Claim, ...] = ()
    advice: tuple[Advice, ...] = ()

    def __post_init__(self):
        def member(value):
            if type(value) is not int or not 0 <= value < 5:
                raise ValueError("observation refers to a foreign public seat")

        def group(values):
            if type(values) is not tuple or len(set(values)) != len(values):
                raise ValueError("observation needs a unique immutable group")
            for value in values:
                member(value)

        member(self.observer)
        if self.own_role not in ROLES:
            raise ValueError("observation has an unsupported own role")
        group(self.known_evil)
        if self.pair is not None:
            group(self.pair)
            if self.own_role != "percival" or len(self.pair) != 2:
                raise ValueError("selected five-role candidate pair is malformed")
        for name, carrier in (
            ("proposals", Proposal),
            ("ballots", Ballot),
            ("quests", Quest),
            ("claims", Claim),
            ("advice", Advice),
        ):
            rows = getattr(self, name)
            if type(rows) is not tuple or any(type(row) is not carrier for row in rows):
                raise ValueError("observation needs exact frozen history records")
            for row in rows:
                if hasattr(row, "team"):
                    group(row.team)
                if hasattr(row, "epoch") and (type(row.epoch) is not int or row.epoch < 1):
                    raise ValueError("observation has an invalid epoch")
                if type(row) is Proposal:
                    member(row.leader)
                elif type(row) is Ballot:
                    group(row.approve)
                elif type(row) is Quest:
                    if type(row.fails) is not int or not 0 <= row.fails <= len(row.team):
                        raise ValueError("observation has an invalid revealed failure count")
                else:
                    member(row.speaker)
                    if type(row) is Claim and row.role not in ROLES:
                        raise ValueError("observation has an unsupported claim")
                    if type(row) is Advice and type(row.approve) is not bool:
                        raise ValueError("observation needs an actual speech opinion")

    def data(self):
        return asdict(self)

    @classmethod
    def from_data(cls, data):
        data = dict(data)
        data["known_evil"] = tuple(data["known_evil"])
        data["pair"] = None if data["pair"] is None else tuple(data["pair"])
        for name, carrier in (
            ("proposals", Proposal),
            ("ballots", Ballot),
            ("quests", Quest),
            ("claims", Claim),
            ("advice", Advice),
        ):
            rows = []
            for row in data[name]:
                row = dict(row)
                for key in ("team", "approve"):
                    if key in row and type(row[key]) is list:
                        row[key] = tuple(row[key])
                rows.append(carrier(**row))
            data[name] = tuple(rows)
        return cls(**data)


def compatible(observation, assignment, *, opening_only=False):
    if assignment[observation.observer] != observation.own_role:
        return False
    if any(assignment[p] not in EVIL for p in observation.known_evil):
        return False
    if observation.pair is not None and {assignment[p] for p in observation.pair} != {
        "merlin",
        "morgana",
    }:
        return False
    return opening_only or all(
        sum(assignment[p] in EVIL for p in row.team) >= row.fails for row in observation.quests
    )
