"""Checked seat visibility and presentation, independent of runtime layout."""

from __future__ import annotations

from dataclasses import dataclass

from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0CheckedValueIR
from .compile_budget_v1 import COMPILE_BUDGET
from .nominal_signatures_v1 import C0NominalFieldType, C0NominalSignatures
from .seat_read_projection_v0 import check_fixed_projection_roots
from .value_symbols_v1 import (
    C0SymbolicExpression,
    C0SymbolicType,
    C0SymbolicValuePorts,
    C0SymbolicValueProgram,
)
from .world_ir_v1 import C0WorldIR


@dataclass(frozen=True)
class C0SeatPresentation:
    title: str
    fields: tuple[tuple[str, str | None], ...]
    published: str
    rejected: str
    no_offers: str
    opening: str | None = None
    terms: tuple[tuple[str, str], ...] = ()
    projection_columns: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    finish_on_action: tuple[tuple[str, str, str], ...] = ()
    published_actions: tuple[tuple[str, str], ...] = ()
    rejected_actions: tuple[tuple[str, str], ...] = ()
    preview_fields: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    projection_focus: tuple[tuple[str, str], ...] = ()
    finish_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()
    published_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()


def presentation_scalar_kind(
    signatures: C0NominalSignatures, path: str, *, allow_optional: bool = True
) -> str | None:
    root, separator, tail = path.partition(".")
    owner = next((item for item in signatures.owners if item.symbol == root), None)
    if owner is None or not separator or not tail:
        return None
    records = {item.symbol: item for item in signatures.records}
    value = C0NominalFieldType("record", record=owner.state)
    for part in tail.split("."):
        while allow_optional and type(value) is C0NominalFieldType and value.kind == "optional":
            value = value.item
        if (
            type(value) is not C0NominalFieldType
            or value.kind != "record"
            or value.record not in records
        ):
            return None
        value = next(
            (item.value for item in records[value.record].fields if item.name == part), None
        )
        if value is None:
            return None
    while allow_optional and type(value) is C0NominalFieldType and value.kind == "optional":
        value = value.item
    if type(value) is not C0NominalFieldType:
        return None
    if value.kind in ("str", "enum"):
        return "str"
    return value.kind if value.kind in ("int", "bool") else None


# These are the five checked candidate shapes, not an arbitrary object serializer.
OFFER_FIELDS = {
    "fixed": ("label", "condition", "payload"),
    "range": (
        "label",
        "collection",
        "item_name",
        "label_value",
        "condition",
        "payload",
        "item_type",
        "max_candidates",
    ),
    "object": (
        "label",
        "kinds",
        "object_read_paths",
        "visible_when",
        "condition",
        "label_value",
        "payload",
        "max_candidates",
    ),
    "participant": (
        "objects",
        "actor_range",
        "labels",
        "visible_when",
        "condition",
        "payload",
        "max_candidates",
        "local_range",
        "private_actor_fields",
    ),
    "fixed_participant": ("label", "object_fields", "actor_fields", "condition", "payload"),
}


@dataclass(frozen=True)
class C0ActorOfferRangeIR:
    name: str
    alias: str
    identity_field: str
    collection: C0SymbolicExpression
    domain: tuple[str, ...]
    family: str | None = None


@dataclass(frozen=True)
class C0LocalValueOfferRangeIR:
    alias: str
    collection: C0SymbolicExpression


@dataclass(frozen=True)
class C0ObjectOfferRangeIR:
    name: str
    payload_field: str
    kinds: tuple[str, ...]
    read_paths: tuple[str, ...]
    singleton: bool


@dataclass(frozen=True)
class C0OfferIR:
    kind: str
    entry: str
    parameters: tuple[tuple[str, object], ...]
    ports: C0SymbolicValuePorts

    def __post_init__(self) -> None:
        if (
            self.kind not in OFFER_FIELDS
            or type(self.parameters) is not tuple
            or tuple(name for name, _ in self.parameters) != OFFER_FIELDS[self.kind]
            or type(self.ports) is not C0SymbolicValuePorts
        ):
            raise C0LawError("visibility offer has an unsupported checked shape")


@dataclass(frozen=True)
class C0PreviewTargetIR:
    entry: str
    action_template: str
    candidate_origin_field: str
    offer_payload_key: str


@dataclass(frozen=True)
class C0SeatProjectionIR:
    symbol: str
    scene: str
    actor: str
    collection_field: str
    current_field: str
    candidate: C0SymbolicType
    candidate_key: str
    object_root: str
    object_kind: str
    max_candidates: int
    body: C0CheckedValueIR
    preview: C0PreviewTargetIR | None = None
    fixed_actor_roots: tuple[tuple[str, str], ...] = ()
    additional_fixed_individual_roots: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class C0CandidateCheckIR:
    index: int
    input_symbol: str
    entry: str
    body: C0CheckedValueIR


