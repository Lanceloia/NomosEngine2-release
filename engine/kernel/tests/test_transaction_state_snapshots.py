"""Internal state sharing never replaces callback or incoming-value isolation."""

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType

import pytest
from nomos_kernel import K0OccurrenceFamily, K0OwnerKey, K0ProfileError
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryActionAttempt,
    _K0InMemoryEvaluation,
    _K0InMemoryProfile,
    _K0InMemorySession,
)
from nomos_kernel._candidate_owner_state_runtime import _K0OwnerStateCandidate
from nomos_kernel._owner_state_runtime import _copy_closed_state
from nomos_kernel._rule_products_abi import K0RuleResult
from nomos_kernel._settlement_outcome_abi import K0SettlementDefect
from nomos_kernel._state_image_abi import _K0OwnerState
from test_causal_wave_stage_isolation import (
    ACTION,
    ACTION_TYPE,
    EVENT,
    EVENT_TYPE,
    OWNER,
    _law,
    _Owner,
    _Replace,
    _Rule,
    _session,
    _source,
    _Value,
)


def test_untouched_owners_are_shared_but_opening_and_changed_states_are_isolated():
    owners = tuple(_Owner(K0OwnerKey(f"owner.{index:02d}")) for index in range(20))
    opening = tuple(_K0OwnerState(owner.key, _Value(0)) for owner in owners)
    session = _K0InMemorySession.create(
        _K0InMemoryProfile(
            owners, (_source(ACTION, K0OccurrenceFamily.ACTION, ACTION_TYPE),), (), 1, 1
        ),
        opening,
    )
    prior = session._states
    assert all(a.state is not b.state for a, b in zip(opening, prior, strict=True))
    object.__setattr__(opening[0].state, "value", 999)
    result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert prior[0].state == _Value(0)
    assert session._states[0].state == _Value(1)
    assert all(a is b for a, b in zip(prior[1:], session._states[1:], strict=True))
    # Publication products cannot hold the authoritative state either.
    object.__setattr__(result.occurrences[0].semantic_envelope, "value", 888)
    assert session._states[0].state == _Value(1)


@pytest.mark.parametrize("fail", [False, True])
def test_owner_apply_gets_disposable_prior_and_retained_product_is_isolated(monkeypatch, fail):
    session = _session(())
    prior = session._states
    captured = []

    def apply(owner, state, contributions):
        assert state is not prior[0].state
        object.__setattr__(state, "value", 777)
        if fail:
            raise K0ProfileError("apply failed after modifying its private input")
        product = contributions[0].contribution.state
        captured.append(product)
        return product

    monkeypatch.setattr(_Owner, "apply_contributions", apply)
    if fail:
        with pytest.raises(K0SettlementDefect):
            session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        assert session._states is prior
        assert session.occurrence_history() == ()
        assert session._fatal
    else:
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        object.__setattr__(captured[0], "value", 888)
        assert session._states[0].state == _Value(1)
    assert prior[0].state == _Value(0)


@pytest.mark.parametrize("fail", [False, True])
def test_causal_write_domain_expands_without_cloning_unrelated_owners(monkeypatch, fail):
    owners = tuple(_Owner(K0OwnerKey(f"owner.{index:02d}")) for index in range(3))
    second = owners[1].key
    event = replace(
        _source(EVENT, K0OccurrenceFamily.EVENT, EVENT_TYPE),
        read_owners=(OWNER, second),
        contribution_owners=(second,),
    )
    session = _K0InMemorySession.create(
        _K0InMemoryProfile(
            owners,
            (_source(ACTION, K0OccurrenceFamily.ACTION, ACTION_TYPE), event),
            (_law("activate"),),
            2,
            1,
        ),
        tuple(_K0OwnerState(owner.key, _Value(0)) for owner in owners),
    )
    live = session._states
    original_evaluate = _Rule.evaluate
    original_snapshot = _K0OwnerStateCandidate._snapshot_states
    stages = []

    def snapshot(candidate):
        states = original_snapshot(candidate)
        stages.append(states)
        return states

    def evaluate(rule, rule_input):
        if rule_input.source == EVENT:
            if fail:
                raise K0ProfileError("later Event failed")
            return _K0InMemoryEvaluation(
                K0RuleResult((_Replace(second, rule_input.evidence),), ()), rule_input.evidence
            )
        return original_evaluate(rule, rule_input)

    monkeypatch.setattr(_K0OwnerStateCandidate, "_snapshot_states", snapshot)
    monkeypatch.setattr(_Rule, "evaluate", evaluate)
    if fail:
        with pytest.raises(K0SettlementDefect):
            session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        assert session._states is live
        assert session.occurrence_history() == ()
        assert session._cursor.next_value == 1
    else:
        result = session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        assert len(result.occurrences) == 2
        assert session._states[0].state == _Value(1)
        assert session._states[1].state == _Value(2)
        assert session._states[2] is live[2]
        assert stages[0][1] is live[1]
        assert stages[0][1].state == _Value(0)
    assert live == tuple(_K0OwnerState(owner.key, _Value(0)) for owner in owners)
    assert stages[0][0].owner == OWNER
    assert stages[0][0].state == _Value(1)


