"""Carrier-free checked world declarations; addresses belong to the backend."""

from __future__ import annotations

from dataclasses import dataclass

from .actor_domain_v1 import C0WorldActorDomainIR, C0WorldReadActorDomainIR
from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0CheckedValueIR
from .nominal_signatures_v1 import C0NominalSignatures
from .object_domain_v1 import C0WorldReadObjectDomainIR
from .semantic_ir_v0 import C0PeriodicFormationIR


@dataclass(frozen=True)
class C0WorldOccurrenceIR:
    symbol: str
    classification: str
    kind: str


@dataclass(frozen=True)
class C0WorldSelectionIR:
    root: str
    selector: str
    payload_field: str
    state: str
    write: bool
    nullable: bool
    primary_kind: str | None
    kinds: tuple[str, ...]
    members: tuple[tuple[str, str], ...]
    identity_field: str | None


@dataclass(frozen=True)
class C0WorldScheduleIR:
    due: str
    one_shot_field: str
    marker_output: str
    subject_output: str
    delay_output: str


@dataclass(frozen=True)
class C0WorldActionIR:
    payload: str
    envelope: str
    actor_identity_field: str | None
    payload_actor_field: str
    envelope_fields: tuple[tuple[str, str], ...]
    sealed_fields: tuple[tuple[str, object], ...] | None
    selected: tuple[C0WorldSelectionIR, ...]
    target_mode: bool
    schedule: C0WorldScheduleIR | None
    form: tuple[str, str] | None
    self_kind: str | None = None


@dataclass(frozen=True)
class C0WorldTransitionIR:
    symbol: str
    occurrence: str
    kind: str
    body: C0CheckedValueIR
    owners: tuple[tuple[str, str], ...]
    effects: tuple[tuple[str, str, str], ...]
    action: C0WorldActionIR | None = None
    predecessor: str | None = None
    edge: str | None = None
    actor_identity_field: str | None = None
    fixed_individuals: tuple[tuple[str, str], ...] = ()
    actor_product: tuple[str, str, bool] | None = None
    actor_domains: tuple[C0WorldActorDomainIR, ...] = ()
    actor_reads: tuple[C0WorldReadActorDomainIR, ...] = ()
    object_product: tuple[str, str] | None = None
    object_reads: tuple[C0WorldReadObjectDomainIR, ...] = ()

    @property
    def formation(self) -> str:
        return {
            "action": "submit",
            "scene_event": "after_occurrence",
            "actor_event": "after_occurrence",
            "due": "due",
        }[self.kind]


@dataclass(frozen=True)
class C0WorldTemporalIR:
    mechanism: str
    dues: tuple[str, ...]
    order: tuple[str, ...]
    max_pending: int
    periodic: tuple[C0PeriodicFormationIR, ...]
    scheduled: tuple[str, ...]
    advance_seats: tuple[str, ...]


