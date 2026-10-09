"""Lower a typed author value law to a private K0 Action."""

from __future__ import annotations

import json
import keyword
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Any, Literal, get_args, get_type_hints

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
from nomos_kernel._dynamic_actor_abi import _K0ActorOwnerPort, _K0ActorParticipantPort
from nomos_kernel._dynamic_owner_abi import (
    _K0ClosedOwnerPort,
    _K0DynamicOwnerKind,
    _K0FormOwnerRequest,
    _K0IndividualOwnerPort,
    _K0IndividualRef,
)
from nomos_kernel._event_jump_abi import _K0ScheduleOnce
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0Owner,
    _K0OwnerView,
    _validate_closed_host_object,
)
from nomos_kernel._rule_products_abi import K0RuleResult

from .actor_domain_v1 import C0ActorDomainEffect, C0ActorDomainPorts
from .actor_product_v1 import C0ActorProductIR, actor_products
from .author_contract_v1 import C0LawError, _unique_object
from .composable_value_v1 import (
    _MAX_INT,
    C0ValuePorts,
    C0ValueProgram,
    C0ValueRangeError,
    C0ValueStateError,
    _assignable,
    compile_value_program,
)
from .semantic_ir_v0 import (
    C0ActionLawIR,
    C0FormationKind,
    C0ObjectFormationEffectIR,
    C0OccurrenceContractIR,
    C0ScheduleEffectIR,
    C0SelectedOwnerIR,
    C0StaticOwnerIR,
)


@dataclass(frozen=True)
class C0ValueActionEvidence:
    scene: object
    actor: object
    payload: object
    delay: int | None = None
    target: object | None = None
    target_owner: K0OwnerKey | None = None
    selected: tuple[tuple[str, object, K0OwnerKey], ...] = ()
    actor_owner: K0OwnerKey | None = None
    actor_ref: _K0ActorRef | None = None
    actor_views: tuple[_K0OwnerView, ...] = ()

    def validate_for_k0(self) -> None:
        if type(self) is not C0ValueActionEvidence:
            raise K0ProfileError("C0 Action evidence is malformed")
        if (
            (self.actor_owner is None) != (self.actor_ref is None)
            or (self.actor_owner is not None and type(self.actor_owner) is not K0OwnerKey)
            or (self.actor_ref is not None and type(self.actor_ref) is not _K0ActorRef)
        ):
            raise K0ProfileError("C0 Action self evidence lacks an exact instance binding")
        for value in (self.scene, self.actor, self.payload):
            validate = getattr(value, "validate_for_k0", None)
            if not callable(validate):
                raise K0ProfileError("C0 Action evidence has no nominal validation")
            validate()
        if self.delay is not None and (
            type(self.delay) is not int or not 0 < self.delay <= _MAX_INT
        ):
            raise K0ProfileError("C0 Action evidence has malformed scheduled delay")
        if (self.target is None) != (self.target_owner is None):
            raise K0ProfileError("C0 Action evidence has incomplete target basis")
        if self.target is not None:
            if type(self.target_owner) is not K0OwnerKey:
                raise K0ProfileError("C0 Action evidence target owner is malformed")
            validate = getattr(self.target, "validate_for_k0", None)
            if not callable(validate):
                raise K0ProfileError("C0 Action evidence target has no nominal validation")
            validate()
        if type(self.selected) is not tuple:
            raise K0ProfileError("C0 Action selected evidence is malformed")
        for item in self.selected:
            if (
                type(item) is not tuple
                or len(item) != 3
                or type(item[0]) is not str
                or not item[0]
                or type(item[2]) is not K0OwnerKey
            ):
                raise K0ProfileError("C0 Action selected evidence is malformed")
            validate = getattr(item[1], "validate_for_k0", None)
            if not callable(validate):
                raise K0ProfileError("C0 Action selected view has no nominal validation")
            validate()
        names = tuple(item[0] for item in self.selected)
        if names != tuple(sorted(set(names))):
            raise K0ProfileError("C0 Action selected evidence is not canonical")
        if type(self.actor_views) is not tuple or any(
            type(view) is not _K0OwnerView
            or type(view.actor_ref) is not _K0ActorRef
            or type(view.owner) is not K0OwnerKey
            or type(view.participant) is not str
            for view in self.actor_views
        ):
            raise K0ProfileError("C0 Action Actor domain evidence is malformed")
        if len({view.owner for view in self.actor_views}) != len(self.actor_views) or len(
            {view.actor_ref for view in self.actor_views}
        ) != len(self.actor_views):
            raise K0ProfileError("C0 Action Actor domain evidence aliases")
        for view in self.actor_views:
            view.view.validate_for_k0()


@dataclass(frozen=True)
class C0ValueActionParticipants:
    actor: str | _K0ActorRef
    target: _K0IndividualRef | None = None
    selected: tuple[tuple[str, str | _K0IndividualRef | _K0ActorRef], ...] = ()
    actors: tuple[tuple[str, _K0ActorRef, K0OwnerKey], ...] = ()

    def validate_for_k0(self) -> None:
        if (
            type(self) is not C0ValueActionParticipants
            or type(self.actor) not in (str, _K0ActorRef)
            or (type(self.actor) is str and not self.actor)
            or (self.target is not None and type(self.target) is not _K0IndividualRef)
            or type(self.selected) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or not item[0]
                or type(item[1]) not in (str, _K0IndividualRef, _K0ActorRef)
                for item in self.selected
            )
        ):
            raise K0ProfileError("C0 Action participants are malformed")
        names = tuple(item[0] for item in self.selected)
        if names != tuple(sorted(set(names))):
            raise K0ProfileError("C0 Action participants are not canonical")
        if (
            type(self.actors) is not tuple
            or any(
                type(pair) is not tuple
                or len(pair) != 3
                or type(pair[0]) is not str
                or type(pair[1]) is not _K0ActorRef
                or type(pair[2]) is not K0OwnerKey
                for pair in self.actors
            )
            or len({ref for _, ref, _ in self.actors}) != len(self.actors)
            or len({owner for _, _, owner in self.actors}) != len(self.actors)
        ):
            raise K0ProfileError("C0 Action Actor domain participants are malformed")


