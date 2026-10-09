"""Focused tests for owner-state isolation and structural profile views."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from nomos_kernel import K0OwnerKey
from nomos_kernel._owner_state_runtime import (
    _build_owner_views,
    _clone_owner_state,
)
from nomos_kernel._state_image_abi import _K0OwnerState


@dataclass(frozen=True)
class _State:
    value: int


@dataclass(frozen=True)
class _View:
    value: int

    def validate_for_k0(self) -> None:
        return None


class _Owner:
    key = K0OwnerKey("owner")
    state_type = _State
    view_type = _View

    def validate_state(self, state: object) -> None:
        if type(state) is not _State:
            raise TypeError("wrong state")

    def encode_state(self, state: object) -> tuple[int]:
        self.validate_state(state)
        assert isinstance(state, _State)
        return (state.value,)

    def decode_state(self, wire: object) -> _State:
        assert type(wire) is tuple and len(wire) == 1
        return _State(wire[0])

    def read_view(self, state: object) -> _View:
        self.validate_state(state)
        assert isinstance(state, _State)
        return _View(state.value)


@dataclass(frozen=True)
class _Profile:
    owners: tuple[_Owner, ...]
    cross_owner_invariants: tuple[object, ...] = ()
    _occurrence_cursor_validator: object | None = None


def test_owner_state_clone_and_view_use_fresh_canonical_state() -> None:
    owner = _Owner()
    state = _State(7)
    cloned = _clone_owner_state(owner, state)
    assert cloned == state
    assert cloned is not state
    rows = _build_owner_views(
        _Profile((owner,)),
        (_K0OwnerState(owner.key, state),),
        (owner.key,),
    )
    assert rows[0].owner == owner.key
    assert rows[0].view == _View(7)


def test_owner_state_runtime_import_does_not_load_dawn() -> None:
    script = (
        "import sys; import nomos_kernel._owner_state_runtime; "
        "print(any(name.startswith('nomos_dawn') for name in sys.modules))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    output = subprocess.check_output(
        [sys.executable, "-c", script], env=env, text=True
    ).strip()
    assert output == "False"
