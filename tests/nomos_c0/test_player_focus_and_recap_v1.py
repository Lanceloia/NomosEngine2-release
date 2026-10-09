"""Presentation focus and recap cannot widen a checked seat's read authority."""

from dataclasses import replace

import pytest
from test_seat_read_projection_v0 import _authored

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.nominal_signatures_v1 import C0NominalFieldType
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.visibility_ir_v1 import presentation_scalar_kind


def _inputs():
    lib, ports, source, assets = _authored()
    next(owner for owner in lib["owners"] if owner["symbol"] == "actor")["seat_read"].append(
        "focus_label"
    )
    seat = source["seats"][0]
    seat["read"].append("actor.focus_label")
    seat["presentation"] = {
        "title": "Tools", "fields": {path: path for path in seat["read"]},
        "published": "Resolved.", "rejected": "Refused.", "no_offers": "No choice.",
        "projection_columns": {"known_tool_condition": {"condition": "Condition"}},
        "projection_focus": {"known_tool_condition": "actor.focus_label"},
        "finish_on_action": {"inspect": {"outcome": "done", "text": "Finished."}},
        "finish_fields": {"inspect": ["actor.name", "actor.can_see_tools"]},
    }
    seat["presentation"]["fields"]["known_tool_condition"] = "Known tools"
    source["temporal"] = {
        "mechanism": "action_value_event_jump", "order": [], "max_pending": 0,
        "periodic": [],
    }
    source["due_events"] = []
    source["game_form"] = {
        "mode": "action_value_event_jump", "end_at": 8, "max_same_time_actions": 8,
        "seats": [{"seat": "actor", "tempo": 1, "eligible": True,
                   "costs": {"make": 1, "inspect": 1}}],
        "world_stops": [{"outcome": "done", "owners": ["actor"],
                         "when": {"not_none": {"ref": "actor.make_ref"}}}],
    }
    assets["action_value_openings"] = [{"seat": "actor", "debt": 0, "tie_priority": 0}]
    assets["time"] = 0
    return lib, ports, source, assets


def _checked(lib, ports, source):
    return check_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def test_checked_focus_and_recap_survive_binding_and_leave_world_unchanged():
    lib, ports, source, assets = _inputs()
    ir, layout = _checked(lib, ports, source)
    seat = ir.visibility.seats[0]
    assert seat.presentation.projection_focus == (("known_tool_condition", "actor.focus_label"),)
    assert seat.presentation.finish_fields == (("inspect", ("actor.name", "actor.can_see_tools")),)
    program = bind_program(ir, layout)
    assert program.seats[0].presentation == seat.presentation
    session = program.start(assets)
    before = session.author_snapshot()
    assert dict(session.read("actor").fields)["actor.focus_label"] == "old"
    session.offers("actor")
    assert session.author_snapshot() == before


@pytest.mark.parametrize("focus", [
    {"foreign": "actor.focus_label"}, {"known_tool_condition": "actor.name"},
    {"known_tool_condition": "scene.title"}, [],
])
def test_focus_rejects_foreign_projection_or_noncurrent_field(focus):
    lib, ports, source, _ = _inputs()
    source["seats"][0]["presentation"]["projection_focus"] = focus
    with pytest.raises(C0LawError, match="presentation"):
        _checked(lib, ports, source)


@pytest.mark.parametrize("path", ["actor.focus_label", "known_tool_condition"])
def test_focus_rejects_hidden_field_or_projection(path):
    lib, ports, source, _ = _inputs()
    source["seats"][0]["presentation"]["fields"][path] = None
    with pytest.raises(C0LawError, match="presentation"):
        _checked(lib, ports, source)


@pytest.mark.parametrize("fields", [
    {"foreign": ["actor.name"]}, {"make": ["actor.name"]},
    {"inspect": ["actor.make_ref"]}, {"inspect": ["scene.title"]},
    {"inspect": ["known_tool_condition"]}, {"inspect": []},
    {"inspect": ["actor.name", "actor.name"]},
])
def test_recap_requires_visible_scalar_paths_and_matching_finish_entry(fields):
    lib, ports, source, _ = _inputs()
    source["seats"][0]["presentation"]["finish_fields"] = fields
    with pytest.raises(C0LawError, match="presentation"):
        _checked(lib, ports, source)


@pytest.mark.parametrize("changes", [
    {"projection_focus": (("known_tool_condition", "actor.name"),)},
    {"projection_focus": (("known_tool_condition", "actor.focus_label"),) * 2},
    {"finish_fields": (("inspect", ("actor.make_ref",)),)},
    {"finish_fields": (("inspect", ("actor.name", "actor.name")),)},
    {"finish_fields": (("make", ("actor.name",)),)},
])
def test_independent_ir_check_rejects_forged_presentation(changes):
    lib, ports, source, _ = _inputs()
    ir, layout = _checked(lib, ports, source)
    seat = ir.visibility.seats[0]
    altered = replace(seat, presentation=replace(seat.presentation, **changes))
    with pytest.raises(C0LawError, match="presentation"):
        bind_program(replace(ir, visibility=replace(ir.visibility, seats=(altered,))), layout)


@pytest.mark.parametrize("value,expected", [
    (C0NominalFieldType("enum", choices=("here", "there")), "str"),
    (C0NominalFieldType("optional", item=C0NominalFieldType("int")), "int"),
    (C0NominalFieldType("optional", item=None), None),
    (C0NominalFieldType("occurrence_ref"), None),
    (C0NominalFieldType("record", record="KnownLabel"), None),
])
def test_recap_scalar_check_uses_nominal_leaf_and_rejects_compound_or_broken_type(value, expected):
    lib, ports, source, _ = _inputs()
    ir, _ = _checked(lib, ports, source)
    signatures = ir.world.signatures
    records = tuple(
        replace(record, fields=tuple(
            replace(field, value=value) if field.name == "focus_label" else field
            for field in record.fields
        )) if record.symbol == "Actor" else record
        for record in signatures.records
    )
    altered = replace(signatures, records=records)
    assert presentation_scalar_kind(altered, "actor.focus_label") == expected
    if value.kind == "optional":
        assert presentation_scalar_kind(altered, "actor.focus_label", allow_optional=False) is None
