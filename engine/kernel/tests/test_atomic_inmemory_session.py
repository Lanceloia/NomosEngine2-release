"""Focused tests for the private atomic in-memory K0 session carriers."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryProfile,
    _K0InMemorySourceSpec,
    _K0OwnerStateCandidate,
)
from nomos_kernel._owner_abi import _K0CapabilityRef

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "src"


@dataclass(frozen=True)
class _Rule:
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: object) -> object:
        raise AssertionError("rule must not be invoked in this focused test")


@dataclass(frozen=True)
class _Owner:
    key: K0OwnerKey


@dataclass(frozen=True)
class _Law:
    key: object
    triggering_event_type: K0EventTypeKey
    resulting_source: K0SourceSpecKey
    read_owners: tuple[K0OwnerKey, ...]


def _spec(
    key: str,
    *,
    family: K0OccurrenceFamily = K0OccurrenceFamily.EVENT,
    event_type: str = "event-a",
    read_owners: tuple[K0OwnerKey, ...],
    contribution_owners: tuple[K0OwnerKey, ...] = (),
    admission: object | None = None,
) -> _K0InMemorySourceSpec:
    return _K0InMemorySourceSpec(
        K0SourceSpecKey(key),
        family,
        K0EventTypeKey(event_type),
        object,
        object,
        object,
        read_owners,
        contribution_owners,
        (),
        (),
        admission,
        _Rule(_K0CapabilityRef("rule")),
        object,
    )


def _profile(
    specs: tuple[_K0InMemorySourceSpec, ...],
    laws: tuple[object, ...],
    owners: tuple[_Owner, ...],
) -> _K0InMemoryProfile:
    return _K0InMemoryProfile(owners, specs, laws, 8, 3)


def test_inmemory_session_import_does_not_load_mind_or_dawn() -> None:
    script = (
        "import sys,nomos_kernel._atomic_inmemory_session;"
        "print(any(n.startswith(('nomos_mind','nomos_dawn')) for n in sys.modules))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(KERNEL_ROOT)},
        text=True,
    ).strip()
    assert output == "False"


def test_action_spec_requires_admission_and_event_specs_forbid_it() -> None:
    owners = (_Owner(K0OwnerKey("a")),)
    with pytest.raises(K0ProfileError, match="admission capability"):
        _spec("action", family=K0OccurrenceFamily.ACTION, read_owners=(owners[0].key,))
    with pytest.raises(K0ProfileError, match="must not declare admission"):
        _spec(
            "event",
            read_owners=(owners[0].key,),
            admission=object(),
        )


def test_attempt_carrier_requires_exact_source() -> None:
    with pytest.raises(K0ProfileError, match="exact source"):
        _K0InMemoryActionAttempt(object(), object())
    assert type(_K0OwnerStateCandidate) is type


def test_profile_rejects_foreign_carriers_and_non_event_law_target() -> None:
    owners = (_Owner(K0OwnerKey("a")),)
    event = _spec("event-a", read_owners=(owners[0].key,))
    with pytest.raises(K0ProfileError, match="profile is not closed"):
        _K0InMemoryProfile((object(),), (event,), (), 8, 3)
    with pytest.raises(K0ProfileError, match="profile is not closed"):
        _K0InMemoryProfile(owners, (object(),), (), 8, 3)
    with pytest.raises(K0ProfileError, match="profile is not closed"):
        _K0InMemoryProfile(owners, (event,), (object(),), 8, 3)
