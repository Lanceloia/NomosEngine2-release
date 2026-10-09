"""Selected existing owners and a new Object share one atomic authored Action."""

from copy import deepcopy

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_multi_participant_action_v0 import _compile, _owners, _world

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.program_binding_v1 import bind_program


def _documents(*, separate_family=False, capacity=4):
    lib, ports, source, assets = _world()
    lib["object_kinds"][0]["max_instances"] = capacity
    kind = "tool"
    if separate_family:
        product = deepcopy(lib["object_kinds"][0])
        product.update(symbol="product", sort="EXAMPLE.FORMED_PRODUCT@1")
        lib["object_kinds"].append(product)
        source["object_kinds"].append({"kind": "product", "sort": product["sort"]})
        kind = "product"
    action = ports["actions"][0]
    action["value"].update(outputs={"newborn": "Tool"}, construct=["Tool"])
    source["actions"][0]["form"] = {"kind": kind, "initial_output": "newborn"}
    lib["lawdefs"][0]["body"]["value"]["outputs"]["newborn"] = {
        "record": {
            "type": "Tool",
            "fields": {"label": {"ref": "tool.label"}, "ready": True, "visible": True},
        }
    }
    return lib, ports, source, assets


def _submit(session, tool=None, victim="a"):
    action = dict(session.program.actions)["enable"]
    if tool is None:
        tool = session.author_object_instances()[0].individual
    payload = action.payload_type("maker", tool, victim)
    return session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, payload))


@pytest.mark.parametrize("separate_family", [False, True])
def test_selected_owners_and_new_identity_commit_together(separate_family):
    lib, ports, source, assets = _documents(separate_family=separate_family)
    session = _compile(lib, ports, source).start(assets)
    old, untouched = session.author_object_instances()
    offer = session.offers("maker")[0]
    published = session.submit("maker", offer.entry, dict(offer.payload))
    assert isinstance(published, K0Published)
    assert len(published.occurrences) == 1
    (action,) = published.occurrences
    spent, unchanged, newborn = session.author_object_instances()
    assert spent.individual == old.individual and spent.owner == old.owner
    assert spent.current_state.ready is False
    assert unchanged == untouched
    assert newborn.individual not in (old.individual, untouched.individual)
    assert newborn.owner not in (old.owner, untouched.owner)
    assert newborn.formed_by == action.occurrence
    assert newborn.current_state.label == old.current_state.label
    assert newborn.current_state.ready is True
    assert (newborn.individual.family == old.individual.family) is not separate_family
    assert [(item.name, item.selector) for item in action.selected_owners] == [
        ("tool", old.individual), ("victim", "a")
    ]
    assert _owners(session)["a"].enabled is True
    assert _owners(session)["b"].enabled is False
    assert _owners(session)["maker"].enabled is False


def test_stale_or_foreign_selection_cannot_form_or_change_any_owner():
    lib, ports, source, assets = _documents()
    program = _compile(lib, ports, source)
    session = program.start(assets)
    foreign = program.start(assets).author_object_instances()[0].individual
    before = session.author_snapshot()
    assert isinstance(_submit(session, foreign), K0NotAdmitted)
    assert isinstance(_submit(session, victim="absent"), K0NotAdmitted)
    assert session.author_snapshot() == before
    old = session.author_object_instances()[0].individual
    assert isinstance(_submit(session), K0Published)
    before = session.author_snapshot()
    assert isinstance(_submit(session, old, "b"), K0NotAdmitted)
    assert session.author_snapshot() == before
    assert len(session.author_object_instances()) == 3


def test_new_individual_can_be_selected_by_the_same_authored_law():
    lib, ports, source, assets = _documents()
    session = _compile(lib, ports, source).start(assets)
    assert isinstance(_submit(session), K0Published)
    newborn = session.author_object_instances()[-1]
    result = _submit(session, newborn.individual, "b")
    assert isinstance(result, K0Published)
    current = session.author_object_instances()
    assert current[2].individual == newborn.individual
    assert current[2].current_state.ready is False
    assert current[3].formed_by == result.occurrences[0].occurrence
    assert len({item.owner for item in current}) == 4
    assert _owners(session)["b"].enabled is True


def test_readonly_participant_remains_readonly_when_forming_an_object():
    lib, ports, source, assets = _documents()
    action = ports["actions"][0]
    action["participants"][0]["write"] = False
    action["effects"]["tool"] = {}
    action["value"]["write_paths"].remove("tool.ready")
    del lib["lawdefs"][0]["body"]["value"]["outputs"]["ready"]
    session = _compile(lib, ports, source).start(assets)
    old = session.author_object_instances()[0]
    assert isinstance(_submit(session), K0Published)
    assert session.author_object_instances()[0] == old
    assert session.author_object_instances()[-1].formed_by is not None


def test_symbolic_program_binds_to_fresh_nominal_layout_without_recompiling(monkeypatch):
    from test_visibility_binding_v1 import _block_frontend
    from test_world_binding_v1 import _layout

    lib, ports, source, assets = _documents(separate_family=True)
    program = _compile(lib, ports, source)
    layout = _layout(program)
    _block_frontend(monkeypatch)
    session = bind_program(program.program_ir, layout).start(assets)
    published = _submit(session)
    assert isinstance(published, K0Published)
    newborn = session.author_object_instances()[-1]
    assert newborn.formed_by == published.occurrences[0].occurrence
    assert _owners(session)["a"].enabled is True


@pytest.mark.parametrize("fault", ["capacity", "state"])
def test_formation_failure_rolls_back_selected_owners_and_history(fault):
    lib, ports, source, assets = _documents(capacity=2 if fault == "capacity" else 4)
    if fault == "state":
        next(record for record in lib["records"] if record["name"] == "Tool")["invariant"] = (
            "state.visible"
        )
        lib["lawdefs"][0]["body"]["value"]["outputs"]["newborn"]["record"]["fields"][
            "visible"
        ] = False
    session = _compile(lib, ports, source).start(assets)
    before = session.author_snapshot()
    with pytest.raises(K0SettlementDefect):
        _submit(session)
    assert session.author_snapshot() == before


@pytest.mark.parametrize("fault", ["wrong_output_type", "undeclared_write", "unselected_kind"])
def test_formation_does_not_expand_type_or_write_authority(fault):
    lib, ports, source, _ = _documents()
    if fault == "wrong_output_type":
        ports["actions"][0]["value"]["outputs"]["newborn"] = "Person"
    elif fault == "undeclared_write":
        ports["actions"][0]["participants"][0]["write"] = False
    else:
        source["actions"][0]["form"]["kind"] = "unselected"
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
