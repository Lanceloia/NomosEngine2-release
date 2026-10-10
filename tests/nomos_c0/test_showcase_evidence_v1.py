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


def test_reuse_validates_stored_bytes_before_rendering(tmp_path):
    raw = (MEDIA / "result.json").read_bytes()
    (tmp_path / "result.json").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(json.dumps({"result_sha256": "wrong"}))
    with pytest.raises(ValueError, match="capture digest"):
        RENDER.load_recorded_report(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "result_sha256": hashlib.sha256(raw).hexdigest(),
    }))
    value, _ = RENDER.load_recorded_report(tmp_path)
    assert value == report()


def test_request_moves_before_publication_then_final_state_holds():
    states = [RENDER.animation_state(time) for time in (6, 6.5, 7, 8)]
    positions = [state["request_y"] for state in states]
    assert positions == sorted(set(positions))
    assert positions[0] == 416 and positions[-1] == 476
    assert all(state["decision"] == state["outcome"] == state["event"] == 0
               for state in states)
    assert RENDER.animation_state(11.5)["outcome"] == 1
    assert RENDER.animation_state(11.5)["event"] == 0
    assert RENDER.animation_state(17) == RENDER.animation_state(21.9)
    assert RENDER.animation_state(22.5)["reset"] == 1


def test_animation_metadata_matches_checked_report_and_published_media():
    metadata = json.loads((MEDIA / "animation.json").read_text(encoding="utf-8"))
    assert metadata["report_sha256"] == RENDER.digest(MEDIA / "result.json")
    assert metadata["renderer_sha256"] == RENDER.digest(MEDIA / "render.py")
    assert metadata["gif_duration_ms"] == 23000
    assert metadata["gif_frames"] > 30
    assert metadata["static_final_state_seconds"] == [17, 22]
    for name, expected in metadata["files_sha256"].items():
        assert RENDER.digest(MEDIA / name) == expected
    for _, left, top, right, bottom in metadata["text_bounds"]:
        assert 0 <= left < right <= 1280
        assert 0 <= top < bottom <= 720