@dataclass(frozen=True)
class C0VisibilitySeatIR:
    symbol: str
    actor: str
    entries: tuple[str, ...]
    read_paths: tuple[str, ...]
    offers: tuple[C0OfferIR, ...]
    offer_limit: int
    presentation: C0SeatPresentation | None = None
    derived_read: C0SeatProjectionIR | None = None
    previews: tuple[C0SeatProjectionIR, ...] = ()
    candidate_checks: tuple[C0CandidateCheckIR, ...] = ()


@dataclass(frozen=True)
class C0VisibilityIR:
    world: C0WorldIR
    seats: tuple[C0VisibilitySeatIR, ...]

    def __post_init__(self) -> None:
        if type(self.world) is not C0WorldIR or type(self.seats) is not tuple or not self.seats:
            raise C0LawError("visibility IR lacks its checked world/seats")
        owners = {item.symbol: item for item in self.world.signatures.owners}
        actions = {item.symbol: item for item in self.world.transitions if item.kind == "action"}
        if (
            any(type(seat) is not C0VisibilitySeatIR for seat in self.seats)
            or len({seat.symbol for seat in self.seats}) != len(self.seats)
            or len({seat.actor for seat in self.seats}) != len(self.seats)
        ):
            raise C0LawError("visibility seats alias")
        for seat in self.seats:
            actor = owners.get(seat.actor)
            if (
                actor is None
                or actor.identity_field is None
                or not seat.entries
                or len(set(seat.entries)) != len(seat.entries)
                or any(
                    entry not in actions or dict(actions[entry].owners).get("actor") != seat.actor
                    for entry in seat.entries
                )
                or len(set(seat.read_paths)) != len(seat.read_paths)
                or f"{seat.actor}.{actor.identity_field}" not in seat.read_paths
                or type(seat.offer_limit) is not int
                or not 1 <= seat.offer_limit <= COMPILE_BUDGET.finite_offers
                or not seat.offers
                or len(seat.offers) > seat.offer_limit
            ):
                raise C0LawError("visibility seat exceeds its Actor/entry authority")
            for path in seat.read_paths:
                root, separator, field = path.partition(".")
                owner = owners.get(root)
                if (
                    not separator
                    or owner is None
                    or (root != seat.actor and owner.identity_field is not None)
                    or field not in owner.seat_readable_paths
                ):
                    raise C0LawError("visibility read crosses its declared seat authority")
            for offer in seat.offers:
                if type(offer) is not C0OfferIR or offer.entry not in seat.entries:
                    raise C0LawError("visibility offer has a foreign entry")
                offer.__post_init__()
            if (
                type(seat.candidate_checks) is not tuple
                or any(
                    type(check) is not C0CandidateCheckIR
                    or type(check.index) is not int
                    or not 0 <= check.index < len(seat.offers)
                    or check.entry != seat.offers[check.index].entry
                    or type(check.input_symbol) is not str
                    or not check.input_symbol
                    or type(check.body) is not C0CheckedValueIR
                    or check.body.signatures is not self.world.signatures
                    for check in seat.candidate_checks
                )
                or len({check.index for check in seat.candidate_checks})
                != len(seat.candidate_checks)
            ):
                raise C0LawError("visibility candidate check has a foreign index or value port")
            projections = (
                () if seat.derived_read is None else (seat.derived_read,)
            ) + seat.previews
            for projection in projections:
                if (
                    type(projection) is not C0SeatProjectionIR
                    or projection.actor != seat.actor
                    or projection.scene not in owners
                    or owners[projection.scene].identity_field is not None
                    or projection.object_kind not in self.world.selected_kinds
                    or type(projection.body) is not C0CheckedValueIR
                    or projection.body.signatures is not self.world.signatures
                    or type(projection.body.value) is not C0SymbolicValueProgram
                    or type(projection.body.value.ports) is not C0SymbolicValuePorts
                    or type(projection.max_candidates) is not int
                    or not 1 <= projection.max_candidates <= 32
                    or (
                        projection.preview is not None
                        and projection.preview.entry not in seat.entries
                    )
                ):
                    raise C0LawError("visibility projection has a foreign owner/value port")
                check_fixed_projection_roots(
                    projection.object_root, projection.object_kind, projection.actor,
                    projection.fixed_actor_roots, projection.additional_fixed_individual_roots,
                    frozenset(symbol for symbol, owner in owners.items()
                              if owner.identity_field is not None),
                    frozenset(self.world.selected_kinds),
                )
                if projection.preview is not None and (
                    projection.fixed_actor_roots or projection.additional_fixed_individual_roots
                ):
                    raise C0LawError("visibility preview cannot bind seat read fixed roots")
                roots = projection.body.value.ports.roots
                names = {
                    "scene", "actor", "candidate", projection.object_root,
                    *(name for name, _ in projection.fixed_actor_roots),
                    *(name for name, _ in projection.additional_fixed_individual_roots),
                }
                if projection.preview is None:
                    names.update(
                        f"{name}_ref" for name in (
                            projection.object_root,
                            *(name for name, _ in projection.additional_fixed_individual_roots),
                        )
                    )
                if (
                    type(roots) is not tuple
                    or any(type(row) is not tuple or len(row) != 2
                           or type(row[0]) is not str for row in roots)
                    or len(roots) != len(names)
                    or {name for name, _ in roots} != names
                ):
                    raise C0LawError("visibility projection inputs alias or omit a fixed root")
            if (
                (seat.derived_read is not None and seat.derived_read.preview is not None)
                or any(item.preview is None for item in seat.previews)
                or len({item.preview.entry for item in seat.previews}) != len(seat.previews)
            ):
                raise C0LawError("visibility read/preview identities alias")
            presentation = seat.presentation
            preview_outputs = {
                item.preview.entry: dict(item.body.value.ports.outputs) for item in seat.previews
            }
            if presentation is not None and (
                type(presentation) is not C0SeatPresentation
                or {path for path, _ in presentation.fields}
                != set(seat.read_paths)
                | ({seat.derived_read.symbol} if seat.derived_read is not None else set())
                or any(entry not in seat.entries for entry, _, _ in presentation.finish_on_action)
                or any(
                    type(messages) is not tuple
                    or any(
                        type(item) is not tuple
                        or len(item) != 2
                        or type(item[0]) is not str
                        or item[0] not in seat.entries
                        or type(item[1]) is not str
                        or not 1 <= len(item[1]) <= 400
                        for item in messages
                    )
                    or len({entry for entry, _ in messages}) != len(messages)
                    for messages in (
                        presentation.published_actions, presentation.rejected_actions
                    )
                )
                or type(presentation.preview_fields) is not tuple
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or item[0] not in preview_outputs
                    or type(item[1]) is not tuple
                    or not item[1]
                    or any(
                        type(column) is not tuple
                        or len(column) != 2
                        or type(column[0]) is not str
                        or column[0] not in preview_outputs[item[0]]
                        or preview_outputs[item[0]][column[0]].kind != "builtin"
                        or preview_outputs[item[0]][column[0]].symbol not in ("str", "int", "bool")
                        or type(column[1]) is not str
                        or not 1 <= len(column[1]) <= 80
                        for column in item[1]
                    )
                    or len({name for name, _ in item[1]}) != len(item[1])
                    for item in presentation.preview_fields
                )
                or len({entry for entry, _ in presentation.preview_fields})
                != len(presentation.preview_fields)
                or type(presentation.projection_focus) is not tuple
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or type(item[1]) is not str
                    or seat.derived_read is None
                    or item[0] != seat.derived_read.symbol
                    or item[1] != f"{seat.actor}.{seat.derived_read.current_field}"
                    or item[1] not in seat.read_paths
                    or dict(presentation.fields).get(item[0]) is None
                    or dict(presentation.fields).get(item[1]) is None
                    or presentation_scalar_kind(
                        self.world.signatures, item[1], allow_optional=False
                    ) != "str"
                    for item in presentation.projection_focus
                )
                or len({name for name, _ in presentation.projection_focus})
                != len(presentation.projection_focus)
                or type(presentation.finish_fields) is not tuple
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or item[0] not in {entry for entry, _, _ in presentation.finish_on_action}
                    or type(item[1]) is not tuple
                    or not 1 <= len(item[1]) <= len(seat.read_paths)
                    or any(
                        type(path) is not str
                        or path not in seat.read_paths
                        or dict(presentation.fields).get(path) is None
                        or presentation_scalar_kind(self.world.signatures, path) is None
                        for path in item[1]
                    )
                    or len(set(item[1])) != len(item[1])
                    for item in presentation.finish_fields
                )
                or len({entry for entry, _ in presentation.finish_fields})
                != len(presentation.finish_fields)
                or type(presentation.published_fields) is not tuple
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or item[0] not in seat.entries
                    or type(item[1]) is not tuple
                    or not 1 <= len(item[1]) <= len(seat.read_paths)
                    or any(
                        type(path) is not str
                        or path not in seat.read_paths
                        or dict(presentation.fields).get(path) is None
                        or presentation_scalar_kind(self.world.signatures, path) is None
                        for path in item[1]
                    )
                    or len(set(item[1])) != len(item[1])
                    for item in presentation.published_fields
                )
                or len({entry for entry, _ in presentation.published_fields})
                != len(presentation.published_fields)
            ):
                raise C0LawError("visibility presentation labels foreign fields/entries")
