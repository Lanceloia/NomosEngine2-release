"""Bind checked world symbols to generated owners and existing private K0 adapters."""

from __future__ import annotations

from dataclasses import dataclass

from nomos_kernel import K0CausalLawKey, K0EventTypeKey, K0OccurrenceFamily, K0SourceSpecKey

from .actor_domain_v1 import (
    C0ActorDomainEffect,
    C0ActorDomainPorts,
    C0ReadActorDomainPorts,
    C0WorldActorDomainIR,
    C0WorldReadActorDomainIR,
)
from .actor_product_v1 import C0ActorProductIR
from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0NamedWorldValueIR, C0ValueBackend
from .composable_action_v1 import (
    C0ActionFormPorts,
    C0ActionParticipantPorts,
    C0ActionSchedulePorts,
    C0ActionTargetPorts,
    C0SelfActorPorts,
    C0ValueActionParticipants,
    C0ValueActionPorts,
    C0ValueActionProgram,
    _checked_bindings,
    _selection_ports,
    _static_actor_owners,
)
from .direct_actor_event_v1 import (
    C0DirectActorEnvelope,
    C0DirectActorParticipants,
    C0DirectActorPorts,
    C0DirectActorProgram,
)
from .direct_scene_event_v1 import (
    C0DirectSceneEnvelope,
    C0DirectSceneParticipants,
    C0DirectScenePorts,
    C0DirectSceneProgram,
)
from .nominal_owner_layout_v1 import C0NominalOwnerLayout
from .object_domain_v1 import C0ReadObjectDomainPorts, C0WorldReadObjectDomainIR
from .object_product_v1 import C0ObjectProductIR
from .scheduled_scene_event_v1 import (
    C0DueEnvelope,
    C0DueParticipants,
    C0DueValue,
    C0ScheduledScenePorts,
    C0ScheduledSceneProgram,
    C0TimeValue,
)
from .semantic_ir_v0 import (
    C0ActionLawIR,
    C0CausalEdgeIR,
    C0DueLawIR,
    C0FixedIndividualIR,
    C0FormationKind,
    C0ObjectFormationEffectIR,
    C0OccurrenceContractIR,
    C0ScheduleEffectIR,
    C0SelectedOwnerIR,
    C0StaticOwnerIR,
    C0TemporalProgramIR,
    C0TransitionIR,
)
from .temporal_lowering_v0 import C0LoweredTemporal, lower_temporal_program
from .world_ir_v1 import (
    C0WorldActionIR,
    C0WorldIR,
    C0WorldOccurrenceIR,
    C0WorldScheduleIR,
    C0WorldSelectionIR,
    C0WorldTemporalIR,
    C0WorldTransitionIR,
)


@dataclass(frozen=True)
class C0WorldLayout:
    world: C0WorldIR
    owners: C0NominalOwnerLayout
    sources: tuple[tuple[str, K0SourceSpecKey], ...]
    classifications: tuple[tuple[str, K0EventTypeKey], ...]
    causal_keys: tuple[tuple[str, K0CausalLawKey], ...]

    def check(self, world: C0WorldIR) -> None:
        if world is not self.world or type(self.owners) is not C0NominalOwnerLayout:
            raise C0LawError("world layout does not implement the selected checked world")
        self.owners.check(world.signatures)
        for rows, expected, carrier in (
            (self.sources, {item.symbol for item in world.occurrences}, K0SourceSpecKey),
            (
                self.classifications,
                {item.classification for item in world.occurrences},
                K0EventTypeKey,
            ),
            (
                self.causal_keys,
                {item.edge for item in world.transitions if item.edge is not None},
                K0CausalLawKey,
            ),
        ):
            if (
                type(rows) is not tuple
                or any(
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or type(item[1]) is not carrier
                    for item in rows
                )
                or len({name for name, _ in rows}) != len(rows)
                or {name for name, _ in rows} != expected
                or len({key for _, key in rows}) != len(rows)
            ):
                raise C0LawError("world layout keys are missing, aliased or unqualified")


@dataclass(frozen=True)
class C0BoundWorld:
    ir: C0WorldIR
    layout: C0WorldLayout
    actions: tuple[tuple[str, C0ValueActionProgram], ...]
    events: tuple[tuple[str, C0DirectSceneProgram | C0DirectActorProgram], ...]
    dues: tuple[tuple[str, C0ScheduledSceneProgram], ...]
    temporal_ir: C0TemporalProgramIR | None
    temporal_binding: C0LoweredTemporal | None


