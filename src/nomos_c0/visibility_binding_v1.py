"""Mechanically bind checked seat declarations; never re-enter the frontend."""

from __future__ import annotations

import keyword
from dataclasses import dataclass
from typing import get_args, get_type_hints

from nomos_kernel import K0OccurrenceRef
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .candidate_input_v1 import C0CandidateCheck, check_candidate_input
from .checked_value_binding_v1 import C0ValueBackend
from .composable_value_v1 import (
    _assignable,
    _complete_value_fields,
    _field_type,
    _nonnull,
    _tuple_item,
)
from .expression_ir_v1 import C0Expression
from .expression_read_authority_v1 import check_expression_reads
from .private_actor_binding_v1 import (
    bind_private_bindings,
    capture_private_bindings,
    check_entry_private_bindings,
    check_private_bindings,
)
from .seat_offer_preview_v0 import C0SeatOfferPreview, C0SeatOfferPreviewPorts
from .seat_offers_v0 import (
    C0ActorOfferRange,
    C0FixedParticipantOfferDeclaration,
    C0LocalValueOfferRange,
    C0ObjectOfferDeclaration,
    C0ObjectOfferRange,
    C0OfferDeclaration,
    C0OfferRangeDeclaration,
    C0ParticipantOfferDeclaration,
    _local_value_read_paths,
    _public_ports,
)
from .seat_read_projection_v0 import C0SeatReadPorts, C0SeatReadProjection
from .value_symbols_v1 import _ValueSymbolTranslation
from .visibility_ir_v1 import (
    OFFER_FIELDS,
    C0ActorOfferRangeIR,
    C0CandidateCheckIR,
    C0LocalValueOfferRangeIR,
    C0ObjectOfferRangeIR,
    C0OfferIR,
    C0PreviewTargetIR,
    C0SeatPresentation,
    C0SeatProjectionIR,
    C0VisibilityIR,
    C0VisibilitySeatIR,
)
from .world_binding_v1 import C0BoundWorld
from .world_ir_v1 import C0WorldIR

_OFFER_TYPES = {
    "fixed": C0OfferDeclaration,
    "range": C0OfferRangeDeclaration,
    "object": C0ObjectOfferDeclaration,
    "participant": C0ParticipantOfferDeclaration,
    "fixed_participant": C0FixedParticipantOfferDeclaration,
}


def _translate_actor_range(value, translation, *, binding):
    if value is None:
        return None
    source = C0ActorOfferRangeIR if binding else C0ActorOfferRange
    target = C0ActorOfferRange if binding else C0ActorOfferRangeIR
    if type(value) is not source:
        raise C0LawError("visibility Actor range has an unsupported checked shape")
    return target(
        value.name,
        value.alias,
        value.identity_field,
        translation.tree(value.collection),
        value.domain,
        value.family,
    )


def _translate_object_ranges(value, *, binding):
    source = C0ObjectOfferRangeIR if binding else C0ObjectOfferRange
    target = C0ObjectOfferRange if binding else C0ObjectOfferRangeIR
    if type(value) is not tuple or any(type(item) is not source for item in value):
        raise C0LawError("visibility Object ranges have an unsupported checked shape")
    return tuple(
        target(item.name, item.payload_field, item.kinds, item.read_paths, item.singleton)
        for item in value
    )


def _translate_local_range(value, translation, *, binding):
    if value is None:
        return None
    source = C0LocalValueOfferRangeIR if binding else C0LocalValueOfferRange
    target = C0LocalValueOfferRange if binding else C0LocalValueOfferRangeIR
    if type(value) is not source:
        raise C0LawError("visibility local value range has an unsupported checked shape")
    return target(value.alias, translation.tree(value.collection))


