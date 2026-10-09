"""A small manual-seat terminal for authored C0 owner-graph programs."""

from __future__ import annotations

import argparse
from pathlib import Path

from nomos_kernel._settlement_outcome_abi import K0Published

from .author_contract_v1 import C0BindingError
from .author_diagnostics_v1 import render_author_guard_report
from .author_document_v1 import read_author_document
from .declarative_graph_ports_v0 import check_graph_ports
from .declarative_nominal_v0 import check_nominal_lib
from .graph_frontend_v1 import _source
from .owner_graph_v1 import compile_owner_graph
from .program_runtime_v1 import C0ControlCommand
from .seat_offers_v0 import C0SeatOffer
from .visibility_ir_v1 import C0SeatPresentation


def _files(name: str) -> tuple[Path, Path, Path, Path]:
    if not name.isidentifier():
        raise ValueError("example name must be an identifier")
    root = Path(__file__).resolve().parent / "examples"
    paths = []
    for part in ("lib", "ports", "source", "assets"):
        yaml_path = root / f"{name}.{part}.yaml"
        paths.append(yaml_path if yaml_path.is_file() else root / f"{name}.{part}.json")
    return tuple(paths)


def _player_field_lines(
    name: str,
    value: object,
    label: str,
    presentation: C0SeatPresentation,
    *,
    focus_key: str | None = None,
) -> tuple[str, ...]:
    if value is None or (type(value) is tuple and not value):
        return ()
    terms = dict(presentation.terms)
    columns = dict(presentation.projection_columns).get(name)
    if columns is None:
        displayed = terms.get(value, value) if type(value) is str else value
        return (f"  {label}: {displayed}",)
    if type(value) is not tuple:
        raise C0BindingError("player projection has a foreign row shape")
    keys = set()
    for row in value:
        if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str:
            raise C0BindingError("player projection has a foreign row shape")
        key, cells = row
        if (
            type(cells) is not tuple
            or any(
                type(cell) is not tuple or len(cell) != 2 or type(cell[0]) is not str
                for cell in cells
            )
            or len(dict(cells)) != len(cells)
            or set(dict(cells)) != set(dict(columns))
            or key in keys
        ):
            raise C0BindingError("player projection has a foreign column shape")
        keys.add(key)
    lines = [f"  {label}:"]
    for key, cells in value:
        if focus_key is not None and key != focus_key:
            continue
        displayed_cells = []
        for column, heading in columns:
            cell = dict(cells)[column]
            displayed = terms.get(cell, cell) if type(cell) is str else cell
            displayed_cells.append(f"{heading}: {displayed}")
        lines.append(f"    {terms.get(key, key)}: " + "; ".join(displayed_cells))
    if focus_key is not None and focus_key not in keys:
        lines.append("    No locally known row for the current focus.")
    return tuple(lines)


def _player_offer_label(offer: C0SeatOffer, presentation: C0SeatPresentation) -> str:
    if not offer.label_fragments:
        return offer.label
    terms = dict(presentation.terms)
    return "".join(
        terms.get(fragment, fragment) if is_value else fragment
        for fragment, is_value in offer.label_fragments
    )


def _player_publication_line(
    offer: C0SeatOffer, presentation: C0SeatPresentation, result: object
) -> str:
    if not isinstance(result, K0Published):
        return dict(presentation.rejected_actions).get(offer.entry, presentation.rejected)
    return dict(presentation.published_actions).get(offer.entry, presentation.published)


def _player_offer_lines(
    offers: tuple[C0SeatOffer, ...], presentation: C0SeatPresentation
) -> tuple[str, ...]:
    lines = []
    for index, offer in enumerate(offers, 1):
        lines.append(f"  {index}. {_player_offer_label(offer, presentation)}")
        columns = dict(presentation.preview_fields).get(offer.entry, ())
        if not columns:
            continue
        if not offer.preview:
            lines.append("     Forecast unavailable for this current choice.")
            continue
        values = dict(offer.preview)
        terms = dict(presentation.terms)
        for name, heading in columns:
            value = values.get(name)
            if type(value) not in (str, int, bool):
                raise C0BindingError("player preview has a foreign scalar shape")
            displayed = terms.get(value, value) if type(value) is str else value
            lines.append(f"     {heading}: {displayed}")
    return tuple(lines)


