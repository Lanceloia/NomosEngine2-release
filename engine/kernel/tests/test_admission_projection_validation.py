from __future__ import annotations

from dataclasses import dataclass

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._admission_abi import (
    _K0AdmissionProjection,
    _validate_admission_projection,
)
from nomos_kernel._owner_abi import (
    _K0ClosedParticipants,
    _K0SealedBinding,
    _K0SealedEvidence,
)


@dataclass(frozen=True)
class Evidence:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class Binding:
    key: str

    def validate_for_k0(self) -> None:
        return None


def _projection() -> _K0AdmissionProjection:
    return _K0AdmissionProjection(Evidence(), Participants(), (Binding("subject"),))


def _validate(projection: object = None) -> None:
    _validate_admission_projection(
        _projection() if projection is None else projection,  # type: ignore[arg-type]
        Evidence,
        Participants,
        ("subject",),
        (Binding,),
    )


def test_projection_validation_is_owned_by_the_extracted_kernel() -> None:
    assert isinstance(_projection().evidence, _K0SealedEvidence)
    assert isinstance(_projection().participants, _K0ClosedParticipants)
    assert isinstance(_projection().bindings[0], _K0SealedBinding)
    _validate()


@pytest.mark.parametrize(
    "projection",
    (
        object(),
        _K0AdmissionProjection(Participants(), Participants(), (Binding("subject"),)),
        _K0AdmissionProjection(Evidence(), Evidence(), (Binding("subject"),)),
        _K0AdmissionProjection(Evidence(), Participants(), (Binding("other"),)),
        _K0AdmissionProjection(Evidence(), Participants(), []),
        _K0AdmissionProjection(Evidence(), Participants(), (object(),)),
    ),
)
def test_projection_validation_rejects_malformed_runtime_values(projection: object) -> None:
    with pytest.raises(K0ProfileError):
        _validate(projection)


def test_projection_validation_rejects_malformed_declared_schema() -> None:
    with pytest.raises(K0ProfileError, match="schema"):
        _validate_admission_projection(
            _projection(), Evidence, Participants, ("subject",), (True,)  # type: ignore[arg-type]
        )


def test_projection_validation_rejects_declared_binding_without_key() -> None:
    projection = _K0AdmissionProjection(Evidence(), Participants(), (object(),))
    with pytest.raises(K0ProfileError, match="admission binding is malformed"):
        _validate_admission_projection(
            projection, Evidence, Participants, ("subject",), (object,)
        )


def test_projection_validation_rejects_hollow_exact_carrier_finitely() -> None:
    hollow = object.__new__(_K0AdmissionProjection)
    with pytest.raises(K0ProfileError, match="malformed projection"):
        _validate(hollow)


def test_projection_validation_rejects_post_mutated_extra_field() -> None:
    projection = _projection()
    object.__setattr__(projection, "extra", "not declared")
    with pytest.raises(K0ProfileError, match="malformed projection"):
        _validate(projection)
