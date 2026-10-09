"""Feasibility counterexamples, not a qualification issuer or runtime cache."""

from dataclasses import FrozenInstanceError, replace

import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._owner_state_runtime import _isolate_candidate_owner_state
from test_local_computation_v1 import State, const, ports, program, ref, state
from test_nominal_owner_layout_v1 import _lib

from nomos_c0 import composable_value_v1 as values
from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.invariant_execution_v1 import compile_invariant_admission


@pytest.fixture
def generated():
    declaration = _lib()
    declaration["records"][0]["invariant"] = {"le": [{"ref": "state.amount"}, {"const": 4}]}
    declaration["pure_definitions"] = []
    lib = check_nominal_lib(declaration)
    item = lib.record("Item")("x", 3, None)
    box = lib.record("Box")(item, (item,))
    return lib, lib.owner("box").owner, box


def checkpoint(lib, owner, current):
    # This is the existing candidate gate being falsified, not a reusable receipt.
    lib.check_record_layout()
    owner.validate_state(current)
    return owner, current, type(current).validate_for_k0


def test_same_state_and_validator_identity_do_not_seal_nested_values(generated):
    lib, owner, current = generated
    before = checkpoint(lib, owner, current)
    object.__setattr__(current.item, "amount", 5)
    lib.check_record_layout()
    assert before[0] is owner and before[1] is current
    assert before[2] is type(current).validate_for_k0
    with pytest.raises(K0ProfileError, match="invariant"):
        owner.validate_state(current)


def test_generated_layout_rejects_replacing_field_getters(generated):
    lib, owner, current = generated
    checkpoint(lib, owner, current)
    carrier = type(current.item)
    descriptor = carrier.__dict__["amount"]
    reads = []

    def get_amount(value):
        reads.append(value)
        return descriptor.__get__(value, carrier) + 2

    with pytest.raises(TypeError, match="read-only"):
        carrier.amount = property(get_amount)
    lib.check_record_layout()
    assert not reads
    owner.validate_state(current)


def test_generated_layout_rejects_constructor_replacement(generated):
    lib, owner, current = generated
    checkpoint(lib, owner, current)

    def constructor(*args, **kwargs):
        raise RuntimeError("constructor changed after the input gate")

    with pytest.raises(TypeError, match="read-only"):
        type(current.item).__init__ = constructor
    lib.check_record_layout()
    owner.validate_state(current)
    assert _isolate_candidate_owner_state(owner, current) == current


def test_invariant_operands_cannot_be_publicly_rebound(generated):
    lib, owner, current = generated
    checkpoint(lib, owner, current)
    invariant = type(current.item).__nomos_invariant__
    limit = invariant.guard_ir.expression.operand[1]
    with pytest.raises(FrozenInstanceError):
        limit.operand = 2
    lib.check_record_layout()
    assert type(current.item).__nomos_invariant__ is invariant
    owner.validate_state(current)


def test_generated_dependency_cannot_switch_validator_from_a_new_getter(generated):
    lib, owner, current = generated
    checkpoint(lib, owner, current)
    carrier = type(current.item)
    descriptor = carrier.__dict__["amount"]
    original = carrier.validate_for_k0
    calls = []

    def nested(value):
        calls.append(value)
        original(value)
        raise K0ProfileError("nested dependency changed during field access")

    def get_amount(value):
        carrier.validate_for_k0 = nested
        return descriptor.__get__(value, carrier)

    with pytest.raises(TypeError, match="read-only"):
        carrier.amount = property(get_amount)
    lib.check_record_layout()
    owner.validate_state(current)
    assert not calls


@pytest.mark.parametrize("planned", [False, True])
def test_read_domain_union_is_not_each_laws_authority(planned):
    selected = ports()
    other = replace(
        selected,
        admission_readable_paths=frozenset({"state.ready"}),
        admission_readable_fields={State: frozenset({"ready"})},
    )
    first = program(guard={"lt": [const(0), ref("state.count")]})
    second = program(guard=ref("state.ready"), selected_ports=other)
    first_reads = first._admission_ports.readable_paths
    second_reads = second._admission_ports.readable_paths
    prepared_domain = first_reads | second_reads
    assert "state.count" in prepared_domain and "state.ready" in prepared_domain
    assert "state.count" not in second_reads
    execute = compile_invariant_admission if planned else lambda value: value.admits
    assert execute(first)(state()) and execute(second)(state())
    with pytest.raises(C0LawError):
        program(guard={"lt": [const(0), ref("state.count")]}, selected_ports=other)
    with pytest.raises(C0LawError, match="read port"):
        values._read_reference(("state", "count"), state(), other.roots, second._admission_ports)


@pytest.mark.parametrize("planned", [False, True])
def test_contiguous_steps_still_read_their_current_state(planned):
    rule = program(guard={"lt": [ref("state.count"), const(4)]})
    execute = compile_invariant_admission(rule) if planned else rule.admits
    before = state(3)
    assert execute(before)
    after = {"state": replace(before["state"], count=4)}
    assert not execute(after)


@pytest.mark.parametrize("planned", [False, True])
def test_unselected_branch_is_not_read_by_entry_union_validation(planned, monkeypatch):
    rule = program(guard={"any": [ref("state.ready"), {"lt": [const(0), ref("state.count")]}]})
    execute = compile_invariant_admission(rule) if planned else rule.admits
    reads = []
    selected, unselected = state(ready=True), state(ready=False)

    def count(value):
        reads.append(value)
        raise RuntimeError("unselected field was read")

    monkeypatch.setattr(State, "count", property(count), raising=False)
    assert execute(selected)
    assert not reads
    with pytest.raises(RuntimeError, match="unselected field"):
        execute(unselected)


@pytest.mark.parametrize("planned", [False, True])
def test_entry_permission_check_does_not_replace_post_read_check(planned, monkeypatch):
    rule = program(guard={"lt": [const(0), ref("state.count")]})
    execute = compile_invariant_admission(rule) if planned else rule.admits
    current_ports = rule._admission_ports
    roots = state()
    assert "count" in current_ports.readable_fields[State]

    def count(value):
        object.__setattr__(current_ports, "readable_fields", {State: frozenset()})
        return 3

    monkeypatch.setattr(State, "count", property(count), raising=False)
    with pytest.raises(C0LawError, match="read port"):
        execute(roots)


@pytest.mark.parametrize("planned", [False, True])
def test_first_rule_can_invalidate_the_next_rules_entry_check(planned, monkeypatch):
    first = program(guard=ref("state.ready"))
    second = program(guard={"lt": [const(0), ref("state.count")]})
    roots = state()
    execute = compile_invariant_admission if planned else lambda value: value.admits
    a, b = execute(first), execute(second)
    assert b(roots)

    def ready(value):
        object.__setattr__(second._admission_ports, "readable_fields", {State: frozenset()})
        return True

    monkeypatch.setattr(State, "ready", property(ready), raising=False)
    assert a(roots)
    with pytest.raises(C0LawError, match="read port"):
        b(roots)
