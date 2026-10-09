"""Candidate group metadata cannot expand the selected Action's read authority."""

from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _compile, _owners
from test_participant_groups_v1 import grouped

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.candidate_input_v1 import check_candidate_input
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.program_binding_v1 import bind_program


def authored():
    lib, ports, source, assets, _ = grouped()
    ports["candidate_inputs"] = [
        {
            "symbol": "selected_available",
            "action": "enable",
            "read": ["victim.enabled"],
            "fields": {},
        }
    ]
    source["seats"][0]["offers"][0]["availability"] = {
        "ref": "selected_available",
        "when": {
            "any_participant": {
                "group": "recipients",
                "as": "person",
                "where": "not person.enabled",
            }
        },
    }
    return lib, ports, source, assets


def test_candidate_inherits_group_but_only_returns_signal_without_world_or_private_read():
    lib, ports, source, assets = authored()
    program = _compile(lib, ports, source)
    assert program.visibility_ir.seats[0].candidate_checks
    session = bind_program(program.program_ir, program.world_layout).start(assets)
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    offers = session.offers("maker")
    assert len(offers) == 4
    assert session.offers("maker") == offers
    assert session.author_snapshot() == before
    assert session._runtime.occurrence_history() == history
    assert tuple(path for path, _ in session.read("maker").fields) == ("maker.name", "maker.known")
    chosen = offers[0]
    assert isinstance(session.submit("maker", chosen.entry, dict(chosen.payload)), K0Published)
    assert _owners(session)["a"].enabled
    assert {offer.label for offer in session.offers("maker")} == {"Use two on b"}


@pytest.mark.parametrize("fault", ["unknown", "unread", "public"])
def test_group_cannot_borrow_missing_grants_or_leak_into_public_offer(fault):
    lib, ports, source, _ = authored()
    offer = source["seats"][0]["offers"][0]
    if fault == "unknown":
        offer["availability"]["when"]["any_participant"]["group"] = "unselected"
    elif fault == "unread":
        ports["candidate_inputs"][0]["read"] = []
    else:
        offer["when"] = offer["availability"]["when"]
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("members", [("tool",), ("victim", "tool")])
def test_candidate_port_cannot_redefine_selected_group(members):
    lib, ports, _, _ = authored()
    library = check_graph_ports(ports, check_nominal_lib(lib))
    action, candidate = library.actions[0], library.candidate_inputs[0]
    value = replace(candidate.value_ports, participant_groups=(("recipients", members),))
    with pytest.raises(C0LawError, match="read-only authority"):
        check_candidate_input(action.ports, value)


def test_independent_bind_rejects_removed_member_read_after_group_expansion():
    lib, ports, source, _ = authored()
    program = _compile(lib, ports, source)
    visibility, seat = program.visibility_ir, program.visibility_ir.seats[0]
    check = seat.candidate_checks[0]
    value = check.body.value
    altered = replace(
        check,
        body=replace(
            check.body,
            value=replace(
                value,
                ports=replace(
                    value.ports,
                    readable_paths=value.ports.readable_paths - {"victim.enabled"},
                    admission_readable_paths=value.ports.admission_readable_paths
                    - {"victim.enabled"},
                ),
            ),
        ),
    )
    ir = replace(
        program.program_ir,
        visibility=replace(
            visibility,
            seats=(replace(seat, candidate_checks=(altered,)), *visibility.seats[1:]),
        ),
    )
    with pytest.raises(C0LawError):
        bind_program(ir, program.world_layout)


def test_group_signal_does_not_replace_real_action_guard():
    lib, ports, source, assets = authored()
    lib["lawdefs"][0]["body"]["value"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    offer = session.offers("maker")[0]
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    assert session._runtime.occurrence_history() == history
