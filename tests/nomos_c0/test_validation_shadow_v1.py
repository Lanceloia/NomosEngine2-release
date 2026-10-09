"""Diagnostic tracing preserves validation calls and cannot authorize reuse."""

import json
import sys
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import _clone_owner_state, _isolate_candidate_owner_state
from test_nominal_owner_layout_v1 import _lib

from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from tools import c0_benchmark_m1_continue as benchmark
from tools.c0_validation_shadow import ValidationShadow


@pytest.fixture
def declared():
    lib = check_nominal_lib(_lib())
    item = lib.record("Item")("x", 3, None)
    state = lib.record("Box")(item, (item,))
    return lib.owner("box").owner, state


@pytest.mark.parametrize(
    "operation,kind", [(_isolate_candidate_owner_state, "isolate"), (_clone_owner_state, "clone")]
)
def test_original_and_clone_are_not_conflated(declared, operation, kind):
    owner, state = declared
    observer = ValidationShadow()
    with observer:
        result = operation(owner, state)
    assert result == state and result is not state
    report = observer.report()
    counts = report["counts"]
    assert counts[f"{kind}_operations"] == 1
    assert counts["scoped_owner_validation_calls"] == 4
    assert counts["same_owner_state_reentries"] == 2
    assert counts["same_owner_state_code_reentries"] == 2
    assert counts["distinct_output_operations"] == 1
    sample = report["samples"][0]
    assert sample["input"] != sample["output"]
    assert [row["state"] for row in sample["calls"]] == [sample["input"]] * 2 + [
        sample["output"]
    ] * 2
    assert "none" in report["qualification"]
    assert not observer.operations and not observer.validation_frames
    assert sys.getprofile() is None
    json.dumps(report)


def test_second_call_failure_is_not_skipped_or_reported_as_success(declared):
    owner, state = declared
    carrier = type(state)
    original = carrier.validate_for_k0
    traces = []

    def check(value):
        traces.append(value is state)
        original(value)
        if len(traces) == 2:
            raise K0ProfileError("second validation failed")

    observer = ValidationShadow()
    # Private fault injection observes isolation; it is not author hot reload.
    type.__setattr__(carrier, "validate_for_k0", check)
    try:
        with pytest.raises(K0ProfileError, match="second validation failed"):
            with observer:
                _isolate_candidate_owner_state(owner, state)
    finally:
        type.__setattr__(carrier, "validate_for_k0", original)
    assert traces == [True, True]
    report = observer.report()
    assert report["counts"]["scoped_owner_validation_calls"] == 2
    assert report["samples"][0]["output"] is None
    assert report["patterns"][0]["value_returned"] is False
    assert not observer.operations and not observer.validation_frames
    assert sys.getprofile() is None


def test_operations_do_not_share_identity_evidence(declared):
    owner, state = declared
    observer = ValidationShadow(sample_limit=1)
    with observer:
        first = _isolate_candidate_owner_state(owner, state)
        second = _isolate_candidate_owner_state(owner, first)
    assert first is not second and state is not second
    report = observer.report()
    assert report["counts"]["isolate_operations"] == 2
    assert report["counts"]["same_owner_state_reentries"] == 4
    assert len(report["samples"]) == 1
    assert report["patterns"][0]["operations"] == 2


def test_tracing_does_not_hash_repr_or_add_state_equality_calls(declared):
    owner, state = declared
    carrier = type(state)
    original = carrier.__eq__
    seen = []

    def eq(left, right):
        seen.append((left is state, right is state))
        return original(left, right)

    def forbidden(*args):
        pytest.fail("observer inspected the world value")

    originals = {name: getattr(carrier, name) for name in ("__eq__", "__hash__", "__repr__")}
    # Private diagnostic spies; no public mutation interface is reopened.
    for name, callback in (("__eq__", eq), ("__hash__", forbidden), ("__repr__", forbidden)):
        type.__setattr__(carrier, name, callback)
    try:
        _isolate_candidate_owner_state(owner, state)
        expected = list(seen)
        seen.clear()
        with ValidationShadow() as observer:
            _isolate_candidate_owner_state(owner, state)
        assert seen == expected
        json.dumps(observer.report())
    finally:
        for name, callback in originals.items():
            type.__setattr__(carrier, name, callback)


