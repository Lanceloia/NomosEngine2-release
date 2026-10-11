"""Build an educational narration/player from a storyboard and saved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/showcase/introduction"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_storyboard(path: Path) -> dict:
    board = json.loads(path.read_text(encoding="utf-8"))
    ids = set()
    for scene in board["scenes"]:
        if not scene["id"] or scene["id"] in ids or not scene["lines"]:
            raise ValueError("Scenes need distinct IDs and narration")
        ids.add(scene["id"])
        for line in scene["lines"]:
            if not isinstance(line["text"], str) or not line["text"].strip():
                raise ValueError("Empty narration")
    return board


def join_audio(paths: list[Path], output: Path) -> list[tuple[float, float]]:
    """Keep a small lead-in and silence between sentences in the same PCM track."""
    intervals = []
    with wave.open(str(paths[0]), "rb") as first:
        fmt = (first.getnchannels(), first.getsampwidth(), first.getframerate())
    channels, width, rate = fmt
    frame = channels * width
    cursor = 0
    with wave.open(str(output), "wb") as joined:
        joined.setnchannels(channels)
        joined.setsampwidth(width)
        joined.setframerate(rate)

        def silence(seconds: float) -> None:
            nonlocal cursor
            size = round(seconds * rate)
            joined.writeframes(b"\0" * size * frame)
            cursor += size

        silence(0.6)
        for path in paths:
            with wave.open(str(path), "rb") as clip:
                if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) != fmt:
                    raise ValueError("Narration clips have inconsistent PCM formats")
                start = cursor / rate
                size = clip.getnframes()
                joined.writeframes(clip.readframes(size))
                cursor += size
                intervals.append((start, cursor / rate))
            silence(0.5)
        silence(0.8)
    return intervals


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    whole, ms = divmod(millis, 1000)
    mins, secs = divmod(whole, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02}:{mins:02}:{secs:02},{ms:03}"


def assemble(board: dict, intervals: list[tuple[float, float]], output: Path) -> None:
    flat = [line for scene in board["scenes"] for line in scene["lines"]]
    if len(flat) != len(intervals):
        raise ValueError("Narration and timing counts differ")
    subtitles = []
    for index, (line, (start, end)) in enumerate(zip(flat, intervals, strict=True), 1):
        line.update(start=start, end=end)
        subtitles.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{line['text']}\n")
    for scene in board["scenes"]:
        scene["start"] = scene["lines"][0]["start"]
        scene["end"] = scene["lines"][-1]["end"]
    board["duration"] = intervals[-1][1] + 1.3
    template = (SOURCE / "player.html").read_text(encoding="utf-8")
    serialized = json.dumps(board, ensure_ascii=False).replace("<", "\\u003c")
    (output / "index.html").write_text(
        template.replace("__INTRODUCTION__", serialized), encoding="utf-8"
    )
    shutil.copytree(SOURCE / "font", output / "font")
    (output / "timeline.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "subtitles.srt").write_text("\n".join(subtitles), encoding="utf-8")
    transcript = "# 中文项目介绍：讲稿与分镜\n\n"
    for scene in board["scenes"]:
        transcript += f"## {scene['title']}\n\n{scene['tag']}\n\n"
        transcript += "\n\n".join(line["text"] for line in scene["lines"]) + "\n\n"
    (output / "TRANSCRIPT.md").write_text(transcript.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    output = args.directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    board = checked_storyboard(SOURCE / "storyboard.json")
    text_dir = output / "speech"
    text_dir.mkdir()
    flat = [line for scene in board["scenes"] for line in scene["lines"]]
    for index, line in enumerate(flat):
        (text_dir / f"{index:02}.txt").write_text(line["text"], encoding="utf-8-sig")
    # Use the installed Windows voice locally. No text is sent to a TTS service.
    powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    windows_dir = subprocess.run(
        ["wslpath", "-w", str(text_dir)], check=True, capture_output=True, text=True
    ).stdout.strip()
    script = """param([string]$Directory,[string]$Voice,[int]$Rate)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($Voice)
$s.Rate = $Rate
try {
  Get-ChildItem -LiteralPath $Directory -Filter '*.txt' | Sort-Object Name | ForEach-Object {
    $s.SetOutputToWaveFile([IO.Path]::ChangeExtension($_.FullName, '.wav'))
    $s.Speak([IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8))
    $s.SetOutputToNull()
  }
} finally { $s.Dispose() }
"""

    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    command = "& {" + script + "} " + literal(windows_dir)
    command += " " + literal(board["voice"]) + " " + str(board["rate"])
    subprocess.run([str(powershell), "-NoProfile", "-Command", command], check=True, timeout=180)
    paths = sorted(text_dir.glob("*.wav"))
    if len(paths) != len(flat):
        raise ValueError("Voice synthesis did not produce every sentence")
    intervals = join_audio(paths, output / "narration.wav")
    assemble(board, intervals, output)
    shutil.rmtree(text_dir)
    inputs = [
        SOURCE / "storyboard.json",
        SOURCE / "player.html",
        Path(__file__),
        ROOT / "docs/showcase/recording/capture-v1/comparison.json",
        ROOT / "docs/showcase/wolf-vote/evidence-predicates-v1/result.json",
        ROOT / "docs/showcase/world-edits/evidence-predicates-v1/result.json",
        *sorted((SOURCE / "font").iterdir()),
    ]
    manifest = {
        "kind": "educational summary, not an execution capture",
        "voice": board["voice"],
        "rate": board["rate"],
        "synthesis": "local Windows System.Speech",
        "duration_seconds": board["duration"],
        "inputs_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
        "outputs_sha256": {
            str(path.relative_to(output)): digest(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
        "note": (
            "Saved evidence is summarized, not rerun. SHA256 identifies bytes; "
            "it is not a signature. No engine or world changes."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built {output}, {board['duration']:.1f} seconds")


if __name__ == "__main__":
    main()
