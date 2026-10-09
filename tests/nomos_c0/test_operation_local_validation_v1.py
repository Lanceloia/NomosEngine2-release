"""Success receipts are generator-qualified and cannot outlive owner operations."""

import builtins
import sys
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import (
    _build_candidate_owner_views,
    _clone_owner_state,
    _isolate_candidate_owner_state,
    _K0OwnerStateDirectory,
)
from nomos_kernel._state_image_abi import _K0OwnerState
from test_nominal_owner_layout_v1 import _lib

from nomos_c0 import validation_operation_v1 as operations
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.generated_record_v1 import make_nominal_record, seal_nominal_record
from nomos_c0.validation_operation_v1 import _active, validation_operation


@pytest.fixture
def declared():
    lib = check_nominal_lib(_lib())
    item = lib.record("Item")("x", 3, None)
    return lib, lib.owner("box").owner, lib.record("Box")(item, (item,))


@contextmanager
def body_calls(carrier):
    wrapper = carrier.validate_for_k0
    body = next(
        cell.cell_contents
        for cell in wrapper.__closure__
        if callable(cell.cell_contents) and hasattr(cell.cell_contents, "__code__")
    )
    calls = []

    def observe(frame, event, arg):
        if event == "call" and frame.f_code is body.__code__:
            value = frame.f_locals["value"]
            if type(value) is carrier:
                calls.append(value)

    assert sys.getprofile() is None
    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(None)