@dataclass(frozen=True)
class C0WorldIR:
    signatures: C0NominalSignatures
    occurrences: tuple[C0WorldOccurrenceIR, ...]
    transitions: tuple[C0WorldTransitionIR, ...]
    selected_kinds: tuple[str, ...]
    temporal: C0WorldTemporalIR | None
    selected_actor_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.signatures) is not C0NominalSignatures
            or type(self.occurrences) is not tuple
            or not self.occurrences
            or any(type(item) is not C0WorldOccurrenceIR for item in self.occurrences)
            or len({item.symbol for item in self.occurrences}) != len(self.occurrences)
            or any(
                item.kind not in ("action", "scene_event", "actor_event", "due")
                for item in self.occurrences
            )
            or type(self.transitions) is not tuple
            or any(type(item) is not C0WorldTransitionIR for item in self.transitions)
            or any(
                item.kind not in ("action", "scene_event", "actor_event", "due")
                for item in self.transitions
            )
            or len({(item.formation, item.symbol) for item in self.transitions})
            != len(self.transitions)
            or type(self.selected_kinds) is not tuple
            or len(set(self.selected_kinds)) != len(self.selected_kinds)
            or not set(self.selected_kinds)
            <= {item.symbol for item in self.signatures.object_kinds}
            or type(self.selected_actor_kinds) is not tuple
            or len(set(self.selected_actor_kinds)) != len(self.selected_actor_kinds)
            or not set(self.selected_actor_kinds)
            <= {item.symbol for item in self.signatures.actor_kinds}
        ):
            raise C0LawError("world IR has missing or aliased declarations")
        occurrences = {item.symbol: item for item in self.occurrences}
        for item in self.transitions:
            if (
                type(item.body) is not C0CheckedValueIR
                or item.body.signatures is not self.signatures
                or item.occurrence not in occurrences
                or item.kind != occurrences[item.occurrence].kind
                or (item.action is not None) != (item.kind == "action")
                or (item.predecessor is not None) != (item.kind in ("scene_event", "actor_event"))
                or (item.edge is not None) != (item.predecessor is not None)
                or (item.predecessor is not None and item.predecessor not in occurrences)
                or item.predecessor == item.occurrence
                or (item.kind != "due" and item.fixed_individuals)
            ):
                raise C0LawError("world transition differs from its formation declaration")
            if item.actor_product is not None and (
                type(item.actor_product) is not tuple
                or len(item.actor_product) != 3
                or item.actor_product[0] not in self.selected_actor_kinds
                or type(item.actor_product[1]) is not str
                or type(item.actor_product[2]) is not bool
            ):
                raise C0LawError("world Actor product lacks a selected nominal kind")
            if item.object_product is not None and (
                item.kind not in ("scene_event", "actor_event")
                or type(item.object_product) is not tuple
                or len(item.object_product) != 2
                or item.object_product[0] not in self.selected_kinds
                or type(item.object_product[1]) is not str
                or not item.object_product[1]
            ):
                raise C0LawError("world Object product lacks a selected required causal output")
            if (
                type(item.actor_domains) is not tuple
                or (item.actor_domains and item.kind not in ("due", "action"))
                or any(
                    type(domain) is not C0WorldActorDomainIR
                    or domain.kind not in self.selected_actor_kinds
                    or domain.value.signatures is not self.signatures
                    for domain in item.actor_domains
                )
                or len({domain.name for domain in item.actor_domains}) != len(item.actor_domains)
                or len({domain.kind for domain in item.actor_domains}) != len(item.actor_domains)
            ):
                raise C0LawError("world Actor domains are not an exact selected finite domain")
            if (
                item.action is not None
                and item.action.self_kind is not None
                and (
                    item.action.self_kind not in self.selected_actor_kinds
                    or item.action.actor_identity_field is not None
                    or any(root == "actor" for root, _ in item.owners)
                )
            ):
                raise C0LawError("world self Action lacks an exact selected Actor kind")
            if (
                type(item.actor_reads) is not tuple
                or (item.actor_reads and item.kind not in ("actor_event", "scene_event"))
                or any(
                    type(domain) is not C0WorldReadActorDomainIR
                    or domain.kind not in self.selected_actor_kinds
                    for domain in item.actor_reads
                )
                or len({domain.name for domain in item.actor_reads}) != len(item.actor_reads)
                or len({domain.kind for domain in item.actor_reads}) != len(item.actor_reads)
            ):
                raise C0LawError("world read Actor domains lack an exact selected kind")
            if (
                type(item.object_reads) is not tuple
                or (item.object_reads and item.kind != "due")
                or any(
                    type(domain) is not C0WorldReadObjectDomainIR
                    or domain.kind not in self.selected_kinds
                    for domain in item.object_reads
                )
                or len({domain.name for domain in item.object_reads}) != len(item.object_reads)
                or len({domain.kind for domain in item.object_reads}) != len(item.object_reads)
            ):
                raise C0LawError("world read Object domains lack an exact selected due kind")
        if {item.occurrence for item in self.transitions} != set(occurrences):
            raise C0LawError("world occurrence lacks its checked transition")
        edges = [item.edge for item in self.transitions if item.edge is not None]
        if len(set(edges)) != len(edges):
            raise C0LawError("world causal edges alias")
        dues = {item.symbol for item in self.transitions if item.kind == "due"}
        if (dues and self.temporal is None) or (
            self.temporal is not None
            and (
                type(self.temporal) is not C0WorldTemporalIR
                or set(self.temporal.dues) != dues
                or (not dues and self.temporal.mechanism != "action_value_event_jump")
            )
        ):
            raise C0LawError("world due formation lacks its temporal declaration")
