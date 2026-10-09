"""Measure a short real M1 NPC/due replay, separate from Compile and Start."""

from __future__ import annotations

import argparse
import cProfile
import json
from contextlib import nullcontext
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0 import source_bundle_v1
from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle
from tools.c0_profile_pipeline import _snapshot_digest


def measure(bundle_path: Path, *, profile_path: Path | None = None, run_observer=None):
    if profile_path is not None and run_observer is not None:
        raise ValueError("use one observer at a time")
    started = perf_counter()
    bundle = read_source_bundle(bundle_path)
    program = compile_source_bundle(bundle)
    compile_seconds = perf_counter() - started
    return measure_program(
        program,
        bundle.assets.to_data(),
        compile_seconds=compile_seconds,
        profile_path=profile_path,
        run_observer=run_observer,
    )


def measure_program(program, assets, *, compile_seconds=None, profile_path=None, run_observer=None):
    """Run the same short route from a fresh Session; allow diagnostic build experiments."""
    if profile_path is not None and run_observer is not None:
        raise ValueError("use one observer at a time")
    started = perf_counter()
    session = program.start(assets)
    start_seconds = perf_counter() - started
    profiler = cProfile.Profile() if profile_path is not None else None
    continue_seconds = submit_seconds = 0.0
    inputs = []
    if profiler is not None:
        profiler.enable()
    with nullcontext() if run_observer is None else run_observer:
        for index in range(3):
            started = perf_counter()
            frame = session.continue_form("adventurer")
            continue_seconds += perf_counter() - started
            if frame.finished or frame.ready_seats != ("adventurer",):
                raise ValueError("short benchmark lost its current player opportunity")
            if index < 2:
                matches = [offer for offer in frame.offers if offer.entry == "wait_adventurer"]
                if len(matches) != 1:
                    raise ValueError("short benchmark needs one current paid wait offer")
                inputs.append(
                    {
                        "entry": matches[0].entry,
                        "payload": dict(matches[0].payload),
                        "at": session.time,
                    }
                )
                started = perf_counter()
                result = session.submit("adventurer", matches[0].entry, dict(matches[0].payload))
                submit_seconds += perf_counter() - started
                if not isinstance(result, K0Published):
                    raise ValueError("short benchmark wait was not admitted")
    if profiler is not None:
        profiler.disable()
        profiler.dump_stats(profile_path)
    snapshot = session.author_snapshot()
    return {
        "profiled": profiler is not None,
        "compile_including_load_seconds": compile_seconds,
        "start_seconds": start_seconds,
        "continue_seconds": continue_seconds,
        "submit_seconds": submit_seconds,
        "run_seconds": continue_seconds + submit_seconds,
        "time": session.time,
        "occurrences": len(snapshot.occurrences),
        "state_digest": _snapshot_digest(snapshot, session._runtime._individual_scope),
        "assets_digest": sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest(),
        "inputs": inputs,
        "action_value_history": [asdict(row) for row in session._runtime.action_value_history()],
        "compiler_origin": source_bundle_v1.__file__,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    report = measure(args.bundle, profile_path=args.profile)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({key: value for key, value in report.items() if key != "action_value_history"})
    )


if __name__ == "__main__":
    main()
