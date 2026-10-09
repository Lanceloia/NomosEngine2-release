"""Semantic preservation is closed data, not owner-defined Python equality."""

from dataclasses import dataclass, field
from types import MappingProxyType

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import _copy_closed_state, _isolate_candidate_owner_state


@dataclass(frozen=True, slots=True)
class Record:
    value: object


class Owner:
    state_type = Record

    def validate_state(self, state):
        pass


@pytest.mark.parametrize("change", [True, (1, 2), Record(2), "1", [1]])
def test_changed_type_shape_or_value_is_rejected_while_copying(change):
    class MutatingOwner(Owner):
        def validate_state(self, state):
            object.__setattr__(state, "value", change)

    original = Record(1)
    with pytest.raises(K0ProfileError):
        _isolate_candidate_owner_state(MutatingOwner(), original)
    assert original.value == 1


def test_unchanged_ordered_tree_never_executes_equality_or_constructors():
    @dataclass(frozen=True, slots=True)
    class Trap:
        value: tuple

        def __post_init__(self):
            pytest.fail("copy invoked a constructor")

        def __eq__(self, other):
            pytest.fail("copy/check invoked native equality")

    value = object.__new__(Trap)
    object.__setattr__(value, "value", (Record(1),))

    class TrapOwner(Owner):
        state_type = Trap

    result = _isolate_candidate_owner_state(TrapOwner(), value)
    assert result is not value
    assert result.value[0] is not value.value[0]
    assert result.value[0].value == 1


def test_validator_retained_nested_objects_never_enter_final_copy():
    retained = []

    class RetainingOwner(Owner):
        def validate_state(self, state):
            retained.append(state.value[0])

    original = Record((Record(1),))
    result = _isolate_candidate_owner_state(RetainingOwner(), original)
    object.__setattr__(retained[0], "value", 9)
    assert original.value[0].value == result.value[0].value == 1


def test_compare_false_fields_are_still_part_of_kernel_state():
    @dataclass(frozen=True)
    class State:
        value: int = field(compare=False)

    class MutatingOwner(Owner):
        state_type = State

        def validate_state(self, state):
            object.__setattr__(state, "value", 2)

    with pytest.raises(K0ProfileError, match="semantics"):
        _isolate_candidate_owner_state(MutatingOwner(), State(1))


def test_unordered_shapes_compare_data_without_invoking_original_key_callbacks():
    seen = []

    @dataclass(frozen=True)
    class Key:
        value: int

        def __hash__(self):
            seen.append(self)
            return 0

        def __eq__(self, other):
            seen.extend((self, other))
            return type(other) is Key and self.value == other.value

    a, b = Key(1), Key(2)
    original = Record((frozenset((a, b)), MappingProxyType({a: Record(1), b: Record(2)})))
    seen.clear()
    result = _isolate_candidate_owner_state(Owner(), original)
    assert all(value is not a and value is not b for value in seen)
    assert sorted(key.value for key in result.value[0]) == [1, 2]
    assert result.value[1] is not original.value[1]


@pytest.mark.parametrize("shape", ["set", "map"])
def test_unordered_change_rejects_and_mapping_order_does_not_matter(shape):
    original = (
        Record(frozenset((Record(1), Record(2))))
        if shape == "set"
        else Record(MappingProxyType({"a": Record(1), "b": Record(2)}))
    )
    reordered = (
        Record(frozenset((Record(2), Record(1))))
        if shape == "set"
        else Record(MappingProxyType({"b": Record(2), "a": Record(1)}))
    )
    result = _copy_closed_state(reordered, original)
    assert result == original and result is not original
    changed = (
        Record(frozenset((Record(3),)))
        if shape == "set"
        else Record(MappingProxyType({"a": 3}))
    )
    with pytest.raises(K0ProfileError, match="semantics"):
        _copy_closed_state(changed, original)


def test_unordered_structural_comparison_preserves_multiplicity():
    @dataclass(frozen=True, eq=False)
    class Distinct:
        value: int

    pair = Distinct(1), Distinct(1)
    original = Record(frozenset(pair))
    changed = Record(frozenset(pair[:1]))
    with pytest.raises(K0ProfileError, match="semantics"):
        _copy_closed_state(changed, original)
