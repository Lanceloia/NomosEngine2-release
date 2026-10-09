"""Thin terminal for a non-canon world compiled from Lib, Source, and Assets."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields, is_dataclass
from pathlib import Path

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._settlement_outcome_abi import K0Published, K0SettlementDefect

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_contracts_v1 import C0GraphLibrary
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_runtime_v1 import C0ControlCommand, C0OwnerGraphSession

ROOT = Path(__file__).resolve().parent
_DEFAULT_NOMINAL = check_nominal_lib(
    (ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8")
)
SCENE_KEY = _DEFAULT_NOMINAL.owner("scene").owner.key
SENDER_KEY = _DEFAULT_NOMINAL.owner("sender").owner.key
RECEIVER_KEY = _DEFAULT_NOMINAL.owner("receiver").owner.key
Parcel = _DEFAULT_NOMINAL.record("Parcel")
Receipt = _DEFAULT_NOMINAL.record("Receipt")


def library() -> C0GraphLibrary:
    return check_graph_ports(
        (ROOT / "parcel_delivery_v0.ports.json").read_text(encoding="utf-8"),
        _DEFAULT_NOMINAL,
    )


def open_session(
    assets_path: Path,
    source_path: Path | None = None,
    lib_path: Path | None = None,
    ports_path: Path | None = None,
) -> C0OwnerGraphSession:
    source = (ROOT / "parcel_delivery_v0.source.json") if source_path is None else source_path
    lib = (ROOT / "parcel_delivery_v0.lib.json") if lib_path is None else lib_path
    ports = (ROOT / "parcel_delivery_v0.ports.json") if ports_path is None else ports_path
    checked = (
        _DEFAULT_NOMINAL if lib_path is None else check_nominal_lib(lib.read_text(encoding="utf-8"))
    )
    graph = check_graph_ports(ports.read_text(encoding="utf-8"), checked)
    program = compile_owner_graph(graph, source.read_text(encoding="utf-8"))
    return program.start(assets_path.read_text(encoding="utf-8"))


def _render(value: object) -> str:
    if type(value) is K0OccurrenceRef:
        return f"ref:{value.value}"
    if is_dataclass(value):
        return json.dumps({item.name: _render(getattr(value, item.name)) for item in fields(value)})
    return str(value)


def play(session: C0OwnerGraphSession) -> None:
    form = session.program.game_form
    if form is None:
        raise C0BindingError("parcel terminal needs an event-jump GameForm")
    seat = form.seats[0]
    while True:
        frame = session.form_frame(seat)
        if frame.ready_seats and seat not in frame.ready_seats:
            seat = frame.ready_seats[0]
            frame = session.form_frame(seat)
        print(f"\nTime {frame.time} | seat {seat}")
        for path, value in frame.view.fields:
            print(f"  {path}: {_render(value)}")
        if frame.finished:
            print("Delivery session finished.")
            return
        choices: list[tuple[str, str, object | None]] = (
            [(offer.label, "action", offer) for offer in frame.offers]
            if seat in frame.ready_seats
            else []
        )
        if seat in frame.ready_seats:
            label = (
                "Pass available actions (no world action)"
                if frame.offers
                else "Finish this seat's turn (no world action)"
            )
            choices.append((label, "pass", None))
        for other in frame.ready_seats:
            if other != seat:
                choices.append((f"Switch to {other}", "switch", other))
        if not frame.ready_seats:
            choices.append(("Advance to next event", "advance", None))
        choices.append(("Quit", "quit", None))
        print("Choose:")
        for index, (label, _, _) in enumerate(choices, start=1):
            print(f"  {index}. {label}")
        if seat in frame.ready_seats:
            for fault in frame.offer_faults:
                print(f"  Unavailable: {fault.label} ({fault.code})")
        try:
            command = input("> ").strip()
        except EOFError:
            return
        if command == "quit":
            return
        if (
            not command.isascii()
            or not command.isdecimal()
            or len(command) > len(str(len(choices)))
        ):
            print("Enter one of the listed numbers.")
            continue
        number = int(command)
        if not 1 <= number <= len(choices):
            print("Enter one of the listed numbers.")
            continue
        _, kind, selected = choices[number - 1]
        try:
            if kind == "quit":
                return
            if kind == "switch":
                seat = selected
                print(f"Switched to {seat}.")
            elif kind == "pass":
                session.apply_control(C0ControlCommand("defer", seat))
                print(f"{seat} passed; no world Action was made.")
                if not session.form_frame(seat).ready_seats:
                    before = session.time
                    advanced = session.apply_control(C0ControlCommand("continue", seat))
                    print(f"Time advanced {before} -> {advanced.result.time}.")
            elif kind == "advance":
                before = session.time
                advanced = session.apply_control(C0ControlCommand("continue", seat))
                print(f"Time advanced {before} -> {advanced.result.time}.")
            else:
                outcome = session.apply_control(
                    C0ControlCommand("submit", seat, offer=selected)
                ).result
                print(
                    "Action settled; world state updated."
                    if isinstance(outcome, K0Published)
                    else "Action not admitted; world state unchanged."
                )
        except C0BindingError:
            print("That choice is no longer available; world state unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-canon C0 parcel delivery world")
    parser.add_argument("--lib", type=Path)
    parser.add_argument("--ports", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--assets", type=Path, default=ROOT / "parcel_delivery_v0.a.assets.json")
    args = parser.parse_args()
    try:
        session = open_session(args.assets, args.source, args.lib, args.ports)
    except (C0LawError, C0BindingError, OSError) as error:
        parser.exit(2, f"Cannot build parcel world: {error}\n")
    try:
        play(session)
    except K0SettlementDefect:
        parser.exit(3, "World settlement failed; this session is closed.\n")


if __name__ == "__main__":
    main()
