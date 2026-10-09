"""Lazy diagnostic paths retain full traversal, ordering and failure locations."""

from dataclasses import InitVar, dataclass, field, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import ClassVar

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_abi import _validate_closed_host_object


def reference(value, label):
    if value is None or type(value) in (bool, int, str) or isinstance(value, (Enum, type)):
        return
    if type(value) is tuple:
        for index, child in enumerate(value):
            reference(child, f"{label}[{index}]")
        return
    if type(value) is frozenset:
        for index, child in enumerate(sorted(value, key=repr)):
            reference(child, f"{label}[{index}]")
        return
    if type(value) is MappingProxyType:
        for key, child in value.items():
            reference(key, f"{label}.key")
            reference(child, f"{label}[{key!r}]")
        return
    parameters = getattr(type(value), "__dataclass_params__", None)
    if not is_dataclass(value) or parameters is None or not parameters.frozen:
        raise K0ProfileError(f"{label} must use recursively frozen closed configuration")
    for member in fields(value):
        reference(getattr(value, member.name), f"{label}.{member.name}")


@dataclass(frozen=True)
class Box:
    first: object
    second: object = None


class TupleSubclass(tuple):
    pass


@pytest.mark.parametrize(
    "value",
    [
        Box((Box(3), frozenset({1, 2}), MappingProxyType({"a": Box(None)}))),
        Box((Box((Box([]),)),)),
        Box(MappingProxyType({"a": Box({})})),
        Box(frozenset({1.5, 2.5})),
        Box(TupleSubclass((1, 2))),
        Box([1], {"later": "invalid"}),
        {"root": "mutable"},
    ],
)
def test_paths_and_first_refusal_match_eager_reference(value):
    outcomes = []
    for validate in (reference, _validate_closed_host_object):
        try:
            validate(value, "candidate")
        except K0ProfileError as error:
            outcomes.append(str(error))
        else:
            outcomes.append(None)
    assert outcomes[0] == outcomes[1]


def test_every_read_rechecks_values_and_current_frozen_metadata(monkeypatch):
    value = Box(Box(3))
    _validate_closed_host_object(value, "candidate")
    object.__setattr__(value.first, "first", [])
    with pytest.raises(K0ProfileError, match=r"candidate.first.first must"):
        _validate_closed_host_object(value, "candidate")
    object.__setattr__(value.first, "first", 3)
    parameters = Box.__dataclass_params__
    monkeypatch.setattr(parameters, "frozen", False)
    with pytest.raises(K0ProfileError, match="candidate must"):
        _validate_closed_host_object(value, "candidate")


def test_pseudo_fields_are_filtered_but_noninit_real_fields_are_checked():
    @dataclass(frozen=True)
    class Record:
        ignored: ClassVar[object] = []
        input_only: InitVar[object] = None
        real: object = field(init=False, default=None)

    value = Record([])
    _validate_closed_host_object(value, "config")
    object.__setattr__(value, "real", [])
    with pytest.raises(K0ProfileError, match=r"config.real must"):
        _validate_closed_host_object(value, "config")


def test_fields_snapshot_and_getter_order_match_reference(monkeypatch):
    calls = []

    @dataclass(frozen=True)
    class Record:
        first: object
        second: object

        def __getattribute__(self, name):
            if name in ("first", "second"):
                calls.append(name)
                if name == "first":
                    type(self).__dataclass_fields__.pop("second", None)
            return object.__getattribute__(self, name)

    value = Record(1, [])
    original = dict(Record.__dataclass_fields__)
    for validate in (reference, _validate_closed_host_object):
        monkeypatch.setattr(Record, "__dataclass_fields__", original.copy())
        calls.clear()
        with pytest.raises(K0ProfileError, match=r"config.second must"):
            validate(value, "config")
        assert calls == ["first", "second"]


def test_mapping_key_repr_timing_is_not_deferred():
    calls = []

    @dataclass(frozen=True)
    class Key:
        number: int

        def __repr__(self):
            calls.append(self.number)
            return f"Key({self.number})"

    value = MappingProxyType({Key(1): Box(1), Key(2): []})
    for validate in (reference, _validate_closed_host_object):
        calls.clear()
        with pytest.raises(K0ProfileError, match=r"config\[Key\(2\)\] must"):
            validate(value, "config")
        assert calls == [1, 2]