@dataclass(frozen=True)
class C0SelfActorPorts:
    family: str
    state_type: type
    factory: object

    @property
    def view_type(self):
        return self.state_type


@dataclass(frozen=True)
class C0ValueActionPorts:
    source_key: K0SourceSpecKey
    event_type: K0EventTypeKey
    scene_owner: _K0Owner
    actor_owner: _K0Owner | C0SelfActorPorts
    payload_type: type
    contribution_type: type
    envelope_type: type
    value_ports: C0ValuePorts
    actor_identity_field: str | None
    payload_actor_field: str
    state_effects: dict[str, dict[str, str]]
    envelope_fields: dict[str, str]
    sealed_envelope_fields: dict[str, object] | None = None
    schedule: C0ActionSchedulePorts | None = None
    form: C0ActionFormPorts | None = None
    target: C0ActionTargetPorts | None = None
    participants: tuple[C0ActionParticipantPorts, ...] = ()
    actor_product: C0ActorProductIR | None = None
    actor_domains: tuple[C0ActorDomainPorts, ...] = ()


@dataclass(frozen=True)
class C0ActionSchedulePorts:
    due_source: K0SourceSpecKey
    one_shot_field: str
    subject_output: str
    delay_output: str


@dataclass(frozen=True)
class C0ActionFormPorts:
    family: str
    state_type: type
    initial_output: str


@dataclass(frozen=True)
class C0ActionTargetPorts:
    payload_field: str
    state_type: type
    write: bool
    kind: _K0DynamicOwnerKind | None = None
    kinds: tuple[_K0DynamicOwnerKind, ...] = ()


@dataclass(frozen=True)
class C0ActionParticipantPorts:
    name: str
    selector: Literal["individual", "closed_domain", "actor"]
    payload_field: str
    state_type: type
    write: bool
    nullable: bool
    kind: _K0DynamicOwnerKind | None = None
    kinds: tuple[_K0DynamicOwnerKind, ...] = ()
    members: tuple[tuple[str, _K0Owner], ...] = ()
    identity_field: str | None = None
    actor_kind: C0SelfActorPorts | None = None


def _selection_ports(
    target: C0ActionTargetPorts | None,
    participants: tuple[C0ActionParticipantPorts, ...],
) -> tuple[C0ActionParticipantPorts, ...]:
    if target is not None:
        if participants:
            raise C0LawError("C0 Action cannot mix target and participant declarations")
        return (
            C0ActionParticipantPorts(
                "target",
                "individual",
                target.payload_field,
                target.state_type,
                target.write,
                False,
                target.kind,
                target.kinds,
            ),
        )
    return participants


def _active_selections(
    ports: tuple[C0SelectedOwnerIR, ...], payload: object
) -> tuple[C0SelectedOwnerIR, ...]:
    return tuple(
        port
        for port in ports
        if not (port.nullable and getattr(payload, port.payload_field) is None)
    )


def _selected_owner_ir(port: C0ActionParticipantPorts) -> C0SelectedOwnerIR:
    return C0SelectedOwnerIR(
        port.name,
        port.selector,
        port.payload_field,
        port.state_type,
        port.write,
        port.nullable,
        (port.actor_kind.family,)
        if port.actor_kind is not None
        else tuple(kind.family for kind in port.kinds),
        tuple((name, owner.key.value) for name, owner in port.members),
        port.identity_field,
    )


def _frozen_record(carrier: object) -> bool:
    return (
        isinstance(carrier, type)
        and is_dataclass(carrier)
        and carrier.__dataclass_params__.frozen
        and all(item.init for item in fields(carrier))
    )


