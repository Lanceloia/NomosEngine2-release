"""Current field snapshots retain ordering, pseudo-field and native boundaries."""

from dataclasses import _FIELD, _FIELD_CLASSVAR, InitVar, dataclass, fields
from types import MappingProxyType
from typing import ClassVar

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import _copy_closed_state, _snapshot_record_fields


def test_inherited_real_fields_match_dataclasses_order_and_skip_pseudo_fields():
    @dataclass(frozen=True, slots=True)
    class Base:
        first: int
        category: ClassVar[str] = "record"

    @dataclass(frozen=True, slots=True)
    class Child(Base):
        second: str
        hint: InitVar[int] = 0

    original = Child(1, "two", 9)
    snapshot = _snapshot_record_fields(Child)
    assert tuple(snapshot) == fields(Child)
    assert [item.name for item in snapshot] == ["first", "second"]
    result = _copy_closed_state(original, original)
    assert result == original and result is not original


@pytest.mark.parametrize("proxy", [False, True])
def test_snapshot_is_complete_before_nested_native_hash_reclassifies_later_field(proxy):
    mutate = False

    @dataclass(frozen=True)
    class Key:
        number: int

        def __hash__(self):
            if mutate:
                State.__dataclass_fields__["later"]._field_type = _FIELD_CLASSVAR
            return self.number

    @dataclass(frozen=True)
    class State:
        first: frozenset
        later: int

    original = State(frozenset((Key(1),)), 2)
    metadata = State.__dataclass_fields__
    if proxy:
        State.__dataclass_fields__ = MappingProxyType(metadata)
    mutate = True
    result = _copy_closed_state(original)
    assert result.later == 2
    assert result.first is not original.first
    assert metadata["later"]._field_type is _FIELD_CLASSVAR
    assert [item.name for item in _snapshot_record_fields(State)] == ["first"]


def test_each_copy_still_rejects_a_changed_later_descriptor(monkeypatch):
    @dataclass(frozen=True)
    class State:
        number: int

    original = State(1)
    assert _copy_closed_state(original) == original
    calls = []
    monkeypatch.setattr(State, "number", property(lambda self: calls.append(self)), raising=False)
    with pytest.raises(K0ProfileError, match="computed descriptor"):
        _copy_closed_state(original)
    assert not calls


def _failure(callback, carrier):
    try:
        callback(carrier)
    except BaseException as error:
        return type(error), str(error), type(error.__cause__)
    return None


@pytest.mark.parametrize("where", ["metadata", "values", "iter", "field"])
@pytest.mark.parametrize("error_type", [StopIteration, LookupError, AttributeError])
def test_native_metadata_failure_boundaries_match_dataclasses_fields(where, error_type):
    class Entry:
        @property
        def _field_type(self):
            if where == "field":
                raise error_type("native field")
            return _FIELD

    class Values:
        def __iter__(self):
            if where == "iter":
                raise error_type("native iterable")
            return iter((Entry(),))

    class Metadata:
        def values(self):
            if where == "values":
                raise error_type("native values")
            return Values()

    class Meta(type):
        def __getattribute__(self, name):
            if name == "__dataclass_fields__" and where == "metadata":
                raise error_type("native metadata")
            return super().__getattribute__(name)

    class Carrier(metaclass=Meta):
        __dataclass_fields__ = Metadata()

    assert _failure(_snapshot_record_fields, Carrier) == _failure(fields, Carrier)


def test_standard_values_field_stop_iteration_keeps_generator_error():
    class Entry:
        @property
        def _field_type(self):
            raise StopIteration("native field")

    class Carrier:
        __dataclass_fields__ = {"field": Entry()}

    assert _failure(_snapshot_record_fields, Carrier) == _failure(fields, Carrier)


def test_native_values_are_materialized_once_before_traversal():
    calls = []

    @dataclass(frozen=True)
    class State:
        number: int

    class Metadata:
        def values(self):
            calls.append("values")
            return State.__dataclass_fields__.values()

    class Carrier:
        __dataclass_fields__ = Metadata()

    assert tuple(_snapshot_record_fields(Carrier)) == fields(State)
    assert calls == ["values"]
