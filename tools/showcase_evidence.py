"""Check stored experiment evidence without rendering or running a world."""

from __future__ import annotations

import hashlib
import json


def validate_report(report):
    before, after = report["original"], report["edited"]
    prefix = after["published"]
    if not (
        report["files_modified"] is False
        and report["same_assets_and_witness"] is True
        and before["stage"] == after["stage"] == "run"
        and before["goal_status"] == "met"
        and before["steps_completed"] == 10
        and after["goal_status"] == "not_met_within_bound"
        and after["stop_reason"] == "k0_not_admitted"
        and after["steps_completed"] == 9
        and after["requested_step"] == 10
        and len(prefix) == report["unchanged_published_prefix"] == 12
        and before["published"][:len(prefix)] == prefix
        and [(row["family"], row["source"]) for row in before["published"][len(prefix):]]
        == [("action", "c0.six-seat.witch-b"),
            ("event", "c0.six-seat.resolve-after-witch-b")]
    ):
        raise ValueError("actual report does not support the documented showcase")


def load_recorded_report(directory):
    raw = (directory / "result.json").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != manifest["result_sha256"]:
        raise ValueError("stored report does not match its capture digest")
    report = json.loads(raw)
    validate_report(report)
    return report, manifest
