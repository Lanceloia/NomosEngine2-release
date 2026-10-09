"""The terminal displays a finished GameForm without advancing it again."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import nomos_c0.owner_graph_play_v1 as play
from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.author_document_v1 import parse_author_document
from nomos_c0.seat_offers_v0 import C0SeatOffer


def test_terminal_has_no_format_dependent_document_helper():
    assert not hasattr(play, "_read_document")


@pytest.mark.parametrize("temporal", (False, True))
def test_player_view_reads_finished_frame_before_advancing(monkeypatch, capsys, temporal) -> None:
    def unexpected_advance(seat: str) -> None:
        raise AssertionError(f"finished seat {seat} was advanced")

    session = SimpleNamespace(
        time=4500,
        human_seats=lambda: ("seat",),
        form_frame=lambda seat: SimpleNamespace(finished=True, ready_seats=()),
        continue_form=unexpected_advance,
        read=lambda seat: SimpleNamespace(fields=()),
    )
    presentation = SimpleNamespace(
        title="Finished world", opening="Choose what happens.", fields=(), projection_focus=(),
        finish_fields=(),
    )
    program = SimpleNamespace(
        seats=(SimpleNamespace(symbol="seat", presentation=presentation),),
        profile=SimpleNamespace(temporal_policy=object() if temporal else None),
        game_form=object(),
        start=lambda assets: session,
    )
    monkeypatch.setattr(
        play,
        "read_author_document",
        lambda path: parse_author_document("{}", file=str(path), format="yaml"),
    )
    monkeypatch.setattr(play, "_source", lambda source: {})
    monkeypatch.setattr(play, "check_nominal_lib", lambda lib, domains: object())
    monkeypatch.setattr(play, "check_graph_ports", lambda ports, checked: object())
    monkeypatch.setattr(play, "compile_owner_graph", lambda library, source: program)

    args = ["--player-view"]
    for kind in ("lib", "ports", "source", "assets"):
        args.extend((f"--{kind}", f"{kind}.yaml"))
    assert play.main(args) == 0
    time_heading = "\nTime: 4500\n" if temporal else "\n"
    assert capsys.readouterr().out == (
        "Finished world\nChoose what happens.\n"
        + time_heading
        + "Current view:\nGameForm finished.\n"
    )


def test_player_projection_uses_authored_terms_and_columns() -> None:
    presentation = SimpleNamespace(
        terms=(("site_a", "The doorway"), ("protected", "Inside the light")),
        projection_columns=(("protection", (("status", "Now"),)),),
        projection_focus=(),
    )
    assert play._player_field_lines(
        "protection",
        (("site_a", (("status", "protected"),)),),
        "Known protection",
        presentation,
    ) == (
        "  Known protection:",
        "    The doorway: Now: Inside the light",
    )
    assert play._player_field_lines("site", "site_a", "Location", presentation) == (
        "  Location: The doorway",
    )
    assert play._player_field_lines("memory", None, "Last observation", presentation) == ()
    assert play._player_field_lines("empty", (), "No observations yet", presentation) == ()
    assert play._player_field_lines("charges", 0, "Charges", presentation) == ("  Charges: 0",)
    assert play._player_field_lines("ice", False, "Ice", presentation) == ("  Ice: False",)

    with pytest.raises(C0BindingError, match="foreign column shape"):
        play._player_field_lines(
            "protection",
            (("site_a", (("other", "protected"),)),),
            "Known protection",
            presentation,
        )


def test_player_view_reports_malformed_projection_without_partial_rows(monkeypatch, capsys) -> None:
    session = SimpleNamespace(
        human_seats=lambda: ("seat",),
        form_frame=lambda seat: SimpleNamespace(finished=True, ready_seats=()),
        read=lambda seat: SimpleNamespace(
            fields=(("protection", (("site_a", (("other", "protected"),)),)),)
        ),
    )
    presentation = SimpleNamespace(
        title="Finished world",
        opening=None,
        fields=(("protection", "Known protection"),),
        finish_fields=(),
        terms=(),
        projection_columns=(("protection", (("status", "Now"),)),),
        projection_focus=(),
    )
    program = SimpleNamespace(
        seats=(SimpleNamespace(symbol="seat", presentation=presentation),),
        profile=SimpleNamespace(temporal_policy=None),
        game_form=object(),
        start=lambda assets: session,
    )
    monkeypatch.setattr(
        play,
        "read_author_document",
        lambda path: parse_author_document("{}", file=str(path), format="yaml"),
    )
    monkeypatch.setattr(play, "_source", lambda source: {})
    monkeypatch.setattr(play, "check_nominal_lib", lambda lib, domains: object())
    monkeypatch.setattr(play, "check_graph_ports", lambda ports, checked: object())
    monkeypatch.setattr(play, "compile_owner_graph", lambda library, source: program)
    args = ["--player-view"]
    for kind in ("lib", "ports", "source", "assets"):
        args.extend((f"--{kind}", f"{kind}.yaml"))

    assert play.main(args) == 3
    output = capsys.readouterr().out
    assert "World could not render this view." in output
    assert "Known protection:" not in output


def test_player_offer_translates_only_typed_value_fragments() -> None:
    presentation = SimpleNamespace(terms=(("site_a", "The doorway"),))
    offer = C0SeatOffer(
        "cross",
        "Cross toward site_a",
        (("crossing", "site_a"),),
        label_fragments=(("Cross toward ", False), ("site_a", True)),
    )
    assert play._player_offer_label(offer, presentation) == "Cross toward The doorway"
    assert offer.label == "Cross toward site_a"


def test_player_action_feedback_requires_publication_and_a_matching_entry(monkeypatch):
    class Published:
        pass

    monkeypatch.setattr(play, "K0Published", Published)
    presentation = SimpleNamespace(
        published_actions=(("invite", "You called an invitation; no acceptance is implied."),),
        rejected_actions=(("wait", "The attempt failed; no particular cause is certified."),),
        published="Action resolved.",
        rejected="That action could not happen.",
    )
    invite = C0SeatOffer("invite", "Invite", ())
    wait = C0SeatOffer("wait", "Wait", ())
    assert play._player_publication_line(invite, presentation, Published()) == (
        "You called an invitation; no acceptance is implied."
    )
    assert play._player_publication_line(wait, presentation, Published()) == "Action resolved."
    assert play._player_publication_line(invite, presentation, object()) == (
        "That action could not happen."
    )
    assert play._player_publication_line(wait, presentation, object()) == (
        "The attempt failed; no particular cause is certified."
    )


def test_player_menu_delta_uses_only_current_visible_choices():
    presentation = SimpleNamespace(terms=(), preview_fields=())
    first = (C0SeatOffer("look", "Look", (("secret", "never print"),)),)
    second = first + (C0SeatOffer("cross", "Cross", ()),)
    previous = play._player_offer_lines(first, presentation)
    current = play._player_offer_lines(second, presentation)
    assert previous == ("  1. Look",)
    assert current == ("  1. Look", "  2. Cross")
    assert play._player_offer_change_lines(previous, None) == ()
    assert play._player_offer_change_lines(previous, previous) == ()
    assert play._player_offer_change_lines(current, previous) == (
        "Available choices changed; check the current list below.",
    )
    assert play._player_offer_change_lines((), previous)
    assert "never print" not in "\n".join(current)


def test_player_choices_show_only_labeled_forecasts_and_keep_unknown_choices():
    presentation = SimpleNamespace(
        terms=(("protected", "Within the light"), ("unknown", "Not known")),
        preview_fields=(("cross", (("after", "Protection if successful"),)),),
    )
    offer = C0SeatOffer(
        "cross", "Cross", (("secret", "no payload dump"),),
        preview=(("after", "protected"), ("unlabeled", "do not serialize")),
    )
    assert play._player_offer_lines((offer,), presentation) == (
        "  1. Cross", "     Protection if successful: Within the light",
    )
    assert play._player_offer_lines((C0SeatOffer("cross", "Cross", ()),), presentation) == (
        "  1. Cross", "     Forecast unavailable for this current choice.",
    )
    unknown = C0SeatOffer("cross", "Cross", (), preview=(("after", "unknown"),))
    assert play._player_offer_lines((unknown,), presentation)[1].endswith("Not known")
    with pytest.raises(C0BindingError, match="foreign scalar"):
        play._player_offer_lines(
            (C0SeatOffer("cross", "Cross", (), preview=(("after", object()),)),), presentation,
        )


def test_player_view_diff_compares_only_rendered_local_fields_and_keeps_full_readback():
    presentation = SimpleNamespace(
        fields=(("charges", "Charges"), ("roll", "Last roll"), ("ref", None)),
        terms=(),
        projection_columns=(),
        projection_focus=(),
    )
    original = (("charges", 5), ("roll", 12), ("ref", 1))
    full, previous = play._player_view_lines(original, presentation, None)
    assert full == ("Current view:", "  Charges: 5", "  Last roll: 12")
    assert "ref" not in previous
    unchanged, _ = play._player_view_lines(
        (("charges", 5), ("roll", 12), ("ref", 2)), presentation, previous
    )
    assert unchanged == ("No displayed values changed.",)
    changed, current = play._player_view_lines(
        (("charges", 4), ("roll", None), ("ref", 3)), presentation, previous
    )
    assert changed == (
        "Displayed values changed since the previous view:",
        "  Charges: 4",
        "  Last roll: No longer present in this view.",
    )
    restored, _ = play._player_view_lines(original, presentation, None)
    assert restored == full
    assert current == {"charges": ("  Charges: 4",), "roll": ()}


def test_player_diff_reports_omitted_optional_once_without_restoring_old_value():
    presentation = SimpleNamespace(
        fields=(("charge", "Charge"), ("roll", "Crossing roll"), ("ref", None)),
        terms=(), projection_columns=(), projection_focus=(),
    )
    _, previous = play._player_view_lines(
        (("charge", 0), ("roll", 4), ("ref", 12)), presentation, None
    )
    previous.update({"ref": ("Secret ref",), "foreign": ("Secret foreign field",)})
    lines, current = play._player_view_lines((("charge", 0),), presentation, previous)
    assert lines == (
        "Displayed values changed since the previous view:",
        "  Crossing roll: No longer present in this view.",
    )
    assert current == {"charge": ("  Charge: 0",), "roll": ()}
    lines, repeated = play._player_view_lines((("charge", 0),), presentation, current)
    assert lines == ("No displayed values changed.",)
    assert repeated == current
    full, _ = play._player_view_lines((("charge", 0),), presentation, current, full=True)
    assert full == ("Current view:", "  Charge: 0")


def test_focus_uses_raw_local_key_and_full_view_preserves_focused_cache():
    presentation = SimpleNamespace(
        fields=(("actor.site", "Location"), ("coverage", "Known coverage")),
        terms=(("a", "Door"), ("b", "Hall")),
        projection_columns=(("coverage", (("status", "Now"),)),),
        projection_focus=(("coverage", "actor.site"),),
    )
    fields = (("actor.site", "a"), ("coverage", (
        ("a", (("status", "lit"),)), ("b", (("status", "dark"),)),
    )))
    focused, cache = play._player_view_lines(fields, presentation, None)
    assert "Door: Now: lit" in "\n".join(focused)
    assert "Hall" not in "\n".join(focused)
    full, full_cache = play._player_view_lines(fields, presentation, cache, full=True)
    assert "Hall: Now: dark" in "\n".join(full)
    assert full_cache == cache
    changed_remote = (fields[0], ("coverage", (
        ("a", (("status", "lit"),)), ("b", (("status", "lit"),)),
    )))
    delta, _ = play._player_view_lines(changed_remote, presentation, full_cache)
    assert delta == ("No displayed values changed.",)
    with pytest.raises(C0BindingError):
        play._player_view_lines((fields[0], ("coverage", (
            ("a", (("status", "lit"),)), ("b", (("wrong", "dark"),)),
        ))), presentation, cache)
    with pytest.raises(C0BindingError):
        play._player_field_lines("coverage", (fields[1][1][0],) * 2,
                                 "Known coverage", presentation, focus_key="a")
    missing, _ = play._player_view_lines((("actor.site", "c"), fields[1]), presentation, None)
    assert "No locally known row" in "\n".join(missing)
    assert "Hall" not in "\n".join(missing)


def test_finish_recap_is_ordered_local_scalar_memory_not_a_world_summary():
    presentation = SimpleNamespace(
        fields=(("actor.seen", "Last seen"), ("actor.charge", "Charge"),
                ("actor.safe", "Observed safe"), ("actor.missing", "Unknown")),
        terms=(("b", "Resident"),), projection_columns=(),
        finish_fields=(("leave", ("actor.seen", "actor.charge", "actor.safe", "actor.missing")),),
    )
    fields = (("actor.safe", False), ("actor.charge", 0), ("actor.seen", "b"))
    assert play._player_finish_lines("leave", fields, presentation) == (
        "Your retained local record:", "  Last seen: Resident", "  Charge: 0",
        "  Observed safe: False",
    )
    assert play._player_finish_lines("other", fields, presentation) == ()
    with pytest.raises(C0BindingError, match="foreign scalar"):
        play._player_finish_lines("leave", (("actor.seen", {"private": 1}),), presentation)


def test_terminal_history_keeps_same_frame_records_without_reinjecting_memory():
    presentation = SimpleNamespace(
        fields=(("actor.person", "Last person"), ("actor.life", "Last observed life"),
                ("actor.private", None)), terms=(), projection_columns=(),
        finish_fields=(("leave", ("actor.person", "actor.life")),),
    )
    history, truncated = {}, set()
    first = (("actor.person", "A"), ("actor.life", "alive"), ("actor.private", "never retain"))
    second = (("actor.person", "B"), ("actor.life", "frozen"), ("actor.private", "hidden"))
    play._remember_displayed_finish_fields(first, presentation, history, 1, truncated)
    play._remember_displayed_finish_fields(first, presentation, history, 2, truncated)
    play._remember_displayed_finish_fields(second, presentation, history, 3, truncated)
    cleared = (("actor.person", None), ("actor.life", None), ("actor.private", "hidden"))
    play._remember_displayed_finish_fields(cleared, presentation, history, 4, truncated)
    output = "\n".join(play._player_finish_history_lines("leave", history, truncated))
    assert len(history["leave"]) == 2
    assert "Display frame 1" in output and "Display frame 3" in output
    assert "Display frame 2" not in output
    assert "not current safety updates" in output
    assert "Last person: A\n  Last observed life: alive" in output
    assert "Last person: B\n  Last observed life: frozen" in output
    assert "private" not in output and "hidden" not in output
    assert cleared[0][1] is None
    assert play._player_finish_history_lines("foreign", history, truncated) == ()


def test_terminal_history_is_bounded_and_discloses_truncation():
    presentation = SimpleNamespace(
        fields=(("actor.value", "Shown value"),), terms=(), projection_columns=(),
        finish_fields=(("leave", ("actor.value",)),),
    )
    history, truncated = {}, set()
    for frame in range(70):
        play._remember_displayed_finish_fields(
            (("actor.value", frame),), presentation, history, frame, truncated
        )
    assert len(history["leave"]) == 64 and history["leave"][0][0] == 6
    assert truncated == {"leave"}
    assert "Older displays omitted" in "\n".join(
        play._player_finish_history_lines("leave", history, truncated)
    )


@pytest.mark.parametrize("post_fault", (False, True))
@pytest.mark.parametrize("action_record", (False, True))
@pytest.mark.parametrize(
    "published,outcome", [(True, "departed"), (True, "other"), (False, "departed")]
)
def test_player_finish_message_requires_own_published_action_and_matching_outcome(
    monkeypatch, capsys, post_fault: bool, published: bool, outcome: str, action_record: bool
) -> None:
    class Published:
        pass

    completed = False
    reads = []
    offer = C0SeatOffer("leave", "Leave", ())

    def frame(seat):
        if completed and post_fault:
            raise C0BindingError("finished frame unavailable")
        return SimpleNamespace(
            finished=completed,
            ready_seats=() if completed else ("seat",),
            outcome=outcome if completed else None,
        )

    def submit(command):
        nonlocal completed
        completed = True
        return SimpleNamespace(result=Published() if published else object())

    def read(seat):
        reads.append(completed)
        return SimpleNamespace(fields=(("actor.charge", 0 if completed else 1),))

    session = SimpleNamespace(
        human_seats=lambda: ("seat",),
        form_frame=frame,
        continue_form=frame,
        read=read,
        offers=lambda seat: (offer,) if not completed else (),
        apply_control=submit,
    )
    presentation = SimpleNamespace(
        title="A world",
        opening=None,
        fields=(("actor.charge", "Charge"),),
        terms=(),
        projection_columns=(),
        finish_on_action=(("leave", "departed", "You step outside."),),
        projection_focus=(),
        finish_fields=(("leave", ("actor.charge",)),),
        published_fields=(("leave", ("actor.charge",)),) if action_record else (),
        published="Resolved.",
        rejected="Refused.",
        published_actions=(),
        rejected_actions=(),
        preview_fields=(),
    )
    program = SimpleNamespace(
        seats=(SimpleNamespace(symbol="seat", presentation=presentation),),
        profile=SimpleNamespace(temporal_policy=None),
        game_form=object(),
        start=lambda assets: session,
    )
    monkeypatch.setattr(play, "K0Published", Published)
    monkeypatch.setattr(
        play,
        "read_author_document",
        lambda path: parse_author_document("{}", file=str(path), format="yaml"),
    )
    monkeypatch.setattr(play, "_source", lambda source: {})
    monkeypatch.setattr(play, "check_nominal_lib", lambda lib, domains: object())
    monkeypatch.setattr(play, "check_graph_ports", lambda ports, checked: object())
    monkeypatch.setattr(play, "compile_owner_graph", lambda library, source: program)
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    args = ["--player-view"]
    for kind in ("lib", "ports", "source", "assets"):
        args.extend((f"--{kind}", f"{kind}.yaml"))

    assert play.main(args) == (3 if post_fault else 0)
    output = capsys.readouterr().out
    assert ("immediately after this action" in output) == (published and action_record)
    if post_fault:
        assert "World could not advance." in output
        assert "You step outside." not in output
        assert "Earlier records displayed" not in output
    else:
        assert reads == ([False, True, True] if published and action_record else [False, True])
        if published and outcome == "departed":
            assert "Earlier records displayed" in output
            assert "Charge: 1" in output and "Charge: 0" in output
            assert "You step outside." in output
            assert "GameForm finished." not in output
        else:
            assert "Earlier records displayed" not in output
            assert "You step outside." not in output
            assert "GameForm finished." in output


def test_player_presentation_without_game_form_keeps_running_after_publish(
    monkeypatch, capsys
) -> None:
    class Published:
        pass

    submitted = False
    offer = C0SeatOffer("inspect", "Inspect", ())

    def submit(command):
        nonlocal submitted
        submitted = True
        return SimpleNamespace(result=Published())

    def no_form_frame(seat):
        raise AssertionError("a program without GameForm has no frame")

    session = SimpleNamespace(
        human_seats=lambda: ("seat",),
        form_frame=no_form_frame,
        read=lambda seat: SimpleNamespace(fields=()),
        offers=lambda seat: () if submitted else (offer,),
        apply_control=submit,
    )
    presentation = SimpleNamespace(
        title="A world",
        opening=None,
        fields=(),
        published="Resolved.",
        projection_focus=(),
        finish_fields=(),
        published_fields=(),
        published_actions=(),
        rejected_actions=(),
        preview_fields=(),
        no_offers="Nothing else to do.",
    )
    program = SimpleNamespace(
        seats=(SimpleNamespace(symbol="seat", presentation=presentation),),
        profile=SimpleNamespace(temporal_policy=None),
        game_form=None,
        start=lambda assets: session,
    )
    monkeypatch.setattr(play, "K0Published", Published)
    monkeypatch.setattr(
        play,
        "read_author_document",
        lambda path: parse_author_document("{}", file=str(path), format="yaml"),
    )
    monkeypatch.setattr(play, "_source", lambda source: {})
    monkeypatch.setattr(play, "check_nominal_lib", lambda lib, domains: object())
    monkeypatch.setattr(play, "check_graph_ports", lambda ports, checked: object())
    monkeypatch.setattr(play, "compile_owner_graph", lambda library, source: program)
    commands = iter(("view", "1"))

    def choose(prompt):
        assert not submitted
        assert "'view'" in prompt
        return next(commands)

    monkeypatch.setattr("builtins.input", choose)
    args = ["--player-view"]
    for kind in ("lib", "ports", "source", "assets"):
        args.extend((f"--{kind}", f"{kind}.yaml"))

    assert play.main(args) == 0
    output = capsys.readouterr().out
    assert output.count("Current view:") == 2
    assert (
        "Resolved.\n\nNo displayed values changed.\n"
        "Available choices changed; check the current list below.\nNothing else to do."
    ) in output
