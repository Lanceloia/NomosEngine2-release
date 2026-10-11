"""Presentation contracts without replaying engine worlds."""

from __future__ import annotations

import json
import wave

import pytest

from tools import build_project_introduction as intro
from tools.narrate_showcase_recording import place_clips


def write_wave(path, frames, rate=1000):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\1\0" * frames)


def test_audio_timeline_matches_pcm_and_pauses(tmp_path):
    paths = [tmp_path / "one.wav", tmp_path / "two.wav"]
    write_wave(paths[0], 1000)
    write_wave(paths[1], 2000)
    output = tmp_path / "joined.wav"
    intervals = intro.join_audio(paths, output)
    assert intervals == [(0.6, 1.6), (2.1, 4.1)]
    with wave.open(str(output), "rb") as audio:
        assert audio.getnframes() / audio.getframerate() == 5.4


def test_audio_rejects_mismatched_formats(tmp_path):
    one, two = tmp_path / "one.wav", tmp_path / "two.wav"
    write_wave(one, 1000)
    write_wave(two, 1000, rate=2000)
    with pytest.raises(ValueError, match="inconsistent"):
        intro.join_audio([one, two], tmp_path / "joined.wav")


def test_render_embeds_data_safely_and_emits_timed_subtitles(tmp_path):
    board = {
        "scenes": [
            {"title": "test", "tag": "test", "lines": [{"text": "</script><script>bad</script>"}]}
        ]
    }
    intro.assemble(board, [(0.6, 2.0)], tmp_path)
    page = (tmp_path / "index.html").read_text()
    assert "__INTRODUCTION__" not in page
    assert "</script><script>bad</script>" not in page
    assert "00:00:00,600 --> 00:00:02,000" in (tmp_path / "subtitles.srt").read_text()
    assert json.loads((tmp_path / "timeline.json").read_text())["duration"] == 3.3
    assert 'url("font/nomos-introduction-sc.woff2")' in page
    for name in ("nomos-introduction-sc.woff2", "OFL.txt", "README.md"):
        assert (tmp_path / "font" / name).read_bytes() == (intro.SOURCE / "font" / name).read_bytes()


def test_storyboard_and_player_cover_each_declared_visual():
    board = intro.checked_storyboard(intro.SOURCE / "storyboard.json")
    page = (intro.SOURCE / "player.html").read_text()
    for scene in board["scenes"]:
        assert f"{scene['visual']}: () =>" in page
    assert "候选仍然存在" in json.dumps(board, ensure_ascii=False)
    assert "尚未实现" in json.dumps(board, ensure_ascii=False)


def test_duplicate_scene_identity_rejected(tmp_path):
    path = tmp_path / "bad.json"
    scene = {"id": "a", "lines": [{"text": "test"}]}
    path.write_text(json.dumps({"scenes": [scene, scene]}))
    with pytest.raises(ValueError, match="distinct"):
        intro.checked_storyboard(path)


def test_commentary_positions_and_total_duration(tmp_path):
    one, two = tmp_path / "one.wav", tmp_path / "two.wav"
    write_wave(one, 1000)
    write_wave(two, 2000)
    output = tmp_path / "track.wav"
    intervals = place_clips([one, two], [2, 6], [4, 9], output, 10)
    assert intervals == [(2, 3), (6, 8)]
    with wave.open(str(output), "rb") as track:
        assert track.getnframes() / track.getframerate() == 10


def test_commentary_cannot_spill_into_next_chapter(tmp_path):
    clip = tmp_path / "clip.wav"
    write_wave(clip, 4000)
    with pytest.raises(ValueError, match="exceeds chapter"):
        place_clips([clip], [2], [5], tmp_path / "track.wav", 10)


def test_saved_reports_support_the_three_experiment_summaries():
    showcase = intro.ROOT / "docs/showcase"
    comparison = json.loads((showcase / "recording/capture-v1/comparison.json").read_text())
    assert comparison["equal_published_prefix"] == 12
    assert comparison["candidate_still_present"] is True
    assert comparison["refusal_snapshot_before"] == comparison["refusal_snapshot_after"]
    vote = json.loads((showcase / "wolf-vote/evidence-predicates-v1/result.json").read_text())
    assert vote["same_assets_and_requests"] is True
    assert vote["equal_opening_and_first_nine_steps"] is True
    for version, dead in (("unanimous", []), ("majority", ["F"])):
        steps = vote["versions"][version]["steps"]
        assert len(steps) == 10
        players = steps[-1]["scene"]["players"]
        assert [player["id"] for player in players if not player["alive"]] == dead
    world = json.loads((showcase / "world-edits/evidence-predicates-v1/result.json").read_text())
    assert world["role_move"]["witch_E"]["B_candidate_check"]["offer_found"] is False
    assert list(world["size_change"]["eight"]["opening"]["seats"]) == list("ABCDEFGH")
