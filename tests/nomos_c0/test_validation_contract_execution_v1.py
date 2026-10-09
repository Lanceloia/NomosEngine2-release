"""Issued qualification code preserves live reads and operation-local receipts."""

import builtins
from dataclasses import replace

import pytest
from nomos_kernel import K0OccurrenceRef
from test_nominal_owner_layout_v1 import _lib

from nomos_c0 import validation_operation_v1 as operations
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.generated_record_v1 import make_nominal_record, seal_nominal_record
from nomos_c0.validation_contract_execution_v1 import compile_contract_execution


def issued(dependencies, references=()):
    contract = operations._ValidationContract(dependencies, references)
    object.__setattr__(contract, "_execution", compile_contract_execution(dependencies, references))
    return contract


@pytest.mark.parametrize("fault", ["none", "mismatch", "missing", "stop", "unsealed"])
def test_issued_checks_match_generic_reads_short_circuit_and_exception(monkeypatch, fault):
    carrier = seal_nominal_record(make_nominal_record("Probe", [("number", int)], namespace={}))
    dependency = operations._RecordDependency(
        carrier,
        (
            ("__init__", carrier.__init__),
            ("number", object() if fault == "mismatch" else carrier.number),
            ("absent" if fault == "missing" else "__eq__", carrier.__eq__),
        ),
    )
    contract = issued((dependency,), ((K0OccurrenceRef, K0OccurrenceRef.__post_init__),))
    generic = replace(contract)
    assert generic._execution is None
    reads = []

    def observed(target, name):
        reads.append((target, name))
        if fault == "stop" and name == "number":
            raise StopIteration("live metadata getter failed")
        return builtins.getattr(target, name)

    monkeypatch.setattr(operations, "getattr", observed, raising=False)
    if fault == "unsealed":
        monkeypatch.setattr(operations, "is_sealed_nominal_record", lambda target: False)

    def outcome(callback):
        reads.clear()
        try:
            result = callback()
        except (AttributeError, StopIteration, RuntimeError) as error:
            result = (type(error), str(error), type(error.__cause__))
        return result, tuple(reads)

    assert outcome(contract.current) == outcome(generic.current)


@pytest.mark.parametrize("fault", ["validator", "slot", "seal", "reference"])
def test_compiler_issued_contract_rechecks_current_metadata(fault, monkeypatch):
    lib = check_nominal_lib(_lib())
    carrier = lib.record("Item")
    contract = lib.record("Box").__nomos_validation_contract__
    assert contract._execution is not None and contract.current() is True
    if fault == "reference":
        monkeypatch.setattr(K0OccurrenceRef, "__post_init__", lambda value: None)
        assert contract.current() is False
        return
    name, changed = {
        "validator": ("validate_for_k0", lambda value: None),
        "slot": ("amount", property(lambda value: 3)),
        "seal": ("_c0_sealed", False),
    }[fault]
    original = getattr(carrier, name)
    type.__setattr__(carrier, name, changed)
    try:
        assert contract.current() is False
    finally:
        type.__setattr__(carrier, name, original)
    assert contract.current() is True


@pytest.mark.parametrize("fault", ["none", "mismatch", "missing", "stop"])
def test_reference_reads_preserve_order_and_error_boundary(fault):
    reads = []
    original = object()

    class ReferenceType(type):
        def __getattribute__(cls, name):
            if name == "__post_init__":
                reads.append(type.__getattribute__(cls, "__name__"))
                if fault == "stop":
                    raise StopIteration("reference getter failed")
                if fault == "missing":
                    raise AttributeError("reference getter missing")
            return super().__getattribute__(name)

    class First(metaclass=ReferenceType):
        __post_init__ = original

    class Second(metaclass=ReferenceType):
        __post_init__ = original

    contract = issued(
        (), ((First, object() if fault == "mismatch" else original), (Second, original))
    )
    generic = replace(contract)

    def outcome(callback):
        reads.clear()
        try:
            result = callback()
        except (AttributeError, StopIteration, RuntimeError) as error:
            result = (type(error), str(error), type(error.__cause__))
        return result, tuple(reads)

    assert outcome(contract.current) == outcome(generic.current)


def test_empty_issued_contract_and_nonidentifier_names():
    assert issued(()).current() is True
    name = "not an identifier; raise RuntimeError('injected')"
    carrier = make_nominal_record("Probe", [], namespace={name: object()})
    expected = getattr(carrier, name)
    seal_nominal_record(carrier)
    assert issued((operations._RecordDependency(carrier, ((name, expected),)),)).current() is True


def test_execution_type_cannot_be_reconfigured():
    execution = issued(())._execution
    with pytest.raises(TypeError, match="read-only"):
        execution.execute = lambda *args: True
    with pytest.raises(TypeError, match="read-only"):
        del execution.execute
