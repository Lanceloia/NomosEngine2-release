"""Add local Mandarin commentary to an immutable, already recorded walkthrough."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

from tools.build_project_introduction import ROOT, digest, stamp


def inspect_duration(binary: str, path: Path) -> float:
    result = subprocess.run(
        [binary, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=10
    )
    found = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not found:
        raise ValueError("Cannot inspect source video duration")
    hours, minutes, seconds = map(float, found.groups())
    return hours * 3600 + minutes * 60 + seconds


def place_clips(paths, starts, limits, output, duration):
    with wave.open(str(paths[0]), "rb") as first:
        fmt = first.getnchannels(), first.getsampwidth(), first.getframerate()
    channels, width, rate = fmt
    intervals = []
    with wave.open(str(output), "wb") as joined:
        joined.setnchannels(channels)
        joined.setsampwidth(width)
        joined.setframerate(rate)
        cursor = 0
        for path, start, limit in zip(paths, starts, limits, strict=True):
            target = round(start * rate)
            if target < cursor:
                raise ValueError("Commentary overlaps previous chapter")
            joined.writeframes(b"\0" * (target - cursor) * channels * width)
            with wave.open(str(path), "rb") as clip:
                if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) != fmt:
                    raise ValueError("Inconsistent voice formats")
                frames = clip.getnframes()
                end = (target + frames) / rate
                if end > limit:
                    raise ValueError("Commentary exceeds chapter; shorten the script")
                joined.writeframes(clip.readframes(frames))
            cursor = target + frames
            intervals.append((target / rate, end))
        total = round(duration * rate)
        if cursor > total:
            raise ValueError("Commentary exceeds source video")
        joined.writeframes(b"\0" * (total - cursor) * channels * width)
    return intervals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("ffmpeg")
    parser.add_argument("font_directory", type=Path)
    args = parser.parse_args()
    output = args.directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "docs/showcase/recording/capture-v1"
    narration = ROOT / "docs/showcase/recording/narration.json"
    board = json.loads(narration.read_text(encoding="utf-8"))
    recording = json.loads((source / "recording.json").read_text())
    export = json.loads((source / "video-export.json").read_text())
    duration = inspect_duration(args.ffmpeg, source / "demo.webm")
    lead = max(0, duration - export["playback_seconds"])
    if len(board["chapters"]) != len(recording["chapters"]):
        raise ValueError("Recording and commentary chapter counts differ")
    speech = output / "speech"
    speech.mkdir()
    for index, text in enumerate(board["chapters"]):
        (speech / f"{index:02}.txt").write_text(text, encoding="utf-8-sig")
    windows_dir = (
        subprocess.run(["wslpath", "-w", str(speech)], check=True, text=True, capture_output=True)
        .stdout.strip()
        .replace("'", "''")
    )
    voice = board["voice"].replace("'", "''")
    rate = int(board["rate"])
    command = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');$s.Rate={rate};try{{"
        f"Get-ChildItem -LiteralPath '{windows_dir}' -Filter '*.txt' | Sort-Object Name | "
        "ForEach-Object {$s.SetOutputToWaveFile([IO.Path]::ChangeExtension($_.FullName,'.wav'));"
        "$s.Speak([IO.File]::ReadAllText($_.FullName,[Text.Encoding]::UTF8));$s.SetOutputToNull()}"
        "}finally{$s.Dispose()}"
    )
    subprocess.run(
        [
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-NoProfile",
            "-Command",
            command,
        ],
        check=True,
        timeout=120,
    )
    chapters = recording["chapters"]
    starts = [chapter["output_at"] + lead + 0.2 for chapter in chapters]
    limits = [chapter["start"] + lead - 0.2 for chapter in chapters[1:]] + [duration - 0.2]
    intervals = place_clips(
        sorted(speech.glob("*.wav")), starts, limits, output / "narration.wav", duration
    )
    subtitles = []
    for index, (text, (start, end)) in enumerate(zip(board["chapters"], intervals, strict=True), 1):
        # Put longer commentary on two lines inside the added subtitle band.
        if len(text) > 40:
            middle = len(text) // 2
            text = text[:middle] + "\n" + text[middle:]
        subtitles.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    (output / "subtitles.srt").write_text("\n".join(subtitles), encoding="utf-8")
    subtitle_filter = (
        "pad=iw:ih+110:0:0:color=0x171b1e,subtitles=filename='subtitles.srt':"
        f"fontsdir='{args.font_directory.resolve()}':"
        "force_style='Fontname=Noto Sans SC,Fontsize=19,MarginV=9,Outline=0'"
    )
    subprocess.run(
        [
            args.ffmpeg,
            "-hide_banner",
            "-i",
            str(source / "demo.webm"),
            "-i",
            str(output / "narration.wav"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output / "experiment.mp4"),
        ],
        cwd=output,
        check=True,
        capture_output=True,
        timeout=120,
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        "<title>真实实验 · 中文讲解版</title><style>body{margin:32px;background:#171b1e;"
        'color:#eef4f6;font:18px/1.7 "Microsoft YaHei",sans-serif}video{width:100%;'
        "max-height:80vh}a{color:#77e0c1}</style><h1>真实规则编辑实验 · 中文讲解</h1>"
        '<video controls preload="metadata" src="experiment.mp4"></video>'
        "<p>既有命令输出录像加合成中文旁白与字幕；没有重跑或模拟世界。"
        '<a href="../capture-v1/replay.html">原始分章回放</a></p></html>',
        encoding="utf-8",
    )
    shutil.rmtree(speech)
    inputs = [
        source / "demo.webm",
        source / "recording.json",
        source / "video-export.json",
        narration,
        Path(__file__),
    ]
    manifest = {
        "kind": "commentary derivative of an immutable execution recording",
        "duration_seconds": duration,
        "estimated_setup_seconds": lead,
        "voice": board["voice"],
        "synthesis": "local Windows System.Speech",
        "chapter_intervals": intervals,
        "inputs_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
        "outputs_sha256": {path.name: digest(path) for path in output.iterdir() if path.is_file()},
        "note": (
            "Original capture unchanged. Alignment estimated from its export timing; "
            "no new engine run. Font used locally, not redistributed."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Narrated {output}, {duration:.2f}s")


if __name__ == "__main__":
    main()
