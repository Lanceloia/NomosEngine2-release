"""Change one in-memory authored Law clause; replay the unchanged real witness."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import nomos_c0
import nomos_t0
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_t0.author_check_v0 import parse_case
from nomos_t0.witness_v0 import check_witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="include complete occurrence evidence")
    args = parser.parse_args()
    root = Path(nomos_c0.__file__).resolve().parent / "examples"
    cases = Path(nomos_t0.__file__).resolve().parent / "examples"
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
    if not args.json:
        for key in ("original", "edited"):
            report[key] = {
                field: report[key][field]
                for field in ("stop_reason", "goal_status", "steps_completed", "requested_step")
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
