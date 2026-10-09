"""Receipt dispatch keeps identity, failure and nested-operation boundaries."""

import builtins
import weakref
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nomos_kernel import K0ProfileError
from test_nominal_owner_layout_v1 import _lib
from test_operation_local_validation_v1 import body_calls

from nomos_c0 import validation_operation_v1 as operations
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.generated_record_v1 import make_nominal_record, seal_nominal_record


@contextmanager
def _dispatch_operation(*carriers):
    """Exercise private dispatch, not the generator's qualification procedure."""
    contract = SimpleNamespace(
        dependencies=tuple(SimpleNamespace(carrier=carrier) for carrier in carriers)
    )
    operation = operations._Operation(contract, object())
    token = operations._active.set(operation)
    try:
        yield operation
    finally:
        operation.invalidate()
        operations._active.reset(token)


class _Value:
    def __eq__(self, other):
        pytest.fail("receipt dispatch compared values")

    def __hash__(self):
        pytest.fail("receipt dispatch hashed a value")


def test_inline_dispatch_uses_one_id_on_success_and_hit_without_method_call(monkeypatch):
    ids = []
    validated = []

    def observed_id(value):
        ids.append(value)
        return builtins.id(value)

    def forbidden(*args):
        pytest.fail("wrapper called the old operation.validate layer")

    monkeypatch.setattr(operations, "id", observed_id, raising=False)
    monkeypatch.setattr(operations._Operation, "validate", forbidden, raising=False)
    validate = operations.wrap_generated_validator(_Value, validated.append)
    first, second = _Value(), _Value()
    with _dispatch_operation(_Value) as operation:
        validate(first)
        assert len(ids) == 1 and ids[0] is first
        prior = operation.successes[builtins.id(first)]
        assert prior[0] is first and prior[1] is _Value
        validate(first)
        validate(second)
        assert len(ids) == 3
        assert len(validated) == 2 and validated[0] is first and validated[1] is second


@pytest.mark.parametrize("mismatch", ["object", "carrier"])
def test_receipt_requires_both_strong_object_and_carrier_identity(mismatch):
    calls = []
    value, other = _Value(), _Value()
    validate = operations.wrap_generated_validator(_Value, calls.append)
    with _dispatch_operation(_Value) as operation:
        operation.successes[builtins.id(value)] = (
            other if mismatch == "object" else value,
            object if mismatch == "carrier" else _Value,
        )
        validate(value)
        assert len(calls) == 1 and calls[0] is value
        prior = operation.successes[builtins.id(value)]
        assert prior[0] is value and prior[1] is _Value


def test_receipt_retains_strong_reference_until_invalidation():
    validate = operations.wrap_generated_validator(_Value, lambda value: None)
    with _dispatch_operation(_Value) as operation:
        value = _Value()
        reference = weakref.ref(value)
        validate(value)
        del value
        assert reference() is not None
        operation.invalidate()
        assert reference() is None and operation.successes == {}


@pytest.mark.parametrize("error_type", [K0ProfileError, KeyboardInterrupt, SystemExit])
def test_base_exception_clears_and_disables_scope_and_is_not_swallowed(error_type):
    calls = []
    failure = error_type("dispatch failure")

    def body(value):
        calls.append(value)
        if len(calls) == 2:
            raise failure

    validate = operations.wrap_generated_validator(_Value, body)
    first, second = _Value(), _Value()
    with _dispatch_operation(_Value) as operation:
        validate(first)
        with pytest.raises(error_type) as caught:
            validate(second)
        assert caught.value is failure
        assert operation.successes == {} and operation.enabled is False
        validate(first)
        validate(first)
        assert len(calls) == 4 and operation.successes == {}


def test_disabled_operation_still_validates_without_identity_lookup(monkeypatch):
    calls = []
    validate = operations.wrap_generated_validator(_Value, calls.append)

    def forbidden_id(value):
        pytest.fail("disabled operation computed an identity key")

    monkeypatch.setattr(operations, "id", forbidden_id, raising=False)
    with _dispatch_operation(_Value) as operation:
        operation.invalidate()
        value = _Value()
        validate(value)
        validate(value)
        assert len(calls) == 2 and operation.successes == {}


@pytest.mark.parametrize("boundary", ["foreign_owner", "nested_operation"])
def test_body_boundary_prevents_success_receipt_after_return(boundary):
    calls = []

    def body(value):
        calls.append(value)
        if boundary == "foreign_owner":
            operations.check_owner_boundary(object())
        else:
            with operations.validation_operation(None, object()):
                assert operations._active.get() is None

    validate = operations.wrap_generated_validator(_Value, body)
    with _dispatch_operation(_Value) as operation:
        value = _Value()
        validate(value)
        assert operations._active.get() is operation
        assert operation.enabled is False and operation.successes == {}
        validate(value)
        assert len(calls) == 2 and operation.successes == {}


def test_foreign_carrier_invalidates_prior_receipts_before_callback():
    known = operations.wrap_generated_validator(_Value, lambda value: None)

    def foreign_body(value):
        operation = operations._active.get()
        assert operation.enabled is False and operation.successes == {}
        raise K0ProfileError("foreign current callback")

    foreign = operations.wrap_generated_validator(object, foreign_body)
    with _dispatch_operation(_Value) as operation:
        known(_Value())
        assert operation.successes
        with pytest.raises(K0ProfileError, match="foreign current callback"):
            foreign(object())
        assert operation.enabled is False and operation.successes == {}


def test_no_operation_never_reuses_success():
    calls = []
    validate = operations.wrap_generated_validator(_Value, calls.append)
    value = _Value()
    assert operations._active.get() is None
    validate(value)
    validate(value)
    assert len(calls) == 2


def test_actual_generated_graph_keeps_nested_receipts_and_new_operation_validation():
    lib = check_nominal_lib(_lib())
    owner = lib.owner("box").owner
    item = lib.record("Item")("x", 3, None)
    state = lib.record("Box")(item, (item,))
    with body_calls(type(item)) as nested:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
            owner.validate_state(replace(state))
        assert len(nested) == 1
        with owner.validation_operation():
            owner.validate_state(state)
        assert len(nested) == 2
    object.__setattr__(item, "amount", 5)
    with pytest.raises(K0ProfileError, match="invariant"):
        with owner.validation_operation():
            owner.validate_state(state)


def test_sealed_native_callback_has_no_new_qualification():
    calls = []

    def body(value):
        calls.append(value)
        if len(calls) == 2:
            raise K0ProfileError("second native callback")

    native = seal_nominal_record(
        make_nominal_record("Native", [("value", int)], namespace={"validate_for_k0": body})
    )
    value = native(1)
    with operations.validation_operation(native, object()):
        assert operations._active.get() is None
        value.validate_for_k0()
        with pytest.raises(K0ProfileError, match="second native callback"):
            value.validate_for_k0()
    assert len(calls) == 2
