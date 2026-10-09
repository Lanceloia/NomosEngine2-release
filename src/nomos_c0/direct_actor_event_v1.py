"""Compile an authored causal Event with a bounded Actor-local effect."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import get_type_hints

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryEvaluation,
    _K0InMemoryRuleInput,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._owner_abi import _K0CapabilityRef, _K0Owner
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
from .direct_scene_event_v1 import C0DirectSceneProgram
from .object_product_v1 import C0ObjectProductIR, object_products
from .scheduled_scene_event_v1 import C0ScheduledSceneProgram
from .semantic_ir_v0 import (
    C0CausalEdgeIR,
    C0FormationKind,
    C0OccurrenceContractIR,
    C0StaticOwnerIR,
    C0TransitionIR,
)


@dataclass(frozen=True)
class C0EventTrigger:
    occurrence: K0OccurrenceRef


@dataclass(frozen=True)
class C0DirectActorEvidence:
    scene: object
    actor: object
    domains: tuple[tuple[str, object], ...] = ()

    def validate_for_k0(self) -> None:
        if type(self) is not C0DirectActorEvidence:
            raise K0ProfileError("Actor Event evidence is malformed")
        if (
            type(self.domains) is not tuple
            or any(
                type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str
                for pair in self.domains
            )
            or len({name for name, _ in self.domains}) != len(self.domains)
        ):
            raise K0ProfileError("Actor Event domain evidence is malformed")
        for state in (self.scene, self.actor, *(state for _, state in self.domains)):
            validate = getattr(state, "validate_for_k0", None)
            if not callable(validate):
                raise K0ProfileError("Actor Event evidence lacks a nominal owner state")
            validate()


@dataclass(frozen=True)
class C0DirectActorParticipants:
    actor: str

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0DirectActorParticipants
            or type(self.actor) is not str
            or not self.actor
        ):
            raise K0ProfileError("Actor Event participant is malformed")


@dataclass(frozen=True)
class C0DirectActorEnvelope:
    trigger: K0OccurrenceRef
    event: K0OccurrenceRef

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0DirectActorEnvelope
            or type(self.trigger) is not K0OccurrenceRef
            or type(self.event) is not K0OccurrenceRef
        ):
            raise K0ProfileError("Actor Event envelope is malformed")


@dataclass(frozen=True)
class C0DirectActorPorts:
    source_key: K0SourceSpecKey
    event_type: K0EventTypeKey
    causal_key: K0CausalLawKey
    scene_owner: _K0Owner
    actor_owner: _K0Owner
    actor_identity_field: str
    contribution_type: type
    value_ports: C0ValuePorts
    actor_product: C0ActorProductIR | None = None
    read_actor_domains: tuple[C0ReadActorDomainPorts, ...] = ()
    object_product: C0ObjectProductIR | None = None

    def roots(self):
        return {
            "scene": self.scene_owner.state_type,
            "actor": self.actor_owner.state_type,
            "trigger": C0EventTrigger,
            **{domain.name: domain.wrapper for domain in self.read_actor_domains},
        }

    def check_domains(self):
        check_read_actor_domains(self.read_actor_domains, ("scene", "actor", "trigger"))


@dataclass(frozen=True)
class C0DirectActorProgram:
    ports: C0DirectActorPorts
    ir: C0TransitionIR
    edge: C0CausalEdgeIR

    def __post_init__(self) -> None:
        self.ports.check_domains()
        if (
            type(self.ports) is not C0DirectActorPorts
            or type(self.ir) is not C0TransitionIR
            or type(self.edge) is not C0CausalEdgeIR
            or self.edge.target_source != self.ir.source_key
            or self.edge.causal_key != self.ports.causal_key.value
            or self.ports.contribution_type is not self.ports.actor_owner.contribution_type
            or self.ir.actor_product != self.ports.actor_product
            or self.ir.object_product != self.ports.object_product
            or self.ports.scene_owner.key == self.ports.actor_owner.key
            or self.ports.scene_owner.view_type is not self.ports.scene_owner.state_type
            or self.ports.actor_owner.view_type is not self.ports.actor_owner.state_type
            or self.ports.value_ports.roots != self.ports.roots()
            or get_type_hints(self.ports.actor_owner.state_type).get(
                self.ports.actor_identity_field
            )
            is not str
        ):
            raise C0LawError("Actor Event IR differs from its causal binding")
        self.ir.check_causal_binding(
            source_key=self.ports.source_key.value,
            event_type=self.ports.event_type.value,
            value_ports=self.ports.value_ports,
            owners=tuple(
                C0StaticOwnerIR(root, owner.key.value, owner.state_type)
                for root, owner in (
                    ("scene", self.ports.scene_owner),
                    ("actor", self.ports.actor_owner),
                )
            ),
            write_root="actor",
            protected_fields=frozenset({self.ports.actor_identity_field}),
        )

    @property
    def value(self) -> C0ValueProgram:
        return self.ir.value

    @property
    def effects(self) -> tuple[tuple[str, str], ...]:
        return tuple((field, output) for _, field, output in self.ir.effects)

    @property
    def occurrence_contract(self) -> C0OccurrenceContractIR:
        return C0OccurrenceContractIR(
            self.ir.source_key,
            self.ir.event_type,
            K0OccurrenceFamily.EVENT,
            C0DirectActorEnvelope,
            C0DirectActorParticipants,
        )

    def build(self) -> tuple[_K0InMemorySourceSpec, K0CausalLawDefinition]:
        ports = self.ports
        owners = tuple(sorted((ports.scene_owner.key, ports.actor_owner.key)))
        source = _K0InMemorySourceSpec(
            K0SourceSpecKey(self.ir.source_key),
            K0OccurrenceFamily.EVENT,
            K0EventTypeKey(self.ir.event_type),
            type(None),
            C0DirectActorEvidence,
            C0DirectActorParticipants,
            owners,
            (ports.actor_owner.key,) if self.ir.effects else (),
            (),
            (),
            None,
            _Rule(self, _K0CapabilityRef("c0.direct_actor.rule.v1")),
            C0DirectActorEnvelope,
            actor_product=None if self.ir.actor_product is None else self.ir.actor_product.port(),
            actor_domains=tuple(domain.port() for domain in ports.read_actor_domains),
            form_owner_family=None
            if self.ir.object_product is None
            else self.ir.object_product.family,
        )
        causal = K0CausalLawDefinition(
            K0CausalLawKey(self.edge.causal_key),
            K0EventTypeKey(self.edge.predecessor.event_type),
            K0SourceSpecKey(self.ir.source_key),
            1,
            owners,
            _Projector(self, _K0CapabilityRef("c0.direct_actor.projector.v1")),
            actor_domains=tuple(domain.port() for domain in ports.read_actor_domains),
        )
        return source, causal


def _roots(
    program: C0DirectActorProgram,
    scene: object,
    actor: object,
    trigger: K0OccurrenceRef,
    domains=(),
):
    ports = program.ports
    if (
        type(scene) is not ports.scene_owner.view_type
        or type(actor) is not ports.actor_owner.view_type
    ):
        raise K0ProfileError("Actor Event received a foreign owner view")
    projected = dict(domains)
    if (
        len(projected) != len(domains)
        or set(projected) != {domain.name for domain in ports.read_actor_domains}
        or any(
            type(projected[domain.name]) is not domain.wrapper
            for domain in ports.read_actor_domains
        )
    ):
        raise K0ProfileError("Actor Event domain evidence differs from its declared projection")
    return {"scene": scene, "actor": actor, "trigger": C0EventTrigger(trigger), **projected}


@dataclass(frozen=True)
class _Projector:
    program: C0DirectActorProgram
    capability_ref: _K0CapabilityRef

    def project(self, trigger: object, views: tuple[object, ...]) -> tuple[_K0Activation, ...]:
        if not self.program.edge.predecessor.matches(trigger):
            return ()
        by_owner = {view.owner: view.view for view in views}
        ports = self.program.ports
        scene = by_owner[ports.scene_owner.key]
        actor = by_owner[ports.actor_owner.key]
        domains = tuple((domain.name, domain.project(views)) for domain in ports.read_actor_domains)
        try:
            if not self.program.ir.condition(
                _roots(self.program, scene, actor, trigger.occurrence, domains)
            ):
                return ()
        except C0ValueStateError as error:
            raise K0ProfileError("Actor Event guard met malformed owner state") from error
        return (
            _K0Activation(
                self.program.ir.source_key,
                C0DirectActorEvidence(scene, actor, domains),
                C0DirectActorParticipants(getattr(actor, ports.actor_identity_field)),
                (),
            ),
        )


@dataclass(frozen=True)
class _Rule:
    # A shared body's sealed basis may come from any of its checked formation edges.
    program: C0DirectActorProgram
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        ports = self.program.ports
        if (
            type(rule_input) is not _K0InMemoryRuleInput
            or rule_input.source != K0SourceSpecKey(self.program.ir.source_key)
            or type(rule_input.evidence) is not C0DirectActorEvidence
            or type(rule_input.participants) is not C0DirectActorParticipants
            or rule_input.trigger is None
            or rule_input.bindings
        ):
            raise K0ProfileError("Actor Event has no sealed causal basis")
        scene, actor = rule_input.evidence.scene, rule_input.evidence.actor
        roots = _roots(self.program, scene, actor, rule_input.trigger, rule_input.evidence.domains)
        if rule_input.participants.actor != getattr(actor, ports.actor_identity_field):
            raise K0ProfileError("Actor Event participant changed its owner")
        try:
            self.program.ir.condition(roots, formed=True)
            outputs = self.program.ir.evaluate(roots, occurrence=rule_input.occurrence)
        except C0ValueStateError as error:
            raise K0ProfileError("Actor Event effect failed on sealed basis") from error
        updated = replace(
            actor,
            **{field: outputs[output] for field, output in self.program.effects},
        )
        owner = ports.actor_owner
        owner.validate_state(updated)
        if owner.read_view(updated) is not updated:
            raise K0ProfileError("Actor Event owner view loses its candidate state")
        contribution = ports.contribution_type(owner.key, updated)
        owner.validate_contribution(contribution)
        result = K0RuleResult(
            (contribution,) if self.program.ir.effects else (),
            (),
            formed_actors=actor_products(self.program.ir.actor_product, outputs),
            formed_owners=object_products(self.program.ir.object_product, outputs),
        )

        return _K0InMemoryEvaluation(
            result, C0DirectActorEnvelope(rule_input.trigger, rule_input.occurrence)
        )


def compile_direct_actor_event(
    row: dict[str, object],
    ports: C0DirectActorPorts,
    trigger: C0ValueActionProgram | C0DirectSceneProgram | C0ScheduledSceneProgram,
) -> C0DirectActorProgram:
    if (
        type(row) is not dict
        or set(row)
        != {
            "name",
            "form",
            ("trigger_action" if type(trigger) is C0ValueActionProgram else "trigger_event"),
            "source_key",
            "event_type",
            "causal_key",
            "when_false",
            "law",
            "effect",
        }
        or row["form"] != "direct_actor"
        or row["when_false"] != "no_event"
        or type(ports) is not C0DirectActorPorts
        or type(trigger)
        not in (
            C0ValueActionProgram,
            C0DirectSceneProgram,
            C0DirectActorProgram,
            C0ScheduledSceneProgram,
        )
        or ports.scene_owner.key == ports.actor_owner.key
        or ports.scene_owner.view_type is not ports.scene_owner.state_type
        or ports.actor_owner.view_type is not ports.actor_owner.state_type
        or ports.contribution_type is not ports.actor_owner.contribution_type
        or type(ports.actor_identity_field) is not str
        or get_type_hints(ports.actor_owner.state_type).get(ports.actor_identity_field) is not str
        or type(ports.value_ports) is not C0ValuePorts
        or ports.value_ports.roots != ports.roots()
    ):
        raise C0LawError("Actor Event declaration or Lib ports are not closed")
    try:
        keys = (
            K0SourceSpecKey(row["source_key"]),
            K0EventTypeKey(row["event_type"]),
            K0CausalLawKey(row["causal_key"]),
        )
    except (TypeError, K0ProfileError) as error:
        raise C0LawError("Actor Event identity is malformed") from error
    if keys != (ports.source_key, ports.event_type, ports.causal_key):
        raise C0LawError("Actor Event identity differs from Lib binding")
    if ports.source_key.value == trigger.occurrence_contract.source_key:
        raise C0LawError("Actor Event source aliases its trigger")
    actor_fields = get_type_hints(ports.actor_owner.state_type)
    effect = row["effect"]
    if type(effect) is not dict or set(effect) != {"actor"}:
        raise C0LawError("Actor Event effect must target its declared Actor")
    fields = effect["actor"]
    outputs = ports.value_ports.outputs
    if (
        type(fields) is not dict
        or (not fields and ports.actor_product is None and ports.object_product is None)
        or ports.actor_identity_field in fields
        or any(
            type(field) is not str
            or field
            not in ports.value_ports.writable_fields.get(ports.actor_owner.state_type, frozenset())
            or type(output) is not str
            or output not in outputs
            or not _assignable(outputs[output], actor_fields.get(field))
            for field, output in fields.items()
        )
        or len(set(fields.values())) != len(fields)
        or set(fields.values())
        | product_outputs(ports.actor_product)
        | product_outputs(ports.object_product)
        != set(outputs)
        or set(fields.values())
        & (product_outputs(ports.actor_product) | product_outputs(ports.object_product))
        or product_outputs(ports.actor_product) & product_outputs(ports.object_product)
    ):
        raise C0LawError("Actor Event effect crosses a typed Actor write port")
    try:
        value_source = json.dumps(row["law"])
    except (TypeError, ValueError, RecursionError) as error:
        raise C0LawError("Actor Event law is not JSON data") from error
    value = compile_value_program(
        value_source,
        ports.value_ports,
        state_outputs={f"actor.{field}": output for field, output in fields.items()},
    )
    return C0DirectActorProgram(
        replace(ports, value_ports=value._ports),
        C0TransitionIR(
            ports.source_key.value,
            ports.event_type.value,
            value,
            tuple(("actor", field, output) for field, output in sorted(fields.items())),
            tuple(
                C0StaticOwnerIR(root, owner.key.value, owner.state_type)
                for root, owner in (("scene", ports.scene_owner), ("actor", ports.actor_owner))
            ),
            C0FormationKind.AFTER_OCCURRENCE,
            actor_product=ports.actor_product,
            object_product=ports.object_product,
        ),
        C0CausalEdgeIR(ports.causal_key.value, trigger.occurrence_contract, ports.source_key.value),
    )
