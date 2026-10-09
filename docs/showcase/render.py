"""Render documented showcase media from a fresh, checked real demo report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


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
        and len(before["published"]) > len(prefix)
    ):
        raise ValueError("actual report does not support the documented showcase")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_fingerprint(root):
    files = [root / "tools/release_rule_edit_demo.py"]
    for folder in ("src/nomos_c0", "src/nomos_t0", "engine/kernel/src/nomos_kernel"):
        files.extend(p for p in (root / folder).rglob("*")
                     if p.suffix in (".py", ".yaml", ".json") and p.is_file())
    entries = {str(p.relative_to(root)): digest(p) for p in sorted(files)}
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), entries


def command(root, args, env=None):
    return subprocess.run(args, cwd=root, env=env, check=True, capture_output=True,
                          text=True, timeout=120).stdout


def render(report, manifest, font, mono, output):
    from PIL import Image, ImageDraw, ImageFont

    title = ImageFont.truetype(font, 40)
    body = ImageFont.truetype(font, 25)
    small = ImageFont.truetype(font, 19)
    code = ImageFont.truetype(mono, 23)
    original, edited = report["original"], report["edited"]

    def frame(number, heading):
        canvas = Image.new("RGB", (1280, 720), "#101619")
        draw = ImageDraw.Draw(canvas)
        draw.text((48, 32), "NOMOS ENGINE 2  /  RULE EDIT EXPERIMENT", font=code,
                  fill="#83d4de")
        draw.text((48, 92), heading, font=title, fill="#f3f6f7")
        draw.line((48, 610, 1232, 610), fill="#3b4a50", width=2)
        draw.text((48, 632), "实际运行报告可视化 · 非录屏 · 内存改规则，不改原文件",
                  font=small, fill="#c5d1d6")
        draw.text((48, 665), f"{manifest['code_revision'][:12]}  |  Python "
                  f"{manifest['python_version'].split()[0]}  |  {number}/4",
                  font=code, fill="#9aadb5")
        return canvas, draw

    frames = []
    image, draw = frame(1, "同一个开局，同一条十步行动见证")
    for y, line in zip((205, 262, 319, 400, 465), (
        "六席狼人杀：B 是女巫，也是本夜被袭击的人。",
        "第一版允许自救；第二版只增加一条救人条件。",
        "开局 Assets、行动见证、C0 / K0 执行器不变。",
        "不是修改结局文案，而是修改世界允许的行动。",
        "两版分别真实 Compile → Start → Run。",
    )):
        draw.text((48, y), line, font=body, fill="#e0e8eb")
    frames.append(image)

    image, draw = frame(2, "只改救人分支：女巫不能自救")
    draw.text((48, 205), "新增作者条件", font=body, fill="#e0e8eb")
    draw.rectangle((48, 264, 1232, 348), fill="#203238")
    draw.text((72, 287), "- not_self: actor.name != scene.pending_attack",
              font=code, fill="#9de7cf")
    draw.text((48, 402), "这条条件在女巫救人分支内，不限制放弃使用解药。",
              font=body, fill="#e0e8eb")
    draw.text((48, 465), "规则位置与手工编辑命令：docs/AUTHORING.md",
              font=body, fill="#c5d1d6")
    frames.append(image)

    image, draw = frame(3, "相同的前九步，第十步才分叉")
    draw.text((48, 205), f"前九步：{report['unchanged_published_prefix']} 条完整发生记录相同",
              font=body, fill="#9de7cf")
    for x, label, result, color in (
        (48, "原规则", original, "#9de7cf"),
        (664, "禁止自救", edited, "#f5c678"),
    ):
        draw.text((x, 275), label, font=title, fill=color)
        draw.text((x, 346), f"steps_completed: {result['steps_completed']}",
                  font=code, fill="#e0e8eb")
        draw.text((x, 394), f"stop: {result['stop_reason']}", font=code, fill=color)
        goal = "目标达成" if result["goal_status"] == "met" else "目标未达成"
        draw.text((x, 442), goal, font=body, fill=color)
    draw.text((48, 528), "拒绝版停在第十步：未发布本次行动，不由宿主补写结局。",
              font=body, fill="#e0e8eb")
    frames.append(image)

    image, draw = frame(4, "复现与检查，不只看一张图")
    draw.text((48, 202), "$ python tools/release_rule_edit_demo.py", font=code,
              fill="#9de7cf")
    draw.text((48, 265), "加 --json 查看完整发生、参与者和来源依据。", font=body,
              fill="#e0e8eb")
    draw.text((48, 330), "本次原始输出：docs/showcase/result.json", font=code,
              fill="#c5d1d6")
    draw.text((48, 390), "版本与输入摘要：docs/showcase/manifest.json", font=code,
              fill="#c5d1d6")
    draw.text((48, 480), "长期目标：让世界规则产生故事，支援 RPG / TRPG 沙盒。",
              font=body, fill="#e0e8eb")
    frames.append(image)
    frames[2].save(output / "rule-edit.png")
    frames[0].save(output / "rule-edit.gif", save_all=True, append_images=frames[1:],
                   duration=[3000, 3500, 5000, 3500], loop=0, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, help="local Chinese font; not redistributed")
    parser.add_argument("--mono", required=True, help="local monospace font")
    args = parser.parse_args()
    from PIL import ImageFont
    ImageFont.truetype(args.font, 20)
    ImageFont.truetype(args.mono, 20)
    root = Path(__file__).resolve().parents[2]
    output = Path(__file__).resolve().parent
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("src", "engine/kernel/src"))
    fingerprint, entries = code_fingerprint(root)
    raw = command(root, [sys.executable, "tools/release_rule_edit_demo.py", "--json"], env)
    report = json.loads(raw)
    validate_report(report)
    if code_fingerprint(root)[0] != fingerprint:
        raise RuntimeError("code or authored inputs changed during capture")
    origins = json.loads(command(root, [sys.executable, "-c",
        "import json,nomos_c0,nomos_t0,nomos_kernel; "
        "print(json.dumps({m.__name__:m.__file__ for m in "
        "(nomos_c0,nomos_t0,nomos_kernel)}))"], env))
    if any(not Path(path).resolve().is_relative_to(root) for path in origins.values()):
        raise RuntimeError("demo modules were not loaded from this checkout")
    manifest = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "code_revision": command(root, ["git", "rev-parse", "HEAD"]).strip(),
        "code_worktree_changes": command(root, ["git", "diff", "HEAD", "--name-only",
            "--", "src", "engine/kernel/src", "tools/release_rule_edit_demo.py"]).splitlines(),
        "python_version": sys.version,
        "module_origins": origins,
        "command": "python tools/release_rule_edit_demo.py --json",
        "result_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "code_and_inputs_sha256": fingerprint,
        "file_sha256": entries,
        "media": "four result slides, 15 seconds; not a screen recording or execution timer",
    }
    render(report, manifest, args.font, args.mono, output)
    (output / "result.json").write_text(raw, encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Captured checked real report and media at {output}")


if __name__ == "__main__":
    main()
