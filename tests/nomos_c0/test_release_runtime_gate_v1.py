"""Performance gates classify evidence, not world success or correctness."""

import argparse
import json
import os
from copy import deepcopy
from hashlib import sha256

import pytest

from tools import release_runtime_gate as gate
from tools.release_runtime_gate import assess_report, comparable, main, positive_count, verdict


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [
        ([1.0] * 8, "passed"),
        ([1.10] * 8, "passed"),
        ([1.11] * 8, "regressed"),
        ([1.0] * 6 + [1.4, 1.5], "passed"),
        ([1.0] * 5 + [1.11] * 3, "regressed"),
        ([0.8, 1.10] * 4, "passed"),
    ],
)
def test_gate_uses_approved_budget_and_noise_is_not_a_veto(ratios, expected):
    assert verdict(ratios) == expected


@pytest.mark.parametrize(
    "ratios", [[1] * 4, [1] * 9, [0] * 8, [float("nan")] * 8, [float("inf")] * 8]
)
def test_gate_requires_eight_finite_positive_ratios(ratios):
    with pytest.raises(ValueError, match="exactly eight finite positive"):
        verdict(ratios)


def sample_row(sample, seconds=1):
    if sample == "parcel":
        return {"digests": ["same"] * 2, "sessions_per_pair": 2, "run_seconds": seconds}
    row = {"state_digest": "same", "occurrences": 3, "time": 2, "run_seconds": seconds}
    if sample == "short":
        row |= {
            "inputs": [],
            "assets_digest": "same",
            "action_value_history": [],
            "appraisal_digest": "same",
        }
    else:
        row |= {"actions": [], "history_digest": "same"}
    return row


def saved_report():
    return {
        "input_fingerprint": {"source": "bytes"},
        "parcel_sessions_per_pair": 2,
        "builds": [{"input_fingerprint": {"source": "bytes"}, "parcel_sessions_per_pair": 2}] * 2,
        "cores": [{"commit": "baseline"}, {"commit": "measured-candidate"}],
        "samples": {
            sample: {
                "status": "inconclusive",
                "pairs": [
                    {
                        "order": [0, 1] if index % 2 == 0 else [1, 0],
                        "baseline": sample_row(sample),
                        "candidate": sample_row(sample, ratio),
                    }
                    for index, ratio in enumerate([1] * 6 + [1.3, 1.4])
                ],
            }
            for sample in ("short", "parcel")
        },
    }


def test_saved_assessment_rechecks_semantics_and_preserves_original_results():
    evidence = saved_report()
    original = deepcopy(evidence)
    result = assess_report(evidence)
    assert evidence == original
    assert result["samples"]["short"]["status"] == "passed"
    assert result["samples"]["short"]["original_status"] == "inconclusive"
    assert result["samples"]["short"]["noise_warning"] is True
    assert result["measured_cores"][1]["commit"] == "measured-candidate"
    assert result["full"] == "not_assessed"
    evidence["samples"]["short"]["pairs"][0]["candidate"]["state_digest"] = "wrong"
    with pytest.raises(RuntimeError, match="semantic difference"):
        assess_report(evidence)


def test_saved_assessment_rejects_different_author_inputs_and_truncated_pairs():
    evidence = saved_report()
    evidence["builds"] = [{"input_fingerprint": {"source": "changed"}}] * 2
    with pytest.raises(ValueError, match="identical author bytes"):
        assess_report(evidence)
    evidence = saved_report()
    evidence["samples"]["parcel"]["pairs"].pop()
    with pytest.raises(ValueError, match="exactly eight"):
        assess_report(evidence)


