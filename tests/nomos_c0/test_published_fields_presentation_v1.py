"""Published action records reuse checked seat reads, never hidden world state."""

from dataclasses import replace

import pytest
from test_player_focus_and_recap_v1 import _checked, _inputs

import nomos_c0.owner_graph_play_v1 as play
from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.program_runtime_v1 import C0ControlCommand


def _authored():
    lib, ports, source, assets = _inputs()
    source["seats"][0]["presentation"]["published_fields"] = {
        "inspect": ["actor.name", "actor.can_see_tools"],
    }
    return lib, ports, source, assets


def test_published_fields_survive_binding_without_writing_world():
    lib, ports, source, assets = _authored()
    ir, layout = _checked(lib, ports, source)
    program = bind_program(ir, layout)
    assert program.seats[0].presentation.published_fields == (
        ("inspect", ("actor.name", "actor.can_see_tools")),
    )
    session = program.start(assets)
    before = session.author_snapshot()
    session.read("actor")
    assert session.author_snapshot() == before


@pytest.mark.parametrize("paths", [
    {"foreign": ["actor.name"]}, {"inspect": ["scene.title"]},
    {"inspect": ["actor.make_ref"]}, {"inspect": ["known_tool_condition"]},
    {"inspect": ["actor.name", "actor.name"]}, {"inspect": []}, [],
])
def test_frontend_rejects_foreign_hidden_or_compound_fields(paths):
    lib, ports, source, _ = _authored()
    source["seats"][0]["presentation"]["published_fields"] = paths
    with pytest.raises(C0LawError, match="presentation"):
        _checked(lib, ports, source)


def test_frontend_rejects_unlabelled_scalar():
    lib, ports, source, _ = _authored()
    source["seats"][0]["presentation"]["fields"]["actor.name"] = None
    with pytest.raises(C0LawError, match="presentation"):
        _checked(lib, ports, source)


@pytest.mark.parametrize("fields", [
    (("foreign", ("actor.name",)),), (("inspect", ("actor.make_ref",)),),
    (("inspect", ("actor.name", "actor.name")),),
    (("inspect", ("actor.name",)),) * 2,
])
def test_independent_ir_rejects_forged_fields(fields):
    lib, ports, source, _ = _authored()
    ir, layout = _checked(lib, ports, source)
    seat = ir.visibility.seats[0]
    altered = replace(seat, presentation=replace(seat.presentation, published_fields=fields))
    with pytest.raises(C0LawError, match="presentation"):
        bind_program(replace(ir, visibility=replace(ir.visibility, seats=(altered,))), layout)


def test_repeated_equal_action_record_retains_zero_false_and_no_world_inference(monkeypatch):
    class Published:
        pass

    monkeypatch.setattr(play, "K0Published", Published)
    lib, ports, source, _ = _authored()
    ir, _ = _checked(lib, ports, source)
    presentation = ir.visibility.seats[0].presentation
    fields = (("actor.name", "Here"), ("actor.can_see_tools", False))
    lines = play._player_published_lines("inspect", Published(), fields, presentation)
    assert "immediately after" in lines[0]
    assert lines[-1].endswith("False")
    assert play._player_published_lines("inspect", Published(), fields, presentation) == lines
    assert play._player_published_lines("inspect", object(), fields, presentation) == ()
    assert play._player_published_lines("make", Published(), fields, presentation) == ()
    assert play._player_published_lines(
        "inspect", Published(), (("actor.name", 0), ("actor.can_see_tools", None)), presentation
    )[1].endswith("0")


def test_real_published_action_renders_omitted_optional_leaf_without_world_write():
    lib, ports, source, assets = _authored()
    actor_record = next(item for item in lib["records"] if item["name"] == "Actor")
    actor_record["fields"].append(
        {"name": "last_result", "type": {"optional": {"int": [1, 20]}}}
    )
    actor_owner = next(item for item in lib["owners"] if item["symbol"] == "actor")
    actor_owner["seat_read"].append("last_result")
    seat = source["seats"][0]
    seat["read"].append("actor.last_result")
    seat["presentation"]["fields"]["actor.last_result"] = "Last optional result"
    seat["presentation"]["published_fields"]["inspect"].append("actor.last_result")
    assets["opening"]["actor"]["last_result"] = None
    ir, layout = _checked(lib, ports, source)
    program = bind_program(ir, layout)
    session = program.start(assets)
    offer = next(item for item in session.offers("actor") if item.entry == "inspect")
    result = session.apply_control(C0ControlCommand("submit", "actor", offer=offer)).result
    fields = session.read("actor").fields
    assert "actor.last_result" not in dict(fields)
    before = session.author_snapshot()
    lines = play._player_published_lines("inspect", result, fields, program.seats[0].presentation)
    assert lines[-1] == "  Last optional result: Not present in this view."
    assert session.author_snapshot() == before


def test_renderer_rejects_compound_read(monkeypatch):
    class Published:
        pass

    monkeypatch.setattr(play, "K0Published", Published)
    lib, ports, source, _ = _authored()
    ir, _ = _checked(lib, ports, source)
    with pytest.raises(C0BindingError, match="action record"):
        play._player_published_lines(
            "inspect", Published(), (("actor.name", {}), ("actor.can_see_tools", True)),
            ir.visibility.seats[0].presentation,
        )
