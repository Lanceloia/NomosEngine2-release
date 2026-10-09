"""Verify installed resources and real submissions outside an engine checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

from nomos_kernel._settlement_outcome_abi import K0Published

import nomos_c0
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.source_bundle_v1 import compile_source_bundle, read_source_bundle
from nomos_examples import everflame_bundle_path


def verify(world: str) -> dict[str, object]:
    started = perf_counter()
    if world == "everflame":
        bundle = read_source_bundle(everflame_bundle_path())
        program = compile_source_bundle(bundle)
        assets = bundle.assets.to_data()
        seat, entry = "adventurer", "wait_adventurer"
    else:
        root = Path(nomos_c0.__file__).resolve().parent / "examples"
        lib, ports, source, opening = (
            read_author_document(root / filename)
            for filename in (
                "three_seat_werewolf_v0.lib.yaml",
                "three_seat_werewolf_v0.ports.yaml",
                "six_seat_werewolf_v0.source.yaml",
                "six_seat_werewolf_v0.assets.yaml",
            )
        )
        nominal = check_nominal_lib(lib, source.to_data().get("actor_domains"))
        program = compile_owner_graph(check_graph_ports(ports, nominal), source)
        assets = opening.to_data()
        seat, entry = "A", "vote_a"
    compile_seconds = perf_counter() - started
    started = perf_counter()
    session = program.start(assets)
    start_seconds = perf_counter() - started
    started = perf_counter()
    if world == "everflame":
        frame = session.continue_form(seat)
        offers = frame.offers
    else:
        offers = session.offers(seat)
    offer = next(row for row in offers if row.entry == entry)
    result = session.submit(seat, offer.entry, dict(offer.payload))
    if not isinstance(result, K0Published):
        raise RuntimeError("installed demo Action was not published")
    run_seconds = perf_counter() - started
    prefix = Path(sys.prefix).resolve()
    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in sys.modules.items()
        if name.startswith("nomos_") and getattr(module, "__file__", None)
    }
    if any(not Path(origin).is_relative_to(prefix) for origin in origins.values()):
        raise RuntimeError("installed smoke imported code outside its environment")
    return {
        "world": world,
        "python": sys.version.split()[0],
        "compile_seconds": compile_seconds,
        "start_seconds": start_seconds,
        "run_seconds": run_seconds,
        "entry": offer.entry,
        "time": session.author_snapshot().time,
        "published_sources": [item.source.value for item in result.occurrences],
        "occurrence_count": len(session._runtime.occurrence_history()),
        "origins": origins,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", choices=("werewolf", "everflame"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.world)
    if args.output is not None:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "origins"}
            | {"verified_module_origins": len(report["origins"])},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