@dataclass(frozen=True)
class _Seat:
    symbol: str
    actor: str
    entries: tuple[str, ...]
    read_paths: tuple[str, ...]
    offers: tuple[
        C0OfferDeclaration
        | C0OfferRangeDeclaration
        | C0ObjectOfferDeclaration
        | C0ParticipantOfferDeclaration
        | C0FixedParticipantOfferDeclaration,
        ...,
    ]
    offer_limit: int
    presentation: C0SeatPresentation | None = None
    derived_read: C0SeatReadProjection | None = None
    offer_previews: tuple[C0SeatOfferPreview, ...] = ()
    candidate_checks: tuple[tuple[int, C0CandidateCheck], ...] = ()


@dataclass(frozen=True)
class C0BoundVisibility:
    ir: C0VisibilityIR
    seats: tuple[_Seat, ...]


def capture_visibility(
    backend: C0ValueBackend,
    world: C0WorldIR,
    seats: tuple[_Seat, ...],
) -> C0VisibilityIR:
    if backend.layout.signatures is not world.signatures or backend.owner_layout is None:
        raise C0LawError("visibility capture needs the world's generated layout")
    translation = _ValueSymbolTranslation(dict(backend.layout.records), binding=False)

    def offer_ir(offer):
        kind = next(
            (name for name, carrier in _OFFER_TYPES.items() if type(offer) is carrier), None
        )
        if kind is None:
            raise C0LawError("visibility capture lacks a checked candidate shape")
        return C0OfferIR(
            kind,
            offer.entry,
            tuple(
                (
                    name,
                    translation.symbolize_type(getattr(offer, name))
                    if name == "item_type"
                    else _translate_actor_range(getattr(offer, name), translation, binding=False)
                    if name == "actor_range"
                    else _translate_local_range(getattr(offer, name), translation, binding=False)
                    if name == "local_range"
                    else _translate_object_ranges(getattr(offer, name), binding=False)
                    if name == "objects" and kind == "participant"
                    else capture_private_bindings(getattr(offer, name), backend)
                    if name == "private_actor_fields"
                    else translation.tree(getattr(offer, name)),
                )
                for name in OFFER_FIELDS[kind]
            ),
            translation.ports(offer.ports),
        )

    def projection_ir(projection):
        port = projection.ports
        preview = (
            None
            if type(projection) is C0SeatReadProjection
            else C0PreviewTargetIR(
                projection.entry,
                port.action_template,
                port.candidate_origin_field,
                port.offer_payload_key,
            )
        )
        return C0SeatProjectionIR(
            port.symbol,
            port.scene_owner,
            port.actor,
            port.collection_field,
            port.current_field,
            translation.symbolize_type(port.candidate_type),
            port.candidate_key,
            port.object_root,
            port.object_kind,
            port.max_candidates,
            backend.capture(projection.value),
            preview,
        )

    return C0VisibilityIR(
        world,
        tuple(
            C0VisibilitySeatIR(
                seat.symbol,
                seat.actor,
                seat.entries,
                seat.read_paths,
                tuple(offer_ir(offer) for offer in seat.offers),
                seat.offer_limit,
                seat.presentation,
                None if seat.derived_read is None else projection_ir(seat.derived_read),
                tuple(projection_ir(preview) for preview in seat.offer_previews),
                tuple(
                    C0CandidateCheckIR(
                        index, check.input_symbol, check.entry, backend.capture(check.value)
                    )
                    for index, check in seat.candidate_checks
                ),
            )
            for seat in seats
        ),
    )


