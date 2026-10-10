"""Record real author-edit commands; render their output without simulating a world."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import asdict
from difflib import unified_diff
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "lib.yaml": "src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml",
    "ports.yaml": "src/nomos_c0/examples/three_seat_werewolf_v0.ports.yaml",
    "source.yaml": "src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml",
    "assets.yaml": "src/nomos_t0/examples/werewolf_witch_b.assets.yaml",
    "case.yaml": "src/nomos_t0/examples/werewolf_self_heal_b.case.yaml",
}
ANCHOR = "                      - victim_exists: scene.pending_attack is not None\n"
CLAUSE = "                      - not_self: actor.name != scene.pending_attack\n"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(work):
    work.mkdir(exist_ok=False)
    manifest = {}
    for name, source in INPUTS.items():
        raw = (ROOT / source).read_bytes()
        (work / name).write_bytes(raw)
        manifest[name] = {"source": source, "sha256": digest(raw)}
    (work / "original.lib.yaml").write_bytes((work / "lib.yaml").read_bytes())
    write_json(work / "inputs.json", manifest)
    lines = (work / "lib.yaml").read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if "- save_choice:" in line)
    print("临时副本已就绪；原仓库文件不会改写。当前救人分支：\n")
    print("\n".join(lines[start:start + 11]))


def edit(work):
    import yaml

    path = work / "lib.yaml"
    before = path.read_text(encoding="utf-8")
    if before.count(ANCHOR) != 1 or CLAUSE in before:
        raise ValueError("edit needs the unique, unedited save branch")
    after = before.replace(ANCHOR, ANCHOR + CLAUSE)
    expected = deepcopy(yaml.safe_load(before))
    law = next(row for row in expected["lawdefs"] if row["name"] == "action.witch_intervene")
    law["body"]["value"]["guard"]["require"][-1]["save_choice"]["if"]["then"][
        "require"
    ].append({"not_self": "actor.name != scene.pending_attack"})
    if yaml.safe_load(after) != expected:
        raise ValueError("edit changed more than one declared clause")
    path.write_text(after, encoding="utf-8")
    diff = "".join(unified_diff(before.splitlines(True), after.splitlines(True),
                                "original.lib.yaml", "lib.yaml", n=3))
    (work / "law.diff").write_text(diff, encoding="utf-8")
    print(diff, end="")
    print("仅新增一条 Law 条件；Assets、Source、Ports、case 未改。")


def replay(work, name):
    arguments = [part for key in ("lib", "ports", "source", "assets", "case")
                 for part in (f"--{key}", str(work / f"{key}.yaml"))]
    # The child is the real T0 CLI; presentation does not implement settlement.
    child = subprocess.run([sys.executable, "-m", "nomos_t0.author_check_v0",
                            *arguments, "--json"], capture_output=True, text=True, check=False)
    if child.stderr:
        print(child.stderr, file=sys.stderr, end="")
    report = json.loads(child.stdout)
    write_json(work / f"{name}.json", report)
    print(f"T0 实际退出码：{child.returncode}")
    print(f"完成 {report['steps_completed']} 步；发布 {len(report['published'])} 条发生")
    print(f"stop: {report['stop_reason']}    goal: {report['goal_status']}\n")
    for row in report["published"]:
        print(f"  #{row['occurrence']:02}  {row['source']}")
    if report["requested_step"] is not None:
        print(f"\n停在第 {report['requested_step']} 步：B / Save victim")
    # Preserve the real witness status, including expected refusal exit 3.
    return child.returncode


def compare(work):
    from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

    from nomos_c0.author_document_v1 import read_author_document
    from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
    from nomos_c0.declarative_nominal_v0 import check_nominal_lib
    from nomos_c0.owner_graph_v1 import compile_owner_graph
    from nomos_t0.witness_v0 import _freeze, _trace_row

    before, after = (load_json(work / f"{name}.json") for name in ("original", "changed"))
    if not (before["goal_status"] == "met" and after["steps_completed"] == 9
            and after["requested_step"] == 10 and after["stop_reason"] == "k0_not_admitted"
            and len(after["published"]) == 12
            and before["published"][:12] == after["published"]):
        raise ValueError("the executed reports do not support the presentation")
    source = read_author_document(work / "source.yaml")
    nominal = check_nominal_lib(read_author_document(work / "lib.yaml"),
                                source.to_data()["actor_domains"])
    program = compile_owner_graph(
        check_graph_ports(read_author_document(work / "ports.yaml"), nominal), source)
    session = program.start(read_author_document(work / "assets.yaml").to_data())
    prefix = read_author_document(ROOT / "docs/showcase/world-edits/actions.yaml").to_data()
    for row in prefix["role_prefix"]:
        candidates = [offer for offer in session.offers(row["seat"])
                      if offer.label == row["label"]]
        if len(candidates) != 1 or session.offer_faults(row["seat"]):
            raise ValueError("diagnostic prefix has no unique legal candidate")
        offer = candidates[0]
        result = session.submit(row["seat"], offer.entry, dict(offer.payload))
        if not isinstance(result, K0Published):
            raise ValueError("diagnostic prefix was not actually published")
    snapshot = session.author_snapshot()
    published = json.loads(json.dumps([asdict(_trace_row(row)) for row in snapshot.occurrences]))
    if published != after["published"]:
        raise ValueError("diagnostic replay differs from the T0 prefix")
    matches = [row for row in session.offers("B") if row.label == "Save victim"]
    if len(matches) != 1:
        raise ValueError("expected the existing save candidate")
    offer = matches[0]
    diagnostic = session.author_guard_report("B", offer)
    if session.author_snapshot() != snapshot:
        raise ValueError("reading diagnostics wrote world state")
    result = session.submit("B", offer.entry, dict(offer.payload))
    final = session.author_snapshot()
    if not isinstance(result, K0NotAdmitted) or snapshot != final:
        raise ValueError("expected zero-write refusal")
    failures = [row for row in diagnostic.failures if "not_self" in row.names]
    if len(failures) != 1:
        raise ValueError("missing real author predicate diagnostic")
    manifest = load_json(work / "inputs.json")
    unchanged = {name: digest((work / name).read_bytes()) == row["sha256"]
                 for name, row in manifest.items() if name != "lib.yaml"}
    if not all(unchanged.values()):
        raise ValueError("a non-Law input was changed")
    write_json(work / "comparison.json", {
        "unchanged_inputs": unchanged, "equal_published_prefix": 12,
        "candidate_still_present": True, "diagnostic": asdict(diagnostic),
        "refusal_snapshot_before": _freeze(snapshot), "refusal_snapshot_after": _freeze(final),
        "original_lib_sha256": digest((work / "original.lib.yaml").read_bytes()),
        "changed_lib_sha256": digest((work / "lib.yaml").read_bytes()),
    })
    print("同一开局 / 同一行动见证：")
    print("  前九步的 12 条发生记录完全相同（含来源）")
    print("  第十步：原规则发布；改后 K0NotAdmitted")
    print("  Save victim 候选仍存在，不是菜单自动消失\n")
    failure = failures[0]
    print(f"  {'/'.join(failure.names)} = false")
    print(f"  {failure.expression}\n")
    print("拒绝前后完整作者状态与发生历史相同；本次没有写入。")
    print("这是准入拒绝，不是测试准入后的故障回滚。")


def world(work):
    child = subprocess.run([sys.executable, "tools/release_world_edit_demo.py", "--json"],
                           cwd=ROOT, capture_output=True, text=True, check=True)
    report = json.loads(child.stdout)
    write_json(work / "world.json", report)
    roles = report["role_move"]
    print("规则不变，改开局职业 B -> E：")
    for key, seat in (("witch_B", "B"), ("witch_E", "E")):
        row = roles[key]
        offers = row["before_save"]["seats"][seat]["offers"]
        print(f"  {seat} 的选项：" + " / ".join(item["label"] for item in offers))
        print("  实际救人来源：" + row["actions"][-1]["published"][0]["source"])
    print("  改后 B 的 Save victim 候选：" + str(roles["witch_E"]["B_candidate_check"][
        "offer_found"]))
    eight = report["size_change"]["eight"]
    print("\n同一份规则库，扩为八席：" + ", ".join(eight["opening"]["seats"]))
    for row in eight["actions"]:
        print(f"  {row['seat']} / {row['label']} -> {row['published'][0]['source']}")
    print("新增 G/H 有独立本人视图；不是只增加两个按钮。")
    print("此实验同步修改了角色 / 私有开局 / 参与者声明，不是一键配置。")


def render_page(record):
    template = (ROOT / "docs/showcase/recording/player.html").read_text(encoding="utf-8")
    payload = json.dumps(record, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace("__RECORDING__", payload)


def record(destination):
    import nomos_kernel

    import nomos_c0
    import nomos_t0

    if any(not Path(module.__file__).resolve().is_relative_to(ROOT)
           for module in (nomos_c0, nomos_t0, nomos_kernel)):
        raise ValueError("record with C0/T0/K0 installed from this checkout")
    destination.mkdir(exist_ok=False, parents=True)
    inputs = {name: digest((ROOT / path).read_bytes()) for name, path in INPUTS.items()}
    phases = (
        ("准备：真正的作者文件", "prepare", "", 0, 8),
        ("原规则：同一条十步行动见证", "replay", " original", 0, 12),
        ("只加一条条件", "edit", "", 0, 12),
        ("重新编译与执行：第十步分叉", "replay", " changed", 3, 14),
        ("核对：来源相同，拒绝没有写入", "compare", "", 0, 15),
        ("不只是条件判断：职业与人数", "world", "", 0, 15),
    )
    chapters, events = [], []
    env = {**os.environ, "PYTHONUNBUFFERED": "1",
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ne2-showcase-") as temporary:
        work = Path(temporary) / "work"
        env["WORK"] = str(work)
        for title, operation, suffix, expected, hold in phases:
            command = f'python tools/showcase_recording.py {operation} "$WORK"{suffix}'
            begin = time.monotonic() - started
            events.append([begin, "o", f"$ {command}\r\n"])
            child = subprocess.run(["bash", "-c", command], cwd=ROOT, env=env,
                                   capture_output=True, text=True, check=False)
            if child.returncode != expected:
                raise RuntimeError(
                    f"unexpected exit {child.returncode}: {child.stderr}\n{child.stdout}")
            ended = time.monotonic() - started
            output = child.stdout + child.stderr + f"\n[exit {child.returncode}]\n"
            events.append([ended, "o", output.replace("\n", "\r\n")])
            chapters.append({"title": title, "command": command, "output": output,
                             "start": begin, "output_at": ended,
                             "process_seconds": ended - begin, "reading_seconds": hold})
            print(f"Recorded: {operation} (exit {child.returncode})", flush=True)
            time.sleep(hold)
        for name in ("original.json", "changed.json", "comparison.json", "world.json",
                     "law.diff", "inputs.json"):
            (destination / name).write_bytes((work / name).read_bytes())
    if inputs != {name: digest((ROOT / path).read_bytes()) for name, path in INPUTS.items()}:
        raise ValueError("repository author inputs changed during recording")
    duration = time.monotonic() - started
    code_paths = [Path(__file__), ROOT / "tools/release_world_edit_demo.py"]
    for folder in ("src/nomos_c0", "src/nomos_t0", "engine/kernel/src/nomos_kernel"):
        code_paths.extend((ROOT / folder).rglob("*.py"))
    recording = {"chapters": chapters, "duration": duration}
    write_json(destination / "recording.json", recording)
    header = {"version": 2, "width": 110, "height": 28, "duration": duration,
              "title": "NomosEngine2: real author-edit commands",
              "env": {"TERM": "dumb", "SHELL": "/bin/bash"}}
    (destination / "session.cast").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in (header, *events)) + "\n",
        encoding="utf-8")
    (destination / "replay.html").write_text(render_page(recording), encoding="utf-8")
    manifest = {
        "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                  cwd=ROOT, text=True).strip(),
        "worktree_changes": subprocess.check_output(["git", "status", "--short"],
                                                     cwd=ROOT, text=True).splitlines(),
        "python": sys.version, "repository_inputs_unchanged": True,
        "inputs_sha256": inputs,
        "code_sha256": {str(path.relative_to(ROOT)): digest(path.read_bytes())
                        for path in sorted(code_paths)},
        "artifacts_sha256": {path.name: digest(path.read_bytes())
                             for path in sorted(destination.iterdir())},
        "note": ("Actual subprocess outputs, then reading pauses. "
                 "HTML/video replay is not a live GUI capture."),
    }
    write_json(destination / "manifest.json", manifest)
    print(f"Recording: {destination}; {duration:.1f}s (includes explicit reading pauses)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=(
        "prepare", "edit", "replay", "compare", "world", "record"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("name", nargs="?", choices=("original", "changed"))
    args = parser.parse_args(argv)
    if args.operation == "replay":
        if args.name is None:
            parser.error("replay requires original or changed")
        return replay(args.directory, args.name)
    if args.name is not None:
        parser.error("only replay takes a report name")
    globals()[args.operation](args.directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