@pytest.mark.parametrize("change", ["pair", "build", "report", "invalid_count"])
def test_saved_assessment_rejects_workload_that_disagrees_with_declarations(change):
    evidence = saved_report()
    if change == "pair":
        pair = evidence["samples"]["parcel"]["pairs"][0]
        for variant in ("baseline", "candidate"):
            pair[variant]["sessions_per_pair"] = 1
            pair[variant]["digests"] = ["same"]
    elif change == "build":
        evidence["builds"] = deepcopy(evidence["builds"])
        evidence["builds"][0]["parcel_sessions_per_pair"] = 1
    elif change == "report":
        evidence["parcel_sessions_per_pair"] = 1
    else:
        evidence["parcel_sessions_per_pair"] = 0
    with pytest.raises(ValueError, match="workload"):
        assess_report(evidence)


def test_saved_cli_does_not_start_workers_or_overwrite_evidence(monkeypatch, tmp_path, capsys):
    evidence = tmp_path / "original.json"
    output = tmp_path / "assessment.json"
    contents = json.dumps(saved_report()).encode()
    evidence.write_bytes(contents)
    monkeypatch.setattr(gate, "CoreWorker", lambda *a, **kw: pytest.fail("must not start a worker"))
    monkeypatch.setattr(
        "sys.argv", ["gate", "--assess-report", str(evidence), "--output", str(output)]
    )
    main()
    assessment = json.loads(output.read_text())
    assert assessment["evidence_sha256"] == sha256(contents).hexdigest()
    assert evidence.read_bytes() == contents
    assert assessment == json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        "sys.argv", ["gate", "--assess-report", str(evidence), "--output", str(evidence)]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert evidence.read_bytes() == contents
    alias = tmp_path / "alias.json"
    os.link(evidence, alias)
    monkeypatch.setattr(
        "sys.argv", ["gate", "--assess-report", str(evidence), "--output", str(alias)]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert evidence.read_bytes() == contents


@pytest.mark.parametrize(
    "full_ratio, short_ratio, exit_code", [(1.1, 1, 0), (1.11, 1, 3), (1, 1.11, 2)]
)
def test_measurement_has_fixed_pairs_and_full_uses_ten_percent_budget(
    monkeypatch, tmp_path, capsys, full_ratio, short_ratio, exit_code
):
    calls = []

    class Worker:
        ready = {"input_fingerprint": {}, "parcel_sessions_per_pair": 256}

        def __init__(self, core, *args, **kwargs):
            self.candidate = core.name == "candidate"

        def measure(self, sample):
            calls.append((self.candidate, sample))
            ratio = full_ratio if sample == "full" else short_ratio
            return sample_row(sample, ratio if self.candidate else 1)

        def close(self):
            pass

    output = tmp_path / "measurement.json"
    monkeypatch.setattr(gate, "CoreWorker", Worker)
    monkeypatch.setattr(gate, "input_fingerprint", lambda *args: {})
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *args, **kwargs: "fake")
    monkeypatch.setattr(
        "sys.argv",
        [
            "gate",
            "--baseline",
            str(tmp_path / "baseline"),
            "--candidate",
            str(tmp_path / "candidate"),
            "--bundle",
            "unused",
            "--resources",
            "unused",
            "--output",
            str(output),
            "--full",
        ],
    )
    if exit_code:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == exit_code
    else:
        main()
    report = json.loads(output.read_text())
    assert all(len(row["pairs"]) == 8 for row in report["samples"].values())
    assert calls.count((False, "short")) == calls.count((True, "short")) == 8
    assert calls.count((False, "parcel")) == calls.count((True, "parcel")) == 8
    assert (
        calls.count((False, "full")) == calls.count((True, "full")) == (0 if exit_code == 2 else 1)
    )


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


@pytest.mark.parametrize("sample", ["short", "parcel"])
def test_full_gate_rejects_a_missing_short_gate_before_starting_workers(
    monkeypatch, capsys, sample
):
    monkeypatch.setattr(
        "sys.argv",
        ["gate", "--bundle", "unused.yaml", "--resources", "unused", "--sample", sample, "--full"],
    )
    monkeypatch.setattr(
        "tools.release_runtime_gate.CoreWorker",
        lambda *args, **kwargs: pytest.fail("invalid full gate must not start a worker"),
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "full gate requires both short and parcel samples" in capsys.readouterr().err
