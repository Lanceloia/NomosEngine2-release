"""One authored crossing Law settles seeded outcomes in actual K0 owners."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published

from nomos_c0.author_contract_v1 import C0BindingError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.owner_graph_v1 import compile_owner_graph

AUTHOR = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"
STEM = "finite_region_dice_v1"


def _program():
    lib, ports, source = (
        read_author_document(AUTHOR / f"{STEM}.{part}.yaml").to_data()
        for part in ("lib", "ports", "source")
    )
    return compile_owner_graph(check_graph_ports(ports, check_nominal_lib(lib)), source)


def _assets(*, seed: int = 17):
    assets = deepcopy(read_author_document(AUTHOR / f"{STEM}.assets.yaml").to_data())
    assets["opening"]["scene"]["die_seed"] = seed
    return assets


def test_success_asset_card_changes_only_the_trusted_seed() -> None:
    expected = _assets(seed=1)
    assert read_author_document(AUTHOR / f"{STEM}.success.assets.yaml").to_data() == expected


@pytest.mark.parametrize(
    ("seed", "roll", "passed", "region"),
    [(17, 7, False, "wall"), (1, 19, True, "goal")],
)
def test_same_author_law_settles_success_or_collision_with_a_real_die(
    seed: int, roll: int, passed: bool, region: str
) -> None:
    session = _program().start(_assets(seed=seed))
    opening = dict(session.read("traveler").fields)
    assert opening["traveler.region"] == "start"
    assert "traveler.last_roll" not in opening
    offer = session.offers("traveler")[0]
    assert offer.label == "Cross to goal"
    result = session.submit("traveler", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    occurrence = result.occurrences[0]
    assert occurrence.semantic_envelope.roll == roll
    assert occurrence.semantic_envelope.passed is passed
    owners = dict(session.author_snapshot().owners)
    assert owners["traveler"].region == region
    assert owners["traveler"].last_roll == roll
    assert owners["traveler"].last_total == roll
    assert owners["traveler"].last_passed is passed
    assert owners["traveler"].last_crossing_ref == occurrence.occurrence
    assert owners["scene"].die_seed != seed
    view = dict(session.read("traveler").fields)
    assert view["traveler.region"] == region
    assert view["traveler.last_roll"] == roll
    assert session.offers("traveler") == ()


def test_balance_bonus_and_die_are_both_inputs_to_the_same_threshold() -> None:
    assets = _assets(seed=17)
    assets["opening"]["traveler"]["balance_bonus"] = 4
    session = _program().start(assets)
    offer = session.offers("traveler")[0]
    result = session.submit("traveler", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].semantic_envelope.roll == 7
    traveler = dict(session.author_snapshot().owners)["traveler"]
    assert traveler.last_total == 11
    assert traveler.last_passed is True
    assert traveler.region == "goal"


def test_balance_penalty_raises_the_threshold_without_negative_integers() -> None:
    assets = _assets(seed=1)
    assets["opening"]["traveler"]["balance_penalty"] = 9
    session = _program().start(assets)
    offer = session.offers("traveler")[0]
    result = session.submit("traveler", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    assert result.occurrences[0].semantic_envelope.roll == 19
    traveler = dict(session.author_snapshot().owners)["traveler"]
    assert traveler.last_passed is False
    assert traveler.region == "wall"


def test_forged_crossing_and_wrong_region_cannot_draw_or_write() -> None:
    program = _program()
    session = program.start(_assets())
    action = dict(program.actions)["cross"]
    before = session.author_snapshot()
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(
            action.source_key, action.payload_type(actor="traveler", crossing="invented")
        )
    )
    assert isinstance(result, K0NotAdmitted)
    assert session.author_snapshot() == before

    no_knowledge = _assets()
    no_knowledge["opening"]["traveler"]["known_crossings"] = []
    session = program.start(no_knowledge)
    before = session.author_snapshot()
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(
            action.source_key, action.payload_type(actor="traveler", crossing="passage")
        )
    )
    assert isinstance(result, K0NotAdmitted)
    assert session.author_snapshot() == before

    wrong_start = _assets()
    wrong_start["opening"]["traveler"]["region"] = "wall"
    session = program.start(wrong_start)
    before = session.author_snapshot()
    result = session._runtime.settle(
        _K0InMemoryActionAttempt(
            action.source_key, action.payload_type(actor="traveler", crossing="passage")
        )
    )
    assert isinstance(result, K0NotAdmitted)
    assert session.author_snapshot() == before


def test_opening_rejects_a_crossing_to_an_undeclared_region() -> None:
    assets = _assets()
    assets["opening"]["scene"]["crossings"][0]["collision"] = "not_a_region"
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)


def test_opening_rejects_duplicate_region_and_crossing_keys() -> None:
    assets = _assets()
    assets["opening"]["scene"]["regions"].append("start")
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)
    assets = _assets()
    assets["opening"]["scene"]["crossings"].append(
        deepcopy(assets["opening"]["scene"]["crossings"][0])
    )
    with pytest.raises(C0BindingError, match="opening guard"):
        _program().start(assets)
