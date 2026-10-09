"""Compile one authored direct causal Event that writes its declared Scene owner."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import get_type_hints

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryEvaluation,
    _K0InMemoryRuleInput,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0Owner, _K0OwnerView
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation

from .actor_domain_v1 import C0ReadActorDomainPorts, check_read_actor_domains
from .actor_product_v1 import C0ActorProductIR, actor_products, product_outputs
from .author_contract_v1 import C0LawError
from .composable_action_v1 import C0ValueActionProgram
from .composable_value_v1 import (
    C0ValuePorts,
    C0ValueProgram,
    C0ValueStateError,
    _assignable,
    compile_value_program,
)
from .object_product_v1 import C0ObjectProductIR, object_products
from .semantic_ir_v0 import (
    C0CausalEdgeIR,
    C0FormationKind,
    C0OccurrenceContractIR,
    C0StaticOwnerIR,
    C0TransitionIR,
)


@dataclass(frozen=True)
class C0DirectSceneEvidence:
    scene: object
    actor_views: tuple[_K0OwnerView, ...] = ()

    def validate_for_k0(self) -> None:
        if type(self) is not C0DirectSceneEvidence:
            raise K0ProfileError("direct Event evidence is malformed")
        validate = getattr(self.scene, "validate_for_k0", None)
        if not callable(validate):
            raise K0ProfileError("direct Event evidence has no nominal Scene")
        validate()
        if type(self.actor_views) is not tuple or any(
            type(view) is not _K0OwnerView
            or type(view.actor_ref) is not _K0ActorRef
            or type(view.owner) is not K0OwnerKey
            or type(view.participant) is not str
            for view in self.actor_views
        ):
            raise K0ProfileError("Scene Event domain evidence lacks actual ref/owner/view")
        if len({view.owner for view in self.actor_views}) != len(self.actor_views) or len(
            {view.actor_ref for view in self.actor_views}
        ) != len(self.actor_views):
            raise K0ProfileError("Scene Event domain evidence aliases")
        for view in self.actor_views:
            view.view.validate_for_k0()


@dataclass(frozen=True)
class C0DirectSceneParticipants:
    actors: tuple[tuple[str, _K0ActorRef, K0OwnerKey], ...] = ()

    def validate_for_k0(self):
        if type(self.actors) is not tuple or any(
            type(row) is not tuple
            or len(row) != 3
            or type(row[0]) is not str
            or type(row[1]) is not _K0ActorRef
            or type(row[2]) is not K0OwnerKey
            for row in self.actors
        ):
            raise K0ProfileError("Scene Event participants lack actual domain identities")
        if len({ref for _, ref, _ in self.actors}) != len(self.actors) or len(
            {owner for _, _, owner in self.actors}
        ) != len(self.actors):
            raise K0ProfileError("Scene Event domain participants alias")


@dataclass(frozen=True)
class C0DirectSceneEnvelope:
    trigger: K0OccurrenceRef
    event: K0OccurrenceRef

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0DirectSceneEnvelope
            or type(self.trigger) is not K0OccurrenceRef
            or type(self.event) is not K0OccurrenceRef
        ):
            raise K0ProfileError("direct Event envelope is malformed")


@dataclass(frozen=True)
class C0DirectScenePorts:
    source_key: K0SourceSpecKey
    event_type: K0EventTypeKey
    causal_key: K0CausalLawKey
    scene_owner: _K0Owner
    contribution_type: type
    value_ports: C0ValuePorts
    actor_product: C0ActorProductIR | None = None
    read_actor_domains: tuple[C0ReadActorDomainPorts, ...] = ()
    object_product: C0ObjectProductIR | None = None

    def roots(self):
        from .direct_actor_event_v1 import C0EventTrigger

        return {
            "scene": self.scene_owner.state_type,
            "trigger": C0EventTrigger,
            **{domain.name: domain.wrapper for domain in self.read_actor_domains},
        }

    def check_domains(self):
        from .direct_actor_event_v1 import C0EventTrigger

        check_read_actor_domains(self.read_actor_domains, ("scene", "actor", "trigger"))
        if self.value_ports.writable_fields.get(C0EventTrigger):
            raise C0LawError("Scene Event trigger is a readonly occurrence basis")


@dataclass(frozen=True)
class C0DirectSceneProgram:
    ports: C0DirectScenePorts
    ir: C0TransitionIR
    edge: C0CausalEdgeIR

    def __post_init__(self) -> None:
        self.ports.check_domains()
        if (
            type(self.ports) is not C0DirectScenePorts
            or type(self.ir) is not C0TransitionIR
            or type(self.edge) is not C0CausalEdgeIR
            or self.edge.target_source != self.ir.source_key
            or self.edge.causal_key != self.ports.causal_key.value
            or self.ir.actor_product != self.ports.actor_product
            or self.ir.object_product != self.ports.object_product
            or self.ports.contribution_type is not self.ports.scene_owner.contribution_type
            or self.ports.scene_owner.view_type is not self.ports.scene_owner.state_type
            or self.ports.value_ports.roots != self.ports.roots()
        ):
            raise C0LawError("direct Event IR differs from its causal binding")
        owner = self.ports.scene_owner
        self.ir.check_causal_binding(
            source_key=self.ports.source_key.value,
            event_type=self.ports.event_type.value,
            value_ports=self.ports.value_ports,
            owners=(C0StaticOwnerIR("scene", owner.key.value, owner.state_type),),
            write_root="scene",
        )

    @property
    def value(self) -> C0ValueProgram:
        return self.ir.value

    @property
    def effects(self) -> tuple[tuple[str, str], ...]:
        return tuple((field, output) for _, field, output in self.ir.effects)

    @property
    def source_key(self) -> K0SourceSpecKey:
        return K0SourceSpecKey(self.ir.source_key)

    @property
    def event_type(self) -> K0EventTypeKey:
        return K0EventTypeKey(self.ir.event_type)

    @property
    def envelope_type(self) -> type:
        return C0DirectSceneEnvelope

    @property
    def occurrence_contract(self) -> C0OccurrenceContractIR:
        return C0OccurrenceContractIR(
            self.ir.source_key,
            self.ir.event_type,
            K0OccurrenceFamily.EVENT,
            C0DirectSceneEnvelope,
            C0DirectSceneParticipants,
        )

    def build(self) -> tuple[_K0InMemorySourceSpec, K0CausalLawDefinition]:
        ports = self.ports
        owner = ports.scene_owner.key
        source = _K0InMemorySourceSpec(
            self.source_key,
            K0OccurrenceFamily.EVENT,
            self.event_type,
            type(None),
            C0DirectSceneEvidence,
            C0DirectSceneParticipants,
            (owner,),
            (owner,) if self.ir.effects else (),
            (),
            (),
            None,
            _Rule(self, _K0CapabilityRef("c0.direct_scene.rule.v1")),
            C0DirectSceneEnvelope,
            actor_product=None if self.ir.actor_product is None else self.ir.actor_product.port(),
            actor_domains=tuple(domain.port() for domain in ports.read_actor_domains),
            form_owner_family=None
            if self.ir.object_product is None
            else self.ir.object_product.family,
        )
        causal = K0CausalLawDefinition(
            K0CausalLawKey(self.edge.causal_key),
            K0EventTypeKey(self.edge.predecessor.event_type),
            self.source_key,
            1,
            (owner,),
            _Projector(self, _K0CapabilityRef("c0.direct_scene.projector.v1")),
            actor_domains=tuple(domain.port() for domain in ports.read_actor_domains),
        )
        return source, causal


def _roots(program, evidence, trigger):
    from .direct_actor_event_v1 import C0EventTrigger

    evidence.validate_for_k0()
    ports = program.ports
    domains = {domain.name: domain for domain in ports.read_actor_domains}
    if (
        type(trigger) is not K0OccurrenceRef
        or type(evidence.scene) is not ports.scene_owner.view_type
        or any(
            view.participant not in domains
            or view.actor_ref.family != domains[view.participant].kind.symbol
            or type(view.view) is not domains[view.participant].kind.factory.state_type
            for view in evidence.actor_views
        )
    ):
        raise K0ProfileError("Scene Event received a foreign nominal domain basis")
    return {
        "scene": evidence.scene,
        "trigger": C0EventTrigger(trigger),
        **{
            domain.name: domain.project(evidence.actor_views) for domain in ports.read_actor_domains
        },
    }


@dataclass(frozen=True)
class _Projector:
    program: C0DirectSceneProgram
    capability_ref: _K0CapabilityRef

    def project(self, trigger: object, views: tuple[object, ...]) -> tuple[_K0Activation, ...]:
        if not self.program.edge.predecessor.matches(trigger):
            return ()
        by_owner = {item.owner: item.view for item in views}
        scene = by_owner[self.program.ports.scene_owner.key]
        if type(scene) is not self.program.ports.scene_owner.view_type:
            raise K0ProfileError("direct Event received a foreign Scene view")
        evidence = C0DirectSceneEvidence(
            scene, tuple(view for view in views if view.participant is not None)
        )
        try:
            if not self.program.ir.condition(_roots(self.program, evidence, trigger.occurrence)):
                return ()
        except C0ValueStateError as error:
            raise K0ProfileError("direct Event guard met malformed Scene state") from error
        return (
            _K0Activation(
                self.program.ir.source_key,
                evidence,
                C0DirectSceneParticipants(
                    tuple(
                        (view.participant, view.actor_ref, view.owner)
                        for view in evidence.actor_views
                    )
                ),
                (),
            ),
        )


@dataclass(frozen=True)
class _Rule:
    # Shared result sources use one body; edge-specific checks belong to the projector.
    program: C0DirectSceneProgram
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        if (
            type(rule_input) is not _K0InMemoryRuleInput
            or rule_input.source != self.program.source_key
            or type(rule_input.evidence) is not C0DirectSceneEvidence
            or type(rule_input.participants) is not C0DirectSceneParticipants
            or rule_input.trigger is None
            or rule_input.bindings
        ):
            raise K0ProfileError("direct Event has no sealed causal basis")
        scene = rule_input.evidence.scene
        roots = _roots(self.program, rule_input.evidence, rule_input.trigger)
        if rule_input.participants.actors != tuple(
            (view.participant, view.actor_ref, view.owner)
            for view in rule_input.evidence.actor_views
        ):
            raise K0ProfileError("Scene Event participants differ from sealed domain evidence")
        try:
            self.program.ir.condition(roots, formed=True)
            outputs = self.program.ir.evaluate(roots, occurrence=rule_input.occurrence)
        except C0ValueStateError as error:
            raise K0ProfileError("direct Event effect failed on sealed basis") from error
        updated = replace(
            scene,
            **{field: outputs[output] for field, output in self.program.effects},
        )
        owner = self.program.ports.scene_owner
        owner.validate_state(updated)
        if owner.read_view(updated) is not updated:
            raise K0ProfileError("direct Event Scene view loses its candidate state")
        contribution = self.program.ports.contribution_type(owner.key, updated)
        owner.validate_contribution(contribution)
        result = K0RuleResult(
            (contribution,) if self.program.ir.effects else (),
            (),
            formed_actors=actor_products(self.program.ir.actor_product, outputs),
            formed_owners=object_products(self.program.ir.object_product, outputs),
        )

        return _K0InMemoryEvaluation(
            result, C0DirectSceneEnvelope(rule_input.trigger, rule_input.occurrence)
        )


def compile_direct_scene_event(
    row: dict[str, object],
    ports: C0DirectScenePorts,
    trigger: C0ValueActionProgram | C0DirectSceneProgram,
) -> C0DirectSceneProgram:
    """Compile a direct Event; false guards intentionally produce no Event."""
    from .direct_actor_event_v1 import C0DirectActorProgram
    from .scheduled_scene_event_v1 import C0ScheduledSceneProgram

    if (
        type(row) is not dict
        or set(row)
        not in (
            {
                "name",
                "form",
                "trigger_action",
                "source_key",
                "event_type",
                "causal_key",
                "when_false",
                "law",
                "effect",
            },
            {
                "name",
                "form",
                "trigger_event",
                "source_key",
                "event_type",
                "causal_key",
                "when_false",
                "law",
                "effect",
            },
        )
        or row["form"] != "direct"
        or row["when_false"] != "no_event"
        or type(ports) is not C0DirectScenePorts
        or not isinstance(ports.scene_owner, _K0Owner)
        or ports.scene_owner.view_type is not ports.scene_owner.state_type
        or type(ports.value_ports) is not C0ValuePorts
        or ports.value_ports.roots != ports.roots()
        or ports.contribution_type is not ports.scene_owner.contribution_type
        or (
            ("trigger_action" in row and type(trigger) is not C0ValueActionProgram)
            or (
                "trigger_event" in row
                and type(trigger)
                not in (
                    C0DirectSceneProgram,
                    C0DirectActorProgram,
                    C0ScheduledSceneProgram,
                )
            )
        )
    ):
        raise C0LawError("direct Event declaration or Lib ports are not closed")
    try:
        keys = (
            K0SourceSpecKey(row["source_key"]),
            K0EventTypeKey(row["event_type"]),
            K0CausalLawKey(row["causal_key"]),
        )
    except (TypeError, K0ProfileError) as error:
        raise C0LawError("direct Event identity is malformed") from error
    if keys != (ports.source_key, ports.event_type, ports.causal_key):
        raise C0LawError("direct Event identity differs from Lib binding")
    if ports.source_key.value == trigger.occurrence_contract.source_key:
        raise C0LawError("direct Event source aliases its trigger")
    scene_fields = get_type_hints(ports.scene_owner.state_type)
    outputs = ports.value_ports.outputs
    effect = row["effect"]
    if type(effect) is not dict or set(effect) != {"scene"}:
        raise C0LawError("direct Event effect must target its declared Scene")
    effect_fields = effect["scene"]
    if (
        type(effect_fields) is not dict
        or (not effect_fields and ports.actor_product is None and ports.object_product is None)
        or any(
            type(field) is not str
            or field
            not in ports.value_ports.writable_fields.get(ports.scene_owner.state_type, frozenset())
            or type(output) is not str
            or output not in outputs
            or not _assignable(outputs[output], scene_fields.get(field))
            for field, output in effect_fields.items()
        )
        or len(set(effect_fields.values())) != len(effect_fields)
        or set(effect_fields.values())
        | product_outputs(ports.actor_product)
        | product_outputs(ports.object_product)
        != set(outputs)
        or set(effect_fields.values())
        & (product_outputs(ports.actor_product) | product_outputs(ports.object_product))
        or product_outputs(ports.actor_product) & product_outputs(ports.object_product)
    ):
        raise C0LawError("direct Event effect crosses a typed Scene write port")
    try:
        value_source = json.dumps(row["law"])
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("direct Event law is not JSON data") from error
    value = compile_value_program(
        value_source,
        ports.value_ports,
        state_outputs={f"scene.{field}": output for field, output in effect_fields.items()},
    )
    return C0DirectSceneProgram(
        replace(ports, value_ports=value._ports),
        C0TransitionIR(
            ports.source_key.value,
            ports.event_type.value,
            value,
            tuple(("scene", field, output) for field, output in effect_fields.items()),
            (C0StaticOwnerIR("scene", ports.scene_owner.key.value, ports.scene_owner.state_type),),
            C0FormationKind.AFTER_OCCURRENCE,
            actor_product=ports.actor_product,
            object_product=ports.object_product,
        ),
        C0CausalEdgeIR(ports.causal_key.value, trigger.occurrence_contract, ports.source_key.value),
    )
