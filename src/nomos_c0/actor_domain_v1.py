"""Typed instance-wise due effects over an explicitly selected finite Actor domain."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, get_args, get_origin, get_type_hints

from nomos_kernel import K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_actor_abi import _K0ActorDomainPort

from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0CheckedValueIR
from .composable_value_v1 import C0ValuePorts, C0ValueProgram, C0ValueStateError, _assignable

if TYPE_CHECKING:
    from .graph_contracts_v1 import C0GraphActorKind


@dataclass(frozen=True)
class C0ActorDomainPorts:
    name: str
    kind: C0GraphActorKind
    value_ports: C0ValuePorts
    effects: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class C0ActorDomainEffect:
    ports: C0ActorDomainPorts
    value: C0ValueProgram
    effects: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if (
            type(self.ports) is not C0ActorDomainPorts
            or type(self.value) is not C0ValueProgram
            or self.value._ports != self.ports.value_ports
            or self.value._ports.roots.get("actor") is not self.ports.kind.factory.state_type
            or type(self.effects) is not tuple
            or self.effects != self.ports.effects
            or not self.effects
            or any(
                type(item) is not tuple
                or len(item) != 2
                or any(type(part) is not str for part in item)
                for item in self.effects
            )
            or len({field for field, _ in self.effects}) != len(self.effects)
            or len({output for _, output in self.effects}) != len(self.effects)
            or {output for _, output in self.effects} != set(self.value._ports.outputs)
        ):
            raise C0LawError("Actor domain effect lacks one exact nominal instance port")
        fields = get_type_hints(self.ports.kind.factory.state_type)
        writes = self.value._ports.writable_fields
        if set(writes) - {self.ports.kind.factory.state_type} or any(
            field not in writes.get(self.ports.kind.factory.state_type, frozenset())
            or not _assignable(self.value._ports.outputs[output], fields.get(field))
            for field, output in self.effects
        ):
            raise C0LawError("Actor domain effect exceeds its instance write authority")

    def port(self):
        return _K0ActorDomainPort(self.ports.name, (self.ports.kind.symbol,), True)

    def contribution(self, view, roots, occurrence):
        if (
            view.participant != self.ports.name
            or view.actor_ref is None
            or view.actor_ref.family != self.ports.kind.symbol
            or type(view.view) is not self.ports.kind.factory.state_type
        ):
            raise K0ProfileError("Actor domain lost its actual instance basis")
        outputs = self.value.evaluate({**roots, "actor": view.view}, occurrence=occurrence)
        if outputs is None:
            raise C0ValueStateError("required Actor domain instance has no admitted effect")
        state = replace(view.view, **{field: outputs[output] for field, output in self.effects})
        owner = self.ports.kind.factory.build(view.owner)
        owner.validate_state(state)
        contribution = owner.contribution_type(view.owner, state)
        owner.validate_contribution(contribution)
        return contribution


@dataclass(frozen=True)
class C0WorldActorDomainIR:
    name: str
    kind: str
    value: C0CheckedValueIR
    effects: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class C0ReadActorDomainPorts:
    name: str
    kind: C0GraphActorKind
    wrapper: type
    members_field: str
    record: type
    identity_field: str
    fields: tuple[tuple[str, str], ...]

    def __post_init__(self):
        wrapper_fields = get_type_hints(self.wrapper)
        members = wrapper_fields.get(self.members_field)
        record_fields = get_type_hints(self.record)
        state_fields = get_type_hints(self.kind.factory.state_type)
        declared = {
            field.name: field.value for field in getattr(self.record, "__nomos_fields__", ())
        }
        state_declared = {
            field.name: field.value
            for field in getattr(self.kind.factory.state_type, "__nomos_fields__", ())
        }
        wrapper_declared = {
            field.name: field.value for field in getattr(self.wrapper, "__nomos_fields__", ())
        }
        member_spec = wrapper_declared.get(self.members_field)
        if (
            type(self.name) is not str
            or not self.name.isidentifier()
            or set(wrapper_fields) != {self.members_field}
            or get_origin(members) is not tuple
            or get_args(members) != (self.record, Ellipsis)
            or record_fields.get(self.identity_field) is not _K0ActorRef
            or type(self.fields) is not tuple
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(type(part) is not str for part in pair)
                for pair in self.fields
            )
            or len({field for field, _ in self.fields}) != len(self.fields)
            or self.identity_field in {field for field, _ in self.fields}
            or set(record_fields) != {self.identity_field, *(field for field, _ in self.fields)}
            or any(
                source not in state_fields or record_fields[field] != state_fields[source]
                for field, source in self.fields
            )
            or set(declared) != set(record_fields)
            or member_spec is None
            or member_spec.maximum < self.kind.max_instances
            or any(declared[field] != state_declared.get(source) for field, source in self.fields)
        ):
            raise C0LawError("read Actor domain lacks an exact nominal projection")

    def port(self):
        return _K0ActorDomainPort(self.name, (self.kind.symbol,), False)

    def project(self, views):
        entries = []
        for view in views:
            if view.participant != self.name:
                continue
            if (
                view.actor_ref is None
                or view.actor_ref.family != self.kind.symbol
                or type(view.view) is not self.kind.factory.state_type
            ):
                raise K0ProfileError("read Actor domain lost its actual nominal instance")
            entry = self.record(
                **{
                    self.identity_field: view.actor_ref,
                    **{field: getattr(view.view, source) for field, source in self.fields},
                }
            )
            entry.validate_for_k0()
            entries.append(entry)
        result = self.wrapper(**{self.members_field: tuple(entries)})
        result.validate_for_k0()
        return result


@dataclass(frozen=True)
class C0WorldReadActorDomainIR:
    name: str
    kind: str
    wrapper: str
    members_field: str
    record: str
    identity_field: str
    fields: tuple[tuple[str, str], ...]


def check_read_actor_domains(domains, reserved):
    if (
        type(domains) is not tuple
        or any(type(domain) is not C0ReadActorDomainPorts for domain in domains)
        or len({domain.name for domain in domains}) != len(domains)
        or len({domain.kind.symbol for domain in domains}) != len(domains)
        or any(domain.name in reserved for domain in domains)
    ):
        raise C0LawError("Event read domains alias a root or nominal kind")
    for domain in domains:
        domain.__post_init__()
