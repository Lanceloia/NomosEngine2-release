"""Check selected Object plans against exact native owner factories."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel._dynamic_owner_abi import (
    _K0DynamicOwnerKind,
)

from .author_contract_v1 import C0LawError
from .graph_contracts_v1 import C0GraphObjectKind
from .nominal_types_v1 import ObjectSortRef


class ObjectOwnerPlanError(ValueError):
    """A declared Object sort cannot bind to one runtime owner family."""


@dataclass(frozen=True, order=True)
class ObjectOwnerPort:
    sort: ObjectSortRef
    family: str
    state_record: str
    max_instances: int

    def __post_init__(self) -> None:
        if (
            type(self.sort) is not ObjectSortRef
            or type(self.family) is not str
            or not self.family
            or type(self.state_record) is not str
            or not self.state_record
            or type(self.max_instances) is not int
            or not 1 <= self.max_instances <= 256
        ):
            raise ObjectOwnerPlanError("Object owner port is malformed")
        self.sort.validate_for_ir()


@dataclass(frozen=True)
class ObjectOwnerPlan:
    ports: tuple[ObjectOwnerPort, ...]

    def __post_init__(self) -> None:
        if type(self.ports) is not tuple or not self.ports:
            raise ObjectOwnerPlanError("Object owner plan needs exact ports")
        if any(type(port) is not ObjectOwnerPort for port in self.ports):
            raise ObjectOwnerPlanError("Object owner plan has a foreign port")
        if self.ports != tuple(sorted(self.ports)):
            raise ObjectOwnerPlanError("Object owner plan is not canonical")
        if len({port.sort for port in self.ports}) != len(self.ports) or len(
            {port.family for port in self.ports}
        ) != len(self.ports):
            raise ObjectOwnerPlanError("Object sort or owner family is duplicated")
        for port in self.ports:
            port.__post_init__()


def plan_object_owners(
    sorts: tuple[ObjectSortRef, ...], ports: tuple[ObjectOwnerPort, ...]
) -> ObjectOwnerPlan:
    if (
        type(sorts) is not tuple
        or any(type(sort) is not ObjectSortRef for sort in sorts)
        or sorts != tuple(sorted(set(sorts)))
        or type(ports) is not tuple
    ):
        raise ObjectOwnerPlanError("Object owner planning needs canonical sorts and exact ports")
    if any(type(port) is not ObjectOwnerPort for port in ports):
        raise ObjectOwnerPlanError("Object owner planning has a foreign port")
    plan = ObjectOwnerPlan(tuple(sorted(ports)))
    if tuple(port.sort for port in plan.ports) != sorts:
        raise ObjectOwnerPlanError("Object owner ports do not cover exactly the declared sorts")
    return plan


def _bind_object_owner_plan(
    plan: ObjectOwnerPlan | None, selected: tuple[C0GraphObjectKind, ...]
) -> tuple[_K0DynamicOwnerKind, ...]:
    if plan is None:
        if selected:
            raise C0LawError("selected Object kinds lack an owner plan")
        return ()
    if type(plan) is not ObjectOwnerPlan or type(selected) is not tuple:
        raise C0LawError("Object owner binding is malformed")
    try:
        plan.__post_init__()
    except ObjectOwnerPlanError as error:
        raise C0LawError("Object owner plan is malformed") from error
    kinds = {item.sort: item for item in selected if type(item) is C0GraphObjectKind}
    if len(kinds) != len(selected) or len(plan.ports) != len(selected):
        raise C0LawError("Object owner plan does not cover selected kinds")
    bound = []
    for port in plan.ports:
        item = kinds.get(port.sort)
        if (
            item is None
            or item.symbol != port.family
            or item.state_record != port.state_record
            or item.k0_kind.family != port.family
            or item.k0_kind.max_instances != port.max_instances
            or item.k0_kind.state_type.__name__ != port.state_record
        ):
            raise C0LawError("Object owner plan differs from selected K0 kind")
        bound.append(item.k0_kind)
    return tuple(bound)