def capture_world(
    backend: C0ValueBackend,
    actions: tuple[tuple[str, C0ValueActionProgram], ...],
    events: tuple[tuple[str, C0DirectSceneProgram | C0DirectActorProgram], ...],
    dues: tuple[tuple[str, C0ScheduledSceneProgram], ...],
    selected_kinds: tuple[str, ...],
    temporal: C0TemporalProgramIR | None,
    values: tuple[C0NamedWorldValueIR, ...],
    selected_actor_kinds: tuple[str, ...] = (),
) -> tuple[C0WorldIR, C0WorldLayout]:
    """Convert checked frontend artifacts once; no native profile is captured."""
    owner_layout = backend.owner_layout
    if owner_layout is None:
        raise C0LawError("world capture needs generated nominal owner bindings")
    owner_layout.check(backend.layout.signatures)
    records = {carrier: symbol for symbol, carrier in backend.layout.records}
    owners = {item.owner.key.value: item for item in owner_layout.owners}
    kinds = {item.symbol: item for item in owner_layout.object_kinds}
    checked_values = {(item.formation, item.symbol): item.body for item in values}
    entries = (*actions, *events, *dues)
    if len(checked_values) != len(entries):
        raise C0LawError("world capture lacks its exact checked values")

    def record(carrier):
        if carrier not in records:
            raise C0LawError("world carrier has no nominal record declaration")
        return records[carrier]

    def owner(key, carrier):
        declared = owners.get(key)
        if declared is None or declared.owner.state_type is not carrier:
            raise C0LawError("world owner differs from the generated nominal layout")
        return declared.symbol

    source_symbols = {}
    classification_symbols = {}
    causal_keys = []
    occurrence_contracts = {}
    occurrences = []
    entry_sources = {}
    for name, program in entries:
        kind = {
            C0ValueActionProgram: "action",
            C0DirectSceneProgram: "scene_event",
            C0DirectActorProgram: "actor_event",
            C0ScheduledSceneProgram: "due",
        }.get(type(program))
        if kind is None:
            raise C0LawError("world capture contains a foreign transition implementation")
        contract = program.occurrence_contract
        source = source_symbols.get(contract.source_key)
        if source is None:
            source = f"{program.ir.formation.value}.{name}"
            source_symbols[contract.source_key] = source
            classification = classification_symbols.setdefault(
                contract.event_type, f"classification.{source}"
            )
            occurrences.append(C0WorldOccurrenceIR(source, classification, kind))
            occurrence_contracts[contract.source_key] = contract
        elif contract != occurrence_contracts[contract.source_key]:
            raise C0LawError("shared world source has incompatible occurrence contracts")
        entry_sources[program.ir.formation.value, name] = source
    transitions = []
    for name, program in entries:
        ir, ports = program.ir, program.ports
        action = None
        fixed = ()
        predecessor = edge = actor_identity = None
        if type(program) is C0ValueActionProgram:
            selections = tuple(
                C0WorldSelectionIR(
                    port.name,
                    port.selector,
                    port.payload_field,
                    record(port.state_type),
                    port.write,
                    port.nullable,
                    port.actor_kind.family
                    if port.actor_kind is not None
                    else None
                    if port.kind is None
                    else port.kind.family,
                    (port.actor_kind.family,)
                    if port.actor_kind is not None
                    else tuple(kind.family for kind in port.kinds),
                    tuple(
                        (member, owner(item.key.value, item.state_type))
                        for member, item in port.members
                    ),
                    port.identity_field,
                )
                for port in _selection_ports(ports.target, ports.participants)
            )
            form = ir.form
            if form is not None and (
                form.family not in kinds
                or form.state_type is not kinds[form.family].k0_kind.state_type
            ):
                raise C0LawError("world formation differs from its declared Object kind")
            schedule = ir.schedule
            action = C0WorldActionIR(
                record(ports.payload_type),
                record(ports.envelope_type),
                ports.actor_identity_field,
                ports.payload_actor_field,
                ir.envelope_fields,
                None
                if ports.sealed_envelope_fields is None
                else tuple(ports.sealed_envelope_fields.items()),
                selections,
                ir.target_mode,
                None
                if schedule is None
                else C0WorldScheduleIR(
                    source_symbols[schedule.due_source],
                    schedule.one_shot_field,
                    schedule.marker_output,
                    schedule.subject_output,
                    schedule.delay_output,
                ),
                None if form is None else (form.family, form.initial_output),
                None if ir.self_actor is None else ir.self_actor[0],
            )
            kind = "action"
        elif type(program) in (C0DirectSceneProgram, C0DirectActorProgram):
            contract = program.edge.predecessor
            if contract != occurrence_contracts.get(contract.source_key):
                raise C0LawError("world causal predecessor is not the exact selected occurrence")
            predecessor = source_symbols[contract.source_key]
            edge = f"after_occurrence.{name}"
            causal_keys.append((edge, K0CausalLawKey(program.edge.causal_key)))
            kind = "scene_event" if type(program) is C0DirectSceneProgram else "actor_event"
            if kind == "actor_event":
                actor_identity = ports.actor_identity_field
        else:
            kind = "due"
            fixed = tuple((item.root, item.family) for item in ir.fixed_individuals)
            for item in ir.fixed_individuals:
                if (
                    item.family not in kinds
                    or item.state_type is not kinds[item.family].k0_kind.state_type
                ):
                    raise C0LawError("world fixed individual differs from its declared Object kind")
        body = checked_values.get((ir.formation.value, name))
        if body is None or body.signatures is not backend.layout.signatures:
            raise C0LawError("world capture has a foreign checked value")
        if ir.object_product is not None and (
            ir.object_product.family not in kinds
            or ir.object_product.state_type
            is not kinds[ir.object_product.family].k0_kind.state_type
        ):
            raise C0LawError("world causal product differs from its declared Object kind")
        transitions.append(
            C0WorldTransitionIR(
                name,
                entry_sources[ir.formation.value, name],
                kind,
                body,
                tuple((item.root, owner(item.key, item.state_type)) for item in ir.owners),
                ir.effects,
                action,
                predecessor,
                edge,
                actor_identity,
                fixed,
                None
                if ir.actor_product is None
                else (
                    ir.actor_product.family,
                    ir.actor_product.initial_output,
                    ir.actor_product.required,
                ),
                tuple(
                    C0WorldActorDomainIR(
                        domain.ports.name,
                        domain.ports.kind.symbol,
                        backend.capture(domain.value),
                        domain.effects,
                    )
                    for domain in (ir.actor_domains if kind in ("due", "action") else ())
                ),
                tuple(
                    C0WorldReadActorDomainIR(
                        domain.name,
                        domain.kind.symbol,
                        record(domain.wrapper),
                        domain.members_field,
                        record(domain.record),
                        domain.identity_field,
                        domain.fields,
                    )
                    for domain in (
                        ports.read_actor_domains if kind in ("actor_event", "scene_event") else ()
                    )
                ),
                None
                if ir.object_product is None
                else (
                    ir.object_product.family,
                    ir.object_product.initial_output,
                ),
                tuple(
                    C0WorldReadObjectDomainIR(
                        domain.name,
                        domain.kind.symbol,
                        record(domain.wrapper),
                        domain.members_field,
                        record(domain.record),
                        domain.identity_field,
                        domain.fields,
                    )
                    for domain in (ports.read_object_domains if kind == "due" else ())
                ),
            )
        )
    if temporal is not None:
        temporal.check()
    world = C0WorldIR(
        backend.layout.signatures,
        tuple(occurrences),
        tuple(transitions),
        selected_kinds,
        None
        if temporal is None
        else C0WorldTemporalIR(
            temporal.mechanism,
            tuple(name for name, _ in temporal.due_laws),
            temporal.order,
            temporal.max_pending,
            temporal.periodic,
            tuple(source_symbols[source] for source in temporal.scheduled_sources),
            temporal.advance_seats,
        ),
        selected_actor_kinds,
    )
    layout = C0WorldLayout(
        world,
        owner_layout,
        tuple((symbol, K0SourceSpecKey(key)) for key, symbol in source_symbols.items()),
        tuple((symbol, K0EventTypeKey(key)) for key, symbol in classification_symbols.items()),
        tuple(causal_keys),
    )
    layout.check(world)
    return world, layout