def test_run_filter_excludes_operations_outside_selected_call(declared):
    owner, state = declared

    def run():
        return _isolate_candidate_owner_state(owner, state)

    observer = ValidationShadow(run_codes=(run.__code__,))
    with observer:
        _isolate_candidate_owner_state(owner, state)
        run()
        _isolate_candidate_owner_state(owner, state)
    assert observer.report()["counts"]["isolate_operations"] == 1


def test_equal_but_distinct_code_is_not_a_selected_run(declared):
    owner, state = declared

    def run():
        return _isolate_candidate_owner_state(owner, state)

    copied_code = run.__code__.replace()
    assert copied_code == run.__code__ and copied_code is not run.__code__
    other_run = FunctionType(copied_code, run.__globals__, closure=run.__closure__)
    observer = ValidationShadow(run_codes=(run.__code__,))
    with observer:
        other_run()
        run()
    assert observer.report()["counts"]["isolate_operations"] == 1


def test_existing_profiler_and_observer_reuse_are_rejected():
    def other(*args):
        pass

    sys.setprofile(other)
    try:
        with pytest.raises(RuntimeError, match="empty profiler"):
            with ValidationShadow():
                pytest.fail("entered occupied profiler")
        assert sys.getprofile() is other
    finally:
        sys.setprofile(None)
    observer = ValidationShadow()
    with observer:
        with pytest.raises(RuntimeError, match="finish observation"):
            observer.report()
    with pytest.raises(RuntimeError, match="fresh instance"):
        with observer:
            pass


def test_replaced_profiler_is_not_silently_overwritten():
    def other(*args):
        pass

    observer = ValidationShadow()
    try:
        with pytest.raises(RuntimeError, match="replaced"):
            with observer:
                sys.setprofile(other)
        assert sys.getprofile() is other
        assert not observer.active and not observer.operations
    finally:
        sys.setprofile(None)


@pytest.mark.parametrize("fails", [False, True])
def test_benchmark_observer_excludes_compile_start_and_snapshot(monkeypatch, fails):
    seen = []

    class Observer:
        def __enter__(self):
            seen.append("enter")

        def __exit__(self, *errors):
            seen.append("exit")

    class Session:
        time = 0
        _runtime = SimpleNamespace(_individual_scope="local")

        def continue_form(self, seat):
            seen.append("continue")
            return SimpleNamespace(
                finished=fails,
                ready_seats=("adventurer",),
                offers=(SimpleNamespace(entry="wait_adventurer", payload=()),),
            )

        def submit(self, *args):
            seen.append("submit")
            self.time += 100
            return 1

        def author_snapshot(self):
            seen.append("snapshot")
            return SimpleNamespace(occurrences=())

    session = Session()
    bundle = SimpleNamespace(assets=SimpleNamespace(to_data=lambda: {}))

    def compile_bundle(actual):
        seen.append("compile")
        return SimpleNamespace(start=start)

    def start(assets):
        seen.append("start")
        return session

    monkeypatch.setattr(benchmark, "read_source_bundle", lambda path: bundle)
    monkeypatch.setattr(benchmark, "compile_source_bundle", compile_bundle)
    monkeypatch.setattr(benchmark, "K0Published", int)
    monkeypatch.setattr(benchmark, "_snapshot_digest", lambda *args: "digest")
    monkeypatch.setattr(benchmark, "asdict", lambda value: value)
    session._runtime.action_value_history = lambda: ()
    if fails:
        with pytest.raises(ValueError, match="opportunity"):
            benchmark.measure(Path("unused"), run_observer=Observer())
        assert seen == ["compile", "start", "enter", "continue", "exit"]
    else:
        result = benchmark.measure(Path("unused"), run_observer=Observer())
        assert result["time"] == 200
        assert seen == [
            "compile",
            "start",
            "enter",
            "continue",
            "submit",
            "continue",
            "submit",
            "continue",
            "exit",
            "snapshot",
        ]


def test_benchmark_rejects_combined_profilers_before_loading_assets():
    with pytest.raises(ValueError, match="one observer"):
        benchmark.measure(Path("unused"), profile_path=Path("unused"), run_observer=object())