def _check_offer(offer, seat, world):
    action = dict(world.actions)[offer.entry]
    declarations = {item.symbol: item for item in world.ir.signatures.owners}
    transition = next(item for item in world.ir.transitions if item.symbol == offer.entry)
    scene = dict(transition.owners)["scene"]
    actor = declarations[seat.actor]
    public = _public_ports(
        action.ports,
        (*seat.read_paths, *(f"{seat.actor}.{path}" for path in actor.seat_readable_paths)),
        scene,
        seat.actor,
    )
    roots = {"scene": action.scene_owner.state_type, "actor": action.actor_owner.state_type}
    paths = set(public.readable_paths)
    if type(offer) is C0ObjectOfferDeclaration:
        if action.ports.target is None or offer.kinds != tuple(
            kind.family for kind in action.ports.target.kinds
        ):
            raise C0LawError("visibility Object domain differs from its Action")
        roots.update(target=action.ports.target.state_type, individual=_K0IndividualRef)
        paths.add("individual")
        paths.update(_object_read_grant(offer, "target", action.value._ports))
    elif type(offer) is C0ParticipantOfferDeclaration:
        actor_range = offer.actor_range
        object_ports = tuple(p for p in action.ports.participants if p.selector == "individual")
        if (
            type(offer.objects) is not tuple
            or type(offer.max_candidates) is not int
            or offer.max_candidates < 1
            or len(offer.objects) != len(object_ports)
            or any(type(role) is not C0ObjectOfferRange for role in offer.objects)
            or tuple(role.name for role in offer.objects) != tuple(p.name for p in object_ports)
            or type(offer.labels) is not tuple
            or not 1 <= len(offer.labels) <= 32
            or any(
                type(label) is not C0Expression
                or label.result_type is not str
                or label.stage != "admission"
                for label in offer.labels
            )
        ):
            raise C0LawError("visibility participant roles or labels differ from their Action")
        resolved = {}
        for role, port in zip(offer.objects, object_ports, strict=True):
            if (
                type(role) is not C0ObjectOfferRange
                or role.payload_field != port.payload_field
                or type(role.kinds) is not tuple
                or role.kinds != tuple(k.family for k in port.kinds)
                or type(role.singleton) is not bool
                or (role.singleton and (len(port.kinds) != 1 or port.kind.max_instances != 1))
                or type(role.read_paths) is not tuple
                or any(type(path) is not str for path in role.read_paths)
                or len(set(role.read_paths)) != len(role.read_paths)
                or any(
                    not path.startswith(role.name + ".")
                    or path not in action.value._ports.readable_paths
                    for path in role.read_paths
                )
                or {path for path in offer.ports.readable_paths if path.startswith(role.name + ".")}
                != set(role.read_paths)
                or role.name in roots
                or role.name + "_ref" in roots
            ):
                raise C0LawError(
                    "visibility Object role crosses its declared read authority/domain"
                )
            roots[role.name] = port.state_type
            roots[role.name + "_ref"] = _K0IndividualRef
            paths.update(role.read_paths)
            paths.add(role.name + "_ref")
            resolved[role.payload_field] = ("ref", role.name + "_ref")
        actor_ports = tuple(
            p for p in action.ports.participants if p.selector in ("closed_domain", "actor")
        )
        private = offer.private_actor_fields
        check_private_bindings(private, action.ports)
        private_fields = {binding.payload_field for binding in private}
        if actor_range is not None and any(
            p.name == actor_range.name and p.payload_field in private_fields for p in actor_ports
        ):
            raise C0LawError("visibility private Actor cannot also have a public range")
        if actor_range is not None:
            if type(actor_range) is not C0ActorOfferRange:
                raise C0LawError("visibility participant Actor range is malformed")
            actor_range.__post_init__()
            selected = next((p for p in actor_ports if p.name == actor_range.name), None)
            candidate = offer.ports.roots.get(actor_range.alias)
            if (
                selected is None
                or actor_range.alias in roots
                or actor_range.domain != tuple(name for name, _ in selected.members)
                or actor_range.family
                != (selected.actor_kind.family if selected.selector == "actor" else None)
                or (
                    selected.selector == "closed_domain"
                    and actor_range.identity_field != selected.identity_field
                )
                or candidate is None
                or get_args(actor_range.collection.value_type.annotation) != (candidate, Ellipsis)
                or get_type_hints(candidate).get(actor_range.identity_field)
                is not (_K0ActorRef if selected.selector == "actor" else str)
            ):
                raise C0LawError("visibility participant lacks its selected local Actor range")
            roots[actor_range.alias] = candidate
            paths.update(_local_value_read_paths(actor_range.alias, candidate))
            resolved[selected.payload_field] = (
                "ref",
                actor_range.alias + "." + actor_range.identity_field,
            )
        for port in actor_ports:
            if actor_range is not None and port.name == actor_range.name:
                continue
            if port.selector == "actor" or len(port.members) != 1:
                raise C0LawError("visibility fixed Actor domain differs from its Action")
            if port.payload_field not in private_fields:
                resolved[port.payload_field] = ("const", port.members[0][0])
        hints = get_type_hints(action.payload_type)
        if set(offer.payload) != set(hints) - {
            action.payload_actor_field,
            *private_fields,
        } or any(
            type(expression) is not C0Expression
            or not _assignable(expression.result_type, hints[name])
            or (
                hints[name] not in (str, int, bool, _K0IndividualRef, _K0ActorRef, K0OccurrenceRef)
                and not (
                    hints[name] == str | None
                    and any(p.payload_field == name and p.nullable for p in actor_ports)
                )
            )
            or (
                hints[name] is _K0ActorRef
                and name not in {p.payload_field for p in actor_ports if p.selector == "actor"}
            )
            for name, expression in offer.payload.items()
        ):
            raise C0LawError("visibility participant public/private payload partition is invalid")
        for field, expected in resolved.items():
            expression = offer.payload.get(field)
            if (
                type(expression) is not C0Expression
                or (expression.operation, expression.operand) != expected
            ):
                raise C0LawError("visibility participant payload differs from its resolved value")
        local = offer.local_range
        if local is not None:
            reserved = (
                set(roots)
                | {"occurrence", "payload", "initiator"}
                | {p.name for p in action.ports.participants}
                | {p.name + "_ref" for p in action.ports.participants}
            )
            if (
                type(local) is not C0LocalValueOfferRange
                or type(local.alias) is not str
                or not local.alias.isidentifier()
                or keyword.iskeyword(local.alias)
                or local.alias in reserved
                or type(local.collection) is not C0Expression
                or local.collection.operation != "ref"
            ):
                raise C0LawError("visibility local value range aliases a participant or root")
            check_expression_reads(local.collection, public, frozenset(public.roots))
            root, *parts = local.collection.operand.split(".")
            carrier = public.roots[root]
            for part in parts:
                carrier = _field_type(_nonnull(carrier) or carrier, part, public)
            if local.collection.result_type != carrier:
                raise C0LawError("visibility local collection type differs from its checked read")
            item_type = _tuple_item(local.collection.result_type)
            roots[local.alias] = item_type
            paths.update(_local_value_read_paths(local.alias, item_type))
        if not offer.objects and actor_range is None and local is None:
            raise C0LawError("visibility participant offer has no finite range")
    elif type(offer) is C0FixedParticipantOfferDeclaration:
        participants = action.ports.participants
        objects = tuple(p for p in participants if p.selector == "individual")
        actors = tuple(p for p in participants if p.selector == "closed_domain")
        if (
            not participants
            or len(objects) + len(actors) != len(participants)
            or any(len(p.kinds) != 1 or p.kinds[0].max_instances != 1 for p in objects)
            or any(len(p.members) != 1 for p in actors)
            or len({p.kinds[0].family for p in objects}) != len(objects)
            or len({p.members[0][0] for p in actors}) != len(actors)
        ):
            raise C0LawError("visibility fixed participants need nonempty singleton domains")
        expected_objects = tuple(
            (item.payload_field, item.kinds[0].family)
            for item in action.ports.participants
            if item.selector == "individual" and len(item.kinds) == 1
        )
        expected_actors = tuple(
            (item.payload_field, item.members[0][0])
            for item in action.ports.participants
            if item.selector == "closed_domain" and len(item.members) == 1
        )
        if offer.object_fields != expected_objects or offer.actor_fields != expected_actors:
            raise C0LawError("visibility fixed participants differ from their Action")
        hints = get_type_hints(action.payload_type)
        selected_fields = {
            action.payload_actor_field,
            *(name for name, _ in expected_objects),
            *(name for name, _ in expected_actors),
        }
        if set(offer.payload) != set(hints) - selected_fields or any(
            type(expression) is not C0Expression
            or expression.result_type is not hints[name]
            or hints[name] not in (str, int, bool, K0OccurrenceRef)
            for name, expression in offer.payload.items()
        ):
            raise C0LawError("visibility fixed participant payload differs from its Action")
    fields = {carrier: set(names) for carrier, names in public.readable_fields.items()}
    if type(offer) is C0ParticipantOfferDeclaration and offer.actor_range is not None:
        for carrier, names in _complete_value_fields(roots[offer.actor_range.alias]).items():
            fields.setdefault(carrier, set()).update(names)
    if type(offer) is C0ParticipantOfferDeclaration and offer.local_range is not None:
        for carrier, names in _complete_value_fields(roots[offer.local_range.alias]).items():
            fields.setdefault(carrier, set()).update(names)
    for path in paths - set(public.readable_paths):
        root, *parts = path.split(".")
        carrier = roots[root]
        for part in parts:
            fields.setdefault(carrier, set()).add(part)
            annotation = get_type_hints(carrier)[part]
            carrier = _nonnull(annotation) or annotation
    if (
        offer.ports.roots != roots
        or not offer.ports.readable_paths <= paths
        or offer.ports.admission_readable_paths != offer.ports.readable_paths
        or offer.ports.admission_readable_fields != offer.ports.readable_fields
        or any(
            not names <= fields.get(carrier, set())
            for carrier, names in offer.ports.readable_fields.items()
        )
        or (hasattr(offer, "max_candidates") and offer.max_candidates != seat.offer_limit)
    ):
        raise C0LawError("visibility offer crosses its declared read/domain authority")
    if type(offer) is C0ParticipantOfferDeclaration:
        if offer.actor_range is not None:
            check_expression_reads(
                offer.actor_range.collection,
                public,
                frozenset(public.roots),
            )
        for expression in (
            offer.visible_when,
            offer.condition,
            *offer.labels,
            *offer.payload.values(),
        ):
            check_expression_reads(expression, offer.ports, frozenset(roots))


