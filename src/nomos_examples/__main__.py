"""Run shipped declarations through the same C0 terminal, without checkout paths."""

import argparse
from pathlib import Path

from nomos_c0.owner_graph_play_v1 import main as play

from . import everflame_bundle_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", choices=("werewolf", "everflame"))
    parser.add_argument("--author-diagnostics", action="store_true")
    args = parser.parse_args(argv)
    if args.world == "everflame":
        if args.author_diagnostics:
            parser.error("Everflame player entry does not expose author diagnostics")
        return play(["--bundle", str(everflame_bundle_path()), "--player-view"])
    import nomos_c0

    root = Path(nomos_c0.__file__).resolve().parent / "examples"
    paths = (
        ("lib", "three_seat_werewolf_v0.lib.yaml"),
        ("ports", "three_seat_werewolf_v0.ports.yaml"),
        ("source", "six_seat_werewolf_v0.source.yaml"),
        ("assets", "six_seat_werewolf_v0.assets.yaml"),
    )
    command = [part for kind, filename in paths for part in (f"--{kind}", str(root / filename))]
    if args.author_diagnostics:
        command.append("--author-diagnostics")
    return play(command)


if __name__ == "__main__":
    raise SystemExit(main())
