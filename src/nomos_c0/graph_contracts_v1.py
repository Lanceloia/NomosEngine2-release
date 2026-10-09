"""Graph declaration contracts shared by frontend and backend."""

from __future__ import annotations

from dataclasses import dataclass, field

from nomos_kernel._dynamic_owner_abi import (
    _K0DynamicOwnerKind,
)
from nomos_kernel._owner_abi import (
    _K0Owner,
)

from .author_document_v1 import C0SourceContext
from .candidate_input_v1 import C0CandidateInputPorts
from .checked_value_binding_v1 import C0ValueBackend
from .composable_action_v1 import (
    C0ValueActionPorts,
)
from .direct_actor_event_v1 import (
    C0DirectActorPorts,
)
from .direct_scene_event_v1 import (
    C0DirectScenePorts,
)
from .nominal_types_v1 import (
    ObjectSortRef,
)
from .opening_construction_v1 import C0OpeningConstructionPort
from .pure_definition_v1 import C0PureDefinition
from .scheduled_scene_event_v1 import (
    C0ScheduledScenePorts,
)
from .seat_offer_preview_v0 import C0SeatOfferPreviewPorts
from .seat_offers_v0 import (
    C0FiniteOfferProvider,
)
from .seat_read_projection_v0 import C0SeatReadPorts


@dataclass(frozen=True)
class C0GraphOwner:
    symbol: str
    owner: _K0Owner
    identity_field: str | None
    seat_readable_paths: frozenset[str]


@dataclass(frozen=True)
class C0GraphObjectKind:
    symbol: str
    sort: ObjectSortRef
    state_record: str
    k0_kind: _K0DynamicOwnerKind
    specializes: tuple[ObjectSortRef, ...] = ()


@dataclass(frozen=True)
class C0GraphActorKind:
    symbol: str
    state_record: str
    version: str
    max_instances: int
    factory: object
    seat_readable_paths: frozenset[str]


@dataclass(frozen=True)
class C0GraphAction:
    symbol: str
    actor: str
    ports: C0ValueActionPorts


@dataclass(frozen=True)
class C0GraphEvent:
    symbol: str
    ports: C0DirectScenePorts | C0DirectActorPorts
    effects: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class C0GraphOperation:
    symbol: str
    receiver: ObjectSortRef
    template: str
    implementations: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class C0GraphLibrary:
    owners: tuple[C0GraphOwner, ...]
    actions: tuple[C0GraphAction, ...]
    events: tuple[C0GraphEvent, ...]
    offer_provider: C0FiniteOfferProvider
    due_events: tuple[C0GraphDue, ...] = ()
    owner_templates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    lawdefs: tuple[str, ...] = ()
    object_kinds: tuple[C0GraphObjectKind, ...] = ()
    operations: tuple[C0GraphOperation, ...] = ()
    seat_read_ports: tuple[C0SeatReadPorts, ...] = ()
    seat_offer_preview_ports: tuple[C0SeatOfferPreviewPorts, ...] = ()
    pure_definitions: tuple[C0PureDefinition, ...] = ()
    appraisal_definitions: tuple[str, ...] = field(default=(), kw_only=True)
    actor_kinds: tuple[C0GraphActorKind, ...] = field(default=(), kw_only=True)
    candidate_inputs: tuple[C0CandidateInputPorts, ...] = field(default=(), kw_only=True)
    opening_constructions: tuple[C0OpeningConstructionPort, ...] = field(default=(), kw_only=True)
    value_backend: C0ValueBackend = field(kw_only=True)
    lib_context: C0SourceContext | None = None
    ports_context: C0SourceContext | None = None


@dataclass(frozen=True)
class C0GraphDue:
    symbol: str
    ports: C0ScheduledScenePorts
    effects: tuple[tuple[str, str, str], ...]
