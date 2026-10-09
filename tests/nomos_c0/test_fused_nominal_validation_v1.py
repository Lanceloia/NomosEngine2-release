"""Fused checks preserve ordered reads, exact types and current callbacks."""

from dataclasses import make_dataclass, replace
from types import SimpleNamespace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from test_declarative_nominal_v0 import _source
from test_nominal_owner_layout_v1 import _lib
from test_operation_local_validation_v1 import body_calls
from test_variant_types_v1 import declaration

from nomos_c0 import declarative_nominal_v0 as nominal
from nomos_c0.nominal_validation_execution_v1 import compile_nominal_field_validation


def _compile(spec, name="field", fallback=None):
    return compile_nominal_field_validation(
        (nominal._FieldSpec(name, spec),), fallback or nominal._compile_value_validator
    )


@pytest.mark.parametrize(
    "spec,values",
    [
        (nominal._TypeSpec("int", int, minimum=0, maximum=2), (0, 2, -1, 3, True, 1.0)),
        (nominal._TypeSpec("str", str, minimum=1, maximum=2), ("a", "ab", "", "abc", 1)),
        (nominal._TypeSpec("bool", bool), (True, False, 0, 1, None)),
        (nominal._TypeSpec("enum", str, choices=("a", "b")), ("a", "b", "c", [], None)),
        (nominal._TypeSpec("ref", K0OccurrenceRef), (K0OccurrenceRef(1), 1, None)),
        (
            nominal._TypeSpec("actor_ref", _K0ActorRef),
            (_K0ActorRef("s", 1, "f"), _K0IndividualRef("s", 1, "f"), None),
        ),
        (
            nominal._TypeSpec("individual_ref", _K0IndividualRef),
            (_K0IndividualRef("s", 1, "f"), _K0ActorRef("s", 1, "f"), None),
        ),
        (
            nominal._TypeSpec("optional", int | None, nominal._TypeSpec("int", int, maximum=2)),
            (None, 0, 2, 3, False),
        ),
        (
            nominal._TypeSpec(
                "tuple", tuple[int, ...], nominal._TypeSpec("int", int, maximum=2), maximum=2
            ),
            ((), (0,), (1, 2), (0, 1, 2), (0, 3), [1], (True,)),
        ),
    ],
)
def test_fused_field_matches_existing_validator(spec, values):
    fused = _compile(spec)
    old = nominal._compile_value_validator(spec)
    for value in values:
        outcomes = []
        for callback in (old, lambda actual: fused(SimpleNamespace(field=actual))):
            try:
                callback(value)
            except Exception as error:
                outcomes.append((type(error), str(error)))
            else:
                outcomes.append(None)
        assert outcomes[0] == outcomes[1]


def test_nested_tuple_optional_checks_exact_types_and_bounds():
    scalar = nominal._TypeSpec("int", int, maximum=2)
    inner = nominal._TypeSpec("tuple", tuple[int, ...], scalar, maximum=2)
    optional = nominal._TypeSpec("optional", tuple[int, ...] | None, inner)
    outer = nominal._TypeSpec("tuple", tuple[tuple[int, ...] | None, ...], optional, maximum=3)
    fused = _compile(outer)
    fused(SimpleNamespace(field=(None, (), (1, 2))))

    class TupleSubclass(tuple):
        pass

    for invalid in ((None,) * 4, ((1, 2, 0),), ((True,),), (TupleSubclass((1,)),)):
        with pytest.raises(K0ProfileError):
            fused(SimpleNamespace(field=invalid))


def test_fused_reads_and_first_error_follow_field_and_element_order():
    events = []

    def validate_item(value):
        events.append(value.amount)
        if value.amount == 2:
            raise K0ProfileError("first nested refusal")

    native = make_dataclass(
        "Native",
        [("amount", int)],
        frozen=True,
        namespace={"validate_for_k0": validate_item},
    )
    fields = (
        nominal._FieldSpec("first", nominal._TypeSpec("int", int, maximum=1)),
        nominal._FieldSpec(
            "items",
            nominal._TypeSpec(
                "tuple", tuple[native, ...], nominal._TypeSpec("record", native), maximum=3
            ),
        ),
        nominal._FieldSpec("later", nominal._TypeSpec("bool", bool)),
    )
    fused = compile_nominal_field_validation(fields, nominal._compile_value_validator)

    class Observed:
        first = 1
        items = (native(1), native(2), native(3))
        later = False

        def __getattribute__(self, name):
            events.append(name)
            return object.__getattribute__(self, name)

    with pytest.raises(K0ProfileError, match="first nested refusal"):
        fused(Observed())
    assert events == ["first", "items", 1, 2]
    events.clear()
    value = Observed()
    value.first = True
    with pytest.raises(K0ProfileError, match="nominal value"):
        fused(value)
    assert events == ["first"]


