"""Contract call fusion preserves current reads and operation boundaries."""

import builtins
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from test_nominal_owner_layout_v1 import _lib

from nomos_c0 import validation_operation_v1 as operations
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.generated_record_v1 import make_nominal_record, seal_nominal_record


@pytest.fixture
def graph():
    lib = check_nominal_lib(_lib())
    item = lib.record("Item")("x", 3, None)
    return lib, lib.owner("box").owner, lib.record("Box")(item, (item,))


@pytest.mark.parametrize("fault", ["none", "mismatch", "missing", "stop", "unsealed"])
def test_fused_contract_matches_original_reads_and_failure_boundary(monkeypatch, fault):
    carrier = seal_nominal_record(
        make_nominal_record("Probe", [("number", int)], namespace={"first": object()})
    )
    attributes = (
        ("first", carrier.first),
        ("number", object() if fault == "mismatch" else carrier.number),
        ("absent" if fault == "missing" else "__init__", carrier.__init__),
    )
    dependency = operations._RecordDependency(carrier, attributes)
    contract = operations._ValidationContract(
        (dependency,), ((K0OccurrenceRef, K0OccurrenceRef.__post_init__),)
    )
    reads = []

    def observed_getattr(target, name):
        reads.append((target, name))
        if fault == "stop" and name == "number":
            raise StopIteration("current getter failed")
        return builtins.getattr(target, name)

    monkeypatch.setattr(operations, "getattr", observed_getattr, raising=False)
    if fault == "unsealed":
        monkeypatch.setattr(operations, "is_sealed_nominal_record", lambda value: False)

    def original():
        return all(item.current() for item in contract.dependencies) and all(
            target.__post_init__ is callback for target, callback in contract.references
        )

    def outcome(callback):
        reads.clear()
        try:
            result = callback()
        except (AttributeError, RuntimeError, StopIteration) as error:
            result = (type(error), str(error), type(error.__cause__))
        return result, tuple(reads)

    assert outcome(contract.current) == outcome(original)


def test_fused_contract_does_not_forward_exact_dependency(monkeypatch):
    carrier = seal_nominal_record(make_nominal_record("Probe", [], namespace={}))
    dependency = operations._RecordDependency(carrier, (("__init__", carrier.__init__),))

    def forbidden(value):
        pytest.fail("exact dependency still used the forwarding call")

    monkeypatch.setattr(operations._RecordDependency, "current", forbidden)
    assert operations._ValidationContract((dependency,), ()).current() is True


def test_nonexact_dependency_keeps_its_current_callback():
    calls = []

    class Dependency(operations._RecordDependency):
        def current(self):
            calls.append(self)
            return False

    dependency = Dependency(object, ())
    assert operations._ValidationContract((dependency,), ()).current() is False
    assert calls == [dependency]


@pytest.mark.parametrize("fault", ["scalar", "invariant", "nominal"])
def test_next_operation_rechecks_actual_values_and_disables_on_failure(graph, fault):
    lib, owner, state = graph
    with owner.validation_operation():
        owner.validate_state(state)
        owner.validate_state(state)
    if fault == "scalar":
        object.__setattr__(state.item, "amount", True)
        invalid = state
    elif fault == "invariant":
        object.__setattr__(state.item, "amount", 5)
        invalid = state
    else:
        invalid = replace(state, item=lib.record("Other")("x", 3, None))
    with owner.validation_operation():
        operation = operations._active.get()
        with pytest.raises(K0ProfileError):
            owner.validate_state(invalid)
        assert operation.enabled is False and operation.successes == {}
    assert operations._active.get() is None


@pytest.mark.parametrize("fault", ["validator", "slot", "seal", "reference"])
def test_every_entry_rechecks_current_metadata(graph, monkeypatch, fault):
    _, owner, state = graph
    carrier = type(state.item)
    with owner.validation_operation():
        assert operations._active.get() is not None
        owner.validate_state(state)
    if fault == "reference":
        monkeypatch.setattr(K0OccurrenceRef, "__post_init__", lambda value: None)
        with owner.validation_operation():
            assert operations._active.get() is None
        return
    name, changed = {
        "validator": ("validate_for_k0", lambda value: None),
        "slot": ("amount", property(lambda value: 3)),
        "seal": ("_c0_sealed", False),
    }[fault]
    original = getattr(carrier, name)
    type.__setattr__(carrier, name, changed)
    try:
        with owner.validation_operation():
            assert operations._active.get() is None
    finally:
        type.__setattr__(carrier, name, original)


def test_foreign_current_callback_keeps_second_call_failure(graph):
    _, owner, state = graph
    carrier = type(state.item)
    original = carrier.validate_for_k0
    calls = []

    def current(value):
        calls.append(value)
        original(value)
        if len(calls) == 2:
            raise K0ProfileError("second foreign callback")

    type.__setattr__(carrier, "validate_for_k0", current)
    try:
        with owner.validation_operation():
            assert operations._active.get() is None
            with pytest.raises(K0ProfileError, match="second foreign callback"):
                owner.validate_state(state)
    finally:
        type.__setattr__(carrier, "validate_for_k0", original)
    assert len(calls) == 2 and operations._active.get() is None


@pytest.mark.parametrize("boundary", ["owner", "reentry"])
def test_owner_and_reentry_clear_existing_receipts(graph, boundary):
    _, owner, state = graph
    with owner.validation_operation():
        operation = operations._active.get()
        owner.validate_state(state)
        assert operation.successes
        if boundary == "owner":
            replace(owner).validate_state(state)
        else:
            with owner.validation_operation():
                assert operations._active.get() is not operation
                owner.validate_state(state)
            assert operations._active.get() is operation
        assert operation.enabled is False and operation.successes == {}
        owner.validate_state(state)
        assert operation.successes == {}
    assert operations._active.get() is None
