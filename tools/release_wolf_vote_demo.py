"""Compare two existing authored Laws via current offers and real C0/K0 settlement."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import nomos_kernel
import yaml
from nomos_kernel._settlement_outcome_abi import K0Published

import nomos_c0
import nomos_t0
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_t0.witness_v0 import _trace_row

HERE = Path(__file__).resolve().parents[1]
INPUTS = HERE / "docs/showcase/wolf-vote"


def replace_selection(source):
    changed = deepcopy(source)
    matches = [row for row in changed["events"] if row.get("family") == "select_target"]
    if len(matches) != 1 or matches[0]["law"] != {"ref": "event.select_unanimous", "args": {}}:
        raise ValueError("expected exactly one unanimous selection binding")
    matches[0]["law"]["ref"] = "event.select_majority"
    return changed


def read_requests(path):
    document = read_author_document(path).to_data()
    if type(document) is not dict or set(document) != {"steps"}:
        raise ValueError("demonstration requests need only a steps list")
    steps = document["steps"]
    if type(steps) is not list or len(steps) != 10 or any(
        type(row) is not dict or set(row) != {"seat", "label"}
        or any(type(value) is not str or not value for value in row.values())
        for row in steps
    ):
        raise ValueError("this comparison needs ten seat/label requests")
    return steps


def capture(session):
    snapshot = session.author_snapshot()
    owners = dict(snapshot.owners)
    scene = owners.pop("scene")
    return {
        "scene": asdict(scene),
        "other_owners": {name: asdict(state) for name, state in owners.items()},
        "published": [asdict(_trace_row(row)) for row in snapshot.occurrences],
    }


def run_version(library, source, assets, requests):
    session = compile_owner_graph(library, source).start(deepcopy(assets))
    opening = capture(session)
    steps = []
    for number, request in enumerate(requests, 1):
        seat, label = request["seat"], request["label"]
        if session.offer_faults(seat):
            raise ValueError(f"step {number}: offer projection fault for {seat}")
        matches = [offer for offer in session.offers(seat) if offer.label == label]
        if len(matches) != 1:
            raise ValueError(f"step {number}: no unique current offer {seat} / {label}")
        offer = matches[0]
        before_count = len(session.author_snapshot().occurrences)
        result = session.submit(seat, offer.entry, dict(offer.payload))
        if not isinstance(result, K0Published):
            raise ValueError(f"step {number}: K0 did not publish {seat} / {label}")
        after = capture(session)
        steps.append({
            "step": number, "seat": seat, "label": label,
            "entry": offer.entry, "payload": dict(offer.payload),
            "new_occurrences": len(after["published"]) - before_count,
            **after,
        })
    return {"opening": opening, "steps": steps}


def validate_versions(versions):
    first, second = versions["unanimous"], versions["majority"]
    if len(first["steps"]) != 10 or len(second["steps"]) != 10:
        raise ValueError("both versions must publish all ten actions")
    for version in (first, second):
        rows = version["steps"][-1]["published"]
        if len(rows) != 13 or sum(row["family"] == "action" for row in rows) != 10:
            raise ValueError("comparison needs ten actual Actions and thirteen occurrences")
    equal = first["opening"] == second["opening"] and first["steps"][:9] == second["steps"][:9]
    commands = [[(step["seat"], step["entry"], step["payload"]) for step in version["steps"]]
                for version in versions.values()]
    scenes = [version["steps"][-1]["scene"] for version in versions.values()]
    if not equal or commands[0] != commands[1] or not (
        scenes[0]["last_death"] is None and scenes[1]["last_death"] == "F"
        and all(scene["phase"] == "day" and scene["round"] == 2 for scene in scenes)
        and all(scene["winner"] == "none" for scene in scenes)
        and [[row["target"] for row in scene["wolf_ballots"]] for scene in scenes]
        == [["F", "F", "E"], ["F", "F", "E"]]
        and [player["id"] for player in scenes[0]["players"] if not player["alive"]] == []
        and [player["id"] for player in scenes[1]["players"] if not player["alive"]] == ["F"]
    ):
        raise ValueError("real post-states do not support the stated rule comparison")
    return equal


def compare(lib, ports, source, assets, requests):
    changed = replace_selection(source)
    checked = check_nominal_lib(lib, source["actor_domains"])
    library = check_graph_ports(ports, checked)
    versions = {
        "unanimous": run_version(library, source, assets, requests),
        "majority": run_version(library, changed, assets, requests),
    }
    equal = validate_versions(versions)
    return {
        "edit": {"family": "select_target", "field": "law.ref",
                 "before": "event.select_unanimous", "after": "event.select_majority"},
        "same_assets_and_requests": True,
        "equal_opening_and_first_nine_steps": equal,
        "requests": requests,
        "versions": versions,
    }


def summary(report):
    lines = ["Same opening and ten requests; only select_target.law.ref changes.",
             "Opening and first nine steps: identical post-states and complete records."]
    for name, version in report["versions"].items():
        final = version["steps"][-1]
        scene = final["scene"]
        lines.append(
            f"{name}: 10 actions published; {len(final['published'])} occurrences; "
            f"round {scene['round']}, {scene['phase']}; death={scene['last_death']}; "
            f"winner={scene['winner']}"
        )
    lines.append("Both versions accept the requests; their world post-states differ.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="include per-step trusted author audit")
    parser.add_argument("--record", type=Path,
                        help="write a new evidence directory; never overwrite")
    args = parser.parse_args(argv)
    if args.record is not None and args.record.exists():
        parser.error("evidence directory already exists; choose a new directory")
    if any(not Path(module.__file__).resolve().is_relative_to(HERE)
           for module in (nomos_c0, nomos_t0, nomos_kernel)):
        parser.error("run with C0/T0/K0 installed from this checkout")
    examples = Path(nomos_c0.__file__).resolve().parent / "examples"
    paths = {
        "lib": examples / "three_seat_werewolf_v0.lib.yaml",
        "ports": examples / "three_seat_werewolf_v0.ports.yaml",
        "source": examples / "six_seat_werewolf_v0.source.yaml",
        "assets": INPUTS / "opening.assets.yaml",
        "requests": INPUTS / "actions.yaml",
    }
    bytes_before = {name: path.read_bytes() for name, path in paths.items()}
    data = {name: read_author_document(path).to_data() for name, path in paths.items()
            if name != "requests"}
    requests = read_requests(paths["requests"])
    report = compare(**data, requests=requests)
    if any(path.read_bytes() != bytes_before[name] for name, path in paths.items()):
        raise RuntimeError("authored inputs changed during capture")
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.record is not None:
        args.record.mkdir(parents=True, exist_ok=False)
        (args.record / "result.json").write_text(raw, encoding="utf-8")
        sources = {"unanimous": data["source"], "majority": replace_selection(data["source"])}
        for name, source in sources.items():
            (args.record / f"{name}.source.yaml").write_text(
                yaml.safe_dump(source, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # Hashes identify the captured checkout, not a trusted artifact issuer.
        code_files = [Path(__file__)]
        for folder in ("src/nomos_c0", "src/nomos_t0", "engine/kernel/src/nomos_kernel"):
            code_files.extend(path for path in (HERE / folder).rglob("*.py"))
        code_hashes = {str(path.relative_to(HERE)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(code_files)}
        manifest = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "code_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip(),
            "capture_worktree_changes": subprocess.check_output(
                ["git", "status", "--short"], cwd=HERE, text=True).splitlines(),
            "python_version": sys.version,
            "code_files_sha256": code_hashes,
            "result_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "effective_sources_sha256": {
                name: hashlib.sha256((args.record / f"{name}.source.yaml").read_bytes()).hexdigest()
                for name in sources
            },
            "inputs": {name: {"path": str(paths[name]), "sha256": hashlib.sha256(value).hexdigest()}
                       for name, value in bytes_before.items()},
            "module_origins": {module.__name__: module.__file__
                               for module in (nomos_c0, nomos_t0, nomos_kernel)},
            "files_modified": False,
            "note": ("Trusted author post-state audit; "
                     "not a player projection or cross-session identity."),
        }
        (args.record / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(raw if args.json else summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