def _checked_bindings(
    ports: C0ValueActionPorts,
) -> tuple[tuple[tuple[str, str, str], ...], tuple[tuple[str, str], ...]]:
    if type(ports) is not C0ValueActionPorts or type(ports.participants) is not tuple:
        raise C0LawError("C0 Action ports are malformed")
    selections = _selection_ports(ports.target, ports.participants)
    self_actor = type(ports.actor_owner) is C0SelfActorPorts
    names = tuple(item.name for item in selections if type(item) is C0ActionParticipantPorts)
    if (
        type(ports.source_key) is not K0SourceSpecKey
        or type(ports.event_type) is not K0EventTypeKey
        or not isinstance(ports.scene_owner, _K0Owner)
        or (not self_actor and not isinstance(ports.actor_owner, _K0Owner))
        or (not self_actor and ports.scene_owner.key == ports.actor_owner.key)
        or ports.scene_owner.view_type is not ports.scene_owner.state_type
        or ports.actor_owner.view_type is not ports.actor_owner.state_type
        or not _frozen_record(ports.payload_type)
        or not callable(getattr(ports.payload_type, "validate_for_k0", None))
        or not _frozen_record(ports.contribution_type)
        or not _frozen_record(ports.envelope_type)
        or type(ports.value_ports) is not C0ValuePorts
        or type(ports.state_effects) is not dict
        or set(ports.state_effects) != {"scene", "actor", *names}
        or type(ports.envelope_fields) is not dict
        or len(names) != len(selections)
        or names != tuple(sorted(set(names)))
        or len({item.payload_field for item in selections}) != len(selections)
    ):
        raise C0LawError("C0 Action owner and participant ports are malformed")
    try:
        for owner in (ports.scene_owner,) if self_actor else (ports.scene_owner, ports.actor_owner):
            _validate_closed_host_object(owner, "C0 Action owner")
    except K0ProfileError as error:
        raise C0LawError("C0 Action owner configuration is not closed") from error
    roots = {
        "scene": ports.scene_owner.view_type,
        "actor": ports.actor_owner.view_type,
        "payload": ports.payload_type,
    }
    if ports.target is not None and type(ports.target) is not C0ActionTargetPorts:
        raise C0LawError("C0 Action target declaration is malformed")
    payload_hints = get_type_hints(ports.payload_type)
    for selected in selections:
        if (
            type(selected.name) is not str
            or not selected.name.isidentifier()
            or keyword.iskeyword(selected.name)
            or selected.name in {"scene", "actor", "payload", "occurrence"}
            or type(selected.payload_field) is not str
            or not _frozen_record(selected.state_type)
            or type(selected.write) is not bool
            or type(selected.nullable) is not bool
            or (selected.nullable and selected.selector != "closed_domain")
        ):
            raise C0LawError("C0 Action participant declaration is malformed")
        if selected.selector == "individual":
            if (
                payload_hints.get(selected.payload_field) is not _K0IndividualRef
                or type(selected.kind) is not _K0DynamicOwnerKind
                or selected.kind.state_type is not selected.state_type
                or type(selected.kinds) is not tuple
                or not selected.kinds
                or any(type(kind) is not _K0DynamicOwnerKind for kind in selected.kinds)
                or selected.kind not in selected.kinds
                or any(kind.state_type is not selected.state_type for kind in selected.kinds)
                or tuple(kind.family for kind in selected.kinds)
                != tuple(sorted({kind.family for kind in selected.kinds}))
                or selected.members
                or selected.identity_field is not None
                or selected.actor_kind is not None
            ):
                raise C0LawError("C0 Action individual participant is not bound")
        elif selected.selector == "actor":
            kind = selected.actor_kind
            if (
                payload_hints.get(selected.payload_field) is not _K0ActorRef
                or type(kind) is not C0SelfActorPorts
                or type(kind.family) is not str
                or not kind.family
                or kind.state_type is not selected.state_type
                or getattr(kind.factory, "state_type", None) is not selected.state_type
                or not callable(getattr(kind.factory, "build", None))
                or selected.kind is not None
                or selected.kinds
                or selected.members
                or selected.identity_field is not None
            ):
                raise C0LawError("C0 Action Actor participant is not bound")
        elif selected.selector == "closed_domain":
            if (
                (
                    payload_hints.get(selected.payload_field) != str | None
                    if selected.nullable
                    else payload_hints.get(selected.payload_field) is not str
                )
                or selected.kind is not None
                or selected.kinds
                or selected.actor_kind is not None
                or type(selected.members) is not tuple
                or not selected.members
                or any(
                    type(member) is not tuple
                    or len(member) != 2
                    or type(member[0]) is not str
                    or not isinstance(member[1], _K0Owner)
                    or member[1].state_type is not selected.state_type
                    or member[1].view_type is not selected.state_type
                    for member in selected.members
                )
                or tuple(member[0] for member in selected.members)
                != tuple(sorted({member[0] for member in selected.members}))
                or type(selected.identity_field) is not str
                or get_type_hints(selected.state_type).get(selected.identity_field) is not str
            ):
                raise C0LawError("C0 Action closed participant is not bound")
        else:
            raise C0LawError("C0 Action participant selector is unknown")
        roots[selected.name] = (
            selected.state_type | None if selected.nullable else selected.state_type
        )
        if selected.write != bool(ports.state_effects[selected.name]):
            raise C0LawError("C0 Action participant write permission differs from its effects")
    if selections and ports.schedule is not None:
        raise C0LawError("C0 Action participants cannot combine scheduling")
    if ports.value_ports.roots != roots:
        raise C0LawError("C0 Action roots do not match their nominal owners")
    if (
        type(ports.payload_actor_field) is not str
        or (
            self_actor
            and (
                ports.actor_identity_field is not None
                or get_type_hints(roots["payload"]).get(ports.payload_actor_field)
                is not _K0ActorRef
            )
        )
        or (
            not self_actor
            and (
                type(ports.actor_identity_field) is not str
                or get_type_hints(roots["actor"]).get(ports.actor_identity_field) is not str
                or get_type_hints(roots["payload"]).get(ports.payload_actor_field) is not str
            )
        )
    ):
        raise C0LawError("C0 Action actor identity ports are not nominal strings")
    contribution_fields = get_type_hints(ports.contribution_type)
    if set(contribution_fields) != {"owner", "state"}:
        raise C0LawError("C0 Action contribution carrier is not owner/state")
    if contribution_fields["owner"] is not K0OwnerKey:
        raise C0LawError("C0 Action contribution owner field is mistyped")
    state_types = set(get_args(contribution_fields["state"]))
    static_states = (
        {roots["scene"]}
        | (set() if self_actor else {roots["actor"]})
        | {item.state_type for item in selections if item.selector == "closed_domain"}
    )
    if not state_types:
        state_types = {contribution_fields["state"]}
    if not static_states <= state_types or any(not _frozen_record(item) for item in state_types):
        raise C0LawError("C0 Action contribution state field misses a nominal owner")
    if not callable(getattr(ports.contribution_type, "validate_for_k0", None)) or not callable(
        getattr(ports.envelope_type, "validate_for_k0", None)
    ):
        raise C0LawError("C0 Action result carriers need K0 validation")

    state: list[tuple[str, str, str]] = []
    used: list[str] = []
    closed_identities = {
        item.name: item.identity_field for item in selections if item.selector == "closed_domain"
    }
    for root, carrier in ((name, value) for name, value in roots.items() if name != "payload"):
        mapping = ports.state_effects[root]
        if type(mapping) is not dict:
            raise C0LawError("C0 Action effect must declare each owner write map")
        carrier = next((item.state_type for item in selections if item.name == root), carrier)
        annotations = get_type_hints(carrier)
        for field, output in mapping.items():
            if (
                (root in names and not selections[names.index(root)].write)
                or field == closed_identities.get(root)
                or type(field) is not str
                or field not in annotations
                or field not in ports.value_ports.writable_fields.get(carrier, frozenset())
                or type(output) is not str
                or not _assignable(ports.value_ports.outputs.get(output), annotations[field])
            ):
                raise C0LawError("C0 Action effect crosses a typed owner write port")
            state.append((root, field, output))
            used.append(output)
    form = ports.form
    if form is not None and (
        type(form) is not C0ActionFormPorts
        or type(form.family) is not str
        or not form.family
        or not _frozen_record(form.state_type)
        or not callable(getattr(form.state_type, "validate_for_k0", None))
        or type(form.initial_output) is not str
        or ports.value_ports.outputs.get(form.initial_output) is not form.state_type
    ):
        raise C0LawError("C0 Action formation lacks one typed initial-state output")
    if ports.actor_product is not None:
        ports.actor_product.check(ports.value_ports.outputs)
    if not state and form is None and ports.actor_product is None:
        raise C0LawError("C0 Action must write or form at least one owner")
    envelope_annotations = get_type_hints(ports.envelope_type)
    if set(ports.envelope_fields) != set(envelope_annotations):
        raise C0LawError("C0 Action envelope does not fill its nominal fields")
    if ports.sealed_envelope_fields is not None and (
        type(ports.sealed_envelope_fields) is not dict
        or not set(ports.sealed_envelope_fields) <= set(ports.envelope_fields)
    ):
        raise C0LawError("C0 Action sealed envelope fields lack declared ports")
    envelope: list[tuple[str, str]] = []
    for field, output in ports.envelope_fields.items():
        if (
            type(field) is not str
            or type(output) is not str
            or envelope_annotations[field] != ports.value_ports.outputs.get(output)
        ):
            raise C0LawError("C0 Action envelope output has the wrong type")
        envelope.append((field, output))
        used.append(output)
    if form is not None:
        used.append(form.initial_output)
    if ports.actor_product is not None:
        used.append(ports.actor_product.initial_output)
    if len(used) != len(set(used)) or set(used) != set(ports.value_ports.outputs):
        schedule = ports.schedule
        if schedule is None:
            raise C0LawError("C0 Action outputs are missing or multiply assigned")
        if (
            type(schedule) is not C0ActionSchedulePorts
            or type(schedule.due_source) is not K0SourceSpecKey
            or type(schedule.one_shot_field) is not str
            or get_type_hints(roots["actor"]).get(schedule.one_shot_field) != K0OccurrenceRef | None
            or not any(
                root == "actor" and field == schedule.one_shot_field for root, field, _ in state
            )
            or schedule.subject_output == schedule.delay_output
            or ports.value_ports.outputs.get(schedule.subject_output) is not str
            or ports.value_ports.outputs.get(schedule.delay_output) is not int
            or set(used + [schedule.subject_output, schedule.delay_output])
            != set(ports.value_ports.outputs)
            or len(used + [schedule.subject_output, schedule.delay_output])
            != len(set(used + [schedule.subject_output, schedule.delay_output]))
        ):
            raise C0LawError("C0 Action schedule crosses its typed one-shot ports")
    elif ports.schedule is not None:
        raise C0LawError("C0 Action schedule lacks its typed value outputs")
    return tuple(state), tuple(envelope)


