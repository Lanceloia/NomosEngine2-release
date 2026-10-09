"""Shared author validation does not preserve the early compiler contracts."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

import nomos_c0
from nomos_c0.author_contract_v1 import (
    C0BindingError,
    C0LawError,
    _exact,
    _object,
    _source_object,
)


def test_current_errors_share_one_neutral_contract():
    assert nomos_c0.C0LawError is C0LawError
    assert nomos_c0.C0BindingError is C0BindingError
    assert C0LawError.__module__ == C0BindingError.__module__ == "nomos_c0.author_contract_v1"
    assert issubclass(C0LawError, ValueError) and issubclass(C0BindingError, ValueError)


@pytest.mark.parametrize("value", [None, [], {1: "bad"}, "{}"])
def test_author_object_requires_exact_dictionary_with_string_keys(value):
    with pytest.raises(C0LawError, match="object with string keys"):
        _object(value, "declaration")


@pytest.mark.parametrize("value", [{}, {"name": "n", "extra": 1}])
def test_author_object_rejects_missing_and_unknown_fields(value):
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        _exact(value, {"name"}, "declaration")


@pytest.mark.parametrize("source", ["", "{", "[]", "null", '{"x": 1, "x": 2}', " " * 131073])
def test_shared_source_validation_has_no_parse_or_duplicate_key_fallback(source):
    with pytest.raises(C0LawError):
        _source_object(source, "declaration")


def test_shared_source_validation_preserves_declared_values():
    source = _source_object('{"name":"n","items":[1,2],"optional":null}', "declaration")
    assert _object(source, "declaration") is source
    _exact(source, {"name", "items", "optional"}, "declaration")
    assert source == {"name": "n", "items": [1, 2], "optional": None}


def test_early_modules_exports_and_exclusive_assets_are_absent():
    for module in (
        "action_start_v0",
        "action_event_v0",
        "derived_event_v0",
        "game_form_v1",
        "library_v1",
        "program_v0",
        "event_jump",
        "event_jump_native",
        "latch_native_v1",
    ):
        assert find_spec("nomos_c0." + module) is None, module
    for name in (
        "C0ActionPorts",
        "C0ActionProgram",
        "C0ActionSession",
        "C0OfferError",
        "C0Program",
        "C0ProgramSession",
        "C0TwoActionProgram",
        "C0TwoActionSession",
        "C0SourceEnvelope",
        "C0DerivedEventProgram",
        "C0EventPorts",
        "C0GameProgram",
        "C0GameSession",
        "C0LibraryCatalog",
        "C0NativeLibraryRegistration",
        "compile_action_program",
        "compile_action_event_program",
        "compile_two_action_program",
        "compile_game_program",
        "compile_library_event",
        "compile_library_game",
        "compile_program",
        "compile_derived_event",
        "compile_derived_event_program",
        "parse_lawdef",
    ):
        assert not hasattr(nomos_c0, name), name
    examples = Path(nomos_c0.__file__).parent / "examples"
    assert not tuple(examples.glob("latch_*"))
    for asset in (
        "action_causes_notice_v0.json",
        "event_jump_time.lib.json",
        "manual_single_seat_v1.form.json",
        "mode_change_closed.assets.json",
        "mode_change_open.assets.json",
        "mode_change_v0.action.json",
        "two_actions_notice_v0.json",
        "two_mode_actions_b.assets.json",
        "two_mode_actions_closed.assets.json",
        "two_mode_actions_v0.json",
        "workshop_event_jump.assets.json",
        "workshop_event_jump.source.json",
    ):
        assert not (examples / asset).exists(), asset
