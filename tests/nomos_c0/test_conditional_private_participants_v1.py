"""Four authored documents, one move Law, actual board/leave and private completion."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel._atomic_inmemory_session import _K0InMemoryActionAttempt
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect
from test_multi_participant_action_v0 import _compile, _owners

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.author_document_v1 import parse_author_document, read_author_document
from nomos_c0.composable_value_v1 import C0ValueProgram
from nomos_c0.private_actor_binding_v1 import check_private_bindings
from nomos_c0.program_binding_v1 import bind_program

ROOT = Path(__file__).resolve().parents[2] / "src/nomos_c0/examples"


def documents():
    return tuple(
        read_author_document(ROOT / f"nullable_transport_v1.{part}.yaml").to_data()
        for part in ("lib", "ports", "source", "assets")
    )


def _session():
    lib, ports, source, assets = documents()
    return _compile(lib, ports, source).start(assets)


def _act(session, seat, entry):
    offer = next(row for row in session.offers(seat) if row.entry == entry)
    result = session.submit(seat, entry, dict(offer.payload))
    assert isinstance(result, K0Published)
    return result


def _container(session):
    return session.author_object_instances()[0]


@pytest.mark.parametrize("with_origins", [False, True])
@pytest.mark.parametrize("bind_again", [False, True])
def test_private_condition_pure_call_has_same_authority_with_document_origins(
    with_origins, bind_again
):
    lib, ports, source, assets = documents()
    lib["pure_definitions"] = [
        {
            "name": "manifest.eligible",
            "parameters": {"included": "bool"},
            "result": "bool",
            "stage": "admission",
            "body": {"ref": "included"},
        }
    ]
    for offer in source["seats"][0]["offers"]:
        binding = offer["for_each_participants"]["rider"]
        binding["when"] = {
            "call": {"ref": "manifest.eligible", "args": {"included": binding["when"]}}
        }
    if with_origins:
        lib, ports, source = (
            parse_author_document(json.dumps(data), file=f"transport.{name}.json", format="json")
            for name, data in (("lib", lib), ("ports", ports), ("source", source))
        )
    program = _compile(lib, ports, source)
    if bind_again:
        from test_world_binding_v1 import _layout

        program = bind_program(program.program_ir, _layout(program))
    session = program.start(assets)
    solo = _act(session, "pilot", "move")
    assert _owners(session)["rider"].site == "left"
    assert [row.name for row in solo.occurrences[0].selected_owners] == ["container"]
    _act(session, "pilot", "move")
    _act(session, "rider", "board")
    carried = _act(session, "pilot", "move")
    assert _owners(session)["rider"].site == _owners(session)["pilot"].site == "right"
    assert [row.name for row in carried.occurrences[0].selected_owners] == ["container", "rider"]
    assert set(dict(session.offers("pilot")[0].payload)) == {"container", "destination"}
    private = program.seats[0].offers[0].private_actor_fields[0]
    condition = private.condition
    definition = condition._ports.pure_definitions[0]
    for change in ({"body": {"const": False}}, {"stage": "effect"}):
        altered = C0ValueProgram(
            condition.guard_ir,
            condition._tree,
            replace(condition._ports, pure_definitions=(replace(definition, **change),)),
            condition._admission_outputs,
            condition._binding_types,
            condition.effects,
        )
        with pytest.raises(C0LawError, match="read-only Action authority"):
            check_private_bindings(
                (replace(private, condition=altered),), dict(program.actions)["move"].ports
            )


def test_one_move_law_handles_solo_boarded_and_departed_heterogeneous_rider():
    session = _session()
    assert type(_owners(session)["pilot"]) is not type(_owners(session)["rider"])
    solo = _act(session, "pilot", "move")
    assert _owners(session)["pilot"].site == _container(session).current_state.site == "right"
    assert _owners(session)["rider"].site == "left"
    assert [row.name for row in solo.occurrences[0].selected_owners] == ["container"]
    _act(session, "pilot", "move")
    board = _act(session, "rider", "board")
    assert _container(session).current_state.passengers == ("pilot", "rider")
    dual = _act(session, "pilot", "move")
    assert _owners(session)["pilot"].site == _owners(session)["rider"].site == "right"
    assert _owners(session)["rider"].luggage == 2
    assert [row.name for row in dual.occurrences[0].selected_owners] == ["container", "rider"]
    assert dual.occurrences[0].source == solo.occurrences[0].source
    assert board.occurrences[0].source != dual.occurrences[0].source
    _act(session, "rider", "leave")
    _act(session, "pilot", "move")
    assert _owners(session)["pilot"].site == _container(session).current_state.site == "left"
    assert _owners(session)["rider"].site == "right"
    assert set(dict(session.read("pilot").fields)) == {"pilot.name", "pilot.site"}


def test_public_offer_has_no_private_selector_and_absent_completion_never_reads_rider():
    session = _session()
    offer = session.offers("pilot")[0]
    assert set(dict(offer.payload)) == {"container", "destination"}
    action = dict(session.program.actions)["move"]
    binding = session.program.seats[0].offers[0].private_actor_fields
    owners = _owners(session)
    container = _container(session)

    class Reads:
        def owner(self, key):
            assert key == action.scene_owner.key
            return owners["scene"]

        def individual(self, ref):
            assert ref == container.individual
            return container.current_state

    values = session._complete_private_values(
        action, binding, dict(offer.payload), "pilot", owners["pilot"], Reads()
    )
    assert values["rider"] is None
    before = session.author_snapshot()
    with pytest.raises(C0BindingError):
        session.submit("pilot", "move", {**dict(offer.payload), "rider": "rider"})
    assert session.author_snapshot() == before


@pytest.mark.parametrize("fault", ["extra", "omitted", "stale"])
def test_world_law_rechecks_manifest_after_private_completion(fault):
    session = _session()
    action = dict(session.program.actions)["move"]
    if fault != "extra":
        _act(session, "rider", "board")
    attempt = action.payload_type(
        "pilot", _container(session).individual, "right", "rider" if fault != "omitted" else None
    )
    if fault == "stale":
        _act(session, "rider", "leave")
    before = session.author_snapshot()
    assert isinstance(
        session._runtime.settle(_K0InMemoryActionAttempt(action.source_key, attempt)), K0NotAdmitted
    )
    assert session.author_snapshot() == before


@pytest.mark.parametrize(
    "fault", ["public", "nullable", "private_read", "cycle", "member", "entry"]
)
def test_compile_rejects_conditional_binding_escapes(fault):
    lib, ports, source, _ = documents()
    binding = source["seats"][0]["offers"][0]["for_each_participants"]["rider"]
    if fault == "public":
        binding.pop("private")
    elif fault == "nullable":
        binding.pop("when")
        ports["actions"][0]["participants"][-1]["nullable"] = False
    elif fault == "private_read":
        lib["records"][3]["fields"].append({"name": "secret", "type": {"int": [0, 5]}})
        binding["when"] = "container.secret == 0"
    elif fault == "cycle":
        binding["when"] = "rider.site == actor.site"
    elif fault == "member":
        binding["fixed_actor"] = "pilot"
    else:
        binding["when"] = False
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)


def test_any_invalid_member_update_rolls_back_pilot_container_and_history():
    lib, ports, source, assets = documents()
    lib["records"][2]["invariant"] = "state.site == 'left'"
    session = _compile(lib, ports, source).start(assets)
    _act(session, "rider", "board")
    before = session.author_snapshot()
    container = _container(session)
    with pytest.raises(K0SettlementDefect):
        _act(session, "pilot", "move")
    assert session.author_snapshot().owners == before.owners
    assert session._runtime.occurrence_history() == before.occurrences
    assert _container(session) == container


def test_independent_program_binding_retains_private_conditions():
    from test_world_binding_v1 import _layout

    lib, ports, source, assets = documents()
    program = _compile(lib, ports, source)
    session = bind_program(program.program_ir, _layout(program)).start(assets)
    _act(session, "rider", "board")
    _act(session, "pilot", "move")
    assert _owners(session)["rider"].site == "right"


@pytest.mark.parametrize(
    "fault", ["member", "legacy_tuple", "entry", "condition_read", "condition_ref"]
)
def test_independent_bind_rejects_private_ir_corruption(fault):
    from test_world_binding_v1 import _layout

    lib, ports, source, _ = documents()
    program = _compile(lib, ports, source)
    visibility = program.visibility_ir
    seat = visibility.seats[0]
    offer = seat.offers[0]
    fields = dict(offer.parameters)
    binding = fields["private_actor_fields"][0]
    if fault == "member":
        fields["private_actor_fields"] = (replace(binding, member="pilot"),)
    elif fault == "legacy_tuple":
        fields["private_actor_fields"] = (("rider", "rider"),)
    elif fault == "entry":
        value = binding.condition.value
        expression = value.tree["outputs"]["included"]
        tree = {
            **value.tree,
            "outputs": {"included": replace(expression, operation="const", operand=False)},
        }
        fields["private_actor_fields"] = (
            replace(binding, condition=replace(binding.condition, value=replace(value, tree=tree))),
        )
    else:
        value = binding.condition.value
        if fault == "condition_read":
            paths = value.ports.readable_paths | {"container.secret"}
            changed = replace(
                value,
                ports=replace(value.ports, readable_paths=paths, admission_readable_paths=paths),
            )
        else:
            expression = value.tree["outputs"]["included"]
            tree = {
                **value.tree,
                "outputs": {"included": replace(expression, operation="ref", operand="rider.site")},
            }
            changed = replace(value, tree=tree)
        fields["private_actor_fields"] = (
            replace(binding, condition=replace(binding.condition, value=changed)),
        )
    changed = replace(offer, parameters=tuple((name, fields[name]) for name, _ in offer.parameters))
    forged = replace(
        visibility, seats=(replace(seat, offers=(changed, seat.offers[1])), visibility.seats[1])
    )
    with pytest.raises(C0LawError):
        bind_program(replace(program.program_ir, visibility=forged), _layout(program))
