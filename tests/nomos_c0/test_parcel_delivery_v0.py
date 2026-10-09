"""Second-domain authored Source builds a small playable C0 parcel world."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nomos_kernel import K0ProfileError, K0SourceSpecKey
from nomos_kernel._settlement_outcome_abi import K0NotAdmitted, K0Published, K0SettlementDefect

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError
from nomos_c0.composable_value_v1 import C0ValueRangeError
from nomos_c0.declarative_graph_ports_v0 import check_graph_ports
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.examples.parcel_delivery_v0 import (
    RECEIVER_KEY,
    ROOT,
    SCENE_KEY,
    SENDER_KEY,
    Parcel,
    Receipt,
    library,
    main,
    open_session,
    play,
)
from nomos_c0.owner_graph_v1 import compile_owner_graph
from nomos_c0.program_runtime_v1 import C0ControlCommand


def _source() -> dict[str, object]:
    return json.loads((ROOT / "parcel_delivery_v0.source.json").read_text(encoding="utf-8"))


def _assets(suffix: str = "a") -> dict[str, object]:
    path = ROOT / f"parcel_delivery_v0.{suffix}.assets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _keyed_route_library():
    nominal = check_nominal_lib((ROOT / "parcel_delivery_v0.lib.json").read_text(encoding="utf-8"))
    ports = json.loads((ROOT / "parcel_delivery_v0.ports.json").read_text(encoding="utf-8"))
    ports["actions"][0]["value"]["collections"]["scene.routes"] = "destination"
    return check_graph_ports(ports, nominal)


def _dispatch(session: object) -> None:
    frame = session.form_frame("sender")
    assert frame.ready_seats == ("sender",)
    assert len(frame.offers) == 1
    offer = frame.offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)


def _advance_to_arrival(session: object, tick: int) -> None:
    assert session.form_frame("sender").ready_seats == ("sender", "receiver")
    before = session._runtime.occurrence_history()
    session.defer_form("sender")
    session.defer_form("receiver")
    assert session._runtime.occurrence_history() == before
    stopped = session.continue_form("receiver")
    assert stopped.time == tick
    assert stopped.ready_seats == ("sender", "receiver")


def test_shared_control_and_author_snapshot_include_due_without_local_leak() -> None:
    program = compile_owner_graph(library(), _source())
    session = program.start(_assets())
    offer = session.form_frame("sender").offers[0]
    dispatched = session.apply_control(C0ControlCommand("submit", "sender", offer=offer))
    assert isinstance(dispatched.result, K0Published)
    after_dispatch = session.author_snapshot()
    assert after_dispatch.occurrences == tuple(dispatched.result.occurrences)
    assert len(after_dispatch.occurrences) == 4
    assert after_dispatch.form_choices == ()

    session.apply_control(C0ControlCommand("defer", "sender"))
    session.apply_control(C0ControlCommand("defer", "receiver"))
    after_defer = session.author_snapshot()
    assert after_defer.occurrences == after_dispatch.occurrences
    assert [item.seat for item in after_defer.form_choices] == ["sender", "receiver"]

    advanced = session.apply_control(C0ControlCommand("continue", "receiver"))
    assert advanced.result.time == 2
    snapshot = session.author_snapshot()
    due = snapshot.occurrences[len(after_defer.occurrences) :]
    assert [item.source for item in due] == [K0SourceSpecKey("c0.parcel.arrive.due")]
    assert snapshot.form_choices == after_defer.form_choices
    assert dict(snapshot.owners)["scene"].parcel.arrival_ref == due[0].occurrence
    assert not hasattr(advanced, "published")
    assert "scene.routes" not in dict(session.read("receiver").fields)

    with pytest.raises(C0BindingError, match="submit needs one current offer"):
        session.apply_control(C0ControlCommand("submit", "sender"))


@pytest.mark.parametrize(("suffix", "arrival_time"), (("a", 2), ("b", 4)))
def test_one_source_and_program_start_two_assets_with_real_k0_chain(
    suffix: str, arrival_time: int
) -> None:
    program = compile_owner_graph(library(), _source())
    session = program.start(_assets(suffix))
    assert session.time == 0
    assert session.form_frame("receiver").offers == ()
    assert "scene.routes" not in dict(session.form_frame("receiver").view.fields)
    _dispatch(session)

    action, depart, notice, manifest = session._runtime.occurrence_history()
    assert [item.source for item in (action, depart, notice, manifest)] == [
        K0SourceSpecKey("c0.parcel.dispatch"),
        K0SourceSpecKey("c0.parcel.depart"),
        K0SourceSpecKey("c0.parcel.notice"),
        K0SourceSpecKey("c0.parcel.manifest"),
    ]
    assert depart.formation_basis.predecessor == action.occurrence
    assert notice.formation_basis.predecessor == depart.occurrence
    assert manifest.formation_basis.predecessor == depart.occurrence
    scene = session._runtime.read_owner(SCENE_KEY).view
    sender = session._runtime.read_owner(SENDER_KEY).view
    receiver = session._runtime.read_owner(RECEIVER_KEY).view
    assert scene.parcel == Parcel("P-1", "dock", "transit", depart.occurrence, None)
    assert sender.sent_ref == action.occurrence
    assert receiver.notice.departure == depart.occurrence
    assert receiver.notice.notification == notice.occurrence
    assert receiver.receipt is None
    assert session.form_frame("receiver").offers == ()

    _advance_to_arrival(session, arrival_time)
    due = session._runtime.occurrence_history()[-1]
    assert due.source == K0SourceSpecKey("c0.parcel.arrive.due")
    assert due.semantic_envelope.formation == action.occurrence
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.arrival_ref == due.occurrence
    offer = session.form_frame("receiver").offers[0]
    assert offer.entry == "confirm"
    assert isinstance(session.submit("receiver", offer.entry, dict(offer.payload)), K0Published)
    confirmation = session._runtime.occurrence_history()[-1]
    assert confirmation.source == K0SourceSpecKey("c0.parcel.confirm")
    assert session._runtime.read_owner(RECEIVER_KEY).view.receipt == Receipt(
        due.occurrence, confirmation.occurrence
    )


def test_one_compiled_program_reuses_two_distinct_assets() -> None:
    program = compile_owner_graph(library(), _source())
    first, second = program.start(_assets("a")), program.start(_assets("b"))
    assert first.program is second.program is program
    _dispatch(first)
    _dispatch(second)
    for session in (first, second):
        action, depart, notice, manifest = session._runtime.occurrence_history()
        assert [item.source for item in (action, depart, notice, manifest)] == [
            K0SourceSpecKey("c0.parcel.dispatch"),
            K0SourceSpecKey("c0.parcel.depart"),
            K0SourceSpecKey("c0.parcel.notice"),
            K0SourceSpecKey("c0.parcel.manifest"),
        ]
        assert depart.formation_basis.predecessor == action.occurrence
        assert notice.formation_basis.predecessor == depart.occurrence
        assert manifest.formation_basis.predecessor == depart.occurrence
        scene = session._runtime.read_owner(SCENE_KEY).view
        assert scene.parcel.depart_ref == depart.occurrence
        assert scene.signal == "manifested"
        assert session._runtime.read_owner(SENDER_KEY).view.sent_ref == action.occurrence
        receiver_notice = session._runtime.read_owner(RECEIVER_KEY).view.notice
        assert receiver_notice.departure == depart.occurrence
        assert receiver_notice.notification == notice.occurrence
    _advance_to_arrival(first, 2)
    _advance_to_arrival(second, 4)
    for session in (first, second):
        due = session._runtime.occurrence_history()[-1]
        assert due.source == K0SourceSpecKey("c0.parcel.arrive.due")
        assert session._runtime.read_owner(SCENE_KEY).view.parcel.arrival_ref == due.occurrence


@pytest.mark.parametrize(
    "routes",
    (
        [],
        [{"destination": "other", "travel": 2}],
        [{"destination": "dock", "travel": 2}, {"destination": "dock", "travel": 3}],
    ),
)
def test_zero_or_multiple_matching_routes_cannot_dispatch(routes: list[dict[str, object]]) -> None:
    assets = _assets()
    assets["opening"]["scene"]["routes"] = routes
    session = compile_owner_graph(library(), _source()).start(assets)
    offer = session.form_frame("sender").offers[0]
    assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0NotAdmitted)
    assert session._runtime.occurrence_history() == ()
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == "home"
    assert session._runtime.read_owner(SENDER_KEY).view.sent_ref is None
    assert session._runtime.read_owner(RECEIVER_KEY).view.notice is None


def test_mixed_routes_select_the_matching_destination() -> None:
    assets = _assets()
    assets["opening"]["scene"]["routes"] = [
        {"destination": "other", "travel": 1},
        {"destination": "dock", "travel": 3},
    ]
    session = compile_owner_graph(library(), _source()).start(assets)
    _dispatch(session)
    _advance_to_arrival(session, 3)
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == "arrived"


@pytest.mark.parametrize(
    ("predicate", "admitted"),
    (
        ({"not": {"eq": [{"ref": "scene.parcel.status"}, {"const": "held"}]}}, True),
        ({"not": {"eq": [{"ref": "scene.parcel.status"}, {"const": "home"}]}}, False),
        (
            {
                "any": [
                    {"eq": [{"ref": "scene.parcel.status"}, {"const": "held"}]},
                    {"eq": [{"ref": "scene.parcel.status"}, {"const": "home"}]},
                ]
            },
            True,
        ),
        (
            {
                "any": [
                    {"eq": [{"ref": "scene.parcel.status"}, {"const": "held"}]},
                    {"eq": [{"ref": "scene.parcel.status"}, {"const": "arrived"}]},
                ]
            },
            False,
        ),
    ),
)
def test_boolean_not_and_any_change_real_k0_admission(
    predicate: dict[str, object], admitted: bool
) -> None:
    source = _source()
    original = source["lawdefs"][0]["body"]["value"]["guard"]
    source["lawdefs"][0]["body"]["value"]["guard"] = {"all": [original, predicate]}
    session = compile_owner_graph(library(), source).start(_assets())
    offer = session.form_frame("sender").offers[0]
    result = session.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published if admitted else K0NotAdmitted)
    assert bool(session._runtime.occurrence_history()) is admitted


@pytest.mark.parametrize(("condition", "admitted"), ((True, False), (False, True)))
def test_union_scalar_equality_does_not_alias_bool_and_int_in_k0(
    condition: bool, admitted: bool
) -> None:
    source = _source()
    original = source["lawdefs"][0]["body"]["value"]["guard"]
    source["lawdefs"][0]["body"]["value"]["guard"] = {
        "all": [
            original,
            {
                "eq": [
                    {
                        "if": {
                            "when": {"const": condition},
                            "then": {"const": True},
                            "else": {"const": 1},
                        }
                    },
                    {"const": 1},
                ]
            },
        ]
    }
    session = compile_owner_graph(library(), source).start(_assets())
    offer = session.form_frame("sender").offers[0]
    result = session.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published if admitted else K0NotAdmitted)
    assert bool(session._runtime.occurrence_history()) is admitted


@pytest.mark.parametrize(
    ("predicate", "diagnostic"),
    (
        ({"not": {"const": 1}}, "unknown or mistyped operation"),
        ({"any": [{"const": 1}]}, "non-boolean member"),
        ({"any": []}, "boolean collection cannot be empty"),
    ),
)
def test_boolean_not_and_any_reject_mistyped_author_laws(
    predicate: dict[str, object], diagnostic: str
) -> None:
    source = _source()
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"] = {"all": [value["guard"], predicate]}
    with pytest.raises(C0LawError, match=diagnostic):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize(("lower_bound", "admitted"), ((0, True), (2, False)))
def test_scalar_binding_and_lt_guard_run_through_k0(lower_bound: int, admitted: bool) -> None:
    source = _source()
    value = source["lawdefs"][0]["body"]["value"]
    value["bindings"].insert(0, {"name": "expected_status", "const": "home"})
    value["guard"]["all"].extend(
        (
            {"eq": [{"ref": "scene.parcel.status"}, {"ref": "expected_status"}]},
            {"lt": [{"const": lower_bound}, {"ref": "route.travel"}]},
        )
    )
    session = compile_owner_graph(library(), source).start(_assets())
    offer = session.form_frame("sender").offers[0]
    result = session.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published if admitted else K0NotAdmitted)
    assert bool(session._runtime.occurrence_history()) is admitted


@pytest.mark.parametrize("change", ("shadowed_binding", "mistyped_lt"))
def test_scalar_binding_and_lt_reject_malformed_author_law(change: str) -> None:
    source = _source()
    value = source["lawdefs"][0]["body"]["value"]
    if change == "shadowed_binding":
        value["bindings"].insert(0, {"name": "actor", "const": "home"})
    else:
        value["guard"]["all"].append({"lt": [{"const": "zero"}, {"ref": "route.travel"}]})
    with pytest.raises(C0LawError):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize(
    ("change", "diagnostic"),
    (
        ("sub_wrong_type", "unknown or mistyped operation"),
        ("is_none_foreign_ref", "reference crosses a declared read boundary"),
        ("all_non_boolean", "non-boolean member"),
    ),
)
def test_v6_value_operations_reject_malformed_author_laws(change: str, diagnostic: str) -> None:
    source = _source()
    value = source["lawdefs"][0]["body"]["value"]
    if change == "sub_wrong_type":
        value["outputs"]["delay"] = {"sub": [{"ref": "route.travel"}, {"const": "one"}]}
    elif change == "is_none_foreign_ref":
        value["guard"]["all"].append({"is_none": {"ref": "scene.private"}})
    else:
        value["guard"]["all"].append({"ref": "route.travel"})
    with pytest.raises(C0LawError, match=diagnostic):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize(
    ("routes", "optional_admitted", "required_admitted"),
    (
        ([], True, False),
        ([{"destination": "dock", "travel": 2}], True, True),
        (
            [{"destination": "dock", "travel": 2}, {"destination": "dock", "travel": 3}],
            False,
            False,
        ),
    ),
)
def test_required_predicate_lookup_distinguishes_zero_one_and_many(
    routes: list[dict[str, object]], optional_admitted: bool, required_admitted: bool
) -> None:
    source = _source()
    value = source["lawdefs"][0]["body"]["value"]
    value["guard"]["all"].remove({"not_none": {"ref": "route"}})
    value["outputs"]["delay"] = {"const": 2}
    assets = _assets()
    assets["opening"]["scene"]["routes"] = routes
    optional = compile_owner_graph(library(), source).start(assets)
    offer = optional.form_frame("sender").offers[0]
    optional_result = optional.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(optional_result, K0Published if optional_admitted else K0NotAdmitted)
    assert bool(optional._runtime.occurrence_history()) is optional_admitted
    assert optional._runtime.read_owner(SCENE_KEY).view.parcel.status == (
        "transit" if optional_admitted else "home"
    )

    value["bindings"][0]["required"] = True
    session = compile_owner_graph(library(), source).start(assets)
    offer = session.form_frame("sender").offers[0]
    result = session.submit("sender", offer.entry, dict(offer.payload))
    assert isinstance(result, K0Published if required_admitted else K0NotAdmitted)
    assert bool(session._runtime.occurrence_history()) is required_admitted
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == (
        "transit" if required_admitted else "home"
    )


@pytest.mark.parametrize(
    ("routes", "admitted", "failure"),
    (
        ([], False, "required or unique lookup failed"),
        ([{"destination": "dock", "travel": 2}], True, None),
        (
            [{"destination": "dock", "travel": 2}, {"destination": "dock", "travel": 3}],
            False,
            "declared collection key is not unique",
        ),
    ),
)
def test_required_key_lookup_rejects_bad_current_state_before_publication(
    routes: list[dict[str, object]], admitted: bool, failure: str | None
) -> None:
    source = _source()
    source["lawdefs"][0]["body"]["value"]["bindings"][0] = {
        "name": "route",
        "collection": "scene.routes",
        "key": "destination",
        "value": {"ref": "payload.destination"},
        "required": True,
    }
    assets = _assets()
    assets["opening"]["scene"]["routes"] = routes
    session = compile_owner_graph(_keyed_route_library(), source).start(assets)
    offer = session.form_frame("sender").offers[0]
    if admitted:
        assert isinstance(session.submit("sender", offer.entry, dict(offer.payload)), K0Published)
    else:
        with pytest.raises(K0ProfileError, match="in-memory preflight failed") as defect:
            session.submit("sender", offer.entry, dict(offer.payload))
        assert failure in str(defect.value.__cause__)
    assert bool(session._runtime.occurrence_history()) is admitted
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == (
        "transit" if admitted else "home"
    )
    assert (session._runtime.read_owner(SENDER_KEY).view.sent_ref is not None) is admitted
    assert (session._runtime.read_owner(RECEIVER_KEY).view.notice is not None) is admitted


@pytest.mark.parametrize(
    "predicate",
    (
        {"eq": [{"ref": "scene.parcel.status"}, {"ref": "route.travel"}]},
        {"le": [{"ref": "scene.parcel.status"}, {"const": 1}]},
    ),
)
def test_value_comparison_rejects_mistyped_v6_law(predicate: dict[str, object]) -> None:
    source = _source()
    source["lawdefs"][0]["body"]["value"]["guard"]["all"].append(predicate)
    with pytest.raises(C0LawError, match="unknown or mistyped operation|scalar"):
        compile_owner_graph(library(), source)


def test_eq_rejects_whole_record_even_with_declared_read_port() -> None:
    source = _source()
    source["lawdefs"][2]["body"]["law"]["guard"] = {
        "eq": [{"ref": "scene.parcel"}, {"ref": "scene.parcel"}]
    }
    with pytest.raises(C0LawError, match="value equality requires scalar"):
        compile_owner_graph(library(), source)


def test_unknown_v6_source_field_rejects_before_start() -> None:
    source = _source()
    source["future_mechanism"] = {}
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize("missing", ("due_events", "temporal"))
def test_v6_temporal_source_requires_both_declarations(missing: str) -> None:
    source = _source()
    del source[missing]
    with pytest.raises(C0LawError, match="missing or unknown fields"):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    (
        ("mechanism", "continuous", "temporal mechanism"),
        ("order", [], "temporal mechanism"),
        ("max_pending", 0, "temporal mechanism"),
        ("max_pending", 2, "temporal mechanism"),
        ("advance_seats", [], "temporal mechanism"),
        ("advance_seats", ["foreign"], "temporal advance seat"),
    ),
)
def test_v6_temporal_selection_rejects_invalid_field_at_compile(
    field: str, value: object, diagnostic: str
) -> None:
    source = _source()
    source["temporal"][field] = value
    with pytest.raises(C0LawError, match=diagnostic):
        compile_owner_graph(library(), source)


@pytest.mark.parametrize("time", (None, -1, True, "0"))
def test_v6_temporal_start_rejects_non_bounded_time(time: object) -> None:
    assets = _assets()
    assets["time"] = time
    with pytest.raises(C0BindingError, match="opening time is not a bounded integer"):
        compile_owner_graph(library(), _source()).start(assets)


def test_opening_guard_range_fault_is_a_start_diagnostic() -> None:
    source = _source()
    source["opening_guard"] = {"eq": [{"sub": [{"const": 0}, {"const": 1}]}, {"const": 0}]}
    program = compile_owner_graph(library(), source)
    with pytest.raises(C0BindingError, match="opening guard evaluation failed") as caught:
        program.start(_assets())
    assert isinstance(caught.value.__cause__, C0ValueRangeError)


def test_v6_is_none_rejects_malformed_operand_at_compile() -> None:
    source = _source()
    source["lawdefs"][0]["body"]["value"]["guard"]["all"].append({"is_none": []})
    with pytest.raises(
        C0LawError, match=r"guard\.all\[5\]\.is_none: value expression must have one operation"
    ):
        compile_owner_graph(library(), source)


def test_record_field_wrong_type_rejects_in_v6_law() -> None:
    source = _source()
    receipt = source["lawdefs"][1]["body"]["value"]["outputs"]["receipt"]
    receipt["record"]["fields"]["arrival"] = {"const": "not-an-occurrence"}
    with pytest.raises(C0LawError, match="record constructor field has the wrong type"):
        compile_owner_graph(library(), source)


def test_copy_cannot_write_undeclared_nominal_field_in_v6_law() -> None:
    source = _source()
    changes = source["lawdefs"][2]["body"]["law"]["outputs"]["parcel"]["copy"]["changes"]
    changes["id"] = {"const": "P-2"}
    with pytest.raises(C0LawError, match="record copy writes an undeclared field"):
        compile_owner_graph(library(), source)


def test_author_law_edit_changes_only_declared_scene_effect() -> None:
    source = _source()
    edited = json.loads(json.dumps(source))
    edited["lawdefs"][4]["body"]["law"]["outputs"]["signal"] = {"const": "flagged"}
    baseline = compile_owner_graph(library(), source).start(_assets())
    changed = compile_owner_graph(library(), edited).start(_assets())
    assert baseline.form_frame("sender") == changed.form_frame("sender")
    assert baseline.form_frame("receiver") == changed.form_frame("receiver")
    _dispatch(baseline)
    _dispatch(changed)
    baseline_scene = baseline._runtime.read_owner(SCENE_KEY).view
    changed_scene = changed._runtime.read_owner(SCENE_KEY).view
    assert replace(baseline_scene, signal="") == replace(changed_scene, signal="")
    assert baseline_scene.signal == "manifested"
    assert changed_scene.signal == "flagged"
    assert (
        baseline._runtime.read_owner(SENDER_KEY).view
        == changed._runtime.read_owner(SENDER_KEY).view
    )
    assert (
        baseline._runtime.read_owner(RECEIVER_KEY).view
        == changed._runtime.read_owner(RECEIVER_KEY).view
    )
    assert [item.source for item in baseline._runtime.occurrence_history()] == [
        item.source for item in changed._runtime.occurrence_history()
    ]


def test_author_due_law_edit_changes_the_receipt_affordance() -> None:
    source = _source()
    edited = json.loads(json.dumps(source))
    edited["lawdefs"][5]["body"]["law"]["outputs"]["parcel"]["copy"]["changes"]["status"] = {
        "const": "held"
    }
    baseline = compile_owner_graph(library(), source).start(_assets())
    changed = compile_owner_graph(library(), edited).start(_assets())
    _dispatch(baseline)
    _dispatch(changed)
    _advance_to_arrival(baseline, 2)
    _advance_to_arrival(changed, 2)
    assert baseline._runtime.read_owner(SCENE_KEY).view.parcel.status == "arrived"
    assert changed._runtime.read_owner(SCENE_KEY).view.parcel.status == "held"
    assert len(baseline.form_frame("receiver").offers) == 1
    assert changed.form_frame("receiver").offers == ()
    assert [item.source for item in baseline._runtime.occurrence_history()] == [
        item.source for item in changed._runtime.occurrence_history()
    ]


def test_source_cannot_override_lib_output_destination() -> None:
    source = _source()
    source["events"][0]["effect"] = {"scene": {"invented": "parcel"}}
    with pytest.raises(C0LawError):
        compile_owner_graph(library(), source)


def test_malformed_route_asset_rejects_before_session() -> None:
    assets = _assets()
    assets["opening"]["scene"]["routes"][0]["travel"] = "two"
    with pytest.raises(C0BindingError):
        compile_owner_graph(library(), _source()).start(assets)


def test_declared_parcel_invariant_rejects_opening_assets_at_start() -> None:
    assets = _assets()
    assets["opening"]["scene"]["parcel"]["status"] = "transit"
    with pytest.raises(C0BindingError, match="opening owner state is not admitted"):
        compile_owner_graph(library(), _source()).start(assets)


def test_declared_parcel_invariant_rejects_due_effect_atomically() -> None:
    source = _source()
    source["lawdefs"][5]["body"]["law"]["outputs"]["parcel"]["copy"]["changes"]["arrival_ref"] = {
        "const": None
    }
    session = compile_owner_graph(library(), source).start(_assets())
    _dispatch(session)
    before_scene = session._runtime.read_owner(SCENE_KEY).view
    before_history = session._runtime.occurrence_history()
    session.defer_form("sender")
    session.defer_form("receiver")
    with pytest.raises(K0SettlementDefect) as defect:
        session.continue_form("receiver")
    assert "declared state invariant is false" in str(defect.value.__cause__)
    assert session._runtime.read_owner(SCENE_KEY).view == before_scene
    assert session._runtime.occurrence_history() == before_history


def test_invalid_event_effect_rolls_back_the_dispatch_wave() -> None:
    source = _source()
    source["lawdefs"][4]["body"]["law"]["outputs"]["signal"] = {"const": "invalid"}
    session = compile_owner_graph(library(), source).start(_assets())
    offer = session.form_frame("sender").offers[0]
    with pytest.raises(K0SettlementDefect):
        session.submit("sender", offer.entry, dict(offer.payload))
    assert session._runtime.occurrence_history() == ()
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == "home"
    assert session._runtime.read_owner(SENDER_KEY).view.sent_ref is None
    assert session._runtime.read_owner(RECEIVER_KEY).view.notice is None
    with pytest.raises(K0SettlementDefect):
        session.submit("sender", offer.entry, dict(offer.payload))


@pytest.mark.parametrize(("suffix", "arrival_time"), (("a", 2), ("b", 4)))
def test_thin_terminal_consumes_form_without_world_branches(
    suffix: str,
    arrival_time: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = iter(("1", "1", "1", "1", "1", "1"))

    def prompt(_text: str) -> str:
        return next(commands)

    monkeypatch.setattr("builtins.input", prompt)
    session = open_session(ROOT / f"parcel_delivery_v0.{suffix}.assets.json")
    play(session)
    output = capsys.readouterr().out
    assert f"Time {arrival_time} | seat receiver" in output
    assert "Acknowledge delivery" in output
    assert f"Time advanced 0 -> {arrival_time}." in output
    assert "sender passed; no world Action was made." in output
    assert "receiver passed; no world Action was made." in output
    assert "Delivery session finished." in output
    assert session._runtime.read_owner(RECEIVER_KEY).view.receipt is not None
    assert "scene.routes" not in output


def test_terminal_invalid_number_and_initial_pass_leave_world_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = iter(("defer", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    session = open_session(ROOT / "parcel_delivery_v0.a.assets.json")
    play(session)
    output = capsys.readouterr().out
    assert "Enter one of the listed numbers." in output
    assert "sender passed; no world Action was made." in output
    assert "Time advanced 0 -> 8." in output
    assert session._runtime.occurrence_history() == ()
    assert session._runtime.read_owner(SCENE_KEY).view.parcel.status == "home"


def test_terminal_hides_stale_offer_at_authored_wake_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source()
    source["game_form"]["wake_at"] = [1]
    session = compile_owner_graph(library(), source).start(_assets())
    commands = iter(("2", "1"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    play(session)
    output = capsys.readouterr().out
    at_wake = output.split("Time 1 | seat sender", 1)[1]
    assert "Dispatch parcel" not in at_wake
    assert "Advance to next event" in at_wake
    assert "Time advanced 1 -> 8." in output
    assert session._runtime.occurrence_history() == ()


def test_terminal_oversized_numeric_input_is_finite_rejection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = iter(("9" * 5000, "3"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    session = open_session(ROOT / "parcel_delivery_v0.a.assets.json")
    play(session)
    assert "Enter one of the listed numbers." in capsys.readouterr().out
    assert session._runtime.occurrence_history() == ()


def test_terminal_switches_to_other_ready_seat_by_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands = iter(("1", "2", "1", "1", "3"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    session = open_session(ROOT / "parcel_delivery_v0.a.assets.json")
    play(session)
    output = capsys.readouterr().out
    assert "Switched to receiver." in output
    assert "Time 0 | seat receiver" in output
    assert "Time advanced 0 -> 2." in output
    assert session._runtime.read_owner(RECEIVER_KEY).view.receipt is None


def test_terminal_uses_authored_game_form_seat_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source()
    source["seats"][0]["name"] = "clerk"
    source["seats"][1]["name"] = "dock_seat"
    source["game_form"]["seats"] = ["clerk", "dock_seat"]
    source["temporal"]["advance_seats"] = ["clerk", "dock_seat"]
    path = tmp_path / "renamed.source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    commands = iter(("1", "1", "1", "1", "1", "1"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))
    session = open_session(ROOT / "parcel_delivery_v0.a.assets.json", path)
    play(session)
    output = capsys.readouterr().out
    assert "Time 0 | seat clerk" in output
    assert "Time 2 | seat dock_seat" in output
    assert "Delivery session finished." in output


def test_explicit_source_path_is_compiled_not_ignored(tmp_path: Path) -> None:
    source = _source()
    source["lawdefs"][4]["body"]["law"]["outputs"]["signal"] = {"const": "flagged"}
    path = tmp_path / "edited.source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    session = open_session(ROOT / "parcel_delivery_v0.a.assets.json", path)
    _dispatch(session)
    assert session._runtime.read_owner(SCENE_KEY).view.signal == "flagged"


def test_missing_author_source_fails_before_play(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["parcel_delivery_v0", "--source", str(tmp_path / "missing.json")]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "Cannot build parcel world:" in captured.err
    assert "Time 0" not in captured.out


def test_terminal_stops_on_fatal_authored_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source()
    source["lawdefs"][4]["body"]["law"]["outputs"]["signal"] = {"const": "invalid"}
    path = tmp_path / "invalid.source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["parcel_delivery_v0", "--source", str(path)])
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 3
    captured = capsys.readouterr()
    assert "World settlement failed" in captured.err
    assert "Published." not in captured.out
