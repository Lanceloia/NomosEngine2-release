"""Check a witness against an already generated Python world."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from nomos_runtime.artifacts import load_world
from nomos_runtime.documents import read_data

from .witness import Report, check_witness, validate_case


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check a named-input witness in a generated Python Session"
    )
    parser.add_argument("world", type=Path, help="trusted generated world .py")
    parser.add_argument("witness", type=Path, help="nomos.witness YAML")
    parser.add_argument("--assets", type=Path, required=True, help="separate opening YAML/JSON")
    parser.add_argument("--json", action="store_true", help="complete structured author report")
    args = parser.parse_args(argv)
    try:
        case = validate_case(read_data(args.witness))
    except (OSError, ValueError) as error:
        report = Report(
            "input",
            getattr(error, "code", "witness_invalid"),
            "unknown",
            0,
            None,
            detail=str(error)[:4096],
        )
    else:
        try:
            assets = read_data(args.assets)
        except (OSError, ValueError) as error:
            report = Report("start", "start_rejected", "unknown", 0, None, detail=str(error)[:4096])
        else:
            try:
                with load_world(args.world) as world:
                    report = check_witness(
                        world.PROGRAM, assets, case, controllers=world.CONTROLLERS
                    )
            except (OSError, ValueError, ImportError, SyntaxError) as error:
                report = Report(
                    "artifact", "artifact_rejected", "unknown", 0, None, detail=str(error)[:4096]
                )
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False))
    else:
        print(f"{report.stage}: {report.stop_reason} | goal: {report.goal_status}")
        print(
            f"Witness steps: {report.steps_completed}; actual occurrences: {len(report.published)}"
        )
        if report.requested_step is not None:
            print(f"First unestablished step: {report.requested_step}")
        if report.detail:
            print(report.detail)
        for item in report.published:
            print(f"  #{item.occurrence} {item.family}: {item.source}")
    if report.stop_reason == "settlement_defect":
        return 4
    if report.stage != "run" or report.stop_reason == "unsupported_goal":
        return 2
    return 0 if report.stop_reason == "witness_completed" and report.goal_status == "met" else 3


if __name__ == "__main__":
    raise SystemExit(main())