def _schedule_ir(ports: C0ValueActionPorts) -> C0ScheduleEffectIR | None:
    schedule = ports.schedule
    if schedule is None:
        return None
    if type(schedule) is not C0ActionSchedulePorts:
        raise C0LawError("Action schedule lacks checked ports")
    marker = ports.state_effects["actor"].get(schedule.one_shot_field)
    if marker is None:
        raise C0LawError("Action schedule lacks its one-shot marker output")
    return C0ScheduleEffectIR(
        schedule.due_source.value,
        schedule.one_shot_field,
        marker,
        schedule.subject_output,
        schedule.delay_output,
    )


def _form_ir(ports: C0ValueActionPorts) -> C0ObjectFormationEffectIR | None:
    form = ports.form
    if form is not None and type(form) is not C0ActionFormPorts:
        raise C0LawError("Action formation lacks checked ports")
    return (
        None
        if form is None
        else C0ObjectFormationEffectIR(form.family, form.state_type, form.initial_output)
    )


def _self_actor_ir(ports):
    actor = ports.actor_owner
    return (actor.family, actor.state_type) if type(actor) is C0SelfActorPorts else None


def _static_actor_owners(ports):
    owners = (C0StaticOwnerIR("scene", ports.scene_owner.key.value, ports.scene_owner.state_type),)
    if type(ports.actor_owner) is not C0SelfActorPorts:
        owners += (
            C0StaticOwnerIR("actor", ports.actor_owner.key.value, ports.actor_owner.state_type),
        )
    return owners


@dataclass(frozen=True)
class _C0ActionBasis:
    scene_type: type
    actor_type: type
    payload_type: type
    actor_identity_field: str | None
    payload_actor_field: str
    target_type: type | None
    participants: tuple[C0SelectedOwnerIR, ...]

    def roots(
        self,
        scene: object,
        actor: object,
        payload: object,
        target: object | None = None,
        selected: tuple[tuple[str, object, K0OwnerKey], ...] = (),
    ) -> dict[str, object]:
        if (
            type(scene) is not self.scene_type
            or type(actor) is not self.actor_type
            or type(payload) is not self.payload_type
        ):
            raise K0ProfileError("compiled Action received a foreign nominal view")
        if self.actor_identity_field is not None and (
            getattr(actor, self.actor_identity_field) != getattr(payload, self.payload_actor_field)
        ):
            raise K0ProfileError("compiled Action payload has another Actor's authority")
        roots = {"scene": scene, "actor": actor, "payload": payload}
        if self.target_type is not None:
            if type(target) is not self.target_type:
                raise K0ProfileError("compiled Action received a foreign target view")
            roots["target"] = target
        elif target is not None:
            raise K0ProfileError("compiled Action received an undeclared target view")
        if self.participants:
            active = _active_selections(self.participants, payload)
            if tuple(name for name, _, _ in selected) != tuple(port.root for port in active):
                raise K0ProfileError("compiled Action selected participants are incomplete")
            for port in self.participants:
                if port.nullable and getattr(payload, port.payload_field) is None:
                    roots[port.root] = None
            for port, (_, view, _) in zip(active, selected, strict=True):
                if type(view) is not port.state_type:
                    raise K0ProfileError("compiled Action received a foreign participant view")
                roots[port.root] = view
        elif selected:
            raise K0ProfileError("compiled Action received undeclared selected views")
        return roots


