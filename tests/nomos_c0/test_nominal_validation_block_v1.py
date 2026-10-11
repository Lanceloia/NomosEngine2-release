"""Nominal blocks retain ordered checks, current callbacks and receipt scope."""

from dataclasses import make_dataclass, replace
from dis import get_instructions

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from test_nominal_owner_layout_v1 import _lib
from test_operation_local_validation_v1 import body_calls
from test_variant_types_v1 import declaration, sample

from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0 import nominal_validation_execution_v1 as execution
from nomos_c0 import validation_operation_v1 as operations
from nomos_c0.composable_value_v1 import C0ValueStateError
from nomos_c0.variant_types_v1 import validate_variant


def _compile(fields, *, cases=(), invariant=None, namespace=None, fallback=None):
    carrier = make_dataclass(
        "Probe",
        [(field.name, field.value.annotation) for field in fields],
        frozen=True,
        namespace=namespace or {},
    )
    carrier.__nomos_cases__ = cases
    block, install = execution.compile_nominal_validation_block(
        carrier, fields, fallback or nominal._compile_value_validator
    )
    install(invariant)
    field_check = execution.compile_nominal_field_validation(
        fields, nominal._compile_value_validator
    )

    def previous(value):
        if type(value) is not carrier:
            raise K0ProfileError("generated record has a foreign nominal type")
        field_check(value)
        validate_variant(value)
        if invariant is not None:
            try:
                if not invariant({"state": value}):
                    raise K0ProfileError("declared state invariant is false")
            except C0ValueStateError as error:
                raise K0ProfileError("declared state invariant met malformed state") from error

    return carrier, block, previous


def _outcome(callback, value):
    try:
        callback(value)
    except Exception as error:
        return type(error), str(error), type(error.__cause__)
    return None


@pytest.mark.parametrize(
    "spec,values",
    [
        (nominal._TypeSpec("int", int, maximum=2), (0, 2, -1, 3, True, None)),
        (nominal._TypeSpec("str", str, minimum=1, maximum=2), ("a", "ab", "", "abc", 1)),
        (nominal._TypeSpec("bool", bool), (True, False, 0, None)),
        (nominal._TypeSpec("enum", str, choices=("a", "b")), ("a", "b", "c", [], None)),
        (
            nominal._TypeSpec("optional", int | None, nominal._TypeSpec("int", int, maximum=2)),
            (None, 0, 2, 3, False),
        ),
        (
            nominal._TypeSpec(
                "tuple", tuple[int, ...], nominal._TypeSpec("int", int, maximum=2), maximum=2
            ),
            ((), (0,), (1, 2), (1, 2, 0), (True,), [1]),
        ),
    ],
)
def test_block_preserves_field_validation_outcomes(spec, values):
    carrier, block, previous = _compile((nominal._FieldSpec("field", spec),))
    for value in values:
        state = carrier(value)
        assert _outcome(block, state) == _outcome(previous, state)


@pytest.mark.parametrize("kind", ["record", "variant", "unknown"])
def test_native_callback_is_current_in_both_inline_and_fallback_paths(kind, monkeypatch):
    native = make_dataclass(
        "Native", [("number", int)], namespace={"validate_for_k0": lambda value: None}
    )
    carrier, block, previous = _compile(
        (nominal._FieldSpec("field", nominal._TypeSpec(kind, native)),)
    )
    state = carrier(native(1))
    block(state)

    def denied(value):
        raise K0ProfileError("current native callback")

    monkeypatch.setattr(native, "validate_for_k0", denied)
    assert _outcome(block, state) == _outcome(previous, state)
    with pytest.raises(K0ProfileError, match="current native callback"):
        block(state)
    foreign = make_dataclass("Native", [("number", int)])
    assert _outcome(block, carrier(foreign(1))) == _outcome(previous, carrier(foreign(1)))


@pytest.mark.parametrize(
    "kind,reference_type",
    [("ref", K0OccurrenceRef), ("actor_ref", _K0ActorRef), ("individual_ref", _K0IndividualRef)],
)
def test_native_reference_constructor_remains_current(kind, reference_type, monkeypatch):
    carrier, block, previous = _compile(
        (nominal._FieldSpec("field", nominal._TypeSpec(kind, reference_type)),)
    )
    reference = reference_type(1) if kind == "ref" else reference_type("s", 1, "f")
    state = carrier(reference)
    block(state)
    object.__setattr__(reference, "value" if kind == "ref" else "ordinal", 0)
    assert _outcome(block, state) == _outcome(previous, state)
    with pytest.raises(K0ProfileError):
        block(state)

    def denied(value):
        raise K0ProfileError("current native reference callback")

    monkeypatch.setattr(reference_type, "__post_init__", denied)
    with pytest.raises(K0ProfileError, match="current native reference callback"):
        block(state)