def bind_world(world: C0WorldIR, layout: C0WorldLayout) -> C0BoundWorld:
    """Realize a checked world without author text or frontend type inference."""
    if type(world) is not C0WorldIR or type(layout) is not C0WorldLayout:
        raise C0LawError("world binding requires checked IR and a generated layout")
    layout.check(world)
    backend = C0ValueBackend(layout.owners.record_layout, layout.owners)
    sources, classifications, edge_keys = map(
        dict, (layout.sources, layout.classifications, layout.causal_keys)
    )
    occurrences = {item.symbol: item for item in world.occurrences}
    owners = {item.symbol: item.owner for item in layout.owners.owners}
    kinds = {item.symbol: item.k0_kind for item in layout.owners.object_kinds}
    graph_kinds = {item.symbol: item for item in layout.owners.object_kinds}

    def selected_kind(name):
        if name not in world.selected_kinds or name not in kinds:
            raise C0LawError("world participant or formation references an unselected Object kind")
        return kinds[name]

    def record(name):
        return layout.owners.record_layout.record(name)

    def contract(symbol):
        item = occurrences[symbol]
        if item.kind == "action":
            declaration = next(entry for entry in world.transitions if entry.occurrence == symbol)
            envelope, participants = record(declaration.action.envelope), C0ValueActionParticipants
        else:
            envelope, participants = {
                "scene_event": (C0DirectSceneEnvelope, C0DirectSceneParticipants),
                "actor_event": (C0DirectActorEnvelope, C0DirectActorParticipants),
                "due": (C0DueEnvelope, C0DueParticipants),
            }[item.kind]
        return C0OccurrenceContractIR(
            sources[symbol].value,
            classifications[item.classification].value,
            K0OccurrenceFamily.ACTION if item.kind == "action" else K0OccurrenceFamily.EVENT,
            envelope,
            participants,
        )

    actions, events, dues = [], [], []
    bound_values = iter(
        backend.bind_many(
            tuple(
                value
                for item in world.transitions
                for value in (item.body, *(domain.value for domain in item.actor_domains))
            )
        )
    )
    for item in world.transitions:
        value = next(bound_values)
        source, event_type = (
            sources[item.occurrence],
            classifications[occurrences[item.occurrence].classification],
        )
        try:
            static = tuple((root, owners[symbol]) for root, symbol in item.owners)
        except KeyError as error:
            raise C0LawError("world transition references an undeclared owner") from error
        owner_ir = tuple(
            C0StaticOwnerIR(root, owner.key.value, owner.state_type) for root, owner in static
        )
        roots = dict(static)
        product = None
        object_product = None
        if item.object_product is not None:
            family, output = item.object_product
            kind = selected_kind(family)
            object_product = C0ObjectProductIR(family, kind.state_type, output)
        if item.actor_product is not None:
            family, output, required = item.actor_product
            kind = next((kind for kind in layout.owners.actor_kinds if kind.symbol == family), None)
            if kind is None or family not in world.selected_actor_kinds:
                raise C0LawError("world Actor product has no selected generated kind")
            product = C0ActorProductIR(family, kind.factory.state_type, output, required)
        actor_kinds = {kind.symbol: kind for kind in layout.owners.actor_kinds}
        domains = []
        for declaration in item.actor_domains:
            kind = actor_kinds.get(declaration.kind)
            if kind is None or declaration.kind not in world.selected_actor_kinds:
                raise C0LawError("world Actor domain has no selected nominal kind")
            domain_value = next(bound_values)
            domains.append(
                C0ActorDomainEffect(
                    C0ActorDomainPorts(
                        declaration.name, kind, domain_value._ports, declaration.effects
                    ),
                    domain_value,
                    declaration.effects,
                )
            )
        if item.kind == "action":
            declaration = item.action
            self_actor = None
            if declaration.self_kind is not None:
                kind = next(
                    (
                        kind
                        for kind in layout.owners.actor_kinds
                        if kind.symbol == declaration.self_kind
                    ),
                    None,
                )
                if kind is None or kind.symbol not in world.selected_actor_kinds:
                    raise C0LawError("world self Action has no selected Actor kind")
                self_actor = C0SelfActorPorts(kind.symbol, kind.factory.state_type, kind.factory)
                roots["actor"] = self_actor
            selections = []
            for selected in declaration.selected:
                actor_kind = None
                if selected.selector == "individual":
                    primary = selected_kind(selected.primary_kind)
                    accepted = tuple(selected_kind(name) for name in selected.kinds)
                    members = ()
                    if selected.members or any(
                        kind.state_type is not record(selected.state)
                        for kind in (primary, *accepted)
                    ):
                        raise C0LawError(
                            "world individual selection crosses its nominal declaration"
                        )
                elif selected.selector == "actor":
                    kind = next(
                        (
                            kind
                            for kind in layout.owners.actor_kinds
                            if kind.symbol == selected.primary_kind
                        ),
                        None,
                    )
                    if (
                        kind is None
                        or kind.symbol not in world.selected_actor_kinds
                        or selected.kinds != (kind.symbol,)
                        or kind.factory.state_type is not record(selected.state)
                        or selected.members
                        or selected.identity_field is not None
                    ):
                        raise C0LawError("world Actor selection crosses its nominal declaration")
                    primary, accepted, members = None, (), ()
                    actor_kind = C0SelfActorPorts(
                        kind.symbol, kind.factory.state_type, kind.factory
                    )
                elif selected.selector == "closed_domain":
                    primary, accepted = None, ()
                    try:
                        members = tuple((name, owners[symbol]) for name, symbol in selected.members)
                    except KeyError as error:
                        raise C0LawError(
                            "world closed participant references an undeclared owner"
                        ) from error
                    if (
                        selected.primary_kind is not None
                        or selected.kinds
                        or any(
                            owner.state_type is not record(selected.state) for _, owner in members
                        )
                    ):
                        raise C0LawError("world closed selection crosses its nominal declaration")
                else:
                    raise C0LawError("world selection has an unknown selector")
                selections.append(
                    C0ActionParticipantPorts(
                        selected.root,
                        selected.selector,
                        selected.payload_field,
                        record(selected.state),
                        selected.write,
                        selected.nullable,
                        primary,
                        accepted,
                        members,
                        selected.identity_field,
                        actor_kind,
                    )
                )
            target = None
            if declaration.target_mode:
                if len(selections) != 1 or selections[0].name != "target":
                    raise C0LawError("world target mode lacks its exact selection")
                selected = selections.pop()
                target = C0ActionTargetPorts(
                    selected.payload_field,
                    selected.state_type,
                    selected.write,
                    selected.kind,
                    selected.kinds,
                )
            schedule = declaration.schedule
            if schedule is not None and occurrences.get(schedule.due, None) is not None:
                if occurrences[schedule.due].kind != "due":
                    raise C0LawError("world scheduling references a non-due occurrence")
            elif schedule is not None:
                raise C0LawError("world scheduling references an undeclared occurrence")
            form = declaration.form
            ports = C0ValueActionPorts(
                source,
                event_type,
                roots["scene"],
                roots["actor"],
                record(declaration.payload),
                layout.owners.contribution_type,
                record(declaration.envelope),
                value._ports,
                declaration.actor_identity_field,
                declaration.payload_actor_field,
                {
                    root: {
                        field: output
                        for selected_root, field, output in item.effects
                        if selected_root == root
                    }
                    for root in (
                        *roots,
                        *(selected.name for selected in selections),
                        *(("target",) if target else ()),
                    )
                },
                dict(declaration.envelope_fields),
                None if declaration.sealed_fields is None else dict(declaration.sealed_fields),
                None
                if schedule is None
                else C0ActionSchedulePorts(
                    sources[schedule.due],
                    schedule.one_shot_field,
                    schedule.subject_output,
                    schedule.delay_output,
                ),
                None
                if form is None
                else C0ActionFormPorts(form[0], selected_kind(form[0]).state_type, form[1]),
                target,
                tuple(selections),
                product,
                tuple(domain.ports for domain in domains),
            )
            _checked_bindings(ports)
            ir = C0ActionLawIR(
                source.value,
                event_type.value,
                value,
                item.effects,
                _static_actor_owners(ports),
                C0FormationKind.SUBMIT,
                declaration.envelope_fields,
                tuple(
                    C0SelectedOwnerIR(
                        selected.root,
                        selected.selector,
                        selected.payload_field,
                        record(selected.state),
                        selected.write,
                        selected.nullable,
                        selected.kinds,
                        tuple(
                            (name, owners[symbol].key.value) for name, symbol in selected.members
                        ),
                        selected.identity_field,
                    )
                    for selected in declaration.selected
                ),
                declaration.target_mode,
                None
                if schedule is None
                else C0ScheduleEffectIR(
                    sources[schedule.due].value,
                    schedule.one_shot_field,
                    schedule.marker_output,
                    schedule.subject_output,
                    schedule.delay_output,
                ),
                None
                if form is None
                else C0ObjectFormationEffectIR(form[0], selected_kind(form[0]).state_type, form[1]),
                actor_product=product,
                self_actor=None
                if self_actor is None
                else (self_actor.family, self_actor.state_type),
                actor_domains=tuple(domains),
            )
            actions.append((item.symbol, C0ValueActionProgram(ir, ports)))
        elif item.kind == "due":
            fixed = tuple(
                (root, name, selected_kind(name).state_type)
                for root, name in item.fixed_individuals
            )
            object_reads = tuple(
                C0ReadObjectDomainPorts(
                    domain.name,
                    graph_kinds[domain.kind],
                    record(domain.wrapper),
                    domain.members_field,
                    record(domain.record),
                    domain.identity_field,
                    domain.fields,
                )
                for domain in item.object_reads
            )
            if value._ports.roots != {
                **{root: owner.state_type for root, owner in static},
                **{root: state_type for root, _, state_type in fixed},
                "due": C0DueValue,
                "time": C0TimeValue,
                **{domain.name: domain.wrapper for domain in object_reads},
            }:
                raise C0LawError("world due roots cross their nominal declarations")
            ports = C0ScheduledScenePorts(
                source,
                event_type,
                roots["scene"],
                layout.owners.contribution_type,
                value._ports,
                tuple((root, owner) for root, owner in static if root != "scene"),
                fixed,
                product,
                tuple(domain.ports for domain in domains),
                object_reads,
            )
            ir = C0DueLawIR(
                source.value,
                event_type.value,
                value,
                item.effects,
                owner_ir,
                C0FormationKind.DUE,
                tuple(C0FixedIndividualIR(*selected) for selected in fixed),
                actor_product=product,
                actor_domains=tuple(domains),
                read_object_domains=object_reads,
            )
            dues.append((item.symbol, C0ScheduledSceneProgram(ports, ir)))
        else:
            edge = C0CausalEdgeIR(
                edge_keys[item.edge].value, contract(item.predecessor), source.value
            )
            ir = C0TransitionIR(
                source.value,
                event_type.value,
                value,
                item.effects,
                owner_ir,
                C0FormationKind.AFTER_OCCURRENCE,
                actor_product=product,
                object_product=object_product,
            )
            if item.kind == "scene_event":
                ports = C0DirectScenePorts(
                    source,
                    event_type,
                    edge_keys[item.edge],
                    roots["scene"],
                    layout.owners.contribution_type,
                    value._ports,
                    product,
                    tuple(
                        C0ReadActorDomainPorts(
                            domain.name,
                            actor_kinds[domain.kind],
                            record(domain.wrapper),
                            domain.members_field,
                            record(domain.record),
                            domain.identity_field,
                            domain.fields,
                        )
                        for domain in item.actor_reads
                    ),
                    object_product,
                )
                program = C0DirectSceneProgram(ports, ir, edge)
            else:
                actor_kinds = {kind.symbol: kind for kind in layout.owners.actor_kinds}
                ports = C0DirectActorPorts(
                    source,
                    event_type,
                    edge_keys[item.edge],
                    roots["scene"],
                    roots["actor"],
                    item.actor_identity_field,
                    layout.owners.contribution_type,
                    value._ports,
                    product,
                    tuple(
                        C0ReadActorDomainPorts(
                            domain.name,
                            actor_kinds[domain.kind],
                            record(domain.wrapper),
                            domain.members_field,
                            record(domain.record),
                            domain.identity_field,
                            domain.fields,
                        )
                        for domain in item.actor_reads
                    ),
                    object_product,
                )
                program = C0DirectActorProgram(ports, ir, edge)
            events.append((item.symbol, program))
    temporal = world.temporal
    temporal_ir = (
        None
        if temporal is None
        else C0TemporalProgramIR(
            temporal.mechanism,
            tuple((name, dict(dues)[name].ir) for name in temporal.dues),
            temporal.order,
            temporal.max_pending,
            temporal.periodic,
            tuple(sources[symbol].value for symbol in temporal.scheduled),
            temporal.advance_seats,
        )
    )
    temporal_binding = (
        None if temporal_ir is None else lower_temporal_program(temporal_ir, tuple(dues))
    )
    return C0BoundWorld(
        world, layout, tuple(actions), tuple(events), tuple(dues), temporal_ir, temporal_binding
    )
