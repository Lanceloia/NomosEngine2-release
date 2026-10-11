"""Copy traversal checks actual native layouts, including inherited descriptors."""

from dataclasses import dataclass

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import _copy_closed_state


def test_inherited_slots_are_copied_without_sharing():
    @dataclass(frozen=True, slots=True)
    class Base:
        first: tuple

    @dataclass(frozen=True, slots=True)
    class Child(Base):
        second: int

    original = Child((Base((1,)),), 2)
    result = _copy_closed_state(original, original)
    assert result == original
    assert result is not original
    assert result.first is not original.first
    assert result.first[0] is not original.first[0]


def test_descriptor_change_between_copies_is_not_cached(monkeypatch):
    @dataclass(frozen=True)
    class Record:
        first: int

    value = Record(1)
    assert _copy_closed_state(value) == value
    calls = []
    monkeypatch.setattr(Record, "first", property(lambda self: calls.append(self)), raising=False)
    with pytest.raises(K0ProfileError, match="computed descriptor"):
        _copy_closed_state(value)
    assert not calls


def test_nested_native_hash_cannot_hide_a_changed_later_descriptor(monkeypatch):
    @dataclass(frozen=True)
    class Key:
        number: int

        def __hash__(self):
            if mutate:
                monkeypatch.setattr(Record, "later", property(lambda self: 3), raising=False)
            return self.number

    @dataclass(frozen=True)
    class Record:
        first: frozenset
        later: int

    mutate = False
    original = Record(frozenset((Key(1),)), 2)
    mutate = True
    with pytest.raises(K0ProfileError, match="computed descriptor"):
        _copy_closed_state(original)
    assert object.__getattribute__(original, "__dict__")["later"] == 2


def test_nested_native_hash_cannot_hide_a_changed_later_slot(monkeypatch):
    @dataclass(frozen=True)
    class Key:
        number: int

        def __hash__(self):
            if mutate:
                monkeypatch.setattr(Record, "later", property(lambda self: 3))
            return self.number

    @dataclass(frozen=True, slots=True)
    class Record:
        first: frozenset
        later: int

    mutate = False
    original = Record(frozenset((Key(1),)), 2)
    mutate = True
    with pytest.raises(K0ProfileError, match="computed descriptor"):
        _copy_closed_state(original)
