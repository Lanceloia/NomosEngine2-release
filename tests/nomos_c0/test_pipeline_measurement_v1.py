"""Replay measurements rename local opaque scopes without erasing semantic differences."""

from dataclasses import dataclass, replace

from nomos_kernel import K0OccurrenceRef, K0OwnerKey
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from nomos_c0.program_runtime_v1 import C0AuthorSnapshot
from tools.c0_benchmark_m1_route import Journey
from tools.c0_profile_pipeline import _local_value, _snapshot_digest


@dataclass(frozen=True)
class MeasuredState:
    item: _K0IndividualRef
    actor: _K0ActorRef
    foreign: _K0IndividualRef
    count: int
    action: K0OccurrenceRef


@dataclass(frozen=True)
class MeasuredObject:
    individual: _K0IndividualRef
    owner: K0OwnerKey
    current_state: MeasuredState


def _snapshot(scope):
    item = _K0IndividualRef(scope, 1, "item")
    actor = _K0ActorRef(scope, 2, "person")
    state = MeasuredState(
        item, actor, _K0IndividualRef("foreign", 3, "item"), 4, K0OccurrenceRef(1)
    )
    return C0AuthorSnapshot(
        (("state", state),),
        (MeasuredObject(item, K0OwnerKey(f"dynamic.{scope}.1"), state),),
        (),
        (),
        0,
    )


def test_digest_preserves_nested_identity_kind_family_ordinal_and_sources():
    first = _snapshot("first")
    assert _snapshot_digest(first, "first") == _snapshot_digest(_snapshot("second"), "second")
    before = _snapshot_digest(first, "first")
    state = dict(first.owners)["state"]
    for changes in (
        {"item": _K0IndividualRef("other", 1, "item")},
        {"item": _K0IndividualRef("first", 1, "different")},
        {"item": _K0IndividualRef("first", 2, "item")},
        {"item": _K0ActorRef("first", 1, "item")},
        {"foreign": _K0IndividualRef("elsewhere", 3, "item")},
        {"action": K0OccurrenceRef(2)},
        {"count": 5},
    ):
        changed = replace(first, owners=(("state", replace(state, **changes)),))
        assert _snapshot_digest(changed, "first") != before
    assert _snapshot_digest(replace(first, time=1), "first") != before
    assert _snapshot_digest(replace(first, form_choices=(K0OccurrenceRef(2),)), "first") != before


def test_only_registered_owner_keys_are_renamed_not_similar_strings():
    key = K0OwnerKey("dynamic.local.1")
    ref = _K0IndividualRef("local", 1, "item")
    assert _local_value(key, "local", {key: ref}) != _local_value(key, "local", {})
    assert _local_value(key.value, "local", {key: ref}) == key.value
    assert _local_value(ref, "elsewhere", {})["scope"] == {"foreign": "local"}


def test_route_call_measurement_preserves_operation_and_stage_totals(monkeypatch):
    class Session:
        time = 100

    clock = iter((10.0, 12.5, 20.0, 20.75))
    monkeypatch.setattr("tools.c0_benchmark_m1_route.perf_counter", lambda: next(clock))
    session = Session()
    journey = Journey(session)
    result = object()
    invoked = []

    def advance():
        invoked.append("continue")
        session.time = 200
        return result

    assert journey.timed("continue", advance) is result
    journey.actions.append({"entry": "chosen"})
    assert journey.timed("read", lambda: result) is result
    assert invoked == ["continue"]
    assert dict(journey.seconds) == {"continue": 2.5, "read": 0.75}
    assert journey.calls == [
        {
            "phase": "continue",
            "completed_actions": 0,
            "before_time": 100,
            "after_time": 200,
            "seconds": 2.5,
        },
        {
            "phase": "read",
            "completed_actions": 1,
            "before_time": 200,
            "after_time": 200,
            "seconds": 0.75,
        },
    ]
