"""Animate the rule-edit experiment, using a checked stored or fresh report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
        and [(row["family"], row["source"]) for row in before["published"][len(prefix):]]
        == [("action", "c0.six-seat.witch-b"),
            ("event", "c0.six-seat.resolve-after-witch-b")]
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


def load_recorded_report(output):
    raw = (output / "result.json").read_bytes()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != manifest["result_sha256"]:
        raise ValueError("stored report does not match its capture digest")
    report = json.loads(raw)
    validate_report(report)
    return report, manifest


def progress(time, start, duration):
    value = max(0.0, min(1.0, (time - start) / duration))
    return value * value * (3 - 2 * value)


def animation_state(time):
    return {
        "rule": progress(time, 2, .6),
        "relation": progress(time, 4, 1.4),
        "request": progress(time, 6, .4),
        "request_y": 416 + 60 * progress(time, 6, 1.6),
        "decision": progress(time, 10, 1.2),
        "outcome": progress(time, 10.5, .6),
        "event": progress(time, 12, 1.2),
        "evidence": progress(time, 14, .8),
        "reset": progress(time, 22, .3),
    }


def render(report, manifest, font, mono, output):
    from PIL import Image, ImageDraw, ImageFont

    bg, ink, muted = "#101619", "#f1f5f5", "#b6c7cc"
    green, amber, line = "#8ce5c5", "#f7cd7a", "#52636c"
    fonts = {size: ImageFont.truetype(font, size) for size in (18, 22, 24, 26, 28, 36, 42)}
    code = ImageFont.truetype(mono, 26)
    text_boxes = set()

    def scene(time):
        state = animation_state(time)
        canvas = Image.new("RGBA", (1280, 720), bg)
        draw = ImageDraw.Draw(canvas)

        def text(x, y, value, size=26, color=ink, opacity=1, center=False, face=None):
            face = face or fonts[size]
            anchor = "mm" if center else "lm"
            box = draw.textbbox((x, y), value, font=face, anchor=anchor)
            if box[0] < 0 or box[1] < 0 or box[2] > 1280 or box[3] > 720:
                raise ValueError(f"showcase text outside canvas: {value}")
            text_boxes.add((value, *box))
            if opacity <= 0:
                return
            layer = Image.new("RGBA", canvas.size)
            ImageDraw.Draw(layer).text((x, y), value, font=face, anchor=anchor, fill=color)
            if opacity < 1:
                layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
            canvas.alpha_composite(layer)

        def stroke(points, color, width=3, opacity=1, arrow=False):
            if opacity <= 0:
                return
            layer = Image.new("RGBA", canvas.size)
            painter = ImageDraw.Draw(layer)
            painter.line(points, fill=color, width=width, joint="curve")
            if arrow and len(points) > 1:
                x, y = points[-1]
                px, py = points[-2]
                angle = math.atan2(y - py, x - px)
                wings = [(x - 10 * math.cos(angle + delta),
                          y - 10 * math.sin(angle + delta)) for delta in (-.48, .48)]
                painter.polygon([(x, y), *wings], fill=color)
            if opacity < 1:
                layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
            canvas.alpha_composite(layer)

        def record(cx, cy, label, opacity):
            if opacity <= 0:
                return
            layer = Image.new("RGBA", canvas.size)
            ImageDraw.Draw(layer).rounded_rectangle(
                (cx - 152, cy - 20, cx + 152, cy + 20), radius=5, fill="#285d50")
            layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
            canvas.alpha_composite(layer)
            text(cx, cy, label, color=green, opacity=opacity, center=True)

        text(48, 35, "NomosEngine2", size=28)
        text(390, 35, "RPG / TRPG 沙盒：用世界规则约束行动", size=24, color=muted)
        text(48, 85, "只改一条规则，让世界判定不同", size=36)
        text(48, 129, "同一开局 · 同一十步行动见证", size=24, color=muted)
        text(695, 129, "两版各自编译、开局、运行", size=26)

        draw.rectangle((48, 161, 1232, 241), fill="#202a2e")
        text(68, 182, "仅编辑版 · 新增：不能救自己", size=24,
             color=amber, opacity=state["rule"])
        text(68, 218, "- not_self: actor.name != scene.pending_attack", face=code,
             color=amber, opacity=state["rule"])
        draw.line((640, 272, 640, 616), fill="#334248", width=2)

        for cx, label, color in ((320, "原版", green), (960, "编辑版", amber)):
            text(cx, 277, label, size=28, color=color, center=True)
            draw.ellipse((cx - 31, 304, cx + 31, 366), outline=ink, width=3)
            text(cx, 335, "B", size=42, center=True)
            text(cx, 385, "女巫 / 受害者", size=24, color=muted, center=True)
            points = []
            controls = ((cx + 26, 311), (cx + 132, 251),
                        (cx + 144, 397), (cx + 25, 356))
            for index in range(round(state["relation"] * 48) + 1):
                u = index / 48
                points.append(tuple((1-u)**3*a + 3*(1-u)**2*u*b +
                                    3*(1-u)*u*u*c + u**3*d
                                    for a, b, c, d in zip(*controls)))
            stroke(points, muted, opacity=state["relation"], arrow=True)
            text(cx + 170, 338, "救自己", size=24, color=muted,
                 opacity=state["relation"], center=True)

            cy = state["request_y"]
            if state["request"]:
                layer = Image.new("RGBA", canvas.size)
                ImageDraw.Draw(layer).rounded_rectangle(
                    (cx - 152, cy - 20, cx + 152, cy + 20),
                    radius=5, outline=ink, width=2)
                layer.putalpha(layer.getchannel("A").point(
                    lambda a: round(a * state["request"])))
                canvas.alpha_composite(layer)
            text(cx, cy, "第10步 · 请求B救B", opacity=state["request"], center=True)
            if cy > 425:
                stroke([(cx, 403), (cx, cy - 23)], line, opacity=state["request"])
            draw.line((cx - 260, 514, cx + 260, 514), fill=line, width=2)
            text(cx - 248, 489, "世界判定", size=22, color=muted)

            if label == "原版":
                stroke([(cx, 496), (cx, 496 + 25 * state["decision"])], green,
                       opacity=state["decision"], arrow=True)
                record(cx, 545, "救人行动已发布", state["outcome"])
                stroke([(cx, 567), (cx, 567 + 9 * state["event"])], green,
                       opacity=state["event"], arrow=True)
                record(cx, 598, "后续结算已发布", state["event"])
            else:
                stroke([(cx, 496), (cx, 496 + 17 * state["decision"])], amber,
                       opacity=state["decision"])
                stroke([(cx - 18, 514), (cx + 18, 514)], amber, width=5,
                       opacity=state["outcome"])
                text(cx, 545, "请求被拒绝", size=28, color=amber,
                     opacity=state["outcome"], center=True)
                text(cx, 598, "本次不发布", color=muted,
                     opacity=state["event"], center=True)

        prefix = report["unchanged_published_prefix"]
        before, after = (len(report[key]["published"]) for key in ("original", "edited"))
        text(48, 645, f"前9步：{prefix}条完整记录一致", size=24,
             opacity=state["evidence"])
        text(695, 645, f"第10步请求后：原版{before}条 / 编辑版{after}条", size=24,
             opacity=state["evidence"])
        text(48, 692, "运行结果示意 · 非录屏 / 非耗时 · 内存改规则", size=22)
        text(1080, 692, "复现见 README", size=18, color=muted,
             opacity=state["evidence"])
        if state["reset"]:
            overlay = Image.new("RGBA", canvas.size, (16, 22, 25,
                               round(255 * state["reset"])))
            canvas.alpha_composite(overlay)
            text(640, 360, "重看对照", size=36, center=True, opacity=state["reset"])
        return canvas.convert("RGB")

    final = scene(18)
    final.save(output / "rule-edit.png")
    final.resize((800, 450), Image.Resampling.LANCZOS).save(output / "rule-edit-800.png")
    # One shared palette avoids per-frame color changes on stationary text.
    palette = final.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames, durations, times = [], [], []
    previous = None
    for index in range(230):
        time = index / 10
        state = animation_state(time)
        if state == previous:
            durations[-1] += 100
            continue
        frames.append(scene(time).quantize(palette=palette, dither=Image.Dither.NONE))
        durations.append(100)
        times.append(time)
        previous = state
    frames[0].save(output / "rule-edit.gif", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=1, optimize=False)

    moments = (0, 3, 5.5, 8.5, 11.5, 18)
    sheet = Image.new("RGB", (1280, 1170), bg)
    for index, time in enumerate(moments):
        thumb = scene(time).resize((640, 360), Image.Resampling.LANCZOS)
        x, y = (index % 2) * 640, (index // 2) * 390
        sheet.paste(thumb, (x, y + 30))
        ImageDraw.Draw(sheet).text((x + 24, y + 3), f"{time:g}s", font=fonts[22], fill=ink)
    sheet.save(output / "storyboard.png")
    with Image.open(output / "rule-edit.gif") as gif:
        stored_durations = []
        for index in range(gif.n_frames):
            gif.seek(index)
            stored_durations.append(gif.info["duration"])
    if sum(stored_durations) != 23000:
        raise ValueError("encoded GIF does not preserve the 23-second storyboard")
    metadata = {
        "report_sha256": manifest["result_sha256"],
        "report_code_revision": manifest["code_revision"],
        "renderer_sha256": digest(Path(__file__)),
        "rendered_at_utc": datetime.now(UTC).isoformat(),
        "media": "continuous explanatory animation; not live footage or execution timing",
        "canvas": [1280, 720],
        "gif_duration_ms": sum(stored_durations),
        "gif_frames": len(stored_durations),
        "static_final_state_seconds": [17, 22],
        "keyframe_times_seconds": list(moments),
        "sampled_changed_state_times_seconds": times,
        "text_bounds": sorted(text_boxes),
        "files_sha256": {name: digest(output / name) for name in (
            "rule-edit.gif", "rule-edit.png", "rule-edit-800.png", "storyboard.png")},
    }
    (output / "animation.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", required=True, help="local Chinese font; not redistributed")
    parser.add_argument("--mono", required=True, help="local monospace font")
    parser.add_argument("--reuse-report", action="store_true",
                        help="verify stored report and render only; do not run the world")
    args = parser.parse_args()
    from PIL import ImageFont
    ImageFont.truetype(args.font, 20)
    ImageFont.truetype(args.mono, 20)
    root = Path(__file__).resolve().parents[2]
    output = Path(__file__).resolve().parent
    if args.reuse_report:
        report, manifest = load_recorded_report(output)
        render(report, manifest, args.font, args.mono, output)
        print(f"Animated verified stored report at {output}; no world execution")
        return
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
        "media": "continuous result animation; see animation.json for rendering metadata",
    }
    render(report, manifest, args.font, args.mono, output)
    (output / "result.json").write_text(raw, encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Captured checked real report and media at {output}")


if __name__ == "__main__":
    main()