def test_deep_tuple_nullable_fallback_rechecks_current_values():
    spec = nominal._TypeSpec("int", int, maximum=2)
    valid, invalid = 2, True
    for _ in range(5):
        spec = nominal._TypeSpec("optional", spec.annotation | None, spec)
        spec = nominal._TypeSpec("tuple", tuple[spec.annotation, ...], spec, maximum=2)
        valid, invalid = (None, valid), (None, invalid)
    fallbacks = []

    def fallback(value):
        fallbacks.append(value)
        return nominal._compile_value_validator(value)

    carrier, block, previous = _compile((nominal._FieldSpec("field", spec),), fallback=fallback)
    assert len(fallbacks) == 1
    for value in (valid, invalid, (), [], (valid, valid, valid)):
        state = carrier(value)
        assert _outcome(block, state) == _outcome(previous, state)
    block(carrier(valid))
    with pytest.raises(K0ProfileError):
        block(carrier(invalid))


def test_block_eliminates_field_forwarding_and_unchanged_empty_variant_preparation(monkeypatch):
    calls = []

    def observed(value):
        calls.append(value)
        validate_variant(value)

    monkeypatch.setattr(execution, "validate_variant", observed)
    carrier, block, _ = _compile(
        (nominal._FieldSpec("field", nominal._TypeSpec("int", int, maximum=2)),)
    )
    assert block.__code__.co_filename == "<c0-nominal-validation-block>"
    assert "validate_fields" not in block.__code__.co_names
    block(carrier(1))
    assert calls == []
    carrier.__nomos_cases__ = {"unit": type(None)}
    with pytest.raises(AttributeError):
        block(carrier(1))
    assert len(calls) == 1


@pytest.mark.parametrize("metadata", [None, False, 1, {"unit": type(None)}, []])
def test_empty_variant_optimization_preserves_changed_native_metadata_errors(metadata):
    carrier, block, previous = _compile(())
    carrier.__nomos_cases__ = metadata
    state = carrier()
    assert _outcome(block, state) == _outcome(previous, state)


@pytest.mark.parametrize("case", ["success", "failure", "waiting"])
def test_real_variants_keep_current_discriminator_payload_and_shape_checks(case):
    lib = nominal.check_nominal_lib(declaration())
    valid = sample(lib, case)
    valid.validate_for_k0()
    for invalid in (
        replace(valid, case="unknown"),
        replace(valid, success=lib.record("Ticket")(99, "s", None)),
        replace(valid, failure="invalid"),
    ):
        with pytest.raises(K0ProfileError):
            invalid.validate_for_k0()
    carrier = type(valid)
    original = carrier.__nomos_cases__
    type.__setattr__(carrier, "__nomos_cases__", (("other", type(None)),))
    try:
        with pytest.raises(K0ProfileError, match="undeclared case"):
            valid.validate_for_k0()
    finally:
        type.__setattr__(carrier, "__nomos_cases__", original)


@pytest.mark.parametrize("failure", ["field", "variant", "invariant", "getter"])
def test_first_failure_and_observed_field_variant_invariant_order_match_previous(failure):
    events = []

    def getter(value, name):
        events.append(name)
        if failure == "getter" and name == "payload":
            raise LookupError("current getter")
        return object.__getattribute__(value, name)

    def invariant(roots):
        events.append("invariant")
        return failure != "invariant"

    fields = (
        nominal._FieldSpec("first", nominal._TypeSpec("int", int, maximum=2)),
        nominal._FieldSpec("case", nominal._TypeSpec("str", str, maximum=16)),
        nominal._FieldSpec(
            "payload", nominal._TypeSpec("optional", int | None, nominal._TypeSpec("int", int))
        ),
    )
    carrier, block, previous = _compile(
        fields,
        cases=(("payload", int),),
        invariant=invariant,
        namespace={"__getattribute__": getter},
    )
    state = carrier(
        True if failure == "field" else 1, "other" if failure == "variant" else "payload", 0
    )
    results = []
    for callback in (previous, block):
        events.clear()
        results.append((_outcome(callback, state), tuple(events)))
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "error_type", [C0ValueStateError, LookupError, StopIteration, K0ProfileError]
)
def test_invariant_failure_and_cause_boundaries_are_unchanged(error_type):
    def invariant(roots):
        raise error_type("invariant failure")

    carrier, block, previous = _compile((), invariant=invariant)
    assert _outcome(block, carrier()) == _outcome(previous, carrier())
    if error_type is C0ValueStateError:
        with pytest.raises(K0ProfileError, match="met malformed state") as caught:
            block(carrier())
        assert type(caught.value.__cause__) is C0ValueStateError