@dataclass(frozen=True)
class C0ValueActionProgram:
    ir: C0ActionLawIR
    ports: C0ValueActionPorts

    def __post_init__(self) -> None:
        if (
            type(self.ir) is not C0ActionLawIR
            or self.ir.source_key != self.ports.source_key.value
            or self.ir.event_type != self.ports.event_type.value
            or self.ir.value._ports != self.ports.value_ports
            or tuple(sorted(self.ir.effects))
            != tuple(
                sorted(
                    (root, field, output)
                    for root, fields in self.ports.state_effects.items()
                    for field, output in fields.items()
                )
            )
            or self.ir.envelope_fields != tuple(self.ports.envelope_fields.items())
            or self.ir.owners != _static_actor_owners(self.ports)
            or self.ir.self_actor != _self_actor_ir(self.ports)
            or self.ir.selected
            != tuple(
                _selected_owner_ir(port)
                for port in _selection_ports(self.ports.target, self.ports.participants)
            )
            or self.ir.target_mode != (self.ports.target is not None)
            or self.ir.schedule != _schedule_ir(self.ports)
            or self.ir.form != _form_ir(self.ports)
            or self.ir.actor_product != self.ports.actor_product
            or type(self.ir.actor_domains) is not tuple
            or any(type(domain) is not C0ActorDomainEffect for domain in self.ir.actor_domains)
            or tuple(domain.ports for domain in self.ir.actor_domains) != self.ports.actor_domains
        ):
            raise C0LawError("Action IR differs from its checked ports")
        expected_roots = {
            **self.ports.value_ports.roots,
            "initiator": self.actor_owner.view_type,
        }
        names = set()
        kinds = set()
        for domain in self.ir.actor_domains:
            domain.__post_init__()
            if (
                domain.ports.name in {*expected_roots, "occurrence"}
                or domain.ports.name in names
                or domain.ports.kind.symbol in kinds
                or domain.value._ports.roots
                != {**expected_roots, "actor": domain.ports.kind.factory.state_type}
            ):
                raise C0LawError("Action Actor domain roots differ from its checked basis")
            names.add(domain.ports.name)
            kinds.add(domain.ports.kind.symbol)
        from .expression_ir_v1 import freeze_value_tree

        object.__setattr__(
            self,
            "ports",
            replace(
                self.ports,
                state_effects=freeze_value_tree(self.ports.state_effects),
                envelope_fields=freeze_value_tree(self.ports.envelope_fields),
                sealed_envelope_fields=(
                    None
                    if self.ports.sealed_envelope_fields is None
                    else freeze_value_tree(self.ports.sealed_envelope_fields)
                ),
            ),
        )

    def _domain_roots(self, roots):
        return {**roots, "initiator": roots["actor"]}

    def _check_domain_views(self, views):
        domains = {domain.ports.name: domain for domain in self.ir.actor_domains}
        if any(
            view.participant not in domains
            or type(view.actor_ref) is not _K0ActorRef
            or view.actor_ref.family != domains[view.participant].ports.kind.symbol
            or type(view.view) is not domains[view.participant].ports.kind.factory.state_type
            for view in views
        ):
            raise K0ProfileError("Action lost its nominal Actor domain basis")

    @property
    def source_key(self) -> K0SourceSpecKey:
        return K0SourceSpecKey(self.ir.source_key)

    @property
    def event_type(self) -> K0EventTypeKey:
        return K0EventTypeKey(self.ir.event_type)

    @property
    def value(self) -> C0ValueProgram:
        return self.ir.value

    @property
    def state_effects(self) -> tuple[tuple[str, str, str], ...]:
        return self.ir.effects

    @property
    def occurrence_contract(self) -> C0OccurrenceContractIR:
        return C0OccurrenceContractIR(
            self.ir.source_key,
            self.ir.event_type,
            K0OccurrenceFamily.ACTION,
            self.envelope_type,
            C0ValueActionParticipants,
        )

    @property
    def envelope_fields(self) -> tuple[tuple[str, str], ...]:
        return self.ir.envelope_fields

    @property
    def scene_owner(self) -> _K0Owner:
        return self.ports.scene_owner

    @property
    def actor_owner(self) -> _K0Owner:
        return self.ports.actor_owner

    @property
    def payload_type(self) -> type:
        return self.ports.payload_type

    @property
    def contribution_type(self) -> type:
        return self.ports.contribution_type

    @property
    def envelope_type(self) -> type:
        return self.ports.envelope_type

    @property
    def actor_identity_field(self) -> str:
        return self.ports.actor_identity_field

    @property
    def payload_actor_field(self) -> str:
        return self.ports.payload_actor_field

    @property
    def schedule(self) -> C0ScheduleEffectIR | None:
        return self.ir.schedule

    @property
    def form(self) -> C0ObjectFormationEffectIR | None:
        return self.ir.form

    @property
    def target(self) -> C0ActionTargetPorts | None:
        return self.ports.target

    @property
    def participants(self) -> tuple[C0ActionParticipantPorts, ...]:
        return self.ports.participants

    def _selections(self) -> tuple[C0SelectedOwnerIR, ...]:
        return self.ir.selected

    def _has_target(self) -> bool:
        return self.ir.target_mode

    def _cost_basis(self) -> _C0ActionBasis:
        return _C0ActionBasis(
            self.scene_owner.view_type,
            self.actor_owner.view_type,
            self.payload_type,
            self.actor_identity_field,
            self.payload_actor_field,
            self.ir.selected[0].state_type if self._has_target() else None,
            self.ir.selected if not self._has_target() else (),
        )

    def _roots(
        self,
        scene: object,
        actor: object,
        payload: object,
        target: object | None = None,
        selected: tuple[tuple[str, object, K0OwnerKey], ...] = (),
    ) -> dict[str, object]:
        return self._cost_basis().roots(scene, actor, payload, target, selected)

    def _basis(self, rule_input: _K0InMemoryRuleInput) -> dict[str, object]:
        if (
            type(rule_input) is not _K0InMemoryRuleInput
            or rule_input.source != self.source_key
            or rule_input.trigger is not None
            or rule_input.bindings
            or type(rule_input.evidence) is not C0ValueActionEvidence
            or type(rule_input.participants) is not C0ValueActionParticipants
        ):
            raise K0ProfileError("compiled Action has foreign rule basis")
        evidence = rule_input.evidence
        self._check_domain_views(evidence.actor_views)
        if rule_input.participants.actors != tuple(
            (view.participant, view.actor_ref, view.owner) for view in evidence.actor_views
        ):
            raise K0ProfileError("Action domain participants disagree with sealed evidence")
        if self.ir.self_actor is not None and (
            evidence.actor_ref is None
            or evidence.actor_ref != getattr(evidence.payload, self.payload_actor_field)
            or evidence.actor_ref.family != self.ir.self_actor[0]
            or evidence.actor_owner is None
        ):
            raise K0ProfileError("compiled self Action lost its exact instance basis")
        if self.ir.self_actor is None and evidence.actor_ref is not None:
            raise K0ProfileError("fixed Actor Action carries a foreign self basis")
        roots = self._roots(
            evidence.scene, evidence.actor, evidence.payload, evidence.target, evidence.selected
        )
        if (not self._has_target()) != (evidence.target_owner is None):
            raise K0ProfileError("compiled Action target basis is incomplete")
        if (self.schedule is None) != (evidence.delay is None):
            raise K0ProfileError("compiled Action has a foreign scheduled delay")
        if (
            self.schedule is not None
            and getattr(evidence.actor, self.schedule.one_shot_field) is not None
        ):
            raise K0ProfileError("scheduled Action lost its one-shot basis")
        if rule_input.participants.actor != getattr(evidence.payload, self.payload_actor_field):
            raise K0ProfileError("compiled Action participants disagree with payload")
        target_ref = (
            getattr(evidence.payload, self.ir.selected[0].payload_field)
            if self._has_target()
            else None
        )
        if rule_input.participants.target != target_ref:
            raise K0ProfileError("compiled Action target participant disagrees with payload")
        expected = tuple(
            (port.root, getattr(evidence.payload, port.payload_field))
            for port in _active_selections(self.ir.selected, evidence.payload)
            if not self._has_target()
        )
        if rule_input.participants.selected != expected:
            raise K0ProfileError("compiled Action selected participants disagree with payload")
        for port, (_, _, owner) in zip(
            (() if self._has_target() else _active_selections(self.ir.selected, evidence.payload)),
            evidence.selected,
            strict=True,
        ):
            if (
                port.selector == "closed_domain"
                and dict((name, K0OwnerKey(key)) for name, key in port.members).get(
                    getattr(evidence.payload, port.payload_field)
                )
                != owner
            ):
                raise K0ProfileError("compiled Action selected a foreign closed owner")
            if port.selector == "closed_domain" and getattr(
                roots[port.root], port.identity_field
            ) != getattr(evidence.payload, port.payload_field):
                raise K0ProfileError("compiled Action selected a mismatched Actor identity")
        try:
            self.ir.condition(roots, formed=True)
        except C0ValueStateError as error:
            raise K0ProfileError("compiled Action basis has malformed owner state") from error
        return roots

    def _outputs(self, rule_input: _K0InMemoryRuleInput) -> dict[str, object]:
        roots = self._basis(rule_input)
        try:
            result = self.ir.evaluate(roots, occurrence=rule_input.occurrence)
        except C0ValueStateError as error:
            raise K0ProfileError("compiled Action effect failed on sealed basis") from error
        return result

    def build_spec(self, *, action_cost_projector=None) -> _K0InMemorySourceSpec:
        """Return the exact spec to register in the caller's private K0 profile."""
        keys = tuple(sorted(K0OwnerKey(owner.key) for owner in self.ir.owners))
        contributions = tuple(
            K0OwnerKey(owner.key)
            for owner in self.ir.owners
            if any(effect_root == owner.root for effect_root, _, _ in self.ir.effects)
        )
        return _K0InMemorySourceSpec(
            self.source_key,
            K0OccurrenceFamily.ACTION,
            self.event_type,
            self.payload_type,
            C0ValueActionEvidence,
            C0ValueActionParticipants,
            keys,
            tuple(sorted(contributions)),
            (),
            (),
            _Admission(self, _K0CapabilityRef("c0.value_action.admission.v1")),
            _Rule(self, _K0CapabilityRef("c0.value_action.rule.v1")),
            self.envelope_type,
            () if self.schedule is None else (K0SourceSpecKey(self.schedule.due_source),),
            form_owner_family=None if self.form is None else self.form.family,
            actor_product=None if self.ir.actor_product is None else self.ir.actor_product.port(),
            action_cost_projector=action_cost_projector,
            actor_self=None
            if self.ir.self_actor is None
            else _K0ActorOwnerPort(
                self.payload_actor_field,
                self.ir.self_actor[0],
                bool(self.ports.state_effects["actor"]),
            ),
            participant_ports=tuple(
                _K0IndividualOwnerPort(
                    port.root,
                    port.payload_field,
                    port.families,
                    port.write,
                )
                if port.selector == "individual"
                else _K0ActorParticipantPort(
                    port.root, port.payload_field, port.families[0], port.write
                )
                if port.selector == "actor"
                else _K0ClosedOwnerPort(
                    port.root,
                    port.payload_field,
                    tuple((name, K0OwnerKey(key)) for name, key in port.members),
                    port.write,
                    port.nullable,
                )
                for port in self.ir.selected
            ),
            actor_domains=tuple(domain.port() for domain in self.ir.actor_domains),
        )


