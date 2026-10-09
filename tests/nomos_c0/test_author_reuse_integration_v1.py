"""Reuse remains subject to each consuming Action and seat's actual permissions."""

import json
from copy import deepcopy

import pytest
from test_control_binding_v1 import _inputs
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import parse_author_document


def _shared():
    lib, ports, source, assets = _inputs()
    offers = source["seats"][1]["offers"]
    source["offer_sets"] = [{"name": "acknowledgements", "offers": deepcopy(offers)}]
    source["seats"][1]["offers"] = [{"use_offer_set": "acknowledgements"}]
    control = source["game_form"]["seats"][1]
    control["costs"] = {}
    control["cost_groups"] = [{"entries": ["confirm", "confirm_alt"], "value": 2}]
    return lib, ports, source, assets


def test_reused_menu_and_cost_keep_real_execution_and_source_locations():
    lib, ports, source, assets = _shared()
    assets["controllers"] = [
        {"seat": "sender", "mode": "human_prompt"},
        {"seat": "receiver", "mode": "finite_appraisal", "profile": "prefer_alt"},
    ]
    document = parse_author_document(json.dumps(source), file="reuse.source.json", format="json")
    program = _compile(lib, ports, document)
    session = program.start(assets)
    offer = session.form_frame("sender").offers[0]
    session.submit("sender", offer.entry, dict(offer.payload))
    frame = session.continue_form("sender")
    assert frame.finished and frame.outcome == "delivered"
    assert session._runtime.action_value_history()[-1].cost == 2
    assert session.appraisal_history()[0].proposal.chosen.entry == "confirm_alt"
    costs = program.program_ir.control.action_values[1].costs
    assert [name for name, _ in costs] == ["confirm", "confirm_alt"]
    for _, value in costs:
        expression = value.value.tree["outputs"]["cost"]
        assert expression.provenance[-1].span.path == (
            "game_form", "seats", 1, "cost_groups", 0, "value",
        )
    for offer in program.seats[1].offers:
        assert any(frame.kind == "offer_set_definition"
                   and frame.span.file == "reuse.source.json"
                   for frame in offer.condition.provenance)


@pytest.mark.parametrize("defect", ["menu_read", "cost_read", "missing_cost"])
def test_reuse_does_not_grant_foreign_read_or_fill_missing_costs(defect):
    lib, ports, source, _ = _shared()
    if defect == "menu_read":
        source["offer_sets"][0]["offers"][0]["when"] = {"is_none": {"ref": "sender.sent_ref"}}
    elif defect == "cost_read":
        source["game_form"]["seats"][1]["cost_groups"][0]["value"] = {"ref": "scene.unknown"}
    else:
        source["game_form"]["seats"][1]["cost_groups"][0]["entries"] = ["confirm"]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
