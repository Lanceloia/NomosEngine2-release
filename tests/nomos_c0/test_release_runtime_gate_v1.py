"""Performance gates classify evidence, not world success or correctness."""

import pytest

from tools.release_runtime_gate import comparable, verdict


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [
        ([1.0] * 4, "passed"),
        ([1.06] * 4, "regressed"),
        ([1.0, 1.01, 1.02, 1.06], "passed"),
        ([1.0, 1.0, 1.06, 1.06], "regressed"),
        ([0.9, 1.05, 0.9, 1.05], "noisy"),
        ([0.9, 1.05] * 4, "inconclusive"),
    ],
)
def test_gate_uses_predeclared_median_count_and_noise_rules(ratios, expected):
    assert verdict(ratios) == expected


def test_state_or_provenance_difference_cannot_pass_on_speed():
    before = {
        "state_digest": "same",
        "occurrences": 3,
        "time": 2,
        "inputs": [],
        "assets_digest": "same",
        "action_value_history": [],
        "appraisal_digest": "same",
        "run_seconds": 10,
    }
    comparable("short", before, before | {"run_seconds": 1})
    for field, value in (
        ("state_digest", "other"),
        ("occurrences", 4),
        ("time", 3),
        ("inputs", ["other"]),
        ("assets_digest", "other"),
    ):
        with pytest.raises(RuntimeError, match="semantic difference"):
            comparable("short", before, before | {field: value, "run_seconds": 1})