@pytest.mark.parametrize("kind", ["record", "variant", "unknown"])
def test_nested_native_callback_remains_current_and_foreign_type_is_rejected(kind, monkeypatch):
    native = make_dataclass(
        "Native",
        [("amount", int)],
        frozen=True,
        namespace={"validate_for_k0": lambda value: None},
    )
    fused = _compile(nominal._TypeSpec(kind, native))
    value = SimpleNamespace(field=native(1))
    fused(value)

    def denied(actual):
        raise K0ProfileError("current native callback")

    monkeypatch.setattr(native, "validate_for_k0", denied)
    with pytest.raises(K0ProfileError, match="current native callback"):
        fused(value)
    foreign = make_dataclass("Native", [("amount", int)], frozen=True)
    with pytest.raises(K0ProfileError, match="nominal value"):
        fused(SimpleNamespace(field=foreign(1)))


@pytest.mark.parametrize(
    "kind,carrier",
    [("ref", K0OccurrenceRef), ("actor_ref", _K0ActorRef), ("individual_ref", _K0IndividualRef)],
)
def test_reference_post_init_remains_current_and_rechecks_value(kind, carrier, monkeypatch):
    fused = _compile(nominal._TypeSpec(kind, carrier))
    reference = carrier(1) if kind == "ref" else carrier("s", 1, "f")
    value = SimpleNamespace(field=reference)
    fused(value)
    object.__setattr__(reference, "value" if kind == "ref" else "ordinal", 0)
    with pytest.raises(K0ProfileError):
        fused(value)

    def denied(actual):
        raise K0ProfileError("current reference callback")

    monkeypatch.setattr(carrier, "__post_init__", denied)
    with pytest.raises(K0ProfileError, match="current reference callback"):
        fused(value)


def test_deep_shapes_fall_back_without_skipping_current_checks():
    spec = nominal._TypeSpec("int", int, maximum=2)
    for _ in range(9):
        spec = nominal._TypeSpec("optional", int | None, spec)
    seen = []

    def fallback(current):
        seen.append(current)
        return nominal._compile_value_validator(current)

    fused = _compile(spec, fallback=fallback)
    assert len(seen) == 1
    fused(SimpleNamespace(field=None))
    fused(SimpleNamespace(field=2))
    with pytest.raises(K0ProfileError):
        fused(SimpleNamespace(field=True))


def test_field_names_are_literals_and_getter_exception_is_not_swallowed():
    name = "x'); raise AssertionError('injected') #"
    fused = _compile(nominal._TypeSpec("bool", bool), name)
    value = SimpleNamespace()
    setattr(value, name, True)
    fused(value)

    class Denied:
        def __getattribute__(self, name):
            raise LookupError("current getter")

    with pytest.raises(LookupError, match="current getter"):
        fused(Denied())


def test_bound_records_do_not_build_fine_grained_field_closures(monkeypatch):
    def forbidden(spec):
        pytest.fail("supported bound field used a fine-grained validator closure")

    monkeypatch.setattr(nominal, "_compile_value_validator", forbidden)
    lib = nominal.check_nominal_lib(_source())
    parcel = lib.record("Parcel")("P", "dock", "home", None, None)
    lib.record("Scene")(parcel, (), "none").validate_for_k0()
    with pytest.raises(K0ProfileError, match="invariant"):
        replace(parcel, status="transit").validate_for_k0()


def test_bound_variant_and_invariant_paths_are_not_skipped():
    lib = nominal.check_nominal_lib(declaration())
    ticket, result = lib.record("Ticket"), lib.record("Result")
    valid = result("r", "success", ticket(2, "s", None), None)
    valid.validate_for_k0()
    for invalid in (
        replace(valid, case="failure"),
        replace(valid, success=replace(valid.success, number=9)),
        replace(valid, case="unknown"),
    ):
        with pytest.raises(K0ProfileError):
            invalid.validate_for_k0()


def test_nested_receipts_are_kept_and_do_not_cross_operations():
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
    with pytest.raises(K0ProfileError, match="invariant"):
        with owner.validation_operation():
            owner.validate_state(state)
