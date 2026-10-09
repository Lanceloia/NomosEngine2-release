"""Run serial AB/BA comparisons with isolated cores and shared author inputs."""

from __future__ import annotations

import argparse
import gc
import io
import json
import os
import statistics
import subprocess
import sys
from contextlib import redirect_stderr
from hashlib import sha256
from pathlib import Path
from time import perf_counter, process_time

import yaml


def verdict(ratios):
    if len(ratios) < 4 or any(value <= 0 for value in ratios):
        raise ValueError("performance gate needs at least four positive paired ratios")
    if max(ratios) / min(ratios) > 1.10:
        return "noisy" if len(ratios) < 8 else "inconclusive"
    required = len(ratios) - 1 if len(ratios) == 4 else 6
    return (
        "passed"
        if statistics.median(ratios) <= 1.05 and sum(value <= 1.05 for value in ratios) >= required
        else "regressed"
    )


def input_fingerprint(bundle_path, resources):
    paths = sorted(bundle_path.parent.rglob("*.yaml"))
    paths += [
        resources / f"parcel_delivery_v0.{suffix}"
        for suffix in ("lib.json", "ports.json", "source.json", "a.assets.json")
    ]
    return {str(path.resolve()): sha256(path.read_bytes()).hexdigest() for path in paths}


def positive_count(value):
    count = int(value)
    if count <= 0:
        raise argparse.ArgumentTypeError("sample repetition count must be positive")
    return count


