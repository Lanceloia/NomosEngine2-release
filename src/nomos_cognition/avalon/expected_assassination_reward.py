"""Owner-approved soft assassination payoff, with the actual winner kept separate."""

import math

from . import graded

SCHEMA = "nomos.avalon.expected-assassination-reward.v1"
CONFIG = {
    "schema": SCHEMA,
    "ruleset": graded.CONFIG["ruleset"],
    "failed_round_grades": {"failed_round_3": -2.0, "failed_round_4": -1.5, "failed_round_5": -1.0},
    "assassination_payoffs": {"merlin_found": 0.0, "merlin_survived": 2.0},
    "probability_source": "frozen formal assassin posterior on true Merlin; not empirical hit rate",
    "cooperation_weight": 0.1,
    "separate_concealment_bonus": False,
    "accumulation_unit": "one completed game; no per-action reward sum",
    "secondary_total_bounds": [-0.1, 0.1],
    "missing_probability": "unknown interval; never a zero point target",
    "actual_winner_unchanged": True,
}


def feedback(game, cooperation, true_merlin_probability):
    if (
        type(cooperation) not in (int, float)
        or not math.isfinite(cooperation)
        or not -1 <= cooperation <= 1
    ):
        raise ValueError("cooperation must be a finite per-game value in [-1,1]")
    p = true_merlin_probability
    if p is not None and (type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1):
        raise ValueError("assassin probability must be finite in [0,1] or unknown")
    successes, failures = game["successes"], game["failures"]
    if (
        any(type(v) is not int or not 0 <= v <= 3 for v in (successes, failures))
        or (successes == 3) == (failures == 3)
        or len(game["quests"]) != successes + failures
    ):
        raise ValueError("soft payoff requires consistent actual terminal counters")
    ending = graded.outcome_name(game)
    attack = game["attack"] is not None
    if attack != (successes == 3) or (not attack and p is not None):
        raise ValueError("probability opportunity differs from the actual terminal")
    secondary = CONFIG["cooperation_weight"] * cooperation
    if not attack:
        primary = CONFIG["failed_round_grades"][ending]
        low = high = primary + secondary
        status = "not_applicable"
    elif p is None:
        primary = None
        low, high = secondary, 2.0 + secondary
        status = "missing"
    else:
        primary = (1 - p) * CONFIG["assassination_payoffs"]["merlin_survived"] + p * CONFIG[
            "assassination_payoffs"
        ]["merlin_found"]
        low = high = primary + secondary
        status = "observed"
    return {
        "schema": SCHEMA,
        "actual_ending": ending,
        "actual_winner": game["winner"],
        "primary": primary,
        "cooperation": cooperation,
        "true_merlin_probability": p,
        "assassination_status": status,
        "secondary": {"cooperation": secondary},
        "complete": status != "missing",
        "total": None if status == "missing" else low,
        "bounds": [low, high],
        "secondary_bounds": [-0.1, 0.1],
    }
