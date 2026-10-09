"""The documentation media must be backed by the checked real experiment report."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "docs/showcase"
SPEC = importlib.util.spec_from_file_location("showcase_render", MEDIA / "render.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


def report():
    return json.loads((MEDIA / "result.json").read_text(encoding="utf-8"))


def test_recorded_actual_report_supports_the_claim():
    RENDER.validate_report(report())


@pytest.mark.parametrize("fault", ["changed_source", "fake_count", "wrong_step", "no_success"])
def test_unsupported_claim_is_rejected(fault):
    value = deepcopy(report())
    if fault == "changed_source":
        value["edited"]["published"][0]["source"] = "not-the-recorded-source"
    elif fault == "fake_count":
        value["unchanged_published_prefix"] = 13
    elif fault == "wrong_step":
        value["edited"]["requested_step"] = 9
    else:
        value["original"]["goal_status"] = "unknown"
    with pytest.raises(ValueError, match="does not support"):
        RENDER.validate_report(value)


def test_manifest_digest_matches_recorded_bytes():
    manifest = json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((MEDIA / "result.json").read_bytes()).hexdigest() == (
        manifest["result_sha256"]
    )
    # This is a reproduction digest, not an authenticated issuer signature.
    fingerprint, entries = RENDER.code_fingerprint(ROOT)
    assert fingerprint == manifest["code_and_inputs_sha256"]
    assert entries == manifest["file_sha256"]