@dataclass(frozen=True)
class _Admission:
    program: C0ValueActionProgram
    capability_ref: _K0CapabilityRef

    def admit(
        self, payload: object, views: tuple[_K0OwnerView, ...]
    ) -> _K0AdmissionProjection | None:
        if type(payload) is not self.program.payload_type:
            return None
        by_owner = {item.owner: item.view for item in views}
        try:
            scene = by_owner[self.program.scene_owner.key]
            self_view = next((item for item in views if item.participant == "actor"), None)
            actor = (
                self_view.view
                if self.program.ir.self_actor is not None and self_view is not None
                else by_owner[self.program.actor_owner.key]
            )
        except KeyError as error:
            raise K0ProfileError("compiled Action lacks a declared owner view") from error
        domain_names = {domain.ports.name for domain in self.program.ir.actor_domains}
        actor_views = tuple(view for view in views if view.participant in domain_names)
        self.program._check_domain_views(actor_views)
        selected_views = {
            item.participant: item
            for item in views
            if item.participant is not None and item.participant not in domain_names
        }
        self_owner = self_ref = None
        if self.program.ir.self_actor is not None:
            chosen = selected_views.pop("actor", None)
            if chosen is None or chosen.actor_ref != getattr(
                payload, self.program.payload_actor_field
            ):
                return None
            self_owner, self_ref = chosen.owner, chosen.actor_ref
        declared = _active_selections(self.program._selections(), payload)
        if set(selected_views) != {port.root for port in declared}:
            raise K0ProfileError("compiled Action lacks its selected participant views")
        if any(
            port.selector == "actor"
            and (
                selected_views[port.root].actor_ref != getattr(payload, port.payload_field)
                or type(selected_views[port.root].actor_ref) is not _K0ActorRef
                or selected_views[port.root].actor_ref.family not in port.families
            )
            for port in declared
        ):
            return None
        target_view = None
        target_owner = None
        selected = ()
        if self.program._has_target():
            chosen = selected_views["target"]
            target_view, target_owner = chosen.view, chosen.owner
        elif declared:
            selected = tuple(
                (port.root, selected_views[port.root].view, selected_views[port.root].owner)
                for port in declared
            )
        try:
            roots = self.program._roots(scene, actor, payload, target_view, selected)
        except K0ProfileError:
            return None
        if any(
            port.selector == "closed_domain"
            and getattr(roots[port.root], port.identity_field)
            != getattr(payload, port.payload_field)
            for port in (() if self.program._has_target() else declared)
        ):
            return None
        if not self.program.ir.condition(roots):
            return None
        # Every required member admits on the same prestate before any output is evaluated.
        domain_roots = self.program._domain_roots(roots)
        for domain in self.program.ir.actor_domains:
            for view in actor_views:
                if view.participant == domain.ports.name and not domain.value.admits(
                    {**domain_roots, "actor": view.view}
                ):
                    return None
        if self.program.schedule is not None and (
            getattr(actor, self.program.schedule.one_shot_field) is not None
        ):
            return None
        evidence = C0ValueActionEvidence(
            scene,
            actor,
            payload,
            target=target_view,
            target_owner=target_owner,
            selected=selected,
            actor_owner=self_owner,
            actor_ref=self_ref,
            actor_views=actor_views,
        )
        target_ref = (
            None if not self.program._has_target() else getattr(payload, declared[0].payload_field)
        )
        participants = C0ValueActionParticipants(
            getattr(payload, self.program.payload_actor_field),
            target_ref,
            tuple(
                (port.root, getattr(payload, port.payload_field))
                for port in (() if self.program._has_target() else declared)
            ),
            tuple((view.participant, view.actor_ref, view.owner) for view in actor_views),
        )
        return _K0AdmissionProjection(evidence, participants, ())

    def admit_at_time(
        self, payload: object, views: tuple[_K0OwnerView, ...], time: _K0FixedTime
    ) -> _K0AdmissionProjection | None:
        if type(time) is not _K0FixedTime:
            raise K0ProfileError("scheduled Action received malformed K0 time")
        projection = self.admit(payload, views)
        if projection is None:
            return None
        if self.program.schedule is not None:
            evidence = projection.evidence
            roots = self.program._roots(
                evidence.scene,
                evidence.actor,
                evidence.payload,
                evidence.target,
                evidence.selected,
            )
            try:
                outputs = self.program.value.evaluate_admission_outputs(roots)
            except C0ValueRangeError:
                return None
            except C0ValueStateError as error:
                raise K0ProfileError(
                    "scheduled Action admission has malformed owner state"
                ) from error
            if outputs is None:
                return None
            delay = outputs[self.program.schedule.delay_output]
            if type(delay) is not int or not 0 < delay <= _MAX_INT - time.ordinal:
                return None
            return _K0AdmissionProjection(
                replace(evidence, delay=delay), projection.participants, projection.bindings
            )
        return projection


