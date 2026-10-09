"""One checked visibility partition uses the actual world under either layout."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, fields, replace

import pytest
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published
from test_multi_participant_action_v0 import _fixed_scalar_world, _fixed_world, _world
from test_nominal_signatures_v1 import assert_symbolic, forbid_frontend
from test_seat_offer_preview_v0 import _authored as _preview
from test_seat_read_projection_v0 import _authored as _projection
from test_world_binding_v1 import ROOT, _compile, _documents, _forbid_checks, _layout

from nomos_c0 import owner_graph_v1, seat_offers_v0
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.program_binding_v1 import bind_program
from nomos_c0.visibility_binding_v1 import _OFFER_TYPES, bind_visibility
from nomos_c0.visibility_ir_v1 import OFFER_FIELDS, C0VisibilityIR
from nomos_c0.world_binding_v1 import bind_world


def _parcel(*, ranged=False):
    lib, ports, source = _documents("parcel_delivery_v0")
    del source["ontology"]
    source["game_form"] = {"mode": "manual"}
    assets = read_author_document(ROOT / "parcel_delivery_v0.a.assets.json").to_data()
    seat = source["seats"][0]
    seat["presentation"] = {
        "title": "Sender",
        "fields": {name: name for name in seat["read"]},
        "published": "Published",
        "rejected": "Rejected",
        "no_offers": "No choice",
    }
    if ranged:
        lib["records"].append(
            {
                "name": "Destination",
                "fields": [{"name": "name", "type": {"str": [1, 64]}}],
                "invariant": None,
            }
        )
        next(item for item in lib["records"] if item["name"] == "Sender")["fields"].append(
            {"name": "destinations", "type": {"tuple": {"item": "Destination", "max": 8}}}
        )
        next(item for item in lib["owners"] if item["symbol"] == "sender")["seat_read"].append(
            "destinations"
        )
        offer = seat["offers"][0]
        offer.update(
            for_each={"collection": {"ref": "actor.destinations"}, "as": "destination"},
            label={"prefix": "Dispatch to ", "value": {"ref": "destination.name"}},
        )
        offer["payload"]["destination"] = {"ref": "destination.name"}
        assets["opening"]["sender"]["destinations"] = [{"name": "dock"}, {"name": "gate"}]
    return lib, ports, source, assets


def _inputs(kind):
    if kind == "fixed":
        return _parcel()
    if kind == "range":
        return _parcel(ranged=True)
    if kind == "object":
        return _projection()
    if kind == "participant":
        return _world()
    return _fixed_world()


def _bound_program(program, layout, assets):
    return bind_program(program.program_ir, layout)


def _block_frontend(monkeypatch):
    _forbid_checks(monkeypatch)
    monkeypatch.setattr(owner_graph_v1, "compile_owner_graph", forbid_frontend)
    monkeypatch.setattr(seat_offers_v0, "compile_seat_offers", forbid_frontend)
    monkeypatch.setattr(seat_offers_v0, "_expr_type", forbid_frontend)
    monkeypatch.setattr(seat_offers_v0, "_compile_expression", forbid_frontend)


@pytest.mark.parametrize("kind", tuple(OFFER_FIELDS))
def test_each_checked_offer_shape_reads_and_settles_under_two_layouts(monkeypatch, kind):
    lib, ports, source, assets = _inputs(kind)
    program = _compile(lib, ports, source)
    ir = program.visibility_ir
    assert type(ir) is C0VisibilityIR and ir.world is program.world_ir
    assert_symbolic(ir)
    assert all(item.owner.key.value not in repr(ir) for item in program.owners)
    assert kind in {offer.kind for seat in ir.seats for offer in seat.offers}
    with pytest.raises(FrozenInstanceError):
        ir.seats = ()
    alternate = _layout(program)
    _block_frontend(monkeypatch)
    outcomes = []
    for layout in (program.world_layout, alternate):
        rebound = _bound_program(program, layout, assets)
        session = rebound.start(assets)
        seat = rebound.seats[0].symbol
        before = session.author_snapshot()
        view, offers = session.read(seat), session.offers(seat)
        assert session.read(seat) == view and session.offers(seat) == offers
        assert session.author_snapshot() == before
        assert not any(name.startswith("receiver.") for name, _ in view.fields)
        assert offers
        wanted = "inspect" if kind == "object" else offers[0].entry
        offer = next(item for item in offers if item.entry == wanted)
        result = session.submit(seat, offer.entry, dict(offer.payload))
        assert isinstance(result, K0Published)
        assert result.occurrences[0].source == dict(rebound.actions)[wanted].source_key
        owners = {name: asdict(state) for name, state in session.author_snapshot().owners}
        objects = tuple(asdict(item.current_state) for item in session.author_object_instances())
        outcomes.append((asdict(view), tuple(item.label for item in offers), owners, objects))
    assert outcomes[0] == outcomes[1]


def test_offer_shapes_are_an_exhaustive_backend_schema():
    for name, carrier in _OFFER_TYPES.items():
        assert (
            tuple(item.name for item in fields(carrier) if item.name not in ("entry", "ports"))
            == OFFER_FIELDS[name]
        )


def test_fixed_scalar_payload_rebinds_without_frontend_under_two_layouts(monkeypatch):
    lib, ports, source, assets = _fixed_scalar_world()
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    assert_symbolic(program.visibility_ir)
    _block_frontend(monkeypatch)
    for layout in (program.world_layout, alternate):
        session = bind_program(program.program_ir, layout).start(assets)
        offer = session.offers("maker")[0]
        assert dict(offer.payload) == {"allowed": True}
        published = session.submit("maker", offer.entry, dict(offer.payload))
        assert isinstance(published, K0Published)
        owners = dict(session.author_snapshot().owners)
        assert owners["a"].enabled and not owners["b"].enabled


@pytest.mark.parametrize("factory", [_projection, _preview])
def test_projection_preview_rebind_candidate_records_and_remain_read_only(monkeypatch, factory):
    lib, ports, source, assets = factory()
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    _block_frontend(monkeypatch)
    for layout in (program.world_layout, alternate):
        rebound = _bound_program(program, layout, assets)
        projection = rebound.seats[0].derived_read or rebound.seats[0].offer_previews[0]
        original = program.seats[0].derived_read or program.seats[0].offer_previews[0]
        if layout is alternate:
            assert projection.ports.candidate_type is not original.ports.candidate_type
        assert projection.ports.value_ports is projection.value._ports
        session = rebound.start(assets)
        before = session.author_snapshot()
        read = dict(session.read("actor").fields)
        offer = next(item for item in session.offers("actor") if item.entry == "inspect")
        if factory is _projection:
            assert read[projection.ports.symbol] == (("old", (("condition", "ready"),)),)
        else:
            assert offer.preview == (("condition", "ready"),)
        assert session.author_snapshot() == before
        assert isinstance(session.submit("actor", "inspect", dict(offer.payload)), K0Published)
        if factory is _projection:
            assert dict(session.read("actor").fields)[projection.ports.symbol] == (
                ("old", (("condition", "spent"),)),
            )
        assert not any(item.entry == "inspect" for item in session.offers("actor"))


def test_same_program_two_assets_changes_local_candidate_projection():
    lib, ports, source, assets = _preview()
    program = _compile(lib, ports, source)
    first = program.start(assets)
    assets["opening"]["actor"]["known_tools"] = []
    second = program.start(assets)
    a = next(item for item in first.offers("actor") if item.entry == "inspect")
    b = next(item for item in second.offers("actor") if item.entry == "inspect")
    assert a.preview == (("condition", "ready"),) and b.preview == ()
    assert isinstance(second.submit("actor", b.entry, dict(b.payload)), K0Published)


def test_range_offer_is_not_world_admission_and_rejection_keeps_state():
    lib, ports, source, assets = _parcel(ranged=True)
    session = _compile(lib, ports, source).start(assets)
    rejected = next(item for item in session.offers("sender") if item.label.endswith("gate"))
    before = session.author_snapshot()
    assert isinstance(
        session.submit("sender", rejected.entry, dict(rejected.payload)), K0NotAdmitted
    )
    assert session.author_snapshot() == before
    admitted = next(item for item in session.offers("sender") if item.label.endswith("dock"))
    assert isinstance(session.submit("sender", admitted.entry, dict(admitted.payload)), K0Published)


@pytest.mark.parametrize("kind", ["object", "participant"])
def test_narrow_object_projection_rebinds_without_world_admission_reads(monkeypatch, kind):
    lib, ports, source, assets = _inputs(kind)
    offer = next(
        item for item in source["seats"][0]["offers"] if item["entry"] in ("inspect", "enable")
    )
    root = "target" if kind == "object" else "tool"
    binding = offer["for_each_object"] if kind == "object" else offer["for_each_participants"][root]
    binding["read"].remove(f"{root}.ready")
    offer["when"] = {"const": True}
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    _block_frontend(monkeypatch)
    for layout in (program.world_layout, alternate):
        rebound = _bound_program(program, layout, assets)
        declaration = next(item for item in rebound.seats[0].offers if item.entry == offer["entry"])
        object_reads = (
            declaration.object_read_paths
            if kind == "object"
            else next(role.read_paths for role in declaration.objects if role.name == root)
        )
        assert f"{root}.ready" not in object_reads
        assert f"{root}.ready" not in declaration.ports.readable_paths
        assert f"{root}.ready" in dict(rebound.actions)[offer["entry"]].value._ports.readable_paths
        session = rebound.start(assets)
        candidate = next(
            item for item in session.offers(rebound.seats[0].symbol) if item.entry == offer["entry"]
        )
        seat = rebound.seats[0].symbol
        assert isinstance(
            session.submit(seat, candidate.entry, dict(candidate.payload)), K0Published
        )
        assert candidate in session.offers(seat)
        before = session.author_snapshot()
        history = session._runtime.occurrence_history()
        assert isinstance(
            session.submit(seat, candidate.entry, dict(candidate.payload)), K0NotAdmitted
        )
        assert session.author_snapshot() == before
        assert session._runtime.occurrence_history() == history


@pytest.mark.parametrize("kind", ["object", "participant"])
def test_projection_cannot_read_an_omitted_world_field_or_inherit_it_at_bind(kind):
    lib, ports, source, _ = _inputs(kind)
    offer = next(
        item for item in source["seats"][0]["offers"] if item["entry"] in ("inspect", "enable")
    )
    root = "target" if kind == "object" else "tool"
    binding = offer["for_each_object"] if kind == "object" else offer["for_each_participants"][root]
    binding["read"].remove(f"{root}.ready")
    with pytest.raises(C0LawError, match="read boundary"):
        _compile(lib, ports, source)
    offer["when"] = {"const": True}
    program = _compile(lib, ports, source)
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    candidate = next(item for item in seat.offers if item.entry == offer["entry"])
    altered = replace(
        candidate,
        ports=replace(
            candidate.ports,
            readable_paths=candidate.ports.readable_paths | {f"{root}.ready"},
            admission_readable_paths=candidate.ports.admission_readable_paths | {f"{root}.ready"},
        ),
    )
    forged = replace(
        ir,
        seats=(
            replace(
                seat, offers=tuple(altered if item is candidate else item for item in seat.offers)
            ),
        ),
    )
    with pytest.raises(C0LawError, match="declared read authority"):
        bind_visibility(forged, bind_world(program.world_ir, program.world_layout))


@pytest.mark.parametrize("fault", ["foreign_actor", "hidden_read", "foreign_entry"])
def test_visibility_rejects_foreign_seat_authority(fault):
    lib, ports, source, _ = _parcel()
    program = _compile(lib, ports, source)
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    with pytest.raises(C0LawError, match="authority|read|alias"):
        altered = replace(
            seat,
            **{
                "foreign_actor": {"actor": "receiver"},
                "hidden_read": {"read_paths": (*seat.read_paths, "receiver.notice")},
                "foreign_entry": {"entries": (*seat.entries, "confirm")},
            }[fault],
        )
        bind_visibility(
            replace(ir, seats=(altered, *ir.seats[1:])),
            bind_world(program.world_ir, program.world_layout),
        )


def test_visibility_rejects_wrong_world_without_frontend():
    first = _compile(*_parcel()[:3])
    second = _compile(*_parcel()[:3])
    with pytest.raises(C0LawError, match="exact selected world"):
        bind_visibility(first.visibility_ir, bind_world(second.world_ir, second.world_layout))


def test_offer_binding_cannot_inherit_hidden_action_scene_reads():
    program = _compile(*_parcel()[:3])
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    offer = seat.offers[0]
    ports = replace(
        offer.ports,
        readable_paths=offer.ports.readable_paths | {"scene.routes"},
        admission_readable_paths=offer.ports.admission_readable_paths | {"scene.routes"},
    )
    forged = replace(
        ir, seats=(replace(seat, offers=(replace(offer, ports=ports),)), *ir.seats[1:])
    )
    with pytest.raises(C0LawError, match="read/domain authority"):
        bind_visibility(forged, bind_world(program.world_ir, program.world_layout))


def test_projection_rejects_foreign_root_record():
    program = _compile(*_projection()[:3])
    ir, seat = program.visibility_ir, program.visibility_ir.seats[0]
    projection = seat.derived_read
    value = projection.body.value
    ports = replace(
        value.ports,
        roots=tuple(
            (name, dict(value.ports.roots)["scene"] if name == "actor" else kind)
            for name, kind in value.ports.roots
        ),
    )
    altered = replace(projection, body=replace(projection.body, value=replace(value, ports=ports)))
    with pytest.raises(C0LawError, match="nominal/read-only port"):
        bind_visibility(
            replace(ir, seats=(replace(seat, derived_read=altered),)),
            bind_world(program.world_ir, program.world_layout),
        )


def test_nullable_nested_object_permission_rebinds_under_two_layouts(monkeypatch):
    lib, ports, source, assets = _projection()
    lib["records"].append(
        {
            "name": "Detail",
            "fields": [{"name": "name", "type": {"str": [1, 64]}}],
            "invariant": None,
        }
    )
    next(item for item in lib["records"] if item["name"] == "Tool")["fields"].append(
        {"name": "detail", "type": {"optional": "Detail"}}
    )
    next(item for item in ports["actions"] if item["symbol"] == "inspect")["value"]["read"].append(
        "target.detail.name"
    )
    next(item for item in source["seats"][0]["offers"] if item["entry"] == "inspect")[
        "for_each_object"
    ]["read"].append("target.detail.name")
    source["lawdefs"][0]["body"]["value"]["outputs"]["formed_tool"]["record"]["fields"][
        "detail"
    ] = {"const": None}
    for item in assets["opening_objects"]:
        item["state"]["detail"] = None
    program = _compile(lib, ports, source)
    alternate = _layout(program)
    _block_frontend(monkeypatch)
    for layout in (program.world_layout, alternate):
        rebound = _bound_program(program, layout, assets)
        declaration = next(item for item in rebound.seats[0].offers if item.entry == "inspect")
        detail = layout.owners.record_layout.record("Detail")
        assert declaration.ports.readable_fields[detail] == frozenset({"name"})
        session = rebound.start(assets)
        offer = next(item for item in session.offers("actor") if item.entry == "inspect")
        assert isinstance(session.submit("actor", offer.entry, dict(offer.payload)), K0Published)