def _object_read_grant(offer, root, action_ports):
    """A projection preserves its own explicit grant, not all world inputs."""
    declared = offer.object_read_paths
    if (
        type(declared) is not tuple
        or any(type(path) is not str for path in declared)
        or len(set(declared)) != len(declared)
        or any(
            not path.startswith(root + ".") or path not in action_ports.readable_paths
            for path in declared
        )
        or {path for path in offer.ports.readable_paths if path.startswith(root + ".")}
        != set(declared)
    ):
        raise C0LawError("visibility Object projection crosses its declared read authority")
    return declared


def _bind_projection(ir, backend, world, translation):
    owners = {item.symbol: item.owner for item in world.layout.owners.owners}
    kinds = {item.symbol: item for item in world.layout.owners.object_kinds}
    candidate = translation.bind_type(ir.candidate).annotation
    value = backend.bind(ir.body)
    ports = value._ports
    actor_fields = get_type_hints(owners[ir.actor].state_type)
    candidate_fields = get_type_hints(candidate)
    if (
        ports.roots
        != {
            "scene": owners[ir.scene].state_type,
            "actor": owners[ir.actor].state_type,
            "candidate": candidate,
            ir.object_root: kinds[ir.object_kind].k0_kind.state_type,
        }
        or ports.writable_fields
        or ports.record_types
        or value._admission_outputs != frozenset(ports.outputs)
        or any(carrier not in (str, int, bool) for carrier in ports.outputs.values())
        or actor_fields.get(ir.current_field) is not str
        or get_args(actor_fields.get(ir.collection_field)) != (candidate, Ellipsis)
        or candidate_fields.get(ir.candidate_key) is not str
        or (
            ir.preview is not None
            and candidate_fields.get(ir.preview.candidate_origin_field) is not str
        )
    ):
        raise C0LawError("visibility projection crosses its checked nominal/read-only port")
    common = dict(
        symbol=ir.symbol,
        scene_owner=ir.scene,
        actor=ir.actor,
        collection_field=ir.collection_field,
        current_field=ir.current_field,
        candidate_type=candidate,
        candidate_key=ir.candidate_key,
        object_root=ir.object_root,
        object_kind=ir.object_kind,
        value_ports=ports,
        max_candidates=ir.max_candidates,
    )
    if ir.preview is None:
        return C0SeatReadProjection(C0SeatReadPorts(**common), value)
    return C0SeatOfferPreview(
        ir.preview.entry,
        C0SeatOfferPreviewPorts(
            **common,
            action_template=ir.preview.action_template,
            candidate_origin_field=ir.preview.candidate_origin_field,
            offer_payload_key=ir.preview.offer_payload_key,
        ),
        value,
    )


