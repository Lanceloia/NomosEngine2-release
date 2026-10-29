"""Versioned per-game priority reward with bounded secondary credit and missing masks."""

import math

from . import graded

SCHEMA = "nomos.avalon.priority-reward.v53"
CONFIG = {
    "schema": SCHEMA,
    "ruleset": graded.CONFIG["ruleset"],
    "grades": {
        "failed_round_3": -2.0,
        "failed_round_4": -1.5,
        "failed_round_5": -1.0,
        "merlin_found": 0.0,
        "merlin_survived": 2.0,
    },
    "weights": {"outcome_grade": 1.0, "cooperation": 0.1, "concealment": 0.1},
    "accumulation_unit": "one completed game; no per-action reward sum",
    "secondary_total_bounds": [-0.1, 0.2],
    "minimum_primary_margin": 0.2,
    "missing_assassination_feedback": "unknown total interval; never a zero target",
}


def bands():
    """Conservative bounds even if every secondary term reaches its opposite extreme."""
    rows = [
        {
            "ending": name,
            "grade": grade,
            "base": grade,
            "minimum": grade - 0.1,
            "maximum": grade + 0.2,
        }
        for name, grade in CONFIG["grades"].items()
    ]
    if any(
        b["minimum"] - a["maximum"] < CONFIG["minimum_primary_margin"] - 1e-12
        for a, b in zip(rows, rows[1:])
    ):
        raise ValueError("secondary budget may overturn primary ending order")
    return rows


def feedback(game, cooperation, concealment):
    """No opportunity is distinct from an opportunity whose feedback is unavailable."""
    if (
        type(cooperation) not in (int, float)
        or not math.isfinite(cooperation)
        or not -1 <= cooperation <= 1
    ):
        raise ValueError("cooperation must be normalized once per game to [-1,1]")
    if concealment is not None and (
        type(concealment) not in (int, float)
        or not math.isfinite(concealment)
        or not 0 <= concealment <= 1
    ):
        raise ValueError("concealment must be bounded actual feedback or None")
    successes, failures = game["successes"], game["failures"]
    if (
        any(type(v) is not int or not 0 <= v <= 3 for v in (successes, failures))
        or (successes == 3) == (failures == 3)
        or len(game["quests"]) != successes + failures
    ):
        raise ValueError("priority reward needs consistent terminal counters")
    name = graded.outcome_name(game)
    grade = CONFIG["grades"][name]
    attack = game["attack"] is not None
    if attack != (successes == 3):
        raise ValueError("ending and assassination opportunity disagree")
    if not attack and concealment is not None:
        raise ValueError("task failure has no assassination concealment observation")
    bands()
    base, cooperation_part = grade, 0.1 * cooperation
    missing = attack and concealment is None
    concealment_part = None if concealment is None else 0.1 * concealment
    lower = base + cooperation_part + (concealment_part or 0.0)
    upper = lower + (0.1 if missing else 0.0)
    return {
        "schema": SCHEMA,
        "ending": name,
        "outcome_grade": grade,
        "primary": base,
        "cooperation": cooperation,
        "concealment": concealment,
        "secondary": {"cooperation": cooperation_part, "concealment": concealment_part},
        "concealment_status": "not_applicable"
        if not attack
        else "missing"
        if missing
        else "observed",
        "complete": not missing,
        "total": None if missing else lower,
        "bounds": [lower, upper],
        "secondary_bounds": [-0.1, 0.2],
    }