def _player_offer_change_lines(
    current: tuple[str, ...], previous: tuple[str, ...] | None
) -> tuple[str, ...]:
    if previous is None or current == previous:
        return ()
    return ("Available choices changed; check the current list below.",)


def _player_view_lines(
    fields: tuple[tuple[str, object], ...],
    presentation: C0SeatPresentation,
    previous: dict[str, tuple[str, ...]] | None,
    *,
    full: bool = False,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    labels = dict(presentation.fields)
    values = dict(fields)
    focuses = dict(presentation.projection_focus)
    focus_keys = {}
    for name, path in focuses.items():
        value = values.get(path)
        if type(value) is not str:
            raise C0BindingError("player focus lacks its visible string field")
        focus_keys[name] = value
    current = {
        name: _player_field_lines(
            name, value, labels[name], presentation, focus_key=focus_keys.get(name)
        )
        for name, value in fields
        if labels[name] is not None
    }
    if previous is not None:
        for name in previous:
            if labels.get(name) is not None:
                current.setdefault(name, ())
    if full:
        lines = ("Current view:",) + tuple(
            line
            for name, value in fields
            if labels[name] is not None
            for line in _player_field_lines(name, value, labels[name], presentation)
        )
    elif previous is None:
        lines = ("Current view:",) + tuple(line for rows in current.values() for line in rows)
    else:
        changed = tuple(
            line
            for name, rows in current.items()
            if rows != previous.get(name, ())
            for line in (rows or (f"  {labels[name]}: No longer present in this view.",))
        )
        lines = (
            ("Displayed values changed since the previous view:",) + changed
            if changed
            else ("No displayed values changed.",)
        )
    return lines, current


def _player_finish_lines(
    entry: str | None, fields: tuple[tuple[str, object], ...], presentation: C0SeatPresentation
) -> tuple[str, ...]:
    paths = dict(presentation.finish_fields).get(entry, ())
    if not paths:
        return ()
    values = dict(fields)
    labels = dict(presentation.fields)
    lines = ["Your retained local record:"]
    for path in paths:
        value = values.get(path)
        if value is None:
            continue
        if type(value) not in (str, int, bool):
            raise C0BindingError("player ending has a foreign scalar shape")
        lines.extend(_player_field_lines(path, value, labels[path], presentation))
    return tuple(lines)


def _remember_displayed_finish_fields(
    fields: tuple[tuple[str, object], ...],
    presentation: C0SeatPresentation,
    history: dict[str, list[tuple[int, tuple[str, ...]]]],
    display_frame: int,
    truncated: set[str],
) -> None:
    # This is a bounded terminal transcript, never Actor memory or an Event log.
    for entry, _ in presentation.finish_fields:
        lines = _player_finish_lines(entry, fields, presentation)[1:]
        if not lines:
            continue
        records = history.setdefault(entry, [])
        if records and records[-1][1] == lines:
            continue
        records.append((display_frame, lines))
        if len(records) > 64:
            del records[0]
            truncated.add(entry)


def _player_published_lines(
    entry: str,
    result: object,
    fields: tuple[tuple[str, object], ...],
    presentation: C0SeatPresentation,
) -> tuple[str, ...]:
    if not isinstance(result, K0Published):
        return ()
    paths = dict(presentation.published_fields).get(entry, ())
    if not paths:
        return ()
    values = dict(fields)
    labels = dict(presentation.fields)
    lines = ["Your local record immediately after this action:"]
    for path in paths:
        # Canonical seat reads omit optional None leaves, including cleared dice records.
        value = values.get(path)
        if value is None:
            lines.append(f"  {labels[path]}: Not present in this view.")
        elif type(value) in (str, int, bool):
            lines.extend(_player_field_lines(path, value, labels[path], presentation))
        else:
            raise C0BindingError("player action record has a foreign scalar shape")
    return tuple(lines)


def _player_finish_history_lines(
    entry: str,
    history: dict[str, list[tuple[int, tuple[str, ...]]]],
    truncated: set[str],
) -> tuple[str, ...]:
    records = history.get(entry, ())
    if not records:
        return ()
    lines = ["Earlier records displayed in this terminal (not current safety updates):"]
    if entry in truncated:
        lines.append("  Older displays omitted; only the latest 64 distinct displays are retained.")
    for frame, record in records:
        lines.append(f"  Display frame {frame} (not an observation count):")
        lines.extend(record)
    return tuple(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a manual-seat C0 owner-graph world")
    parser.add_argument("example", nargs="?", help="bundled example stem")
    parser.add_argument("--lib", type=Path)
    parser.add_argument("--ports", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--bundle", type=Path, help="explicit multi-file Source bundle")
    parser.add_argument(
        "--player-view", action="store_true", help="use the sole human seat's authored labels"
    )
    parser.add_argument(
        "--author-diagnostics",
        action="store_true",
        help="show trusted author guard origins on refusal",
    )
    args = parser.parse_args(argv)
    if args.player_view and args.author_diagnostics:
        parser.error("author diagnostics cannot be used with player view")
    specified = (args.lib, args.ports, args.source, args.assets)
    if args.bundle:
        if args.example or any(specified):
            parser.error("bundle cannot be combined with an example or individual authored paths")
        from .source_bundle_v1 import compile_source_bundle, read_source_bundle

        bundle = read_source_bundle(args.bundle)
        program = compile_source_bundle(bundle)
        assets = bundle.assets.to_data()
    else:
        if args.example and any(specified) or not args.example and not all(specified):
            parser.error("give a bundle, an example stem or all four authored paths")
        paths = _files(args.example) if args.example else specified
        lib_path, ports_path, source_path, assets_path = paths
        source = read_author_document(source_path)
        checked = check_nominal_lib(
            read_author_document(lib_path), _source(source).get("actor_domains")
        )
        library = check_graph_ports(read_author_document(ports_path), checked)
        program = compile_owner_graph(library, source)
        assets = read_author_document(assets_path).to_data()
    seats = tuple(item.symbol for item in program.seats)
    session = program.start(assets)
    seat = seats[0]
    presentation = None
    if args.player_view:
        human_seats = session.human_seats()
        if len(human_seats) != 1:
            parser.error("player view requires exactly one human-controlled seat")
        seat = human_seats[0]
        presentation = next(item.presentation for item in program.seats if item.symbol == seat)
        if presentation is None:
            parser.error("player view requires authored presentation for its human seat")
        print(presentation.title)
        if presentation.opening is not None:
            print(presentation.opening)
    else:
        print("Seats:", ", ".join(seats))
    finished_by_player: str | None = None
    finished_entry: str | None = None
    previous_view: dict[str, tuple[str, ...]] | None = None
    previous_offers: tuple[str, ...] | None = None
    displayed_history: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    truncated_history: set[str] = set()
    display_frame = 0
    show_full_view = True
    while True:
        temporal = program.profile.temporal_policy is not None
        manual_advance = temporal and program.game_form is None
        form = program.game_form is not None
        try:
            if form and args.player_view:
                frame = session.form_frame(seat)
                if not frame.finished:
                    frame = session.continue_form(seat)
            else:
                frame = session.form_frame(seat) if form else None
        except C0BindingError:
            if not args.player_view:
                raise
            print("World could not advance.")
            return 3
        if not args.player_view:
            print(f"\n[{seat}]" + (f" Time: {session.time}" if temporal else ""))
        else:
            print(f"\nTime: {session.time}" if temporal else "")
        if presentation is not None:
            try:
                local_fields = session.read(seat).fields
                visible_lines, previous_view = _player_view_lines(
                    local_fields,
                    presentation,
                    (
                        None
                        if show_full_view or (frame is not None and frame.finished)
                        else previous_view
                    ),
                    full=show_full_view,
                )
                _remember_displayed_finish_fields(
                    local_fields,
                    presentation,
                    displayed_history,
                    display_frame + 1,
                    truncated_history,
                )
            except C0BindingError:
                print("World could not render this view.")
                return 3
            for line in visible_lines:
                print(line)
            display_frame += 1
            show_full_view = False
        else:
            for name, value in session.read(seat).fields:
                print(f"  {name}: {value!r}")
        offers = session.offers(seat) if frame is None or seat in frame.ready_seats else ()
        if presentation is not None:
            try:
                offer_lines = _player_offer_lines(offers, presentation)
            except C0BindingError:
                print("World could not render these choices.")
                return 3
            for line in _player_offer_change_lines(offer_lines, previous_offers) + offer_lines:
                print(line)
            previous_offers = offer_lines
        else:
            for index, offer in enumerate(offers, 1):
                print(f"  {index}. {offer.label}")
        if frame is not None and frame.finished:
            if presentation is not None and finished_entry is not None:
                try:
                    recap = _player_finish_history_lines(
                        finished_entry, displayed_history, truncated_history
                    )
                except C0BindingError:
                    print("World could not render this ending.")
                    return 3
                for line in recap:
                    print(line)
            print(finished_by_player or "GameForm finished.")
            return 0
        if not form and not manual_advance and not any(session.offers(name) for name in seats):
            print(presentation.no_offers if presentation is not None else "No current offers.")
            return 0
        if manual_advance and not any(session.offers(name) for name in seats):
            print("No current offers; time may be advanced by an authorized seat.")
        try:
            prompt = (
                "Choose a number, 'view', or 'quit': "
                if presentation is not None
                else (
                    "Choice, 'seat NAME', 'advance TICK', or 'quit': "
                    if manual_advance
                    else "Choice, 'seat NAME', 'defer', 'continue', or 'quit': "
                    if form
                    else "Choice, 'seat NAME', or 'quit': "
                )
            )
            command = input(prompt).strip()
        except EOFError:
            return 0
        if command == "quit":
            return 0
        if presentation is not None and command == "view":
            show_full_view = True
            continue
        if form and not args.player_view and command in ("defer", "continue"):
            try:
                session.apply_control(C0ControlCommand(command, seat))
            except C0BindingError as error:
                print(f"GameForm control rejected: {error}")
            continue
        if command.startswith("seat "):
            if presentation is not None:
                print("Choose a current number, 'view', or 'quit'.")
                continue
            chosen = command[5:].strip()
            if chosen in seats:
                seat = chosen
            else:
                print("Unknown seat.")
            continue
        if manual_advance and command.startswith("advance "):
            target = command[8:].strip()
            if not target.isdecimal():
                print("Give a future integer tick.")
                continue
            try:
                session.apply_control(C0ControlCommand("advance", seat, target_time=int(target)))
            except C0BindingError as error:
                print(f"Advance rejected: {error}")
            else:
                print(f"Time: {session.time}")
            continue
        if not command.isdecimal() or not 1 <= int(command) <= len(offers):
            print(
                "Choose a current number, 'view', or 'quit'."
                if presentation is not None
                else "Choose a current numbered offer or switch seats."
            )
            continue
        offer = offers[int(command) - 1]
        try:
            result = session.apply_control(C0ControlCommand("submit", seat, offer=offer)).result
        except C0BindingError as error:
            print(f"Submission rejected: {error}")
            continue
        if presentation is not None:
            print(_player_publication_line(offer, presentation, result))
            if isinstance(result, K0Published) and offer.entry in dict(
                presentation.published_fields
            ):
                try:
                    # Read before GameForm continuation; this is not a new world observation.
                    action_lines = _player_published_lines(
                        offer.entry, result, session.read(seat).fields, presentation
                    )
                except C0BindingError:
                    print("World could not render this action record.")
                    return 3
                for line in action_lines:
                    print(line)
            finished_by_player = None
            finished_entry = None
            if form and isinstance(result, K0Published):
                try:
                    completed = session.form_frame(seat)
                except C0BindingError:
                    print("World could not advance.")
                    return 3
                if completed.finished:
                    finished_by_player = next(
                        (
                            message
                            for entry, outcome, message in presentation.finish_on_action
                            if entry == offer.entry and outcome == completed.outcome
                        ),
                        None,
                    )
                    if finished_by_player is not None:
                        finished_entry = offer.entry
        else:
            print("Published." if isinstance(result, K0Published) else type(result).__name__)
            if args.author_diagnostics and not isinstance(result, K0Published):
                for line in render_author_guard_report(session.author_guard_report(seat, offer)):
                    print(line)


if __name__ == "__main__":
    raise SystemExit(main())
