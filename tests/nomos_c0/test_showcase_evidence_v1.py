"""The documented claims must be backed by the checked experiment report."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tools.showcase_evidence import load_recorded_report, validate_report

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "docs/showcase"


def report():
    return json.loads((MEDIA / "result.json").read_text(encoding="utf-8"))


def test_recorded_actual_report_supports_the_claim():
    validate_report(report())


def test_current_predicate_report_preserves_published_records():
    directory = MEDIA / "self-heal-predicates-v1"
    raw = (directory / "result.json").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == manifest["result_sha256"]
    current = json.loads(raw)
    validate_report(current)
    previous = report()
    for version in ("original", "edited"):
        assert current[version]["published"] == previous[version]["published"]
        assert current[version]["goal_status"] == previous[version]["goal_status"]


@pytest.mark.parametrize("fault", [
    "changed_source", "fake_count", "wrong_step", "no_success", "wrong_action", "extra_event",
])
def test_unsupported_claim_is_rejected(fault):
    value = deepcopy(report())
    if fault == "changed_source":
        value["edited"]["published"][0]["source"] = "not-the-recorded-source"
    elif fault == "fake_count":
        value["unchanged_published_prefix"] = 13
    elif fault == "wrong_step":
        value["edited"]["requested_step"] = 9
    elif fault == "no_success":
        value["original"]["goal_status"] = "unknown"
    elif fault == "wrong_action":
        value["original"]["published"][12]["source"] = "unproven-action"
    else:
        value["original"]["published"].append(value["original"]["published"][-1])
    with pytest.raises(ValueError, match="does not support"):
        validate_report(value)


def test_manifest_digest_matches_recorded_bytes():
    manifest = json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((MEDIA / "result.json").read_bytes()).hexdigest() == (
        manifest["result_sha256"]
    )
    # Historical evidence describes its captured checkout, not today's examples.
    # Hashes establish consistency, not an authenticated issuer signature.
    entries = manifest["file_sha256"]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == manifest["code_and_inputs_sha256"]
    captured = MEDIA / "historical-inputs/pre-predicate-cleanup"
    paths = list(captured.glob("*.yaml"))
    assert len(paths) == 3
    for path in paths:
        original = "src/nomos_c0/examples/" + path.name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entries[original]


def test_loading_validates_stored_report_bytes(tmp_path):
    raw = (MEDIA / "result.json").read_bytes()
    (tmp_path / "result.json").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(json.dumps({"result_sha256": "wrong"}))
    with pytest.raises(ValueError, match="capture digest"):
        load_recorded_report(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "result_sha256": hashlib.sha256(raw).hexdigest(),
    }))
    value, _ = load_recorded_report(tmp_path)
    assert value == report()
