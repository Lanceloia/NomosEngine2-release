"""Owner-selected terminal ordering for the explicit forced-fifth training ruleset."""

import math

from nomos_cognition.learning import LearningSchema

from . import decision

SCHEMA = LearningSchema(
    "avalon.stateless.forced-fifth-graded.v2",
    decision.OBSERVATIONS,
    decision.ACTIONS,
    ("outcome_grade", "cooperation", "concealment", "graded_score"),
)
CONFIG = {
    "ruleset": "avalon.training.forced-fifth.v1",
    "grades": {
        "failed_round_3": -1.0,
        "failed_round_4": -0.5,
        "failed_round_5": 0.0,
        "merlin_found": 0.5,
        "merlin_survived": 1.0,
    },
    "weights": {"outcome_grade": 0.8, "cooperation": 0.1, "concealment": 0.1},
}


def outcome_name(game):
    """Classify the existing Owner-selected ending order without auxiliary feedback."""
    if game["reason"] == "three_failed_tasks":
        rounds = len(game["quests"])
        if (
            game["failures"] != 3
            or rounds not in (3, 4, 5)
            or game["successes"] != rounds - 3
            or game["winner"] != "evil"
        ):
            raise ValueError("task-failure grade needs a consistent actual terminal")
        name = f"failed_round_{rounds}"
    elif game["reason"] in ("merlin_found", "merlin_survived"):
        if game["successes"] != 3 or game["winner"] != (
            "evil" if game["reason"] == "merlin_found" else "good"
        ):
            raise ValueError("assassination grade needs a consistent actual terminal")
        name = game["reason"]
    else:
        raise ValueError("unsupported terminal in the forced-fifth training ruleset")
    return name


def outcome_grade(game):
    return CONFIG["grades"][outcome_name(game)]


def feedback(game, cooperation, concealment):
    if (
        any(type(v) not in (float, int) or not math.isfinite(v) for v in (cooperation, concealment))
        or not -1 <= cooperation <= 1
        or not 0 <= concealment <= 1
    ):
        raise ValueError("graded bonuses require bounded actual feedback")
    grade = outcome_grade(game)
    return (grade, cooperation, concealment, 0.8 * grade + 0.1 * cooperation + 0.1 * concealment)
