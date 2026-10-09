"""Object plans cover selected nominal sorts and bind the actual owner factories."""

from dataclasses import replace

import pytest

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import read_author_document
from nomos_c0.declarative_nominal_v0 import check_nominal_lib
from nomos_c0.nominal_types_v1 import ObjectSortRef, SemanticIdentity
from nomos_c0.object_owner_binding_v1 import (
    ObjectOwnerPlanError,
    ObjectOwnerPort,
    _bind_object_owner_plan,
    plan_object_owners,
)


def _sort(name: str) -> ObjectSortRef:
    return ObjectSortRef(SemanticIdentity(name))


def test_exact_object_sort_plan_is_canonical():
    a, b = _sort("TEST.A@1"), _sort("TEST.B@1")
    plan = plan_object_owners(
        (a, b), (ObjectOwnerPort(b, "b", "B", 2), ObjectOwnerPort(a, "a", "A", 1))
    )
    assert tuple(port.sort for port in plan.ports) == (a, b)


@pytest.mark.parametrize("fault", ("missing", "duplicate_sort", "duplicate_family"))
def test_object_sort_plan_rejects_incomplete_or_aliasing_ports(fault):
    a, b = _sort("TEST.A@1"), _sort("TEST.B@1")
    ports = {
        "missing": (ObjectOwnerPort(a, "a", "A", 1),),
        "duplicate_sort": (ObjectOwnerPort(a, "a", "A", 1), ObjectOwnerPort(a, "b", "B", 1)),
        "duplicate_family": (ObjectOwnerPort(a, "a", "A", 1), ObjectOwnerPort(b, "a", "B", 1)),
    }[fault]
    with pytest.raises(ObjectOwnerPlanError):
        plan_object_owners((a, b), ports)


def test_object_owner_port_rejects_non_integer_capacity_and_noncanonical_sorts():
    a, b = _sort("TEST.A@1"), _sort("TEST.B@1")
    with pytest.raises(ObjectOwnerPlanError):
        ObjectOwnerPort(a, "a", "A", True)
    with pytest.raises(ObjectOwnerPlanError):
        plan_object_owners((b, a), (ObjectOwnerPort(a, "a", "A", 1),))


def test_plan_is_verified_against_actual_k0_kind_without_a_second_profile():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "nomos_c0" / "examples"
    selected = check_nominal_lib(
        read_author_document(root / "object_target_v1.lib.yaml")
    ).object_kinds
    sorts = tuple(sorted(item.sort for item in selected))
    plan = plan_object_owners(
        sorts,
        tuple(
            ObjectOwnerPort(k.sort, k.symbol, k.state_record, k.k0_kind.max_instances)
            for k in selected
        ),
    )
    bound = _bind_object_owner_plan(plan, selected)
    assert all(k in bound for k in (item.k0_kind for item in selected))
    bad = replace(
        plan, ports=tuple(replace(p, max_instances=p.max_instances + 1) for p in plan.ports)
    )
    with pytest.raises(C0LawError, match="differs"):
        _bind_object_owner_plan(bad, selected)