def bind_visibility(ir: C0VisibilityIR, world: C0BoundWorld) -> C0BoundVisibility:
    if (
        type(ir) is not C0VisibilityIR
        or type(world) is not C0BoundWorld
        or ir.world is not world.ir
    ):
        raise C0LawError("visibility binding needs the exact selected world")
    ir.__post_init__()
    world.layout.check(ir.world)
    backend = C0ValueBackend(world.layout.owners.record_layout, world.layout.owners)
    translation = _ValueSymbolTranslation(dict(backend.layout.records), binding=True)
    seats = []
    for seat in ir.seats:
        offers = []
        for offer in seat.offers:
            parameters = {
                name: translation.bind_type(item).annotation
                if name == "item_type"
                else _translate_actor_range(item, translation, binding=True)
                if name == "actor_range"
                else _translate_local_range(item, translation, binding=True)
                if name == "local_range"
                else _translate_object_ranges(item, binding=True)
                if name == "objects" and offer.kind == "participant"
                else bind_private_bindings(item, backend)
                if name == "private_actor_fields"
                else translation.tree(item)
                for name, item in offer.parameters
            }
            bound = _OFFER_TYPES[offer.kind](
                entry=offer.entry,
                ports=translation.ports(offer.ports),
                **parameters,
            )
            _check_offer(bound, seat, world)
            offers.append(bound)
        check_entry_private_bindings(offers)
        seats.append(
            _Seat(
                seat.symbol,
                seat.actor,
                seat.entries,
                seat.read_paths,
                tuple(offers),
                seat.offer_limit,
                seat.presentation,
                None
                if seat.derived_read is None
                else _bind_projection(seat.derived_read, backend, world, translation),
                tuple(
                    _bind_projection(item, backend, world, translation) for item in seat.previews
                ),
                tuple(
                    _bind_candidate_check(item, backend, world) for item in seat.candidate_checks
                ),
            )
        )
    return C0BoundVisibility(ir, tuple(seats))


def _bind_candidate_check(ir, backend, world):
    action = dict(world.actions)[ir.entry].ports
    value = backend.bind(ir.body)
    check_candidate_input(action, value._ports)
    if (
        value._admission_outputs != frozenset({"allowed"})
        or value._tree["bindings"]
        or value.effects
        or set(value._tree["outputs"]) != {"allowed"}
        or value._tree["outputs"]["allowed"].result_type is not bool
    ):
        raise C0LawError("candidate input must remain a single admission-time boolean")
    check_expression_reads(
        (value.guard_ir.expression, value._tree["outputs"]["allowed"]),
        value._ports,
        frozenset(value._ports.roots),
    )
    return ir.index, C0CandidateCheck(ir.input_symbol, ir.entry, value)
