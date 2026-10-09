"""Compile an authored one-shot due Event against typed Scene/time ports."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import get_type_hints

from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryEvaluation,
    _K0InMemoryRuleInput,
    _K0InMemorySourceSpec,
)
from nomos_kernel._coordinates import _K0FixedTime
from nomos_kernel._dynamic_owner_abi import _K0FixedDueIndividualPort, _K0IndividualRef
from nomos_kernel._event_jump_abi import (
    _K0PendingDue,
    _K0PendingDueKey,
    _K0PeriodicDueKey,
)
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0Owner, _K0OwnerView
from nomos_kernel._rule_products_abi import K0RuleResult

from .actor_domain_v1 import C0ActorDomainEffect, C0ActorDomainPorts
from .actor_product_v1 import C0ActorProductIR, actor_products, product_outputs
from .author_contract_v1 import C0LawError
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueProgram,
    C0ValueStateError,
    _assignable,
    compile_value_program,
)
from .object_domain_v1 import C0ReadObjectDomainPorts, check_read_object_domains
from .semantic_ir_v0 import (
    C0DueLawIR,
    C0FixedIndividualIR,
    C0FormationKind,
    C0OccurrenceContractIR,
    C0StaticOwnerIR,
)


@dataclass(frozen=True)
class C0DueValue:
    subject: str
    formation: K0OccurrenceRef | None
    periodic_plan: str | None = None
    periodic_ordinal: int | None = None


@dataclass(frozen=True)
class C0TimeValue:
    ordinal: int


@dataclass(frozen=True)
class C0ScheduledSceneEvidence:
    scene: object
    due: C0DueValue
    time: C0TimeValue
    extra_views: tuple[tuple[str, object], ...] = ()
    actor_views: tuple[_K0OwnerView, ...] = ()
    object_views: tuple[_K0OwnerView, ...] = ()

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0ScheduledSceneEvidence
            or type(self.due) is not C0DueValue
            or type(self.due.subject) is not str
            or not self.due.subject
            or (self.due.formation is None)
            != (self.due.periodic_plan is not None and self.due.periodic_ordinal is not None)
            or (self.due.formation is not None and type(self.due.formation) is not K0OccurrenceRef)
            or (
                self.due.periodic_plan is not None
                and (type(self.due.periodic_plan) is not str or not self.due.periodic_plan)
            )
            or (
                self.due.periodic_ordinal is not None
                and (type(self.due.periodic_ordinal) is not int or self.due.periodic_ordinal < 0)
            )
            or type(self.time) is not C0TimeValue
            or type(self.time.ordinal) is not int
            or self.time.ordinal < 0
            or type(self.extra_views) is not tuple
            or any(type(item) is not tuple or len(item) != 2 for item in self.extra_views)
            or any(type(name) is not str for name, _ in self.extra_views)
            or len({name for name, _ in self.extra_views}) != len(self.extra_views)
            or type(self.actor_views) is not tuple
            or any(
                type(view) is not _K0OwnerView or view.actor_ref is None or view.participant is None
                for view in self.actor_views
            )
            or len({view.owner for view in self.actor_views}) != len(self.actor_views)
            or type(self.object_views) is not tuple
            or any(
                type(view) is not _K0OwnerView
                or type(view.individual_ref) is not _K0IndividualRef
                or view.actor_ref is not None
                or view.participant is None
                for view in self.object_views
            )
            or len({view.owner for view in self.object_views}) != len(self.object_views)
            or len({view.individual_ref for view in self.object_views}) != len(self.object_views)
        ):
            raise K0ProfileError("due Event evidence is malformed")
        validate = getattr(self.scene, "validate_for_k0", None)
        if not callable(validate):
            raise K0ProfileError("due Event has no nominal Scene evidence")
        validate()
        for view in self.actor_views:
            view.__post_init__()
            view.view.validate_for_k0()
        for view in self.object_views:
            view.__post_init__()
            view.view.validate_for_k0()
        for name, view in self.extra_views:
            if (
                type(name) is not str
                or not name
                or not callable(getattr(view, "validate_for_k0", None))
            ):
                raise K0ProfileError("due Event has a malformed extra owner view")
            view.validate_for_k0()


@dataclass(frozen=True)
class C0DueParticipants:
    subject: str
    fixed_individuals: tuple[tuple[str, _K0IndividualRef], ...] = ()
    actors: tuple[tuple[str, _K0ActorRef], ...] = ()
    objects: tuple[tuple[str, _K0IndividualRef], ...] = ()

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0DueParticipants
            or type(self.subject) is not str
            or not self.subject
            or type(self.fixed_individuals) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not _K0IndividualRef
                for item in self.fixed_individuals
            )
        ):
            raise K0ProfileError("due Event participants are malformed")
        _validate_actor_refs(self.actors)
        _validate_object_refs(self.objects)


@dataclass(frozen=True)
class C0DueEnvelope:
    formation: K0OccurrenceRef | None
    event: K0OccurrenceRef
    periodic_plan: str | None = None
    periodic_ordinal: int | None = None
    fixed_individuals: tuple[tuple[str, _K0IndividualRef], ...] = ()
    actors: tuple[tuple[str, _K0ActorRef], ...] = ()
    objects: tuple[tuple[str, _K0IndividualRef], ...] = ()

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0DueEnvelope
            or type(self.event) is not K0OccurrenceRef
            or (self.formation is None)
            != (self.periodic_plan is not None and self.periodic_ordinal is not None)
            or (self.formation is not None and type(self.formation) is not K0OccurrenceRef)
            or (
                self.periodic_plan is not None
                and (type(self.periodic_plan) is not str or not self.periodic_plan)
            )
            or (
                self.periodic_ordinal is not None
                and (type(self.periodic_ordinal) is not int or self.periodic_ordinal < 0)
            )
            or type(self.fixed_individuals) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not _K0IndividualRef
                for item in self.fixed_individuals
            )
        ):
            raise K0ProfileError("due Event envelope is malformed")
        _validate_actor_refs(self.actors)
        _validate_object_refs(self.objects)


def _validate_object_refs(objects):
    if (
        type(objects) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or not item[0]
            or type(item[1]) is not _K0IndividualRef
            for item in objects
        )
        or len({ref for _, ref in objects}) != len(objects)
        or objects != tuple(sorted(objects, key=lambda item: (item[0], item[1].ordinal)))
    ):
        raise K0ProfileError("due Event has malformed actual Object participants")
    for _, ref in objects:
        ref.__post_init__()


def _validate_actor_refs(actors):
    if (
        type(actors) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not _K0ActorRef
            for item in actors
        )
        or len({ref for _, ref in actors}) != len(actors)
    ):
        raise K0ProfileError("due Event has malformed actual Actor participants")


@dataclass(frozen=True)
class C0ScheduledScenePorts:
    source_key: K0SourceSpecKey
    event_type: K0EventTypeKey
    scene_owner: _K0Owner
    contribution_type: type
    value_ports: C0ValuePorts
    extra_owners: tuple[tuple[str, _K0Owner], ...] = ()
    fixed_individual_roots: tuple[tuple[str, str, type], ...] = ()
    actor_product: C0ActorProductIR | None = None
    actor_domains: tuple[C0ActorDomainPorts, ...] = ()
    read_object_domains: tuple[C0ReadObjectDomainPorts, ...] = ()


def _check_due_effects(
    effects: tuple[tuple[str, str, str], ...], ports: C0ScheduledScenePorts
) -> None:
    roots = dict((("scene", ports.scene_owner),) + ports.extra_owners)
    if (
        type(effects) is not tuple
        or (not effects and ports.actor_product is None)
        or any(type(item) is not tuple or len(item) != 3 for item in effects)
        or any(
            type(root) is not str or type(field) is not str or type(output) is not str
            for root, field, output in effects
        )
        or any(root not in roots for root, _, _ in effects)
        or len({(root, field) for root, field, _ in effects}) != len(effects)
        or len({owner.key for owner in roots.values()}) != len(roots)
    ):
        raise C0LawError("scheduled Event effects need distinct declared owner roots")
    outputs = ports.value_ports.outputs
    if (
        any(
            type(field) is not str
            or field
            not in ports.value_ports.writable_fields.get(roots[root].state_type, frozenset())
            or type(output) is not str
            or not _assignable(
                outputs.get(output), get_type_hints(roots[root].state_type).get(field)
            )
            for root, field, output in effects
        )
        or len({output for _, _, output in effects}) != len(effects)
        or {output for _, _, output in effects} | product_outputs(ports.actor_product)
        != set(outputs)
        or {output for _, _, output in effects} & product_outputs(ports.actor_product)
    ):
        raise C0LawError("scheduled Event effect crosses a typed owner write port")


@dataclass(frozen=True)
class C0ScheduledSceneProgram:
    ports: C0ScheduledScenePorts
    ir: C0DueLawIR

    def __post_init__(self) -> None:
        if (
            type(self.ir) is not C0DueLawIR
            or self.ir.source_key != self.ports.source_key.value
            or self.ir.event_type != self.ports.event_type.value
            or self.ir.actor_product != self.ports.actor_product
            or self.ir.value._ports != self.ports.value_ports
            or self.ir.owners
            != tuple(
                C0StaticOwnerIR(root, owner.key.value, owner.state_type)
                for root, owner in (("scene", self.ports.scene_owner),) + self.ports.extra_owners
            )
            or self.ir.fixed_individuals
            != tuple(
                C0FixedIndividualIR(root, family, state_type)
                for root, family, state_type in self.ports.fixed_individual_roots
            )
        ):
            raise C0LawError("due IR differs from its checked ports")
        _check_due_effects(self.ir.effects, self.ports)
        check_read_object_domains(
            self.ports.read_object_domains,
            {
                "scene",
                "due",
                "time",
                "actor",
                *(name for name, _ in self.ports.extra_owners),
                *(name for name, _, _ in self.ports.fixed_individual_roots),
                *(domain.name for domain in self.ports.actor_domains),
            },
        )
        if self.ir.read_object_domains != self.ports.read_object_domains:
            raise C0LawError("due read Object-domain IR differs from its declared ports")
        if tuple(item.ports for item in self.ir.actor_domains) != self.ports.actor_domains:
            raise C0LawError("due Actor-domain IR differs from its declared ports")
        roots = self.ports.value_ports.roots
        if any(
            roots.get(domain.name) is not domain.wrapper
            for domain in self.ports.read_object_domains
        ):
            raise C0LawError("due Object domain lacks its declared nominal value root")
        for item in self.ir.actor_domains:
            item.__post_init__()
            if item.value._ports.roots != {
                **roots,
                "actor": item.ports.kind.factory.state_type,
            } or set(roots) & {"actor", item.ports.name}:
                raise C0LawError("Actor domain has undeclared extra roots")

    @property
    def value(self) -> C0ValueProgram:
        return self.ir.value

    @property
    def effects(self) -> tuple[tuple[str, str, str], ...]:
        return self.ir.effects

    @property
    def occurrence_contract(self) -> C0OccurrenceContractIR:
        return C0OccurrenceContractIR(
            self.ir.source_key,
            self.ir.event_type,
            K0OccurrenceFamily.EVENT,
            C0DueEnvelope,
            C0DueParticipants,
        )

    def build_spec(self) -> _K0InMemorySourceSpec:
        read_owners = tuple(sorted(K0OwnerKey(owner.key) for owner in self.ir.owners))
        written = {root for root, _, _ in self.effects}
        contribution_owners = tuple(
            sorted(K0OwnerKey(owner.key) for owner in self.ir.owners if owner.root in written)
        )
        projector = _DueProjector(self, _K0CapabilityRef("c0.scheduled_scene.projector.v1"))
        return _K0InMemorySourceSpec(
            K0SourceSpecKey(self.ir.source_key),
            K0OccurrenceFamily.EVENT,
            K0EventTypeKey(self.ir.event_type),
            type(None),
            C0ScheduledSceneEvidence,
            C0DueParticipants,
            read_owners,
            contribution_owners,
            (),
            (),
            None,
            _Rule(self, _K0CapabilityRef("c0.scheduled_scene.rule.v1")),
            C0DueEnvelope,
            (),
            projector,
            due_fixed_individual_ports=tuple(
                _K0FixedDueIndividualPort(item.root, item.family)
                for item in self.ir.fixed_individuals
            ),
            actor_product=None if self.ir.actor_product is None else self.ir.actor_product.port(),
            actor_domains=tuple(item.port() for item in self.ir.actor_domains),
            read_object_domains=tuple(item.port() for item in self.ir.read_object_domains),
        )


def _due_value(pending: _K0PendingDue) -> C0DueValue:
    if type(pending.key) is _K0PendingDueKey:
        return C0DueValue(pending.subject, pending.key.formation)
    if type(pending.key) is _K0PeriodicDueKey:
        return C0DueValue(
            pending.subject,
            None,
            pending.key.plan.value,
            pending.key.ordinal,
        )
    raise K0ProfileError("due Event has a foreign formation key")


@dataclass(frozen=True)
class _DueProjector:
    program: C0ScheduledSceneProgram
    capability_ref: _K0CapabilityRef

    def project_due(
        self,
        pending: _K0PendingDue,
        time: _K0FixedTime,
        owner_views: tuple[_K0OwnerView, ...],
    ) -> _K0AdmissionProjection:
        if (
            type(pending) is not _K0PendingDue
            or pending.source != K0SourceSpecKey(self.program.ir.source_key)
            or pending.at != time
        ):
            raise K0ProfileError("due Event received a foreign pending obligation")
        by_owner = {item.owner: item.view for item in owner_views}
        scene_root = self.program.ir.owners[0]
        scene = by_owner[K0OwnerKey(scene_root.key)]
        if type(scene) is not scene_root.state_type:
            raise K0ProfileError("due Event received a foreign Scene view")
        extras = tuple(
            (owner.root, by_owner[K0OwnerKey(owner.key)]) for owner in self.program.ir.owners[1:]
        )
        if any(
            type(view) is not owner.state_type
            for (_, view), owner in zip(extras, self.program.ir.owners[1:], strict=True)
        ):
            raise K0ProfileError("due Event received a foreign extra owner view")
        selected = {item.name: item for item in pending.selected_individuals}
        if set(selected) != {item.root for item in self.program.ir.fixed_individuals}:
            raise K0ProfileError("due Event lost a fixed Object binding")
        dynamic_views = {
            item.participant: item.view
            for item in owner_views
            if item.participant and item.actor_ref is None and item.individual_ref is None
        }
        for fixed in self.program.ir.fixed_individuals:
            if (
                selected[fixed.root].individual.family != fixed.family
                or fixed.root not in dynamic_views
                or type(dynamic_views[fixed.root]) is not fixed.state_type
            ):
                raise K0ProfileError("due Event fixed Object view differs from its binding")
        extras += tuple(
            (fixed.root, dynamic_views[fixed.root]) for fixed in self.program.ir.fixed_individuals
        )
        domains = {item.ports.name: item for item in self.program.ir.actor_domains}
        actor_views = tuple(view for view in owner_views if view.actor_ref is not None)
        if any(
            view.participant not in domains
            or view.actor_ref.family != domains[view.participant].ports.kind.symbol
            or type(view.view) is not domains[view.participant].ports.kind.factory.state_type
            for view in actor_views
        ):
            raise K0ProfileError("due Event lost its nominal Actor-domain basis")
        object_views = tuple(view for view in owner_views if view.individual_ref is not None)
        object_domains = {domain.name: domain for domain in self.program.ir.read_object_domains}
        if any(
            view.participant not in object_domains
            or view.individual_ref.family != object_domains[view.participant].kind.symbol
            or type(view.view) is not object_domains[view.participant].kind.k0_kind.state_type
            for view in object_views
        ):
            raise K0ProfileError("due Event lost its nominal Object-domain basis")
        evidence = C0ScheduledSceneEvidence(
            scene,
            _due_value(pending),
            C0TimeValue(time.ordinal),
            extras,
            actor_views,
            object_views,
        )
        refs = tuple((item.name, item.individual) for item in pending.selected_individuals)
        actors = tuple((view.participant, view.actor_ref) for view in actor_views)
        return _K0AdmissionProjection(
            evidence,
            C0DueParticipants(
                pending.subject,
                refs,
                actors,
                tuple((view.participant, view.individual_ref) for view in object_views),
            ),
            (),
        )


@dataclass(frozen=True)
class _Rule:
    program: C0ScheduledSceneProgram
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        pending = rule_input.pending_due
        evidence = rule_input.evidence
        if (
            type(rule_input) is not _K0InMemoryRuleInput
            or rule_input.source != K0SourceSpecKey(self.program.ir.source_key)
            or type(pending) is not _K0PendingDue
            or rule_input.time != pending.at
            or type(evidence) is not C0ScheduledSceneEvidence
            or evidence.due != _due_value(pending)
            or evidence.time != C0TimeValue(pending.at.ordinal)
            or type(rule_input.participants) is not C0DueParticipants
            or rule_input.participants.subject != pending.subject
            or rule_input.participants.fixed_individuals
            != tuple((item.name, item.individual) for item in pending.selected_individuals)
            or rule_input.participants.actors
            != tuple((view.participant, view.actor_ref) for view in evidence.actor_views)
            or rule_input.participants.objects
            != tuple((view.participant, view.individual_ref) for view in evidence.object_views)
            or rule_input.bindings
            or rule_input.trigger is not None
        ):
            raise K0ProfileError("due Event lost its sealed pending basis")
        roots = {
            "scene": evidence.scene,
            "due": evidence.due,
            "time": evidence.time,
            **dict(evidence.extra_views),
            **{
                domain.name: domain.project(evidence.object_views)
                for domain in self.program.ir.read_object_domains
            },
        }
        try:
            self.program.ir.condition(roots, formed=True)
            outputs = self.program.ir.evaluate(roots, occurrence=rule_input.occurrence)
        except C0ValueStateError as error:
            raise K0ProfileError("due Event effect failed on sealed owner state") from error
        carriers = {
            owner.key.value: owner
            for _, owner in (("scene", self.program.ports.scene_owner),)
            + self.program.ports.extra_owners
        }
        owners = {item.root: carriers[item.key] for item in self.program.ir.owners}
        contributions = []
        for root in dict.fromkeys(root for root, _, _ in self.program.effects):
            owner = owners[root]
            state = replace(
                roots[root],
                **{
                    field: outputs[output]
                    for selected, field, output in self.program.effects
                    if selected == root
                },
            )
            owner.validate_state(state)
            if owner.read_view(state) is not state:
                raise K0ProfileError("due Event owner view loses state")
            contribution = self.program.ports.contribution_type(owner.key, state)
            owner.validate_contribution(contribution)
            contributions.append(contribution)
        try:
            for domain in self.program.ir.actor_domains:
                for view in evidence.actor_views:
                    if view.participant == domain.ports.name:
                        contributions.append(
                            domain.contribution(view, roots, rule_input.occurrence)
                        )
        except C0ValueStateError as error:
            raise K0ProfileError(
                "due Actor-domain effect failed on sealed instance state"
            ) from error
        result = K0RuleResult(
            tuple(contributions),
            (),
            formed_actors=actor_products(self.program.ir.actor_product, outputs),
        )

        return _K0InMemoryEvaluation(result, self._envelope(rule_input))

    def _envelope(self, rule_input: _K0InMemoryRuleInput) -> C0DueEnvelope:
        pending = rule_input.pending_due
        if type(pending) is not _K0PendingDue:
            raise K0ProfileError("due Event envelope lacks pending formation")
        if type(pending.key) is _K0PendingDueKey:
            return C0DueEnvelope(
                pending.key.formation,
                rule_input.occurrence,
                fixed_individuals=tuple(
                    (item.name, item.individual) for item in pending.selected_individuals
                ),
                actors=rule_input.participants.actors,
                objects=rule_input.participants.objects,
            )
        if type(pending.key) is _K0PeriodicDueKey:
            return C0DueEnvelope(
                None,
                rule_input.occurrence,
                pending.key.plan.value,
                pending.key.ordinal,
                tuple((item.name, item.individual) for item in pending.selected_individuals),
                rule_input.participants.actors,
                rule_input.participants.objects,
            )
        raise K0ProfileError("due Event envelope has a foreign formation key")


def compile_scheduled_scene_event(
    row: dict[str, object],
    ports: C0ScheduledScenePorts,
    *,
    actor_domains: tuple[C0ActorDomainEffect, ...] = (),
) -> C0ScheduledSceneProgram:
    if (
        type(ports) is not C0ScheduledScenePorts
        or not isinstance(ports.scene_owner, _K0Owner)
        or type(ports.extra_owners) is not tuple
        or type(ports.fixed_individual_roots) is not tuple
        or len(ports.fixed_individual_roots) > 32
        or any(
            type(item) is not tuple
            or len(item) != 3
            or type(item[0]) is not str
            or not item[0]
            or item[0] in ("scene", "due", "time")
            or type(item[1]) is not str
            or not item[1]
            or not isinstance(item[2], type)
            for item in ports.fixed_individual_roots
        )
        or len(ports.extra_owners) > 32
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or not item[0]
            or item[0] in ("scene", "due", "time")
            or not isinstance(item[1], _K0Owner)
            or item[1].view_type is not item[1].state_type
            or item[1].contribution_type is not ports.contribution_type
            for item in ports.extra_owners
        )
        or len({name for name, _ in ports.extra_owners}) != len(ports.extra_owners)
        or len({name for name, _, _ in ports.fixed_individual_roots})
        != len(ports.fixed_individual_roots)
        or {name for name, _ in ports.extra_owners}
        & {name for name, _, _ in ports.fixed_individual_roots}
        or len({owner.key for _, owner in ports.extra_owners}) != len(ports.extra_owners)
        or any(owner.key == ports.scene_owner.key for _, owner in ports.extra_owners)
    ):
        raise C0LawError("scheduled Event owner roots are malformed")
    check_read_object_domains(
        ports.read_object_domains,
        {
            "scene",
            "due",
            "time",
            "actor",
            *(name for name, _ in ports.extra_owners),
            *(name for name, _, _ in ports.fixed_individual_roots),
            *(domain.name for domain in ports.actor_domains),
        },
    )
    if (
        type(row) is not dict
        or set(row) != {"name", "form", "source_key", "event_type", "when_false", "law", "effect"}
        or row["form"] != "due"
        or row["when_false"] != "defect"
        or not isinstance(ports.scene_owner, _K0Owner)
        or ports.scene_owner.view_type is not ports.scene_owner.state_type
        or ports.contribution_type is not ports.scene_owner.contribution_type
        or type(ports.value_ports) is not C0ValuePorts
        or ports.value_ports.roots
        != {
            "scene": ports.scene_owner.view_type,
            "due": C0DueValue,
            "time": C0TimeValue,
            **{name: owner.view_type for name, owner in ports.extra_owners},
            **{name: state_type for name, _, state_type in ports.fixed_individual_roots},
            **{domain.name: domain.wrapper for domain in ports.read_object_domains},
        }
    ):
        raise C0LawError("scheduled Event declaration or Lib ports are not closed")
    try:
        keys = K0SourceSpecKey(row["source_key"]), K0EventTypeKey(row["event_type"])
    except (TypeError, K0ProfileError) as error:
        raise C0LawError("scheduled Event identity is malformed") from error
    if keys != (ports.source_key, ports.event_type):
        raise C0LawError("scheduled Event identity differs from Lib binding")
    effects = row["effect"]
    roots = dict((("scene", ports.scene_owner),) + ports.extra_owners)
    if (
        type(effects) is not dict
        or (not effects and ports.actor_product is None)
        or not set(effects) <= set(roots)
        or any(type(fields) is not dict for fields in effects.values())
        or len({owner.key for owner in roots.values()}) != len(roots)
    ):
        raise C0LawError("scheduled Event effects need distinct declared owner roots")
    flattened = tuple(
        (root, field, output)
        for root, fields in effects.items()
        for field, output in fields.items()
    )
    _check_due_effects(flattened, ports)
    try:
        value_source = json.dumps(row["law"])
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("scheduled Event law is not JSON data") from error
    value = compile_value_program(
        value_source,
        ports.value_ports,
        state_outputs={f"{root}.{field}": output for root, field, output in flattened},
    )
    return C0ScheduledSceneProgram(
        replace(ports, value_ports=value._ports),
        C0DueLawIR(
            keys[0].value,
            keys[1].value,
            value,
            flattened,
            tuple(
                C0StaticOwnerIR(root, owner.key.value, owner.state_type)
                for root, owner in (("scene", ports.scene_owner),) + ports.extra_owners
            ),
            C0FormationKind.DUE,
            tuple(
                C0FixedIndividualIR(root, family, state_type)
                for root, family, state_type in ports.fixed_individual_roots
            ),
            actor_product=ports.actor_product,
            actor_domains=actor_domains,
            read_object_domains=ports.read_object_domains,
        ),
    )
