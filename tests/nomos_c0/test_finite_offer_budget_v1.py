"""Finite offer bounds agree at Ports, Compile, IR and independent Bind."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0Published
from test_multi_participant_action_v0 import _fixed_scalar_world
from test_visibility_binding_v1 import _block_frontend
from test_world_binding_v1 import _compile

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.program_binding_v1 import bind_program


def world(count, limit):
    lib, ports, source, assets = _fixed_scalar_world()
    ports["offer_provider"]["limit"] = limit
    action = source["actions"][0]
    seat = source["seats"][0]
    original_offer = seat["offers"][0]
    actions, entries, offers = [], [], []
    for index in range(count):
        clone = deepcopy(action)
        name = action["name"] if index == 0 else f"dispatch_{index}"
        clone.update(name=name)
        if index:
            clone.update(
                source_key=f"sample.dispatch.{index}", event_type=f"sample.dispatch.{index}.action"
            )
        actions.append(clone)
        entries.append(name)
        item = deepcopy(original_offer)
        item.update(entry=name, label=f"Dispatch choice {index}")
        offers.append(item)
    source["actions"] = actions
    seat.update(entries=entries, offers=offers)
    return lib, ports, source, assets


@pytest.mark.parametrize("count", [65, 256])
def test_larger_finite_domain_compiles_rebinds_and_publishes_last_choice(monkeypatch, count):
    lib, ports, source, assets = world(count, 256)
    program = _compile(lib, ports, source)
    assert len(program.visibility_ir.seats[0].offers) == count
    _block_frontend(monkeypatch)
    rebound = bind_program(program.program_ir, program.world_layout)
    session = rebound.start(assets)
    offers = session.offers("maker")
    assert len(offers) == count
    last = offers[-1]
    published = session.submit("maker", last.entry, dict(last.payload))
    assert isinstance(published, K0Published)
    assert published.occurrences[0].source.value == f"sample.dispatch.{count - 1}"


def test_ports_compile_and_ir_reject_outside_the_same_budget():
    lib, ports, source, _ = world(1, 257)
    with pytest.raises(C0LawError, match="offer limit"):
        check_graph_ports(ports, check_nominal_lib(lib))
    lib, ports, source, _ = world(257, 256)
    with pytest.raises(C0LawError, match="finite_offers=257 exceeds limit=256"):
        _compile(lib, ports, source)
    lib, ports, source, _ = world(1, 256)
    program = _compile(lib, ports, source)
    with pytest.raises(C0LawError, match="visibility seat"):
        replace(
            program.visibility_ir,
            seats=(replace(program.visibility_ir.seats[0], offer_limit=257),),
        )


def test_smaller_author_selected_budget_is_still_enforced():
    lib, ports, source, _ = world(65, 64)
    with pytest.raises(C0LawError, match="offer domain"):
        _compile(lib, ports, source)
