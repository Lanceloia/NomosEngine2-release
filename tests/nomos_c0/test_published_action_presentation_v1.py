"""Finite publication feedback is checked before and independently of binding."""

from dataclasses import replace

import pytest
from test_control_binding_v1 import _inputs

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.graph_frontend_v1 import check_owner_graph
from nomos_c0.program_binding_v1 import bind_program


def _checked(messages, field="published_actions"):
    lib, ports, source, assets = _inputs()
    seat = source["seats"][0]
    seat["presentation"] = {
        "title": "Sender",
        "fields": {path: path for path in seat["read"]},
        "published": "Action resolved.",
        "rejected": "Action refused.",
        "no_offers": "No current action.",
        field: messages,
    }
    ir, layout = check_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)
    return ir, layout, assets


@pytest.mark.parametrize("field", ("published_actions", "rejected_actions"))
def test_publication_messages_survive_program_binding_without_world_changes(field):
    ir, layout, assets = _checked({"dispatch": "The attempt has a finite status message."}, field)
    presentation = ir.visibility.seats[0].presentation
    assert getattr(presentation, field) == (
        ("dispatch", "The attempt has a finite status message."),
    )
    program = bind_program(ir, layout)
    assert program.seats[0].presentation == presentation
    session = program.start(assets)
    before = session.author_snapshot()
    session.read(program.seats[0].symbol)
    session.offers(program.seats[0].symbol)
    assert session.author_snapshot() == before


@pytest.mark.parametrize("messages", [{"foreign": "OK"}, {"dispatch": ""}, {"dispatch": 1}, []])
@pytest.mark.parametrize("field", ("published_actions", "rejected_actions"))
def test_frontend_rejects_foreign_or_malformed_publication_messages(messages, field):
    with pytest.raises(C0LawError, match="presentation"):
        _checked(messages, field)


@pytest.mark.parametrize(
    "messages",
    [(("foreign", "OK"),), (("dispatch", ""),), (("dispatch", "OK"), ("dispatch", "Again"))],
)
@pytest.mark.parametrize("field", ("published_actions", "rejected_actions"))
def test_independent_ir_check_rejects_substituted_publication_messages(messages, field):
    ir, layout, _ = _checked({"dispatch": "Finite status."}, field)
    seat = ir.visibility.seats[0]
    presentation = replace(seat.presentation, **{field: messages})
    with pytest.raises(C0LawError, match="presentation"):
        visibility = replace(
            ir.visibility,
            seats=(replace(seat, presentation=presentation),) + ir.visibility.seats[1:],
        )
        bind_program(replace(ir, visibility=visibility), layout)
