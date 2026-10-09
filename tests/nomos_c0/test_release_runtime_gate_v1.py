"""Performance gates classify evidence, not world success or correctness."""

import argparse

import pytest

from tools.release_runtime_gate import comparable, positive_count, verdict


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


def test_parcel_aggregate_compares_every_fresh_session_and_fixed_workload():
    before = {"digests": ["same"] * 256, "sessions_per_pair": 256, "run_cpu_seconds": 1}
    comparable("parcel", before, before | {"run_cpu_seconds": 0.1})
    with pytest.raises(RuntimeError, match="incomplete aggregate"):
        comparable("parcel", before, before | {"digests": ["same"] * 255})
    with pytest.raises(RuntimeError, match="semantic difference"):
        comparable("parcel", before, before | {"digests": ["same"] * 255 + ["other"]})
    with pytest.raises(RuntimeError, match="semantic difference"):
        comparable("parcel", before, before | {"digests": ["same"] * 32, "sessions_per_pair": 32})


def test_repetition_parameter_is_fixed_positive_not_adaptive():
    assert positive_count("256") == 256
    for value in ("0", "-1", "many"):
        with pytest.raises((ValueError, argparse.ArgumentTypeError)):
            positive_count(value)
