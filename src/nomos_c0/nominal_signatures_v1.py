"""Carrier-free nominal declarations; realization is a separate backend obligation."""

from __future__ import annotations

from dataclasses import dataclass

from .author_contract_v1 import C0LawError
from .value_symbols_v1 import C0SymbolicPureDefinition, C0SymbolicValueProgram


@dataclass(frozen=True)
class C0NominalFieldType:
    kind: str
    record: str = ""
    item: C0NominalFieldType | None = None
    minimum: int = 0
    maximum: int = 0
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class C0NominalField:
    name: str
    value: C0NominalFieldType


@dataclass(frozen=True)
class C0VariantCase:
    name: str
    payload: C0NominalFieldType | None


@dataclass(frozen=True)
class C0RecordSignature:
    symbol: str
    fields: tuple[C0NominalField, ...]
    invariant: C0SymbolicValueProgram | None
    cases: tuple[C0VariantCase, ...] = ()

    def __post_init__(self) -> None:
        if not self.cases:
            return
        if (
            type(self.cases) is not tuple
            or not 2 <= len(self.cases) <= 32
            or any(type(item) is not C0VariantCase for item in self.cases)
        ):
            raise C0LawError("variant signature needs a finite case table")
        names = tuple(item.name for item in self.cases)
        declarations = {item.name: item.value for item in self.fields}
        if (
            len(set(names)) != len(names)
            or declarations.get("case") != C0NominalFieldType("enum", choices=names)
            or any(
                type(name) is not str
                or not name.isascii()
                or not name.isidentifier()
                or name.startswith("_")
                or name == "case"
                for name in names
            )
        ):
            raise C0LawError("variant discriminator does not match its signature")
        for item in self.cases:
            if item.payload is None:
                if item.name in declarations:
                    raise C0LawError("unit variant signature has a payload slot")
            elif (
                type(item.payload) is not C0NominalFieldType
                or item.payload.kind == "optional"
                or declarations.get(item.name) != C0NominalFieldType("optional", item=item.payload)
            ):
                raise C0LawError("variant payload signature does not match its lowered slot")

    @property
    def kind(self) -> str:
        return "variant" if self.cases else "record"


@dataclass(frozen=True)
class C0OwnerSignature:
    symbol: str
    version: str
    state: str
    identity_field: str | None
    seat_readable_paths: frozenset[str]
    write: str = "replace_one"


@dataclass(frozen=True)
class C0ObjectKindSignature:
    symbol: str
    sort: str
    state: str
    version: str
    max_instances: int
    specializes: tuple[str, ...]


@dataclass(frozen=True)
class C0ActorKindSignature:
    symbol: str
    state: str
    version: str
    max_instances: int
    seat_readable_paths: frozenset[str]


@dataclass(frozen=True)
class C0NominalSignatures:
    records: tuple[C0RecordSignature, ...]
    pure_definitions: tuple[C0SymbolicPureDefinition, ...]
    owners: tuple[C0OwnerSignature, ...] = ()
    object_kinds: tuple[C0ObjectKindSignature, ...] = ()
    actor_kinds: tuple[C0ActorKindSignature, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.records) is not tuple
            or not self.records
            or any(type(item) is not C0RecordSignature for item in self.records)
            or len({item.symbol for item in self.records}) != len(self.records)
            or type(self.pure_definitions) is not tuple
            or type(self.owners) is not tuple
            or any(type(item) is not C0OwnerSignature for item in self.owners)
            or len({item.symbol for item in self.owners}) != len(self.owners)
            or type(self.object_kinds) is not tuple
            or any(type(item) is not C0ObjectKindSignature for item in self.object_kinds)
            or len({item.symbol for item in self.object_kinds}) != len(self.object_kinds)
            or type(self.actor_kinds) is not tuple
            or any(type(item) is not C0ActorKindSignature for item in self.actor_kinds)
            or len({item.symbol for item in self.actor_kinds}) != len(self.actor_kinds)
            or {item.symbol for item in self.actor_kinds}
            & {item.symbol for item in self.object_kinds}
            or any(
                item.state not in {record.symbol for record in self.records}
                for item in (*self.owners, *self.object_kinds, *self.actor_kinds)
            )
        ):
            raise C0LawError("nominal signatures are missing or aliased")

    def record(self, symbol: str) -> C0RecordSignature:
        for item in self.records:
            if item.symbol == symbol:
                return item
        raise C0LawError("nominal signature is not declared")
