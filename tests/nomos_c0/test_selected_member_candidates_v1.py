"""Explicit Actor domains can supply candidates without fabricated local knowledge."""

from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_candidate_participants_v1 import _authored
from test_world_binding_v1 import _compile, _layout

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program


def _selected():
    lib, ports, source, assets = _authored()
    offer = source["seats"][0]["offers"][0]
    offer["for_each_participants"]["victim"] = {"selected_members": True, "as": "candidate"}
    offer["label"][-1] = {"ref": "candidate"}
    offer["payload"]["victim"] = {"ref": "candidate"}
    assets["opening"]["maker"]["known"] = []
    return lib, ports, source, assets


def test_selected_keys_survive_independent_bind_without_claiming_knowledge():
    lib, ports, source, assets = _selected()
    program = _compile(lib, ports, source)
    for layout in (program.world_layout, _layout(program)):
        session = bind_program(program.program_ir, layout).start(assets)
        before, history = session.author_snapshot(), session._runtime.occurrence_history()
        offers = session.offers("maker")
        assert tuple(row.label for row in offers) == (
            "Use one on a",
            "Use one on b",
            "Use two on a",
            "Use two on b",
        )
        assert session.author_snapshot() == before
        assert session._runtime.occurrence_history() == history
        assert dict(session.read("maker").fields)["maker.known"] == ()
        assert isinstance(
            session.submit("maker", offers[0].entry, dict(offers[0].payload)), K0Published
        )
        assert dict(session.author_snapshot().owners)["a"].enabled
        assert not dict(session.author_snapshot().owners)["b"].enabled
        assert tuple(row.label for row in session.offers("maker")) == ("Use two on b",)


def test_current_availability_filters_explicit_domain_without_public_private_fields():
    lib, ports, source, assets = _selected()
    assets["opening"]["a"]["enabled"] = True
    session = _compile(lib, ports, source).start(assets)
    assert tuple(row.label for row in session.offers("maker")) == ("Use one on b", "Use two on b")
    assert not any(key.startswith("b.") for key, _ in session.read("maker").fields)


def test_selection_does_not_override_k0_guard_or_source_member_scope():
    lib, ports, source, assets = _selected()
    source["actions"][0]["participants"]["victim"]["actors"] = ["a"]
    lib["lawdefs"][0]["body"]["value"]["guard"] = False
    session = _compile(lib, ports, source).start(assets)
    assert tuple(row.label for row in session.offers("maker")) == ("Use one on a", "Use two on a")
    offer = session.offers("maker")[0]
    before, history = session.author_snapshot(), session._runtime.occurrence_history()
    assert isinstance(session.submit("maker", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session.author_snapshot() == before
    assert session._runtime.occurrence_history() == history


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_selection_requires_the_literal_opt_in(value):
    lib, ports, source, _ = _selected()
    source["seats"][0]["offers"][0]["for_each_participants"]["victim"]["selected_members"] = value
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


@pytest.mark.parametrize("fault", ["domain", "identity", "root", "family"])
def test_independent_bind_rejects_forged_selected_range(fault):
    lib, ports, source, _ = _selected()
    program = _compile(lib, ports, source)
    visibility = program.visibility_ir
    seat = visibility.seats[0]
    declaration = seat.offers[0]
    actor_range = dict(declaration.parameters)["actor_range"]
    changes = (
        {"domain": ("foreign",)}
        if fault == "domain"
        else (
            {"identity_field": "name"}
            if fault == "identity"
            else ({"alias": "actor"} if fault == "root" else {"family": "foreign"})
        )
    )
    parameters = tuple(
        (key, replace(actor_range, **changes) if key == "actor_range" else value)
        for key, value in declaration.parameters
    )
    altered_seat = replace(
        seat, offers=(replace(declaration, parameters=parameters), *seat.offers[1:])
    )
    ir = replace(program.program_ir, visibility=replace(visibility, seats=(altered_seat,)))
    with pytest.raises(C0LawError):
        bind_program(ir, program.world_layout)
