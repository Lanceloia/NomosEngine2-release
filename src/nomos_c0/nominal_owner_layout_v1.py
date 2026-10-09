"""Generate static and dynamic owner bindings from carrier-free declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import reduce
from operator import or_
from types import MappingProxyType
from typing import TYPE_CHECKING, get_type_hints

from nomos_kernel import K0OwnerKey, K0ProfileError
from nomos_kernel._dynamic_owner_abi import _K0DynamicOwnerKind
from nomos_kernel._owner_abi import _K0CapabilityRef

from .author_contract_v1 import C0LawError
from .generated_record_v1 import make_nominal_record, seal_nominal_record
from .nominal_signatures_v1 import C0NominalSignatures
from .nominal_types_v1 import ObjectSortRef, SemanticIdentity

if TYPE_CHECKING:
    from .declarative_nominal_v0 import C0NominalRecordLayout
    from .graph_contracts_v1 import C0GraphObjectKind, C0GraphOwner


@dataclass(frozen=True, init=False)
class C0NominalOwnerLayout:
    signatures: C0NominalSignatures
    record_layout: C0NominalRecordLayout
    owners: tuple[C0GraphOwner, ...]
    object_kinds: tuple[C0GraphObjectKind, ...]
    actor_kinds: tuple[object, ...]
    contribution_type: type
    _keys: tuple[tuple[str, K0OwnerKey], ...]
    _contribution_validator: Callable[[object], None]
    _kind_validators: tuple[Callable[[object], None], ...]
    _actor_validators: tuple[Callable[[object], None], ...]

    def __init__(self, *args, **kwargs) -> None:
        raise C0LawError("owner layouts must be generated from checked signatures")

    def owner(self, symbol: str) -> C0GraphOwner:
        for item in self.owners:
            if item.symbol == symbol:
                return item
        raise C0LawError("owner layout symbol is not declared")

    def check(self, signatures: C0NominalSignatures) -> None:
        from .declarative_nominal_v0 import _DeclaredDynamicOwnerFactory, _DeclaredOwner

        if signatures is not self.signatures:
            raise C0LawError("owner layout does not implement the selected signatures")
        self.record_layout.check(signatures)
        keys = dict(self._keys)
        if (
            tuple(item.symbol for item in self.owners)
            != tuple(item.symbol for item in signatures.owners)
            or len(keys) != len(self._keys)
            or set(keys) != {item.symbol for item in signatures.owners}
            or len(set(keys.values())) != len(keys)
            or getattr(self.contribution_type, "validate_for_k0", None)
            is not self._contribution_validator
            or get_type_hints(self.contribution_type)
            != {
                "owner": K0OwnerKey,
                "state": reduce(
                    or_,
                    dict.fromkeys(
                        self.record_layout.record(item.state) for item in signatures.owners
                    ),
                ),
            }
        ):
            raise C0LawError("generated owner layout or contribution contract was replaced")
        for item, declared in zip(self.owners, signatures.owners, strict=True):
            owner = item.owner
            state = self.record_layout.record(declared.state)
            if (
                type(owner) is not _DeclaredOwner
                or owner.key != keys[declared.symbol]
                or owner.owner_version != declared.version
                or owner.state_type is not state
                or owner.view_type is not state
                or owner.contribution_type is not self.contribution_type
                or owner.local_identity_families
                or item.identity_field != declared.identity_field
                or item.seat_readable_paths != declared.seat_readable_paths
                or declared.write != "replace_one"
            ):
                raise C0LawError("generated owner differs from its semantic declaration")
        if tuple(item.symbol for item in self.object_kinds) != tuple(
            item.symbol for item in signatures.object_kinds
        ) or len(self._kind_validators) != len(self.object_kinds):
            raise C0LawError("generated Object kinds differ from their declarations")
        for item, declared, validator in zip(
            self.object_kinds, signatures.object_kinds, self._kind_validators, strict=True
        ):
            kind = item.k0_kind
            factory = kind.factory
            state = self.record_layout.record(declared.state)
            if (
                item.sort.identity.value != declared.sort
                or item.state_record != declared.state
                or tuple(parent.identity.value for parent in item.specializes)
                != declared.specializes
                or type(kind) is not _K0DynamicOwnerKind
                or kind.family != declared.symbol
                or kind.max_instances != declared.max_instances
                or kind.state_type is not state
                or type(factory) is not _DeclaredDynamicOwnerFactory
                or factory.state_type is not state
                or factory.owner_version != declared.version
                or factory.capability_ref != _object_capability(declared.symbol, declared.version)
                or getattr(factory.contribution_type, "validate_for_k0", None) is not validator
                or get_type_hints(factory.contribution_type)
                != {"owner": K0OwnerKey, "state": state}
            ):
                raise C0LawError("generated Object factory or contribution contract was replaced")
        if len(self.actor_kinds) != len(signatures.actor_kinds) or len(
            self._actor_validators
        ) != len(self.actor_kinds):
            raise C0LawError("generated Actor kinds differ from their declarations")
        for item, declared, validator in zip(
            self.actor_kinds, signatures.actor_kinds, self._actor_validators, strict=True
        ):
            state = self.record_layout.record(declared.state)
            if (
                item.symbol != declared.symbol
                or item.state_record != declared.state
                or item.version != declared.version
                or item.max_instances != declared.max_instances
                or item.seat_readable_paths != declared.seat_readable_paths
                or type(item.factory) is not _DeclaredDynamicOwnerFactory
                or item.factory.state_type is not state
                or item.factory.owner_version != declared.version
                or getattr(item.factory.contribution_type, "validate_for_k0", None) is not validator
                or get_type_hints(item.factory.contribution_type)
                != {"owner": K0OwnerKey, "state": state}
                or item.factory.capability_ref
                != _K0CapabilityRef(
                    f"c0.actor_owner.{declared.symbol}.{declared.version.rsplit(':', 1)[-1]}"
                )
            ):
                raise C0LawError("generated Actor factory differs from its semantic declaration")


def _object_capability(symbol: str, version: str) -> _K0CapabilityRef:
    return _K0CapabilityRef(f"c0.object_owner.{symbol}.{version.rsplit(':', 1)[-1]}")


def bind_nominal_owners(
    signatures: C0NominalSignatures,
    record_layout: C0NominalRecordLayout,
    owner_keys: Mapping[str, K0OwnerKey],
) -> C0NominalOwnerLayout:
    from .declarative_nominal_v0 import (
        C0NominalRecordLayout,
        _DeclaredDynamicOwnerFactory,
        _DeclaredOwner,
        _object_contribution_type,
    )
    from .graph_contracts_v1 import C0GraphActorKind, C0GraphObjectKind, C0GraphOwner

    if type(record_layout) is not C0NominalRecordLayout:
        raise C0LawError("owner binding requires a generated record layout")
    record_layout.check(signatures)
    if (
        not signatures.owners
        or not isinstance(owner_keys, Mapping)
        or set(owner_keys) != {item.symbol for item in signatures.owners}
        or any(type(key) is not K0OwnerKey for key in owner_keys.values())
        or len(set(owner_keys.values())) != len(owner_keys)
        or any(item.write != "replace_one" for item in signatures.owners)
    ):
        raise C0LawError("owner layout keys are missing, aliased or unqualified")
    keys = dict(owner_keys)
    owner_types = MappingProxyType(
        {keys[item.symbol]: record_layout.record(item.state) for item in signatures.owners}
    )

    def validate_contribution(value: object) -> None:
        if type(value.owner) is not K0OwnerKey or type(value.state) is not owner_types.get(
            value.owner
        ):
            raise K0ProfileError("declared contribution has a foreign owner or state")
        value.state.validate_for_k0()

    contribution = seal_nominal_record(
        make_nominal_record(
            "DeclaredContribution",
            [("owner", K0OwnerKey), ("state", reduce(or_, dict.fromkeys(owner_types.values())))],
            namespace={"validate_for_k0": validate_contribution},
        )
    )
    owners = tuple(
        C0GraphOwner(
            item.symbol,
            _DeclaredOwner(
                keys[item.symbol],
                item.version,
                record_layout.record(item.state),
                record_layout.record(item.state),
                contribution,
            ),
            item.identity_field,
            item.seat_readable_paths,
        )
        for item in signatures.owners
    )
    kinds = []
    validators = []
    for item in signatures.object_kinds:
        state = record_layout.record(item.state)
        kind_contribution = _object_contribution_type(state)
        factory = _DeclaredDynamicOwnerFactory(
            _object_capability(item.symbol, item.version),
            item.version,
            state,
            kind_contribution,
        )
        kinds.append(
            C0GraphObjectKind(
                item.symbol,
                ObjectSortRef(SemanticIdentity(item.sort)),
                item.state,
                _K0DynamicOwnerKind(item.symbol, item.max_instances, state, factory),
                tuple(ObjectSortRef(SemanticIdentity(parent)) for parent in item.specializes),
            )
        )
        validators.append(kind_contribution.validate_for_k0)
    actors = tuple(
        C0GraphActorKind(
            item.symbol,
            item.state,
            item.version,
            item.max_instances,
            _DeclaredDynamicOwnerFactory(
                _K0CapabilityRef(f"c0.actor_owner.{item.symbol}.{item.version.rsplit(':', 1)[-1]}"),
                item.version,
                record_layout.record(item.state),
                _object_contribution_type(record_layout.record(item.state)),
            ),
            item.seat_readable_paths,
        )
        for item in signatures.actor_kinds
    )
    layout = object.__new__(C0NominalOwnerLayout)
    for name, value in (
        ("signatures", signatures),
        ("record_layout", record_layout),
        ("owners", owners),
        ("object_kinds", tuple(kinds)),
        ("actor_kinds", actors),
        ("contribution_type", contribution),
        ("_keys", tuple(keys.items())),
        ("_contribution_validator", validate_contribution),
        ("_kind_validators", tuple(validators)),
        (
            "_actor_validators",
            tuple(item.factory.contribution_type.validate_for_k0 for item in actors),
        ),
    ):
        object.__setattr__(layout, name, value)
    layout.check(signatures)
    return layout