@dataclass(frozen=True)
class _Rule:
    program: C0ValueActionProgram
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        outputs = self.program._outputs(rule_input)
        scene = rule_input.evidence.scene
        actor = rule_input.evidence.actor
        changes: dict[str, dict[str, object]] = {
            root: {}
            for root in ("scene", "actor", *(port.root for port in self.program._selections()))
        }
        for root, field, output in self.program.state_effects:
            changes[root][field] = outputs[output]
        contributions = []
        for root, owner, state in (
            ("scene", self.program.scene_owner, scene),
            (
                "actor",
                self.program.actor_owner
                if self.program.ir.self_actor is None
                else self.program.actor_owner.factory.build(rule_input.evidence.actor_owner),
                actor,
            ),
        ):
            if not changes[root]:
                continue
            state = replace(state, **changes[root])
            owner.validate_state(state)
            if owner.read_view(state) is not state:
                raise K0ProfileError("compiled Action owner view loses state")
            contribution = owner.contribution_type(owner.key, state)
            owner.validate_contribution(contribution)
            contributions.append(contribution)
        evidence = rule_input.evidence
        selected = (
            (("target", evidence.target, evidence.target_owner),)
            if self.program._has_target()
            else evidence.selected
        )
        carrier_ports = {
            port.name: port
            for port in _selection_ports(self.program.ports.target, self.program.ports.participants)
        }
        for port, (_, before, owner_key) in zip(
            _active_selections(self.program._selections(), evidence.payload), selected, strict=True
        ):
            if not changes[port.root]:
                continue
            if port.selector == "individual":
                individual = getattr(evidence.payload, port.payload_field)
                if individual.family not in port.families:
                    raise K0ProfileError("compiled Action participant has a foreign family")
                kind = next(
                    (
                        item
                        for item in carrier_ports[port.root].kinds
                        if item.family == individual.family
                    ),
                    None,
                )
                if kind is None:
                    raise K0ProfileError("compiled Action participant has a foreign family")
                owner = kind.factory.build(owner_key)
            elif port.selector == "actor":
                actor_ref = getattr(evidence.payload, port.payload_field)
                if type(actor_ref) is not _K0ActorRef or actor_ref.family not in port.families:
                    raise K0ProfileError("compiled Action participant has a foreign Actor family")
                owner = carrier_ports[port.root].actor_kind.factory.build(owner_key)
            else:
                member_key = dict(port.members).get(getattr(evidence.payload, port.payload_field))
                owner = next(
                    (
                        item
                        for _, item in carrier_ports[port.root].members
                        if item.key.value == member_key
                    ),
                    None,
                )
                if owner is None or owner.key != owner_key:
                    raise K0ProfileError("compiled Action participant has a foreign owner")
            state = replace(before, **changes[port.root])
            owner.validate_state(state)
            contribution = owner.contribution_type(owner.key, state)
            owner.validate_contribution(contribution)
            contributions.append(contribution)
        scheduled = ()
        if self.program.ir.actor_domains:
            # Earlier contributions are candidates, never roots for another member's law.
            domain_roots = self.program._domain_roots(self.program._basis(rule_input))
            try:
                for domain in self.program.ir.actor_domains:
                    for view in evidence.actor_views:
                        if view.participant == domain.ports.name:
                            contributions.append(
                                domain.contribution(view, domain_roots, rule_input.occurrence)
                            )
            except C0ValueStateError as error:
                raise K0ProfileError("Action Actor domain effect failed on sealed basis") from error
        if self.program.schedule is not None:
            schedule = self.program.schedule
            if rule_input.time is None or type(rule_input.time) is not _K0FixedTime:
                raise K0ProfileError("scheduled Action has no current K0 time")
            if getattr(actor, schedule.one_shot_field) is not None:
                raise K0ProfileError("scheduled Action lost its one-shot basis")
            delay = outputs[schedule.delay_output]
            subject = outputs[schedule.subject_output]
            roots = self.program._roots(
                scene,
                actor,
                rule_input.evidence.payload,
                rule_input.evidence.target,
                rule_input.evidence.selected,
            )
            try:
                admitted = self.program.value.evaluate_admission_outputs(roots)
            except C0ValueStateError as error:
                raise K0ProfileError("scheduled Action lost its admitted delay") from error
            if (
                admitted is None
                or type(delay) is not int
                or delay != rule_input.evidence.delay
                or delay != admitted[schedule.delay_output]
                or not 0 < delay <= _MAX_INT - rule_input.time.ordinal
                or type(subject) is not str
                or not subject
            ):
                raise K0ProfileError("scheduled Action has malformed typed delay or subject")
            scheduled = (
                _K0ScheduleOnce(
                    _K0FixedTime(rule_input.time.ordinal + delay),
                    K0SourceSpecKey(schedule.due_source),
                    subject,
                ),
            )
        formed = ()
        if self.program.form is not None:
            form = self.program.form
            initial = outputs[form.initial_output]
            if type(initial) is not form.state_type:
                raise K0ProfileError("compiled Action formed a foreign state type")
            initial.validate_for_k0()
            formed = (_K0FormOwnerRequest(form.family, initial),)
        result = K0RuleResult(
            tuple(sorted(contributions, key=lambda item: item.owner)),
            (),
            scheduled,
            formed,
            actor_products(self.program.ir.actor_product, outputs),
        )

        envelope = self.program.envelope_type(
            **{field: outputs[output] for field, output in self.program.envelope_fields}
        )
        envelope.validate_for_k0()
        return _K0InMemoryEvaluation(result, envelope)


