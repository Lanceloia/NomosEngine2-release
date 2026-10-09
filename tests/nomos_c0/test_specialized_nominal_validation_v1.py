"""Specialized field validators retain bounds, order and current nested callbacks."""

from dataclasses import make_dataclass, replace

import pytest
from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef
from test_declarative_nominal_v0 import _source
from test_variant_types_v1 import declaration

from nomos_c0 import declarative_nominal_v0 as nominal


@pytest.mark.parametrize(
    "spec,values",
    [
        (nominal._TypeSpec("str", str, minimum=1, maximum=3), ("a", "abc", "", "abcd", 1)),
        (nominal._TypeSpec("int", int, minimum=0, maximum=3), (0, 3, -1, 4, True, 1.0)),
        (nominal._TypeSpec("enum", str, choices=("a", "b")), ("a", "b", "c", [], None)),
        (nominal._TypeSpec("bool", bool), (True, False, 0, 1, None)),
        (nominal._TypeSpec("ref", K0OccurrenceRef), (K0OccurrenceRef(1), 1, None)),
        (
            nominal._TypeSpec("individual_ref", _K0IndividualRef),
            (_K0IndividualRef("s", 1, "f"), _K0ActorRef("s", 1, "f"), None),
        ),
        (
            nominal._TypeSpec("actor_ref", _K0ActorRef),
            (_K0ActorRef("s", 1, "f"), _K0IndividualRef("s", 1, "f"), None),
        ),
        (
            nominal._TypeSpec(
                "optional", int | None, nominal._TypeSpec("int", int, minimum=0, maximum=2)
            ),
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
def test_specialized_field_validation_matches_interpreted_contract(spec, values):
    validate = nominal._compile_value_validator(spec)
    for value in values:
        outcomes = []
        for callback in (lambda actual: nominal._value(spec, actual), validate):
            try:
                callback(value)
            except Exception as error:
                outcomes.append((type(error), str(error)))
            else:
                outcomes.append(None)
        assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize(
    "carrier,kind",
    [(K0OccurrenceRef, "ref"), (_K0ActorRef, "actor_ref"), (_K0IndividualRef, "individual_ref")],
)
def test_reference_constructor_check_runs_on_every_call(carrier, kind):
    value = carrier(1) if kind == "ref" else carrier("s", 1, "f")
    validate = nominal._compile_value_validator(nominal._TypeSpec(kind, carrier))
    validate(value)
    object.__setattr__(value, "value" if kind == "ref" else "ordinal", 0)
    with pytest.raises(K0ProfileError):
        validate(value)
    with pytest.raises(K0ProfileError):
        nominal._value(nominal._TypeSpec(kind, carrier), value)


def test_generated_nested_record_is_sealed_and_keeps_exact_nominal_type():
    lib = nominal.check_nominal_lib(_source())
    route = lib.record("Route")
    validate = nominal._compile_value_validator(nominal._TypeSpec("record", route))
    value = route("dock", 2)
    validate(value)
    foreign = make_dataclass("Route", [("destination", str), ("travel", int)], frozen=True)
    with pytest.raises(K0ProfileError, match="nominal value"):
        validate(foreign("dock", 2))
    with pytest.raises(TypeError, match="read-only"):
        route.validate_for_k0 = lambda actual: None
    with pytest.raises(K0ProfileError, match="nominal value"):
        validate(replace(value, travel=0))
    validate(value)


def test_generated_record_uses_specialized_fields_and_rechecks_invariant(monkeypatch):
    lib = nominal.check_nominal_lib(_source())
    parcel = lib.record("Parcel")
    valid = parcel("P", "dock", "home", None, None)

    def interpreted(*args):
        pytest.fail("bound record fell back to runtime kind dispatch")

    monkeypatch.setattr(nominal, "_value", interpreted)
    valid.validate_for_k0()
    with pytest.raises(K0ProfileError, match="invariant"):
        replace(valid, status="transit").validate_for_k0()
    valid.validate_for_k0()


def test_field_and_collection_order_and_first_failure_are_preserved():
    lib = nominal.check_nominal_lib(_source())
    route, parcel, scene = (lib.record(name) for name in ("Route", "Parcel", "Scene"))
    calls = []
    original_route = route.validate_for_k0
    original_parcel = parcel.validate_for_k0

    def check_parcel(actual):
        calls.append(actual.id)
        original_parcel(actual)

    def check_route(actual):
        calls.append(actual.destination)
        original_route(actual)

    # Private read-only spies observe call order, not a supported author rebind.
    type.__setattr__(parcel, "validate_for_k0", check_parcel)
    type.__setattr__(route, "validate_for_k0", check_route)
    try:
        state = scene(
            parcel("P", "dock", "home", None, None), (route("a", 2), route("b", 3)), "none"
        )
        for _ in range(2):
            state.validate_for_k0()
        assert calls == ["P", "a", "b"] * 2
        calls.clear()
        invalid = replace(state, routes=(route("a", 0), route("b", 0)), signal="invalid")
        with pytest.raises(K0ProfileError, match="nominal value"):
            invalid.validate_for_k0()
        assert calls == ["P", "a"]
    finally:
        type.__setattr__(parcel, "validate_for_k0", original_parcel)
        type.__setattr__(route, "validate_for_k0", original_route)


def test_native_nested_validator_remains_a_current_callback(monkeypatch):
    carrier = make_dataclass(
        "Native", [("amount", int)], frozen=True, namespace={"validate_for_k0": lambda value: None}
    )
    validate = nominal._compile_value_validator(nominal._TypeSpec("record", carrier))
    value = carrier(1)
    validate(value)

    def denied(actual):
        raise K0ProfileError("current native validator")

    monkeypatch.setattr(carrier, "validate_for_k0", denied)
    with pytest.raises(K0ProfileError, match="current native validator"):
        validate(value)


def test_variant_discriminator_payload_and_nested_bounds_remain_checked():
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
