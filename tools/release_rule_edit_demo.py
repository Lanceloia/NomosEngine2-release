"""Change one in-memory authored Law clause; replay the unchanged real witness."""

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

import nomos_c0
import nomos_t0
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_t0.author_check_v0 import parse_case
from nomos_t0.witness_v0 import check_witness

HERE = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="include complete occurrence evidence")
    parser.add_argument("--record", type=Path, help="capture into a new evidence directory")
    args = parser.parse_args(argv)
    if args.record is not None and args.record.exists():
        parser.error("capture directory already exists; historical evidence is never overwritten")
    modules = (nomos_c0, nomos_t0, nomos_kernel)
    if any(not Path(module.__file__).resolve().is_relative_to(HERE) for module in modules):
        parser.error("run with C0/T0/K0 installed from this checkout")
    root = Path(nomos_c0.__file__).resolve().parent / "examples"
    cases = Path(nomos_t0.__file__).resolve().parent / "examples"
    paths = {
        "lib": root / "three_seat_werewolf_v0.lib.yaml",
        "ports": root / "three_seat_werewolf_v0.ports.yaml",
        "source": root / "six_seat_werewolf_v0.source.yaml",
        "assets": cases / "werewolf_witch_b.assets.yaml",
        "case": cases / "werewolf_self_heal_b.case.yaml",
    }
    inputs_before = {name: path.read_bytes() for name, path in paths.items()}
    lib = read_author_document(root / "three_seat_werewolf_v0.lib.yaml").to_data()
    ports = read_author_document(root / "three_seat_werewolf_v0.ports.yaml")
    source = read_author_document(root / "six_seat_werewolf_v0.source.yaml")
    assets = read_author_document(cases / "werewolf_witch_b.assets.yaml").to_data()
    witness, goal = parse_case(
        read_author_document(cases / "werewolf_self_heal_b.case.yaml").to_data()
    )
    changed = deepcopy(lib)
    law = next(row for row in changed["lawdefs"] if row["name"] == "action.witch_intervene")
    save = law["body"]["value"]["guard"]["require"][-1]["save_choice"]
    save["if"]["then"]["require"].append({"not_self": "actor.name != scene.pending_attack"})
    reports = []
    for version in (lib, changed):
        nominal = check_nominal_lib(version, source.to_data().get("actor_domains"))
        program = compile_owner_graph(check_graph_ports(ports, nominal), source)
        reports.append(check_witness(program, assets, witness, goal))
    before, after = reports
    if (
        before.goal_status != "met"
        or after.stop_reason != "k0_not_admitted"
        or after.steps_completed != 9
        or after.requested_step != 10
        or before.published[: len(after.published)] != after.published
    ):
        raise RuntimeError("one-clause edit did not produce the expected real witness difference")
    report = {
        "edit": "save branch: actor.name != scene.pending_attack",
        "files_modified": False,
        "same_assets_and_witness": True,
        "unchanged_published_prefix": len(after.published),
        "original": asdict(before),
        "edited": asdict(after),
    }
    if any(path.read_bytes() != inputs_before[name] for name, path in paths.items()):
        raise RuntimeError("authored inputs changed during capture")
    if args.record is not None:
        raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        files = [Path(__file__)]
        for folder in ("src/nomos_c0", "src/nomos_t0", "engine/kernel/src/nomos_kernel"):
            files.extend((HERE / folder).rglob("*.py"))
        manifest = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "code_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip(),
            "capture_worktree_changes": subprocess.check_output(
                ["git", "status", "--short"], cwd=HERE, text=True).splitlines(),
            "python_version": sys.version,
            "module_origins": {module.__name__: module.__file__ for module in modules},
            "code_files_sha256": {str(path.relative_to(HERE)):
                                  hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in sorted(files)},
            "inputs": {name: {"path": str(paths[name]), "sha256": hashlib.sha256(raw).hexdigest()}
                       for name, raw in inputs_before.items()},
            "result_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "files_modified": False,
            "note": "Trusted author audit, not player access or authenticated provenance.",
        }
        args.record.mkdir(parents=True, exist_ok=False)
        (args.record / "result.json").write_text(raw, encoding="utf-8")
        (args.record / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.json:
        for key in ("original", "edited"):
            report[key] = {
                field: report[key][field]
                for field in ("stop_reason", "goal_status", "steps_completed", "requested_step")
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