def test_foreign_root_rejection_precedes_any_field_or_invariant_read():
    def forbidden(value):
        pytest.fail("foreign root crossed the nominal boundary")

    _, block, previous = _compile(
        (nominal._FieldSpec("field", nominal._TypeSpec("int", int)),), invariant=forbidden
    )
    foreign = make_dataclass("Probe", [("field", int)])(0)
    assert _outcome(block, foreign) == _outcome(previous, foreign)
    with pytest.raises(K0ProfileError, match="foreign nominal type"):
        block(foreign)


def test_real_blocks_keep_nested_receipts_and_recheck_invariant_in_new_operation():
    lib = nominal.check_nominal_lib(_lib())
    owner = lib.owner("box").owner
    item = lib.record("Item")("x", 3, None)
    state = lib.record("Box")(item, (item,))
    with body_calls(type(item)) as calls:
        with owner.validation_operation():
            owner.validate_state(state)
            owner.validate_state(state)
            owner.validate_state(replace(state))
        assert len(calls) == 1
        with owner.validation_operation():
            owner.validate_state(state)
        assert len(calls) == 2
    object.__setattr__(item, "amount", 5)
    with owner.validation_operation():
        with pytest.raises(K0ProfileError, match="invariant"):
            owner.validate_state(state)
        assert operations._active.get().enabled is False
    assert operations._active.get() is None


def test_changed_generated_callback_cancels_receipts_and_keeps_second_failure():
    lib = nominal.check_nominal_lib(_lib())
    owner = lib.owner("box").owner
    item = lib.record("Item")("x", 3, None)
    state = lib.record("Box")(item, (item,))
    original = type(item).validate_for_k0
    calls = []

    def current(value):
        calls.append(value)
        original(value)
        if len(calls) == 2:
            raise K0ProfileError("second foreign callback")

    type.__setattr__(type(item), "validate_for_k0", current)
    try:
        with owner.validation_operation():
            assert operations._active.get() is None
            with pytest.raises(K0ProfileError, match="second foreign callback"):
                owner.validate_state(state)
    finally:
        type.__setattr__(type(item), "validate_for_k0", original)
    assert len(calls) == 2 and operations._active.get() is None


@pytest.mark.parametrize("name", ["number", "\u212a", "class", "not-an-identifier"])
def test_field_load_keeps_exact_attribute_name_without_getattr_dispatch(name):
    spec = nominal._FieldSpec(name, nominal._TypeSpec("int", int, maximum=2))
    check = execution.compile_nominal_field_validation((spec,), nominal._compile_value_validator)
    calls = []

    class Native:
        def __getattribute__(self, actual):
            calls.append(actual)
            return object.__getattribute__(self, actual)

    value = Native()
    object.__setattr__(value, name, 1)
    check(value)
    assert calls == [name]
    assert "getattr" not in check.__code__.co_names
    assert any(item.opname == "LOAD_ATTR" and item.argval == name
               for item in get_instructions(check))
    object.__setattr__(value, name, True)
    with pytest.raises(K0ProfileError, match="malformed"):
        check(value)


def test_earlier_getter_changes_later_descriptor_before_its_current_read():
    spec = nominal._TypeSpec("int", int, maximum=2)
    fields = (nominal._FieldSpec("first", spec), nominal._FieldSpec("later", spec))
    calls = []

    class Native:
        @property
        def first(self):
            calls.append("first")
            Native.later = property(lambda self: calls.append("later") or True)
            return 1

        later = 1

    check = execution.compile_nominal_field_validation(fields, nominal._compile_value_validator)
    with pytest.raises(K0ProfileError, match="malformed"):
        check(Native())
    assert calls == ["first", "later"]
