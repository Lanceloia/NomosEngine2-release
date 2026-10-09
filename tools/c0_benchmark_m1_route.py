"""Time a shipped M1 core-rescue route through real current offers to termination."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle
from tools.c0_profile_pipeline import _snapshot_digest


def payload_json(value):
    # Current offers supply local references; full snapshot comparison separately
    # preserves foreign identities. Never serialize opaque scope as an input key.
    if type(value) in (_K0IndividualRef, _K0ActorRef):
        return {
            "kind": type(value).__name__,
            "family": value.family,
            "ordinal": value.ordinal,
            "scope": "local",
        }
    if type(value) is K0OccurrenceRef:
        return {"kind": "K0OccurrenceRef", "value": value.value}
    raise TypeError(f"unsupported benchmark payload: {type(value).__name__}")


class Journey:
    def __init__(self, session):
        self.session = session
        self.seconds = defaultdict(float)
        self.actions = []
        self.calls = []

    def timed(self, phase, operation):
        before = self.session.time
        started = perf_counter()
        result = operation()
        elapsed = perf_counter() - started
        self.seconds[phase] += elapsed
        self.calls.append(
            {
                "phase": phase,
                "completed_actions": len(self.actions),
                "before_time": before,
                "after_time": self.session.time,
                "seconds": elapsed,
            }
        )
        return result

    def frame(self):
        frame = self.timed("continue", lambda: self.session.continue_form("adventurer"))
        if frame.finished or frame.ready_seats != ("adventurer",):
            raise ValueError(f"route lost player opportunity: {frame.outcome}")
        return frame

    def choose(self, entry, **wanted):
        frame = self.frame()
        matches = [
            row
            for row in frame.offers
            if row.entry == entry
            and all(dict(row.payload).get(key) == value for key, value in wanted.items())
        ]
        if len(matches) != 1:
            raise ValueError(f"route needs exactly one current offer: {entry} {wanted}")
        offer = matches[0]
        result = self.timed(
            "submit", lambda: self.session.submit("adventurer", entry, dict(offer.payload))
        )
        if not isinstance(result, K0Published):
            raise ValueError(f"route Action rejected: {entry}")
        self.actions.append(
            {"entry": entry, "payload": dict(offer.payload), "time": self.session.time}
        )
        print(f"{len(self.actions)} time={self.session.time}: {entry}", file=sys.stderr, flush=True)

    def local_site(self):
        view = self.timed("read", lambda: self.session.read("adventurer"))
        return dict(view.fields)["adventurer.site"]

    def cross(self, crossing, destination):
        self.choose("cross_ice_adventurer", crossing=crossing)
        for _ in range(12):
            if self.local_site() == destination:
                return
            options = [
                row
                for row in self.frame().offers
                if row.entry == "cross_ice_adventurer"
                and (
                    dict(row.payload)["crossing"].startswith("recover_")
                    or dict(row.payload)["crossing"] == crossing
                )
            ]
            if len(options) != 1:
                raise ValueError("route recovery is not a unique current offer")
            self.choose(options[0].entry, **dict(options[0].payload))
        if self.local_site() != destination:
            raise ValueError("route crossing did not reach the selected destination")

    def floor(self):
        self.choose("observe_floor_adventurer")
        if any(row.entry == "thaw_floor_adventurer" for row in self.frame().offers):
            self.choose("thaw_floor_adventurer")

    def rescue(self):
        # Replay the existing same-opening integration witness, not an authored plot.
        self.cross("entrance_to_ritual", "ritual_passage_entry")
        self.choose("move_adventurer", destination="ritual_threshold")
        self.choose("move_adventurer", destination="ritual_ring")
        self.choose("carry_from_ritual_adventurer")
        self.choose("observe_routes_adventurer")
        self.choose("move_adventurer", destination="ritual_passage_entry")
        self.cross("ritual_to_entrance", "ballroom_entrance")
        self.choose("observe_routes_adventurer")
        self.cross("entrance_to_chandelier", "ballroom_chandelier_reach")
        self.choose("observe_chandelier_adventurer")
        self.choose("detach_reservoir_adventurer")
        self.floor()
        self.choose("reload_everflame_adventurer")
        self.choose("observe_routes_adventurer")
        self.cross("chandelier_to_entrance", "ballroom_entrance")
        self.cross("entrance_to_ritual", "ritual_passage_entry")
        self.choose("move_adventurer", destination="ritual_threshold")
        self.choose("observe_resident_adventurer", victim="ritual_resident")
        self.choose("thaw_person_adventurer", victim="ritual_resident")
        self.choose("offer_escort_adventurer")
        self.choose("move_adventurer", destination="ritual_passage_entry")
        self.cross("ritual_to_entrance", "ballroom_entrance")
        self.choose("move_adventurer", destination="halls_ballroom_door")
        self.choose("observe_routes_adventurer")
        self.cross("halls_to_bridge_door", "halls_bridge_door")
        self.choose("observe_routes_adventurer")
        self.choose("move_adventurer", destination="bridge_palace_landing")
        self.choose("observe_routes_adventurer")
        self.floor()
        self.choose("bridge_slow_adventurer", destination="bridge_midspan")
        self.choose("observe_routes_adventurer")
        self.floor()
        self.choose("bridge_slow_adventurer", destination="palace_exit")
        for _ in range(8):
            self.choose("wait_adventurer")
        self.choose("leave_palace_adventurer")


def measure(bundle_path, rounds):
    started = perf_counter()
    bundle = read_source_bundle(bundle_path)
    load_seconds = perf_counter() - started
    started = perf_counter()
    program = compile_source_bundle(bundle)
    compile_seconds = perf_counter() - started
    assets = bundle.assets.to_data()
    results = []
    for index in range(rounds):
        print(f"round {index + 1} starting", file=sys.stderr, flush=True)
        started = perf_counter()
        session = program.start(assets)
        start_seconds = perf_counter() - started
        journey = Journey(session)
        started = perf_counter()
        journey.rescue()
        run_seconds = perf_counter() - started
        frame = journey.timed("terminal", lambda: session.form_frame("adventurer"))
        snapshot = session.author_snapshot()
        owners = dict(snapshot.owners)
        resident = owners["ritual_resident"]
        if not (
            frame.finished
            and frame.outcome == "departed_palace"
            and resident.site == "palace_exit"
            and resident.rescue_state == "safe"
            and resident.vital.life == "alive"
            and resident.rescue_ref is not None
            and owners["ritual"].status == "interrupted"
        ):
            raise ValueError("core-rescue route did not achieve its existing witness outcome")
        results.append(
            {
                "start_seconds": start_seconds,
                "run_seconds": run_seconds,
                "phase_seconds": dict(journey.seconds),
                "calls": journey.calls,
                "terminal_outcome": frame.outcome,
                "final_time": session.time,
                "actions": journey.actions,
                "occurrence_count": len(snapshot.occurrences),
                "state_digest": _snapshot_digest(snapshot, session._runtime._individual_scope),
            }
        )
    return {
        "python": platform.python_version(),
        "compiler_origin": sys.modules[compile_source_bundle.__module__].__file__,
        "kernel_origin": sys.modules[K0Published.__module__].__file__,
        "bundle": str(bundle_path.resolve()),
        "assets_digest": sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest(),
        "load_seconds": load_seconds,
        "compile_seconds": compile_seconds,
        "runs": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.bundle, args.rounds)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=payload_json) + "\n"
    )
    print(
        json.dumps(
            {
                "load_seconds": report["load_seconds"],
                "compile_seconds": report["compile_seconds"],
                "runs": [
                    {
                        key: row[key]
                        for key in (
                            "start_seconds",
                            "run_seconds",
                            "terminal_outcome",
                            "final_time",
                            "occurrence_count",
                            "state_digest",
                        )
                    }
                    for row in report["runs"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
