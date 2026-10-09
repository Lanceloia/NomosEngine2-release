"""Measure one authored pipeline and a bounded repeated current-offer replay."""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from nomos_kernel import K0OwnerKey
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from nomos_kernel._settlement_outcome_abi import K0Published

from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.program_start_v1 import check_assets


def _local_value(value, scope, owner_refs):
    if type(value) in (_K0IndividualRef, _K0ActorRef):
        identity = {"kind": type(value).__name__, "family": value.family, "ordinal": value.ordinal}
        identity["scope"] = {"local": True} if value.scope == scope else {"foreign": value.scope}
        return identity
    if type(value) is K0OwnerKey and value in owner_refs:
        return {"owner_of": _local_value(owner_refs[value], scope, owner_refs)}
    if type(value) in (str, int, bool, float, type(None)):
        return value
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "record": type(value).__name__,
            "fields": {
                item.name: _local_value(getattr(value, item.name), scope, owner_refs)
                for item in fields(value)
            },
        }
    if type(value) in (tuple, list):
        return [_local_value(item, scope, owner_refs) for item in value]
    raise TypeError(f"unsupported measurement value: {type(value).__name__}")


def _snapshot_digest(snapshot, scope):
    # Rename only this Session's opaque scope and its registered dynamic owner keys.
    # This is a replay comparison, not authentication or cross-session identity.
    owner_refs = {row.owner: row.individual for row in snapshot.objects}
    owner_refs.update({row.owner: row.actor for row in snapshot.actors})
    normalized = _local_value(snapshot, scope, owner_refs)
    return sha256(json.dumps(normalized, sort_keys=True, allow_nan=False).encode()).hexdigest()


def measure(
    lib_path: Path,
    ports_path: Path,
    source_path: Path,
    assets_path: Path,
    *,
    seat: str,
    entry: str,
    steps: int,
    profiling: bool = False,
) -> dict[str, object]:
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError("steps must be between 1 and 100")
    stages = []
    reads = 0
    tracking_reads = False

    def stage(name: str, operation: Callable):
        before_reads = reads
        started = perf_counter()
        result = operation()
        stages.append(
            {
                "stage": name,
                "seconds": round(perf_counter() - started, 6),
                "owner_reads": reads - before_reads if tracking_reads else None,
            }
        )
        return result

    profiles = {name: cProfile.Profile() for name in ("compile", "run")}

    lib, ports, source, assets = stage(
        "load",
        lambda: tuple(
            read_author_document(path) for path in (lib_path, ports_path, source_path, assets_path)
        ),
    )
    assets = assets.to_data()
    if profiling:
        profiles["compile"].enable()
    nominal = stage(
        "nominal", lambda: check_nominal_lib(lib, source.to_data().get("actor_domains"))
    )
    library = stage("ports", lambda: check_graph_ports(ports, nominal))
    ir, layout = stage("check_source", lambda: check_owner_graph(library, source))
    program = stage("backend", lambda: bind_program(ir, layout))
    profiles["compile"].disable()
    # Standalone Assets cost is reported separately; Start includes its own check.
    stage("check_assets_standalone", lambda: check_assets(program, assets))
    session = stage("start_including_assets", lambda: program.start(assets))
    original_read = session._runtime.read_owner

    def read_owner(key):
        nonlocal reads
        reads += 1
        return original_read(key)

    if profiling:
        profiles["run"].enable()
    with patch.object(session._runtime, "read_owner", read_owner):
        tracking_reads = True
        for index in range(steps):
            stage(f"continue_{index}", lambda: session.continue_form(seat))
            stage(f"read_{index}", lambda: session.read(seat))
            offers = stage(f"offers_{index}", lambda: session.offers(seat))
            selected = tuple(offer for offer in offers if offer.entry == entry)
            if len(selected) != 1:
                raise ValueError("replay entry must select exactly one current offer")
            result = stage(
                f"submit_{index}",
                lambda: session.submit(seat, entry, dict(selected[0].payload)),
            )
            if not isinstance(result, K0Published):
                raise ValueError("replay Action was not published")
    profiles["run"].disable()
    snapshot = session.author_snapshot()
    report = {
        "profiled": profiling,
        "stages": stages,
        "final_time": session.time,
        "local_state_digest": _snapshot_digest(snapshot, session._runtime._individual_scope),
        "occurrences": [
            {
                "ref": occurrence.occurrence.value,
                "family": occurrence.family.value,
                "source": occurrence.source.value,
                "classification": occurrence.classification.value,
            }
            for occurrence in session._runtime.occurrence_history()
        ],
    }
    if profiling:
        for name, profile in profiles.items():
            print(f"\n{name.upper()} (cProfile timings)")
            pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(18)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lib", "ports", "source", "assets"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.lib,
                args.ports,
                args.source,
                args.assets,
                seat=args.seat,
                entry=args.entry,
                steps=args.steps,
                profiling=args.profile,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
