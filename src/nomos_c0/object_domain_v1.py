"""Exact read-only projections of current Object instances for temporal due Events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args, get_origin, get_type_hints

from nomos_kernel import K0ProfileError
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef, _K0ReadObjectDomainPort

from .author_contract_v1 import C0LawError

if TYPE_CHECKING:
    from .graph_contracts_v1 import C0GraphObjectKind


@dataclass(frozen=True)
class C0ReadObjectDomainPorts:
    name: str
    kind: C0GraphObjectKind
    wrapper: type
    members_field: str
    record: type
    identity_field: str
    fields: tuple[tuple[str, str], ...]

    def __post_init__(self):
        wrapper_fields = get_type_hints(self.wrapper)
        record_fields = get_type_hints(self.record)
        state_fields = get_type_hints(self.kind.k0_kind.state_type)
        declared = {
            field.name: field.value for field in getattr(self.record, "__nomos_fields__", ())
        }
        state_declared = {
            field.name: field.value
            for field in getattr(self.kind.k0_kind.state_type, "__nomos_fields__", ())
        }
        member_specs = {
            field.name: field.value for field in getattr(self.wrapper, "__nomos_fields__", ())
        }
        members = wrapper_fields.get(self.members_field)
        specification = member_specs.get(self.members_field)
        if (
            type(self.name) is not str
            or not self.name.isidentifier()
            or set(wrapper_fields) != {self.members_field}
            or get_origin(members) is not tuple
            or get_args(members) != (self.record, Ellipsis)
            or record_fields.get(self.identity_field) is not _K0IndividualRef
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
            or set(declared) != set(record_fields)
            or specification is None
            or specification.maximum < self.kind.k0_kind.max_instances
            or any(
                source not in state_fields
                or record_fields[field] != state_fields[source]
                or declared[field] != state_declared.get(source)
                for field, source in self.fields
            )
        ):
            raise C0LawError("read Object domain lacks an exact nominal projection")

    def port(self):
        return _K0ReadObjectDomainPort(self.name, self.kind.symbol)

    def project(self, views):
        entries = []
        for view in views:
            if view.participant != self.name:
                continue
            if (
                type(view.individual_ref) is not _K0IndividualRef
                or view.actor_ref is not None
                or view.individual_ref.family != self.kind.symbol
                or type(view.view) is not self.kind.k0_kind.state_type
            ):
                raise K0ProfileError("read Object domain lost its actual nominal instance")
            entry = self.record(
                **{
                    self.identity_field: view.individual_ref,
                    **{field: getattr(view.view, source) for field, source in self.fields},
                }
            )
            entry.validate_for_k0()
            entries.append(entry)
        result = self.wrapper(**{self.members_field: tuple(entries)})
        result.validate_for_k0()
        return result


@dataclass(frozen=True)
class C0WorldReadObjectDomainIR:
    name: str
    kind: str
    wrapper: str
    members_field: str
    record: str
    identity_field: str
    fields: tuple[tuple[str, str], ...]


def check_read_object_domains(domains, reserved):
    if (
        type(domains) is not tuple
        or any(type(domain) is not C0ReadObjectDomainPorts for domain in domains)
        or len({domain.name for domain in domains}) != len(domains)
        or len({domain.kind.symbol for domain in domains}) != len(domains)
        or any(domain.name in reserved for domain in domains)
    ):
        raise C0LawError("due read Object domains alias a root or nominal kind")
    for domain in domains:
        domain.__post_init__()