def worker(
    core: Path, bundle_path: Path, resources: Path, *, parcel_only=False, parcel_sessions=256
):
    # Only benchmark helpers come from this checkout; executable cores are explicit.
    sys.path[:0] = [str(core / "src"), str(core / "engine/kernel/src")]
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from nomos_kernel._settlement_outcome_abi import K0Published

    from nomos_c0.author_document_v1 import read_author_document
    from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
    from nomos_c0.declarative_nominal_v0 import check_nominal_lib
    from nomos_c0.owner_graph_v1 import compile_owner_graph
    from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle
    from tools.c0_benchmark_m1_continue import measure_program
    from tools.c0_benchmark_m1_route import Journey, payload_json
    from tools.c0_profile_pipeline import _local_value, _snapshot_digest

    def emit(value):
        print(json.dumps(value), flush=True)

    fingerprint = input_fingerprint(bundle_path, resources)
    started = perf_counter()
    bundle = None if parcel_only else read_source_bundle(bundle_path)
    program = None if parcel_only else compile_source_bundle(bundle)
    compile_seconds = perf_counter() - started
    docs = [
        read_author_document(resources / f"parcel_delivery_v0.{suffix}")
        for suffix in ("lib.json", "ports.json", "source.json", "a.assets.json")
    ]
    started = perf_counter()
    parcel = compile_owner_graph(check_graph_ports(docs[1], check_nominal_lib(docs[0])), docs[2])
    parcel_compile_seconds = perf_counter() - started
    assets = None if parcel_only else bundle.assets.to_data()

    def checked_origins():
        origins = {
            name: module.__file__
            for name, module in sys.modules.items()
            if name.startswith("nomos_") and getattr(module, "__file__", None)
        }
        if any(
            not Path(path).resolve().is_relative_to(core.resolve()) for path in origins.values()
        ):
            raise RuntimeError("benchmark imported a core outside its selected root")
        return origins

    def history_digest(session):
        snapshot = session.author_snapshot()
        refs = {row.owner: row.individual for row in snapshot.objects}
        refs.update({row.owner: row.actor for row in snapshot.actors})
        histories = (session._runtime.action_value_history(), session.appraisal_history())
        normalized = _local_value(histories, session._runtime._individual_scope, refs)
        return sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()

    emit(
        {
            "ready": True,
            "compile_seconds": compile_seconds,
            "parcel_compile_seconds": parcel_compile_seconds,
            "origins": checked_origins(),
            "input_fingerprint": fingerprint,
            "python": sys.version,
            "yaml": yaml.__version__,
            "parcel_sessions_per_pair": parcel_sessions,
        }
    )
    for line in sys.stdin:
        command = json.loads(line)["sample"]
        if command == "quit":
            return
        gc.collect()
        if command == "short":
            report = measure_program(program, assets)
        elif command == "parcel":
            run_seconds = start_seconds = run_cpu_seconds = 0.0
            digests = []
            for _ in range(parcel_sessions):
                started = perf_counter()
                session = parcel.start(docs[3].to_data())
                start_seconds += perf_counter() - started
                cpu_started = process_time()
                started = perf_counter()
                offer = session.form_frame("sender").offers[0]
                if not isinstance(
                    session.submit("sender", offer.entry, dict(offer.payload)), K0Published
                ):
                    raise RuntimeError("parcel dispatch rejected")
                dispatched_count = len(session._runtime.occurrence_history())
                session.defer_form("sender")
                session.defer_form("receiver")
                deferred_count = len(session._runtime.occurrence_history())
                session.continue_form("receiver")
                due_source = session._runtime.occurrence_history()[-1].source.value
                offer = session.form_frame("receiver").offers[0]
                if not isinstance(
                    session.submit("receiver", offer.entry, dict(offer.payload)), K0Published
                ):
                    raise RuntimeError("parcel confirmation rejected")
                run_seconds += perf_counter() - started
                run_cpu_seconds += process_time() - cpu_started
                snapshot = session.author_snapshot()
                scene = dict(snapshot.owners)["scene"]
                receiver = dict(snapshot.owners)["receiver"]
                if (
                    dispatched_count != 4
                    or deferred_count != 4
                    or due_source != "c0.parcel.arrive.due"
                    or snapshot.occurrences[-1].source.value != "c0.parcel.confirm"
                    or len(snapshot.occurrences) != 6
                    or receiver.receipt is None
                    or scene.parcel.status != "arrived"
                    or len(snapshot.form_choices) != 2
                ):
                    raise RuntimeError("parcel sample did not perform its declared work")
                digests.append(_snapshot_digest(snapshot, session._runtime._individual_scope))
                del session
            report = {
                "run_seconds": run_seconds,
                "start_seconds": start_seconds,
                "digests": digests,
                "sessions_per_pair": parcel_sessions,
                "run_cpu_seconds": run_cpu_seconds,
            }
        elif command == "full":
            started = perf_counter()
            session = program.start(assets)
            start_seconds = perf_counter() - started
            journey = Journey(session)
            started = perf_counter()
            with redirect_stderr(io.StringIO()):
                journey.rescue()
            run_seconds = perf_counter() - started
            frame = session.form_frame("adventurer")
            snapshot = session.author_snapshot()
            resident = dict(snapshot.owners)["ritual_resident"]
            if (
                not frame.finished
                or frame.outcome != "departed_palace"
                or resident.site != "palace_exit"
                or resident.rescue_state != "safe"
                or resident.vital.life != "alive"
                or resident.rescue_ref is None
                or dict(snapshot.owners)["ritual"].status != "interrupted"
            ):
                raise RuntimeError("full route did not reach its existing terminal outcome")
            report = {
                "run_seconds": run_seconds,
                "start_seconds": start_seconds,
                "state_digest": _snapshot_digest(snapshot, session._runtime._individual_scope),
                "occurrences": len(snapshot.occurrences),
                "time": session.time,
                "actions": json.loads(json.dumps(journey.actions, default=payload_json)),
                "history_digest": history_digest(session),
            }
            del journey, session
        else:
            raise ValueError("unknown measurement sample")
        if input_fingerprint(bundle_path, resources) != fingerprint:
            raise RuntimeError("author inputs changed during measurement")
        checked_origins()
        emit(report)


