"""Stateless, actor-local Avalon features; no Session, training cache, or terminal labels."""

from nomos_cognition.learning import DecisionFrame, LearningCandidate, LearningSchema

from .model import Belief
from .observations import ASSIGNMENTS, ROLES, Observation

ABILITIES = ("propose", "approve", "quest", "assassinate")
PHASES = ("proposal", "discussion", "response", "approval", "quest", "assassination", "finished")
DISCUSSIONS = ("none", "proposal", "review", "final")
PARTS = ("task", "cooperation", "concealment", "terminal")
COUNTERS = ("mission", "successes", "failures", "rejections", "epoch", "speech_serial")
SCALES = (5, 3, 3, 5, 25, 60)
OBSERVATIONS = (
    *(f"own/{r}" for r in ROLES),
    *(f"known_evil/{p}" for p in range(5)),
    *(f"private_pair/{p}" for p in range(5)),
    *("belief/" + "/".join(a) for a in ASSIGNMENTS),
    *(f"current_team/{p}" for p in range(5)),
    *(f"leader/{p}" for p in range(5)),
    *COUNTERS,
    *(f"phase/{p}" for p in PHASES),
    *(f"discussion/{p}" for p in DISCUSSIONS),
    *(f"ability/{a}" for a in ABILITIES),
    *(
        f"proposal/{epoch}/{axis}"
        for epoch in range(25)
        for axis in (
            "present",
            *(f"leader/{p}" for p in range(5)),
            *(f"team/{p}" for p in range(5)),
            "resolved",
            *(f"yes/{p}" for p in range(5)),
        )
    ),
    *(
        f"quest/{i}/{axis}"
        for i in range(5)
        for axis in ("present", "epoch", *(f"team/{p}" for p in range(5)), "fails")
    ),
    *(f"claim/{p}/{r}" for p in range(5) for r in ROLES),
    *(f"advice/{p}/{team}/{yes}" for p in range(5) for team in range(32) for yes in (False, True)),
)
ACTIONS = (
    *(f"ability/{a}" for a in ABILITIES),
    *(f"member/{p}" for p in range(5)),
    "flag",
    *(f"target/{p}" for p in range(5)),
)
SCHEMA = LearningSchema("avalon.stateless.local.v1", OBSERVATIONS, ACTIONS, PARTS)


def relative(person, observer):
    return (person - observer) % 5


def action_features(ability, inputs, observer):
    if ability not in ABILITIES:
        raise ValueError("unsupported stateless action")
    expected = {
        "propose": "members",
        "approve": "approve",
        "quest": "sabotage",
        "assassinate": "target",
    }[ability]
    if set(inputs) != {expected}:
        raise ValueError("action fields differ from the current generated ability")
    members = inputs[expected] if ability == "propose" else ()
    target = inputs[expected] if ability == "assassinate" else None
    if any(type(p) is not int or not 0 <= p < 5 for p in members) or (
        target is not None and (type(target) is not int or not 0 <= target < 5)
    ):
        raise ValueError("action refers to an unknown seat")
    if ability in ("approve", "quest") and type(inputs[expected]) is not bool:
        raise ValueError("action needs a real boolean")
    return (
        tuple(float(a == ability) for a in ABILITIES)
        + tuple(float(any(relative(p, observer) == i for p in members)) for i in range(5))
        + (float(inputs[expected]) if ability in ("approve", "quest") else 0.0,)
        + tuple(float(target is not None and relative(target, observer) == i) for i in range(5))
    )


def encode(observed, belief, state, ability):
    if type(observed) is not Observation or type(belief) is not Belief:
        raise ValueError("stateless encoding requires local observation and validated belief")
    if set(state) != {*COUNTERS, "team", "leader", "phase", "discussion_kind"}:
        raise ValueError("state must contain only the explicit local public fields")
    if (
        ability not in ABILITIES
        or state["phase"] not in PHASES
        or state["discussion_kind"] not in DISCUSSIONS
    ):
        raise ValueError("unknown decision phase")
    if len(observed.quests) > 5 or any(not 1 <= p.epoch <= 25 for p in observed.proposals):
        raise ValueError("history exceeds the current five-mission rule bounds")
    who = observed.observer
    order = tuple((who + i) % 5 for i in range(5))
    masses = {
        tuple(a[p] for p in order): v
        for a, v in zip(belief.assignments, belief.probabilities, strict=True)
    }
    result = [float(observed.own_role == r) for r in ROLES]
    result += [float(p in observed.known_evil) for p in order]
    result += [float(p in (observed.pair or ())) for p in order]
    result += [masses.get(a, 0.0) for a in ASSIGNMENTS]
    result += [float(p in state["team"]) for p in order]
    result += [float(p == state["leader"]) for p in order]
    for name, scale in zip(COUNTERS, SCALES, strict=True):
        if type(state[name]) is not int or state[name] < 0:
            raise ValueError("public counters must be nonnegative integers")
        result.append(state[name] / scale)
    result += [float(state["phase"] == p) for p in PHASES]
    result += [float(state["discussion_kind"] == p) for p in DISCUSSIONS]
    result += [float(ability == a) for a in ABILITIES]
    proposals = {p.epoch: p for p in observed.proposals}
    ballots = {b.epoch: b for b in observed.ballots}
    for epoch in range(1, 26):
        proposal, ballot = proposals.get(epoch), ballots.get(epoch)
        result += [float(proposal is not None)]
        result += [float(proposal is not None and proposal.leader == p) for p in order]
        result += [float(proposal is not None and p in proposal.team) for p in order]
        result += [float(ballot is not None)]
        result += [float(ballot is not None and p in ballot.approve) for p in order]
    for i in range(5):
        quest = observed.quests[i] if i < len(observed.quests) else None
        result += [float(quest is not None), 0.0 if quest is None else quest.epoch / 25]
        result += [float(quest is not None and p in quest.team) for p in order]
        result += [0.0 if quest is None else quest.fails / 2]
    # Counts use every received record, but intentionally do not encode speech order/rationale.
    for p in order:
        for role in ROLES:
            result.append(
                sum(c.speaker == p and c.role == role and role != "merlin" for c in observed.claims)
                / 25
            )
    advice = {}
    for row in observed.advice:
        team = sum(1 << relative(p, who) for p in row.team)
        key = row.speaker, team, row.approve
        advice[key] = advice.get(key, 0) + 1
    result += [
        advice.get((p, team, yes), 0) / 25
        for p in order
        for team in range(32)
        for yes in (False, True)
    ]
    if len(result) != len(OBSERVATIONS):
        raise ValueError("stateless feature width differs from its schema")
    return tuple(result)


def frame(observed, belief, state, ability, options, *, observer, episode, basis):
    """Options are supplied by runtime choice pools, never generated by the neural model."""
    candidates = tuple(
        LearningCandidate(str(i), action_features(ability, values, observed.observer), 0.0)
        for i, values in enumerate(options)
    )
    return DecisionFrame(
        SCHEMA, observer, episode, basis, encode(observed, belief, state, ability), candidates
    )