def test_full_clone_stage_interface_is_removed():
    assert not hasattr(_K0OwnerStateCandidate, "immutable_stage_states")


def test_opening_validator_cannot_retain_authoritative_storage(monkeypatch):
    retained = []

    def validate(owner, state):
        retained.append(state)

    monkeypatch.setattr(_Owner, "validate_opening_state", validate, raising=False)
    session = _session(())
    for state in retained:
        object.__setattr__(state, "value", 999)
    assert all(item.state == _Value(0) for item in session._states)


def test_kernel_copy_detaches_nested_closed_values_without_running_constructor():
    @dataclass(frozen=True, slots=True)
    class Record:
        values: tuple

        def __post_init__(self):
            raise AssertionError("data detachment must not execute a record constructor")

    value = object.__new__(Record)
    object.__setattr__(value, "values", (_Value(3),))
    original = MappingProxyType({"record": value, "set": frozenset({_Value(4)})})
    copied = _copy_closed_state(original)
    assert copied == original and copied is not original
    assert copied["record"] is not value
    assert copied["record"].values[0] is not value.values[0]
    assert next(iter(copied["set"])) is not next(iter(original["set"]))


def test_kernel_copy_rejects_computed_fields_without_executing_them():
    @dataclass(frozen=True)
    class Record:
        value: int

    record = Record(1)

    class Computed:
        def __get__(self, instance, owner):
            raise AssertionError("computed field must not run")

    setattr(Record, "value", Computed())
    with pytest.raises(K0ProfileError, match="computed descriptor"):
        _copy_closed_state(record)


@pytest.mark.parametrize("value", [[1], {"x": 1}, _Value([1])])
def test_mutable_state_is_not_a_shared_storage_candidate(value):
    with pytest.raises(K0ProfileError, match="frozen closed"):
        _copy_closed_state(value)


def test_candidate_structural_check_never_invokes_native_state_equality(monkeypatch):
    session = _session(())
    live = session._states
    retained = []

    def equal(left, right):
        retained.extend((left, right))
        return type(right) is _Value and left.value == right.value

    with monkeypatch.context() as patch:
        patch.setattr(_Value, "__eq__", equal)
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
    assert retained == []
    assert live[0].state == _Value(0)
    assert session._states[0].state == _Value(1)


@pytest.mark.parametrize("payload", [[1], {"x": 1}, (_Value(1),), ("x", [1])])
def test_enum_leaf_cannot_hide_mutable_or_record_member_data(payload):
    member = Enum("Member", {"A": payload}).A
    with pytest.raises(K0ProfileError, match="Enum member"):
        _copy_closed_state(_Value(member))


def test_enum_leaf_cannot_hide_mutable_auxiliary_attribute():
    member = Enum("Member", {"A": "a"}).A
    member.extra = [1]
    with pytest.raises(K0ProfileError, match="Enum member"):
        _copy_closed_state(_Value(member))


def test_even_scalar_enum_members_are_not_state_isolation_leaves():
    member = Enum("Member", {"A": (1, "a", frozenset({True, None}))}).A
    # A scalar value does not prevent later assignment to the singleton member.
    with pytest.raises(K0ProfileError, match="Enum member"):
        _copy_closed_state(_Value(member))


@pytest.mark.parametrize("callback", ["validate_state", "encode_state"])
@pytest.mark.parametrize("mutate", [False, True])
def test_storage_never_escapes_to_validation_or_codec(
    monkeypatch, callback, mutate
):
    session = _session(())
    live = session._states
    retained = []
    original = getattr(_Owner, callback, None)

    def operation(owner, state):
        assert all(state is not item.state for item in live)
        retained.append(state)
        if mutate:
            object.__setattr__(state, "value", 999)
        return original(owner, state)

    monkeypatch.setattr(_Owner, callback, operation, raising=False)
    if mutate:
        # This callback runs while building the pre-admission view.
        with pytest.raises(K0ProfileError):
            if callback == "encode_state":
                from nomos_kernel._owner_state_runtime import _clone_owner_state

                _clone_owner_state(_Owner(live[0].owner), live[0].state)
            else:
                session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        assert session._states is live
        assert session.occurrence_history() == ()
    else:
        if callback == "encode_state":
            from nomos_kernel._owner_state_runtime import _clone_owner_state

            _clone_owner_state(_Owner(live[0].owner), live[0].state)
        session.settle(_K0InMemoryActionAttempt(ACTION, _Value(1)))
        for state in retained:
            object.__setattr__(state, "value", 999)
        assert session._states[0].state == _Value(1)
    assert live[0].state == _Value(0)