class CoreWorker:
    def __init__(self, core, bundle, resources, *, parcel_only=False, parcel_sessions=256):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--worker",
                str(core),
                "--bundle",
                str(bundle),
                "--resources",
                str(resources),
                "--parcel-sessions-per-pair",
                str(parcel_sessions),
                *(["--sample", "parcel"] if parcel_only else []),
            ],
            cwd="/tmp",
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            self.ready = self.receive()
        except BaseException:
            self.close()
            raise

    def receive(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"measurement worker stopped: {self.process.poll()}")
        return json.loads(line)

    def measure(self, sample):
        self.process.stdin.write(json.dumps({"sample": sample}) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait()


def comparable(sample, before, after):
    if sample == "parcel":
        for row in (before, after):
            if len(row["digests"]) != row["sessions_per_pair"]:
                raise RuntimeError("parcel comparison has an incomplete aggregate")
        keys = ("digests", "sessions_per_pair")
    else:
        keys = ("state_digest", "occurrences", "time")
    if sample == "short":
        keys += ("inputs", "assets_digest", "action_value_history", "appraisal_digest")
    if sample == "full":
        keys += ("actions", "history_digest")
    if any(before[key] != after[key] for key in keys):
        raise RuntimeError(f"{sample} comparison has a semantic difference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--sample", choices=("short", "parcel"), action="append")
    parser.add_argument("--parcel-sessions-per-pair", type=positive_count, default=256)
    args = parser.parse_args()
    if args.full and args.sample and set(args.sample) != {"short", "parcel"}:
        parser.error("full gate requires both short and parcel samples")
    if args.worker:
        worker(
            args.worker.resolve(),
            args.bundle.resolve(),
            args.resources.resolve(),
            parcel_only=args.sample == ["parcel"] and not args.full,
            parcel_sessions=args.parcel_sessions_per_pair,
        )
        return
    if not args.baseline or not args.candidate or not args.output:
        parser.error("paired gate needs --baseline, --candidate, --output")
    workers = []
    report = {
        "python": sys.version.split()[0],
        "samples": {},
        "input_fingerprint": input_fingerprint(args.bundle, args.resources),
        "noise_extension": "all eight ratios, median <=1.05 and at least six <=1.05",
        "gc": "collect before each aggregate sample; normal automatic GC during Run",
        "parcel_sessions_per_pair": args.parcel_sessions_per_pair,
    }
    report["cores"] = [
        {
            "root": str(root.resolve()),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "status": subprocess.check_output(["git", "status", "--short"], cwd=root, text=True),
        }
        for root in (args.baseline, args.candidate)
    ]
    try:
        for core in (args.baseline, args.candidate):
            workers.append(
                CoreWorker(
                    core.resolve(),
                    args.bundle.resolve(),
                    args.resources.resolve(),
                    parcel_only=args.sample == ["parcel"] and not args.full,
                    parcel_sessions=args.parcel_sessions_per_pair,
                )
            )
        report["builds"] = [item.ready for item in workers]
        if any(
            row["input_fingerprint"] != report["input_fingerprint"]
            or row["parcel_sessions_per_pair"] != args.parcel_sessions_per_pair
            for row in report["builds"]
        ):
            raise RuntimeError("workers did not compile identical author bytes")
        for sample in args.sample or ("short", "parcel"):
            pairs = []
            for index in range(8):
                order = (0, 1) if index % 2 == 0 else (1, 0)
                rows = {}
                for variant in order:
                    rows[variant] = workers[variant].measure(sample)
                comparable(sample, rows[0], rows[1])
                pairs.append(
                    {
                        "order": order,
                        "baseline": rows[0],
                        "candidate": rows[1],
                        "ratio": rows[1]["run_seconds"] / rows[0]["run_seconds"],
                    }
                )
                status = verdict([row["ratio"] for row in pairs]) if index >= 3 else "noisy"
                print(
                    f"{sample} pair {index + 1}: {pairs[-1]['ratio']:.4f} {status}",
                    file=sys.stderr,
                    flush=True,
                )
                if index >= 3 and status != "noisy":
                    break
            report["samples"][sample] = {"status": status, "pairs": pairs}
        if args.full and all(row["status"] == "passed" for row in report["samples"].values()):
            before, after = [item.measure("full") for item in workers]
            comparable("full", before, after)
            report["full"] = {
                "baseline": before,
                "candidate": after,
                "ratio": after["run_seconds"] / before["run_seconds"],
            }
    finally:
        for item in workers:
            item.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value["status"] for key, value in report["samples"].items()}))
    if any(row["status"] != "passed" for row in report["samples"].values()):
        raise SystemExit(2)
    if report.get("full", {}).get("ratio", 1) > 1.05:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
