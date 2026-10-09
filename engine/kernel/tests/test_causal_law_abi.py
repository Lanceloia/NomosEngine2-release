"""Focused tests for the closed causal-law profile declaration."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition, _K0PlannedActivation
from nomos_kernel._coordinates import _K0OccurrenceCoordinate
from nomos_kernel._owner_abi import _K0CapabilityRef


@dataclass(frozen=True)
class _Projector:
    capability_ref: _K0CapabilityRef

    def project(self, trigger: object, owner_views: tuple[object, ...]) -> tuple[object, ...]:
        return ()


@dataclass(frozen=True)
class _Participants:
    def validate_for_k0(self) -> None:
        return None


@dataclass(frozen=True)
class _Trigger:
    occurrence: K0OccurrenceRef
    family: K0OccurrenceFamily
    source: K0SourceSpecKey
    classification: K0EventTypeKey
    formation_basis: object
    participants: _Participants
    coordinate: _K0OccurrenceCoordinate
    semantic_envelope: object


def _definition(**changes: object) -> K0CausalLawDefinition:
    fields: dict[str, object] = {
        "key": K0CausalLawKey("test-law"),
        "triggering_event_type": K0EventTypeKey("test-trigger"),
        "resulting_source": K0SourceSpecKey("test-result"),
        "max_activations": 1,
        "read_owners": (K0OwnerKey("owner-b"), K0OwnerKey("owner-a")),
        "activation_projector": _Projector(_K0CapabilityRef("test-projector")),
        "receipt_local": False,
    }
    fields.update(changes)
    return K0CausalLawDefinition(**fields)  # type: ignore[arg-type]


def test_causal_law_canonicalizes_read_owners() -> None:
    definition = _definition()
    assert definition.read_owners == (
        K0OwnerKey("owner-a"),
        K0OwnerKey("owner-b"),
    )


def test_causal_law_reentry_rejects_hollow_or_extra_fields() -> None:
    with pytest.raises(K0ProfileError):
        K0CausalLawDefinition.__post_init__(object.__new__(K0CausalLawDefinition))
    definition = _definition()
    object.__setattr__(definition, "extra", True)
    with pytest.raises(K0ProfileError):
        K0CausalLawDefinition.__post_init__(definition)


@pytest.mark.parametrize("value", (0, -1, True))
def test_causal_law_rejects_non_positive_exact_activation_bound(value: object) -> None:
    with pytest.raises(K0ProfileError):
        _definition(max_activations=value)


def test_causal_law_rejects_duplicate_read_owner() -> None:
    owner = K0OwnerKey("owner")
    with pytest.raises(K0ProfileError):
        _definition(read_owners=(owner, owner))


def test_causal_law_rejects_malformed_projector() -> None:
    with pytest.raises(K0ProfileError):
        _definition(activation_projector=object())


@pytest.mark.parametrize(
    ("field", "key_type"),
    (
        ("key", K0CausalLawKey),
        ("triggering_event_type", K0EventTypeKey),
        ("resulting_source", K0SourceSpecKey),
    ),
)
def test_causal_law_reenters_exact_keys(field: str, key_type: type[object]) -> None:
    invalid = key_type("valid")
    object.__setattr__(invalid, "value", True)
    for value in (object(), object.__new__(key_type), invalid):
        with pytest.raises(K0ProfileError):
            _definition(**{field: value})


def test_causal_law_reenters_read_owner_keys() -> None:
    invalid = K0OwnerKey("valid")
    object.__setattr__(invalid, "value", True)
    for owners in ([K0OwnerKey("owner")], (object(),), (object.__new__(K0OwnerKey),), (invalid,)):
        with pytest.raises(K0ProfileError):
            _definition(read_owners=owners)


def test_causal_law_reenters_projector_capability_reference() -> None:
    invalid = _K0CapabilityRef("valid")
    object.__setattr__(invalid, "value", True)
    for value in (object(), object.__new__(_K0CapabilityRef), invalid):
        with pytest.raises(K0ProfileError):
            _definition(activation_projector=_Projector(value))


def test_planned_activation_is_an_engine_owned_machine_row() -> None:
    trigger = _Trigger(
        K0OccurrenceRef(1),
        K0OccurrenceFamily.EVENT,
        K0SourceSpecKey("trigger"),
        K0EventTypeKey("trigger"),
        object(),
        _Participants(),
        _K0OccurrenceCoordinate(None, 0),
        (),
    )
    activation = object()
    planned = _K0PlannedActivation(_definition(), trigger, activation)
    assert planned.trigger is trigger
    assert planned.activation is activation


def test_causal_law_abi_import_does_not_load_dawn() -> None:
    script = (
        "import sys; import nomos_kernel._causal_law_abi; "
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    output = subprocess.check_output(
        [sys.executable, "-c", script], env=env, text=True
    ).strip()
    assert output == "False"