def test_exact_success_is_reused_but_equal_copy_is_fully_validated(declared):
    _, owner, state = declared
    with body_calls(type(state)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
            equal = replace(state)
            owner.validate_state(equal)
            owner.validate_state(equal)
        owner.validate_state(state)
    assert len(calls) == 3
    assert calls[0] is state and calls[1] is equal and calls[2] is state
    assert _active.get() is None


@pytest.mark.parametrize("operation", [_isolate_candidate_owner_state, _clone_owner_state])
def test_kernel_copy_validates_detached_input_and_output_separately(declared, operation):
    _, owner, state = declared
    with body_calls(type(state)) as calls:
        first = operation(owner, state)
        second = operation(owner, state)
    assert first == state and first is not state and second is not first
    expected = 2 if operation is _isolate_candidate_owner_state else 4
    assert len(calls) == expected
    assert all(item == state and item is not state for item in calls)
    assert len({id(item) for item in calls}) == expected
    assert all(item is not first and item is not second for item in calls)
    assert _active.get() is None


def test_one_view_operation_reuses_only_its_own_clone(declared):
    _, owner, state = declared
    profile = SimpleNamespace(owners=(owner,))
    with body_calls(type(state)) as calls:
        views = _build_candidate_owner_views(
            _K0OwnerStateDirectory(profile, (_K0OwnerState(owner.key, state),)), (owner.key,)
        )
    # Kernel validation input, then detached read_view input.
    assert len(calls) == 2
    assert all(item is not state and item == state for item in calls)
    assert calls[1] is views[0].view
    assert views[0].view == state and views[0].view is not state


def test_owner_identity_and_nested_operations_invalidate_receipts(declared):
    _, owner, state = declared
    other = replace(owner)
    with body_calls(type(state)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            other.validate_state(state)
            owner.validate_state(state)
        with owner.validation_operation():
            owner.validate_state(state)
            with owner.validation_operation():
                owner.validate_state(state)
            owner.validate_state(state)
    assert len(calls) == 6
    assert _active.get() is None


def test_failure_disables_scope_and_new_operation_rechecks_changed_invariant(declared):
    lib, owner, state = declared
    invalid = lib.record("Box")(replace(state.item, amount=5), ())
    with body_calls(type(state)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            with pytest.raises(K0ProfileError, match="invariant"):
                owner.validate_state(invalid)
            owner.validate_state(state)
            owner.validate_state(state)
    assert len(calls) == 4
    assert _active.get() is None
    # State changes outside the operation cannot inherit the previous success.
    object.__setattr__(state.item, "amount", 5)
    with pytest.raises(K0ProfileError, match="invariant"):
        _isolate_candidate_owner_state(owner, state)
    assert _active.get() is None


def test_nested_generated_values_reuse_success_without_hash_or_equality(declared):
    _, owner, state = declared
    with body_calls(type(state.item)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
    assert len(calls) == 1 and calls[0] is state.item


def test_sealed_native_callback_has_no_generator_qualification():
    seen = []

    def validate(value):
        seen.append(value)
        if len(seen) == 2:
            raise K0ProfileError("second native validation")

    native = seal_nominal_record(
        make_nominal_record("Native", [("value", int)], namespace={"validate_for_k0": validate})
    )
    value = native(1)
    with validation_operation(native, object()):
        value.validate_for_k0()
        with pytest.raises(K0ProfileError, match="second native"):
            value.validate_for_k0()
    assert len(seen) == 2 and _active.get() is None


def test_unqualified_invariant_operation_keeps_full_validation():
    row = _lib()
    extended = {"append": [{"ref": "state.items"}, {"ref": "state.item"}]}
    row["records"][1]["invariant"] = {
        "le": [
            {"count_matching": {"collection": extended, "as": "element", "where": {"const": True}}},
            {"const": 3},
        ]
    }
    lib = check_nominal_lib(row)
    carrier = lib.record("Item")
    assert carrier.__nomos_validation_contract__ is not None
    assert lib.record("Box").__nomos_validation_contract__ is None
    owner = lib.owner("box").owner
    state = lib.record("Box")(carrier("x", 3, None), ())
    with body_calls(type(state)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
    assert len(calls) == 2


def test_private_nested_callback_replacement_cancels_qualification(declared):
    _, owner, state = declared
    carrier = type(state.item)
    original = carrier.validate_for_k0
    seen = []

    def changed(value):
        seen.append(value)
        original(value)
        if len(seen) == 2:
            raise K0ProfileError("second callback validation")

    type.__setattr__(carrier, "validate_for_k0", changed)
    try:
        with pytest.raises(K0ProfileError, match="second callback"):
            _build_candidate_owner_views(
                _K0OwnerStateDirectory(
                    SimpleNamespace(owners=(owner,)), (_K0OwnerState(owner.key, state),)
                ),
                (owner.key,),
            )
        assert len(seen) == 2
    finally:
        type.__setattr__(carrier, "validate_for_k0", original)
    assert _active.get() is None


def test_foreign_owner_callback_keeps_second_call_failure(declared, monkeypatch):
    _, owner, state = declared
    original = type(owner).validate_state
    seen = []

    def changed(self, value):
        seen.append(value)
        original(self, value)
        if len(seen) == 2:
            raise K0ProfileError("second owner callback")

    monkeypatch.setattr(type(owner), "validate_state", changed)
    with pytest.raises(K0ProfileError, match="second owner callback"):
        _build_candidate_owner_views(
            _K0OwnerStateDirectory(
                SimpleNamespace(owners=(owner,)), (_K0OwnerState(owner.key, state),)
            ),
            (owner.key,),
        )
    assert len(seen) == 2 and _active.get() is None


def test_private_getter_change_at_scope_entry_is_not_qualified(declared):
    _, owner, state = declared
    carrier = type(state.item)
    original = carrier.amount
    type.__setattr__(carrier, "amount", property(lambda value: 99))
    try:
        with pytest.raises(K0ProfileError, match="nominal value"):
            _isolate_candidate_owner_state(owner, state)
    finally:
        type.__setattr__(carrier, "amount", original)
    assert _active.get() is None


def test_variant_payload_bounds_and_case_still_run_in_each_operation():
    from test_variant_types_v1 import declaration, sample

    lib = check_nominal_lib(declaration())
    owner = lib.owner("state").owner
    state = lib.record("State")(sample(lib))
    with body_calls(type(state)) as calls:
        first = _isolate_candidate_owner_state(owner, state)
    assert len(calls) == 1 and all(item is not state and item == state for item in calls)
    assert all(item is not first for item in calls)
    bad_payload = replace(state.result.success, number=99)
    for invalid in (
        replace(state, result=replace(state.result, success=bad_payload)),
        replace(state, result=replace(state.result, case="failure")),
    ):
        with pytest.raises(K0ProfileError):
            _isolate_candidate_owner_state(owner, invalid)
    assert _active.get() is None


@pytest.mark.parametrize(
    "case", ["matching", "mismatch", "missing", "unsealed", "stop_iteration"]
)
def test_dependency_loop_preserves_original_reads_short_circuit_and_exceptions(
    declared, monkeypatch, case
):
    _, _, state = declared
    carrier = type(state.item)
    attributes = (
        ("validate_for_k0", carrier.validate_for_k0),
        ("amount", carrier.amount if case != "mismatch" else object()),
        ("missing_field" if case == "missing" else "origin", carrier.origin),
    )
    dependency = operations._RecordDependency(carrier, attributes)
    reads = []

    def observed(target, name):
        reads.append(name)
        if case == "stop_iteration" and name == "amount":
            raise StopIteration("qualification getter failed")
        return builtins.getattr(target, name)

    monkeypatch.setattr(operations, "getattr", observed, raising=False)
    if case == "unsealed":
        monkeypatch.setattr(operations, "is_sealed_nominal_record", lambda target: False)

    def original():
        return operations.is_sealed_nominal_record(carrier) and all(
            observed(carrier, name) is value for name, value in attributes
        )

    def outcome(callback):
        reads.clear()
        try:
            result = callback()
        except (AttributeError, RuntimeError, StopIteration) as error:
            result = (type(error), str(error), type(error.__cause__))
        return result, tuple(reads)

    assert outcome(dependency.current) == outcome(original)


def test_contract_stops_before_later_dependencies_and_reference_callbacks(declared):
    _, _, state = declared
    carrier = type(state.item)
    mismatch = operations._RecordDependency(carrier, (("amount", object()),))

    class Untouched:
        def current(self):
            pytest.fail("qualification read beyond its first mismatch")

    class ReferenceType(type):
        def __getattribute__(self, name):
            if name == "__post_init__":
                pytest.fail("qualification read references after dependency mismatch")
            return super().__getattribute__(name)

    class Reference(metaclass=ReferenceType):
        pass

    contract = operations._ValidationContract((mismatch, Untouched()), ((Reference, object()),))
    assert contract.current() is False


def test_empty_contract_and_reference_failure_order():
    assert operations._ValidationContract((), ()).current() is True
    reads = []

    class ReferenceType(type):
        def __getattribute__(self, name):
            if name == "__post_init__":
                reads.append(self.__name__)
            return super().__getattribute__(name)

    class First(metaclass=ReferenceType):
        __post_init__ = object()

    class Second(metaclass=ReferenceType):
        pass

    contract = operations._ValidationContract((), ((First, object()), (Second, object())))
    assert contract.current() is False
    assert reads == ["First"]
    with pytest.raises(AttributeError):
        operations._ValidationContract((), ((Second, object()),)).current()
    assert reads == ["First", "Second"]


def test_native_reference_callback_is_rechecked_at_each_scope_entry(declared, monkeypatch):
    from nomos_kernel import K0OccurrenceRef

    _, owner, state = declared
    with body_calls(type(state)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
        assert len(calls) == 1
        monkeypatch.setattr(K0OccurrenceRef, "__post_init__", lambda value: None)
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
        assert len(calls) == 3
    assert _active.get() is None


def test_contract_preserves_generator_stop_iteration_boundary():
    class Dependency:
        def current(self):
            raise StopIteration("dependency failed")

    with pytest.raises(RuntimeError, match="generator raised StopIteration") as caught:
        operations._ValidationContract((Dependency(),), ()).current()
    assert type(caught.value.__cause__) is StopIteration

    class ReferenceType(type):
        def __getattribute__(self, name):
            if name == "__post_init__":
                raise StopIteration("reference getter failed")
            return super().__getattribute__(name)

    class Reference(metaclass=ReferenceType):
        pass

    with pytest.raises(RuntimeError, match="generator raised StopIteration") as caught:
        operations._ValidationContract((), ((Reference, object()),)).current()
    assert type(caught.value.__cause__) is StopIteration
