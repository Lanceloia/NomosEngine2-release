"""One malformed dynamic offer cannot veto another local, legal Action."""

from copy import deepcopy

from nomos_kernel._settlement_outcome_abi import K0Published
from test_actor_formation_v1 import documents
from test_world_binding_v1 import _compile


def test_dynamic_offer_fault_is_per_declaration_not_per_actor():
    lib, ports, source, assets = documents(
        opening=[{"kind": "sprite", "state": {"count": 0, "awake": True}, "debt": 0}]
    )
    for seat in source["game_form"]["seats"]:
        seat["eligible"] = False
    bad = deepcopy(source["actor_templates"][0]["offers"][0])
    bad.update(
        label="Broken step",
        when={"eq": [{"ceil_div": [1, {"ref": "actor.count"}]}, 1]},
    )
    source["actor_templates"][0]["offers"].append(bad)
    session = _compile(lib, ports, source).start(assets)
    binding = session._runtime.actors()[0]
    before = session.author_snapshot()
    (offer,) = session.offers(binding.seat)
    assert offer.label == "Step"
    (fault,) = session.offer_faults(binding.seat)
    assert (fault.entry, fault.label, fault.code) == ("step", "Broken step", "value_state")
    assert session.author_snapshot() == before
    result = session.submit(binding.seat, offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert session._runtime.read_actor(binding.actor).view.count == 1
