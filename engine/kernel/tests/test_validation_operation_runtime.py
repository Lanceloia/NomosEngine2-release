"""Optional owner validation scopes cannot replace kernel isolation checks."""

from contextlib import contextmanager

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import (
    _build_candidate_owner_views,
    _clone_owner_state,
    _isolate_candidate_owner_state,
    _K0OwnerStateDirectory,
)
from nomos_kernel._state_image_abi import _K0OwnerState
from test_owner_state_runtime import _Owner, _Profile, _State, _View


class ScopedOwner(_Owner):
    def __init__(self):
        self.trace = []

    @contextmanager
    def validation_operation(self):
        self.trace.append("enter")
        try:
            yield
        finally:
            self.trace.append("exit")


@pytest.mark.parametrize("operation", [_clone_owner_state, _isolate_candidate_owner_state])
def test_each_copy_operation_owns_one_scope(operation):
    owner = ScopedOwner()
    original = _State(2)
    first = operation(owner, original)
    second = operation(owner, original)
    assert first == original and first is not original and second is not first
    assert owner.trace == ["enter", "exit"] * 2


def test_view_scope_includes_copy_and_read_but_never_leaks_to_caller():
    owner = ScopedOwner()
    original = _State(2)
    rows = _build_candidate_owner_views(
        _K0OwnerStateDirectory(_Profile((owner,)), (_K0OwnerState(owner.key, original),)),
        (owner.key,),
    )
    assert rows[0].view == _View(2)
    assert owner.trace == ["enter", "exit"]


def test_input_failure_exits_scope_and_does_not_copy():
    owner = ScopedOwner()
    with pytest.raises(TypeError, match="wrong state"):
        _clone_owner_state(owner, _View(2))
    assert owner.trace == ["enter", "exit"]


@pytest.mark.parametrize("fault", ["changed", "mutable"])
def test_candidate_validation_cannot_change_the_detached_input(fault):
    class Owner(ScopedOwner):
        def validate_state(self, state):
            super().validate_state(state)
            object.__setattr__(state, "value", state.value + 1 if fault == "changed" else [])

    owner = Owner()
    original = _State(2)
    with pytest.raises(K0ProfileError):
        _isolate_candidate_owner_state(owner, original)
    assert original == _State(2)
    assert owner.trace == ["enter", "exit"]


def test_kernel_isolation_never_uses_owner_persistence_or_backend_copy(monkeypatch):
    owner = ScopedOwner()

    def unexpected(*args):
        pytest.fail("candidate isolation delegated copying to owner code")

    monkeypatch.setattr(owner, "encode_state", unexpected)
    monkeypatch.setattr(owner, "decode_state", unexpected)
    monkeypatch.setattr(owner, "isolate_candidate_state", unexpected, raising=False)
    original = _State(2)
    result = _isolate_candidate_owner_state(owner, original)
    assert result == original and result is not original


def test_optional_scope_cannot_suppress_validation_failure():
    class SuppressingOwner(ScopedOwner):
        @contextmanager
        def validation_operation(self):
            try:
                yield
            except TypeError:
                pass

    with pytest.raises(TypeError, match="wrong state"):
        _clone_owner_state(SuppressingOwner(), _View(2))
