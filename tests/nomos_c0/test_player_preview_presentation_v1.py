"""Player forecast labels cannot create ports or serialize arbitrary values."""

from dataclasses import replace

import pytest
from test_seat_offer_preview_v0 import _authored

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.owner_graph_play_v1 import _player_offer_lines
from nomos_c0.program_binding_v1 import bind_program


def _checked(columns):
    lib, ports, source, assets = _authored()
    seat = source["seats"][0]
    seat["presentation"] = {
        "title": "Workbench",
        "fields": {name: None for name in seat["read"]},
        "published": "Resolved.", "rejected": "Refused.", "no_offers": "No choice.",
        "preview_fields": columns,
        "terms": {"ready": "Ready to inspect"},
    }
    ir, layout = check_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    return ir, layout, assets


def test_checked_forecast_is_rendered_without_changing_the_session():
    ir, layout, assets = _checked({"inspect": {"condition": "Expected condition"}})
    program = bind_program(ir, layout)
    session = program.start(assets)
    before = session.author_snapshot()
    offers = tuple(row for row in session.offers("actor") if row.entry == "inspect")
    lines = _player_offer_lines(offers, program.seats[0].presentation)
    assert "     Expected condition: Ready to inspect" in lines
    assert session.author_snapshot() == before


@pytest.mark.parametrize("columns", [
    {"foreign": {"condition": "Condition"}},
    {"inspect": {"private": "Secret"}},
    {"inspect": {"condition": ""}},
    {"inspect": {}},
    {"inspect": []},
])
def test_frontend_rejects_foreign_forecast_labels(columns):
    with pytest.raises(C0LawError, match="presentation"):
        _checked(columns)


@pytest.mark.parametrize("columns", [
    (("foreign", (("condition", "Condition"),)),),
    (("inspect", (("private", "Secret"),)),),
    (("inspect", (("condition", ""),)),),
    (("inspect", (("condition", "A"), ("condition", "B"))),),
    (("inspect", ()),),
    (("inspect", (("condition", "A"),)), ("inspect", (("condition", "B"),))),
])
def test_independent_ir_rejects_substituted_forecast_labels(columns):
    ir, layout, _ = _checked({"inspect": {"condition": "Condition"}})
    seat = ir.visibility.seats[0]
    with pytest.raises(C0LawError, match="presentation"):
        visibility = replace(ir.visibility, seats=(
            replace(seat, presentation=replace(seat.presentation, preview_fields=columns)),
        ) + ir.visibility.seats[1:])
        bind_program(replace(ir, visibility=visibility), layout)