def compile_composable_action(
    source: str,
    ports: C0ValueActionPorts,
    *,
    actor_domains: tuple[C0ActorDomainEffect, ...] = (),
) -> C0ValueActionProgram:
    """Compile one authored Action without a world-specific effect callback."""
    if type(source) is not str or not source or len(source) > 65536:
        raise C0LawError("C0 Action source is empty or too large")
    try:
        row: Any = json.loads(source, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise C0LawError("C0 Action source is not valid JSON") from error
    if type(row) is not dict or set(row) not in (
        {"schema", "source_key", "event_type", "value"},
        {"schema", "source_key", "event_type", "value", "schedule"},
    ):
        raise C0LawError("C0 Action source has missing or unknown fields")
    if row["schema"] != "c0.action.value.v1":
        raise C0LawError("C0 Action source schema is unknown")
    state_effects, envelope_fields = _checked_bindings(ports)
    try:
        source_key = K0SourceSpecKey(row["source_key"])
        event_type = K0EventTypeKey(row["event_type"])
    except (TypeError, K0ProfileError) as error:
        raise C0LawError("C0 Action identity is malformed") from error
    if source_key != ports.source_key or event_type != ports.event_type:
        raise C0LawError("C0 Action identity does not match its trusted binding")
    schedule = ports.schedule
    if (
        schedule is None
        and "schedule" in row
        or schedule is not None
        and row.get("schedule")
        != {
            "source": schedule.due_source.value,
            "subject_output": schedule.subject_output,
            "delay_output": schedule.delay_output,
        }
    ):
        raise C0LawError("C0 Action schedule does not match its trusted binding")
    if schedule is not None:
        value_row = row["value"]
        delay_node = (
            value_row.get("outputs", {}).get(schedule.delay_output)
            if type(value_row) is dict and type(value_row.get("outputs")) is dict
            else None
        )
        if (
            type(delay_node) is dict
            and set(delay_node) == {"const"}
            and (type(delay_node["const"]) is not int or not 0 < delay_node["const"] <= _MAX_INT)
        ):
            raise C0LawError("scheduled Action delay literal must be positive and bounded")
    value = compile_value_program(
        json.dumps(row["value"]),
        ports.value_ports,
        admission_outputs=frozenset({schedule.delay_output})
        if schedule is not None
        else frozenset(),
        state_outputs={f"{root}.{field}": output for root, field, output in state_effects},
    )
    for field, expected in (ports.sealed_envelope_fields or {}).items():
        output = ports.envelope_fields[field]
        try:
            actual_source = json.dumps(
                row["value"]["outputs"][output], sort_keys=True, separators=(",", ":")
            )
            expected_source = json.dumps(expected, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise C0LawError("C0 Action sealed envelope expression is malformed") from error
        if actual_source != expected_source:
            raise C0LawError("C0 Action envelope violates its selected identity contract")
    return C0ValueActionProgram(
        C0ActionLawIR(
            source_key=source_key.value,
            event_type=event_type.value,
            value=value,
            effects=state_effects,
            owners=_static_actor_owners(ports),
            formation=C0FormationKind.SUBMIT,
            envelope_fields=envelope_fields,
            selected=tuple(
                _selected_owner_ir(port)
                for port in _selection_ports(ports.target, ports.participants)
            ),
            target_mode=ports.target is not None,
            schedule=_schedule_ir(ports),
            form=_form_ir(ports),
            actor_product=ports.actor_product,
            self_actor=_self_actor_ir(ports),
            actor_domains=actor_domains,
        ),
        replace(ports, value_ports=value._ports),
    )
