"""Run a fixed rule-edit demonstration through the real compiler and runtime."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import platform
import statistics
import sys
from dataclasses import asdict, fields, is_dataclass
from importlib import metadata
from pathlib import Path
from time import perf_counter

import nomos_c0
import nomos_runtime
import nomos_t0
from nomos_c0.author_abilities import compile_author_files
from nomos_c0.python_codegen import emit_world_module
from nomos_runtime.artifacts import load_world
from nomos_runtime.documents import read_data
from nomos_runtime.entities import Reference
from nomos_t0.witness import CONTROL_ERRORS, WitnessError, check_witness, execute, trace

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "src/nomos_c0/author_abilities/examples"
DEMO = ROOT / "demos/werewolf-self-save"


def require(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value, names):
    if isinstance(value, Reference):
        return {"symbol": names[value], "sort": value.sort}
    if is_dataclass(value):
        return {field.name: normalize(getattr(value, field.name), names) for field in fields(value)}
    if isinstance(value, dict):
        return {key: normalize(item, names) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item, names) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((normalize(item, names) for item in value), key=lambda item: json.dumps(item))
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError(f"unsupported audit value: {type(value).__name__}")


def snapshot(session):
    return session.inspect_state(), session.history(), session.acquisitions()


def profile(program, controllers, assets, case):
    started = perf_counter()
    session = program.start(assets, controllers=controllers)
    start_seconds = perf_counter() - started
    rows, prefix, rejected_without_change = [], None, None
    for number, step in enumerate(case["steps"], 1):
        before = snapshot(session)
        started = perf_counter()
        try:
            execute(session, step, {})
        except (WitnessError, *CONTROL_ERRORS) as error:
            elapsed = perf_counter() - started
            rejected_without_change = snapshot(session) == before
            rows.append(
                {
                    "step": number,
                    "action": step["action"],
                    "seconds": elapsed,
                    "status": "rejected",
                    "error_type": type(error).__name__,
                }
            )
            break
        elapsed = perf_counter() - started
        rows.append(
            {"step": number, "action": step["action"], "seconds": elapsed, "status": "published"}
        )
        if number == 5:
            names = {ref: name for name, ref in session.symbols}
            prefix = normalize(snapshot(session), names)
    return {
        "start_seconds": start_seconds,
        "steps": rows,
        "prefix": prefix,
        "rejected_without_change": rejected_without_change,
        "witch": {key: session.read("e")[key] for key in ("alive", "antidote", "poison")},
        "trace": [asdict(row) for row in trace(session)],
    }


def render(result):
    labels = {
        "allow": "允许自救：女巫存活，解药消耗",
        "deny": "禁止自救：同一选择在第6步被拒绝",
        "decline": "禁止自救后不救：正常天亮，女巫死亡",
    }
    cards = []
    for key, case in result["cases"].items():
        timing = case["profile"]
        steps = "".join(
            f"<tr><td>{row['step']}</td><td>{html.escape(row['action'])}</td>"
            f"<td>{html.escape(row['status'])}</td><td>{row['seconds'] * 1000:.2f}</td></tr>"
            for row in timing["steps"]
        )
        cards.append(
            f"<section><h2>{labels[key]}</h2>"
            f"<p>T0：{html.escape(case['witness']['stop_reason'])}；"
            f"完成 {case['witness']['steps_completed']} 步。"
            f"Session启动 {timing['start_seconds'] * 1000:.2f} ms。</p>"
            f"<p>女巫存活：{timing['witch']['alive']}；"
            f"持有解药：{timing['witch']['antidote']}</p>"
            "<table><tr><th>步骤</th><th>行动</th><th>结果</th><th>耗时 ms</th></tr>"
            f"{steps}</table></section>"
        )
    compilation = "".join(
        f"<li>{variant}：检查与生成 {row['seconds']:.3f} s，"
        f"产物加载 {row['artifact_load_seconds']:.3f} s</li>"
        for variant, row in result["compilation"].items()
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>NomosEngine2：修改一条规则</title><style>"
        "body{max-width:880px;margin:36px auto;padding:0 20px;font:17px/1.7 sans-serif;"
        "color:#203047;background:#f4f6f8}section{background:white;padding:20px;"
        "margin:20px 0;border-radius:10px}h1{font-size:28px}h2{font-size:20px}"
        "table{border-collapse:collapse;width:100%}td,th{text-align:left;"
        "padding:6px;border-bottom:1px solid #ddd}code{background:#e9edf1;padding:3px}</style>"
        "<h1>修改一条规则，改变实际行动</h1>"
        "<p>同一六人开局、相同行动前缀，仅将 <code>allow_self_save: true</code> "
        "改为 <code>false</code>。世界由同一编译器与运行时执行。</p>"
        "<p>以下是含固定身份的作者验收视角，不是玩家界面。本示例行动全部手动固定，"
        "不用于证明电脑策略水平。</p>"
        + f"<section><h2>准备耗时</h2><ul>{compilation}</ul></section>"
        + "".join(cards)
        + "<p>三条路线的前5步状态、发生记录与收件在消除Session身份域差异后相同；"
        "被拒绝的自救没有改变状态、发生记录或收件。</p>"
        "<p>表中为本机单次测量；行动耗时包含输入解析、当前选择检查、提交与同步结算。"
        "不含浏览器、网络、用户输入或完整电脑回合。原始数据见同目录 result.json。</p></html>"
    )


def run(output):
    run_started = perf_counter()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    allowed = (DEMO / "allow.source.yaml").read_text()
    denied = (DEMO / "deny.source.yaml").read_text()
    require(allowed.count("allow_self_save: true") == 1, "allow flag must be unique")
    require(
        denied == allowed.replace("allow_self_save: true", "allow_self_save: false"),
        "the source variants must differ only in self-save policy",
    )
    assets = read_data(EXAMPLES / "werewolf.assets.yaml")
    attempt = read_data(DEMO / "attempt.yaml")
    decline = read_data(DEMO / "decline.yaml")
    require(attempt["steps"][:5] == decline["steps"][:5], "prefix must stay fixed")
    require(
        attempt["steps"][-1]["inputs"] == {"save": True, "poison_target": []},
        "the self-save attempt must stay fixed",
    )
    changed = json.loads(json.dumps(attempt["steps"]))
    changed[-1]["inputs"]["save"] = False
    require(changed == decline["steps"], "fallback must only decline the antidote")
    paths = [
        EXAMPLES / "werewolf.lib.yaml",
        EXAMPLES / "werewolf.assets.yaml",
        DEMO / "allow.source.yaml",
        DEMO / "deny.source.yaml",
        DEMO / "attempt.yaml",
        DEMO / "decline.yaml",
        Path(__file__).resolve(),
    ]
    result = {
        "schema": "nomos.showcase.self-save.v1",
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "isolated_python": bool(sys.flags.isolated),
            "prefix": sys.prefix,
            "versions": {
                name: metadata.version(name) for name in ("nomos-engine2", "PyYAML", "pyrsistent")
            },
            "modules": {
                module.__name__: str(Path(module.__file__).resolve())
                for module in (nomos_c0, nomos_runtime, nomos_t0)
            },
        },
        "inputs": {str(path.relative_to(ROOT)): digest(path) for path in paths},
        "compilation": {},
        "cases": {},
    }
    for variant in ("allow", "deny"):
        started = perf_counter()
        program = compile_author_files(
            EXAMPLES / "werewolf.lib.yaml", DEMO / f"{variant}.source.yaml"
        )
        code = emit_world_module(program)
        path = output / f"{variant}.py"
        path.write_text(code)
        result["compilation"][variant] = {
            "seconds": perf_counter() - started,
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        started = perf_counter()
        with load_world(path) as world:
            result["compilation"][variant]["artifact_load_seconds"] = perf_counter() - started
            for key, case in (
                (("allow", attempt),)
                if variant == "allow"
                else (("deny", attempt), ("decline", decline))
            ):
                measured = profile(world.PROGRAM, world.CONTROLLERS, assets, case)
                started = perf_counter()
                report = check_witness(world.PROGRAM, assets, case, controllers=world.CONTROLLERS)
                witness_seconds = perf_counter() - started
                result["cases"][key] = {
                    "profile": measured,
                    "witness": asdict(report),
                    "witness_seconds": witness_seconds,
                }
                require(
                    measured["trace"] == list(result["cases"][key]["witness"]["published"]),
                    f"profile and independent T0 replay differ for {key}",
                )
    cases = result["cases"]
    for key in ("allow", "decline"):
        report = cases[key]["witness"]
        require(
            (report["stop_reason"], report["goal_status"], report["steps_completed"])
            == ("witness_completed", "met", 6),
            f"expected successful witness for {key}",
        )
    rejection = cases["deny"]["witness"]
    require(
        rejection["stage"] == "run"
        and rejection["steps_completed"] == 5
        and rejection["requested_step"] == 6
        and rejection["stop_reason"] in ("control_rejected", "admission_rejected"),
        "the original self-save must be rejected at step 6",
    )
    require(
        cases["deny"]["profile"]["rejected_without_change"] is True,
        "rejection must preserve state, history and receipts",
    )
    require(
        cases["allow"]["profile"]["prefix"]
        == cases["deny"]["profile"]["prefix"]
        == cases["decline"]["profile"]["prefix"],
        "prefix semantics must match",
    )
    require(
        cases["allow"]["profile"]["witch"] == {"alive": True, "antidote": False, "poison": True},
        "self-save did not resolve",
    )
    require(
        cases["decline"]["profile"]["witch"] == {"alive": False, "antidote": True, "poison": True},
        "death did not resolve",
    )
    for case in cases.values():
        prefix = case["profile"].pop("prefix")
        case["profile"]["prefix_sha256"] = hashlib.sha256(
            json.dumps(prefix, sort_keys=True).encode()
        ).hexdigest()
    samples = [row["seconds"] for case in cases.values() for row in case["profile"]["steps"]]
    result["timing"] = {
        "action_samples": len(samples),
        "median_action_seconds": statistics.median(samples),
        "max_action_seconds": max(samples),
    }
    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in sys.modules.items()
        if name.startswith("nomos_") and getattr(module, "__file__", None)
    }
    in_environment = all(Path(path).is_relative_to(Path(sys.prefix)) for path in origins.values())
    result["environment"]["engine_modules"] = origins
    result["environment"]["all_engine_modules_in_environment"] = in_environment
    if sys.flags.isolated:
        require(in_environment, "isolated showcase loaded engine modules outside its environment")
    result["timing"]["checks_seconds_excluding_imports"] = perf_counter() - run_started
    result["passed"] = True
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "report.html").write_text(render(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/showcase-self-save")
    args = parser.parse_args()
    started = perf_counter()
    result = run(args.output)
    print("通过：允许自救时存活；禁止时同一选择被拒绝且零写；改选不救则天亮死亡。")
    print(
        f"18次行动测量：中位 {result['timing']['median_action_seconds'] * 1000:.2f} ms，"
        f"最大 {result['timing']['max_action_seconds'] * 1000:.2f} ms。"
    )
    print(f"总耗时（不含解释器导入）：{perf_counter() - started:.2f} s")
    print(f"结果：{args.output.resolve() / 'report.html'}")


if __name__ == "__main__":
    main()
