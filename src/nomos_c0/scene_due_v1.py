"""Compile a bounded Scene collection due-transition LawDef into private K0."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass, replace
from types import MappingProxyType
from typing import get_args, get_origin, get_type_hints

from nomos_kernel import (
    K0CausalLawKey,
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OccurrenceRef,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryEvaluation,
    _K0InMemoryRuleInput,
    _K0InMemorySourceSpec,
)
from nomos_kernel._causal_law_abi import K0CausalLawDefinition
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0OwnerView,
    _validate_closed_host_object,
)
from nomos_kernel._rule_products_abi import K0RuleResult, _K0Activation

from .author_contract_v1 import C0LawError, _exact, _object, _source_object
from .scene_action_v1 import _check_carriers, _check_fields, _parse_when

_FORMALS = ("carrier_id", "from_status", "due_field", "to_status", "receipt_field")
_OPCODE = "collection_member_due_transition.v1"


@dataclass(frozen=True)
class C0SceneDuePorts:
    """Trusted K0 identity and nominal fields for one complete transition."""

    scene_owner: K0OwnerKey
    law_key: K0CausalLawKey
    trigger_source: K0SourceSpecKey
    trigger_event: K0EventTypeKey
    result_source: K0SourceSpecKey
    result_event: K0EventTypeKey
    scene_type: type
    member_type: type
    evidence_type: type
    participants_type: type
    envelope_type: type
    contribution_type: type
    collection_field: str
    clock_field: str
    member_id_field: str
    status_field: str
    recipient_field: str
    evidence_member_field: str
    evidence_recipient_field: str
    carrier_id: str
    transition: tuple[str, str, str, str]
    phase: str
    trigger_phase: str
    actor_label: str
    kind_label: str


@dataclass(frozen=True)
class C0SceneDueLibraryRegistration:
    manifest_source: str
    ports: dict[str, C0SceneDuePorts]


def _nullable(annotation: object, exact_type: type) -> bool:
    return set(get_args(annotation)) == {exact_type, type(None)}


def _check_ports(ports: C0SceneDuePorts) -> None:
    if type(ports) is not C0SceneDuePorts:
        raise C0LawError("Scene due port is not trusted native input")
    try:
        _validate_closed_host_object(ports, "Scene due port")
    except K0ProfileError as error:
        raise C0LawError("Scene due port is not recursively closed") from error
    if (
        any(
            type(getattr(ports, field)) is not expected
            for field, expected in (
                ("scene_owner", K0OwnerKey),
                ("law_key", K0CausalLawKey),
                ("trigger_source", K0SourceSpecKey),
                ("trigger_event", K0EventTypeKey),
                ("result_source", K0SourceSpecKey),
                ("result_event", K0EventTypeKey),
            )
        )
        or any(
            type(getattr(ports, field)) is not str or not getattr(ports, field)
            for field in (
                "collection_field",
                "clock_field",
                "member_id_field",
                "status_field",
                "recipient_field",
                "evidence_member_field",
                "evidence_recipient_field",
                "carrier_id",
                "phase",
                "trigger_phase",
                "actor_label",
                "kind_label",
            )
        )
        or type(ports.transition) is not tuple
        or len(ports.transition) != 4
        or any(type(value) is not str or not value for value in ports.transition)
    ):
        raise C0LawError("Scene due port identity is malformed")
    if not all(
        is_dataclass(carrier) and getattr(carrier, "__dataclass_params__").frozen
        for carrier in (ports.scene_type, ports.member_type)
    ):
        raise C0LawError("Scene due Scene/member carriers must be frozen dataclasses")
    scene_fields = get_type_hints(ports.scene_type)
    member_fields = get_type_hints(ports.member_type)
    collection = scene_fields.get(ports.collection_field)
    if (
        get_origin(collection) is not tuple
        or get_args(collection) != (ports.member_type, Ellipsis)
        or scene_fields.get(ports.clock_field) is not int
        or member_fields.get(ports.member_id_field) is not str
        or member_fields.get(ports.status_field) is not str
        or not _nullable(member_fields.get(ports.recipient_field), str)
        or not _nullable(member_fields.get(ports.transition[1]), int)
        or not _nullable(member_fields.get(ports.transition[3]), K0OccurrenceRef)
        or ports.transition[0] == ports.transition[2]
    ):
        raise C0LawError("Scene due transition has an untyped or incoherent field")
    _check_fields(
        ports.evidence_type,
        {"phase": str, "scene": ports.scene_type, "actor": str, "kind": str},
        "Scene due evidence",
    )
    _check_fields(ports.participants_type, {"actor": str}, "Scene due participants")
    _check_fields(ports.envelope_type, {"phase": str, "tick": int}, "Scene due envelope")
    _check_fields(ports.contribution_type, {"owner": K0OwnerKey}, "Scene due contribution")
    _check_carriers(ports)
    evidence_fields = get_type_hints(ports.evidence_type)
    if (
        ports.evidence_member_field == ports.evidence_recipient_field
        or evidence_fields.get(ports.evidence_member_field) not in (str, str | None)
        or evidence_fields.get(ports.evidence_recipient_field) not in (str, str | None)
    ):
        raise C0LawError("Scene due evidence lacks addressed member provenance")


@dataclass(frozen=True)
class _BoundDue:
    ports: C0SceneDuePorts
    when: tuple[str, bool | int]

    def member(self, scene: object) -> object | None:
        ports = self.ports
        members = tuple(
            item
            for item in getattr(scene, ports.collection_field)
            if getattr(item, ports.member_id_field) == ports.carrier_id
        )
        if len(members) > 1:
            raise K0ProfileError("Scene due target is not unique")
        return members[0] if members else None

    def permits(self, scene: object, member: object | None) -> bool:
        if member is None or type(member) is not self.ports.member_type:
            return False
        ports = self.ports
        current = getattr(scene, ports.clock_field)
        if self.when[0] == "const":
            author_allows = self.when[1] is True
        elif self.when[0] == "gt":
            author_allows = type(current) is int and current > self.when[1]
        else:
            author_allows = type(current) is int and current < self.when[1]
        return (
            author_allows
            and type(current) is int
            and getattr(member, ports.status_field) == ports.transition[0]
            and getattr(member, ports.transition[1]) == current
            and getattr(member, ports.transition[3]) is None
            and type(getattr(member, ports.recipient_field)) is str
        )

    def evidence(self, scene: object, member: object) -> object:
        ports = self.ports
        return ports.evidence_type(
            **{
                "phase": ports.phase,
                "scene": scene,
                "actors": (),
                "actor": ports.actor_label,
                "kind": ports.kind_label,
                ports.evidence_recipient_field: getattr(member, ports.recipient_field),
                ports.evidence_member_field: getattr(member, ports.member_id_field),
            }
        )

    def checked_scene_and_member(self, rule_input: _K0InMemoryRuleInput) -> tuple[object, object]:
        ports = self.ports
        evidence = rule_input.evidence
        scene = getattr(evidence, "scene", None)
        if (
            rule_input.source != ports.result_source
            or rule_input.trigger is None
            or type(evidence) is not ports.evidence_type
            or type(scene) is not ports.scene_type
            or rule_input.participants != ports.participants_type(actor=ports.actor_label)
        ):
            raise K0ProfileError("compiled Scene due Event lost its source")
        member = self.member(scene)
        if not self.permits(scene, member) or evidence != self.evidence(scene, member):
            raise K0ProfileError("compiled Scene due Event lost its sealed basis")
        return scene, member


@dataclass(frozen=True)
class _Projector:
    bound: _BoundDue
    capability_ref: _K0CapabilityRef

    def project(
        self, trigger: object, views: tuple[_K0OwnerView, ...]
    ) -> tuple[_K0Activation, ...]:
        ports = self.bound.ports
        envelope = trigger.semantic_envelope
        if (
            trigger.source != ports.trigger_source
            or trigger.classification != ports.trigger_event
            or type(envelope) is not ports.envelope_type
            or envelope.phase != ports.trigger_phase
            or len(views) != 1
            or views[0].owner != ports.scene_owner
            or type(views[0].view) is not ports.scene_type
        ):
            return ()
        scene = views[0].view
        if envelope.tick != getattr(scene, ports.clock_field):
            return ()
        member = self.bound.member(scene)
        if not self.bound.permits(scene, member):
            return ()
        return (
            _K0Activation(
                ports.phase,
                self.bound.evidence(scene, member),
                ports.participants_type(actor=ports.actor_label),
                (),
            ),
        )


@dataclass(frozen=True)
class _Rule:
    bound: _BoundDue
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        scene, member = self.bound.checked_scene_and_member(rule_input)
        ports = self.bound.ports
        updated = replace(
            member,
            **{
                ports.status_field: ports.transition[2],
                ports.transition[3]: rule_input.occurrence,
            },
        )
        members = tuple(
            updated if item is member else item for item in getattr(scene, ports.collection_field)
        )
        state = replace(scene, **{ports.collection_field: members})
        state.validate_for_k0()
        result = K0RuleResult((ports.contribution_type(owner=ports.scene_owner, state=state),), ())
        envelope = ports.envelope_type(
            phase=ports.phase,
            tick=getattr(scene, ports.clock_field),
            content=None,
        )
        return _K0InMemoryEvaluation(result, envelope)


@dataclass(frozen=True)
class C0SceneDueProgram:
    _bound: _BoundDue
    lib_id: str
    revision: str
    export: str

    def bind(self) -> tuple[_K0InMemorySourceSpec, K0CausalLawDefinition]:
        ports = self._bound.ports
        prefix = f"c0.scene_due.{self.lib_id}.{self.revision}.{self.export}"
        spec = _K0InMemorySourceSpec(
            ports.result_source,
            K0OccurrenceFamily.EVENT,
            ports.result_event,
            type(None),
            ports.evidence_type,
            ports.participants_type,
            (ports.scene_owner,),
            (ports.scene_owner,),
            (),
            (),
            None,
            _Rule(self._bound, _K0CapabilityRef(f"{prefix}.rule")),
            ports.envelope_type,
        )
        law = K0CausalLawDefinition(
            ports.law_key,
            ports.trigger_event,
            ports.result_source,
            1,
            (ports.scene_owner,),
            _Projector(self._bound, _K0CapabilityRef(f"{prefix}.projector")),
        )
        return spec, law


class C0SceneDueCatalog:
    """Trusted versioned Lib declarations for one Scene collection due opcode."""

    def __init__(self, registrations: tuple[C0SceneDueLibraryRegistration, ...]) -> None:
        if type(registrations) is not tuple:
            raise C0LawError("Scene due libraries must be a tuple")
        libraries = {}
        for registration in registrations:
            if (
                type(registration) is not C0SceneDueLibraryRegistration
                or type(registration.ports) is not dict
            ):
                raise C0LawError("Scene due registration is not trusted")
            manifest = _source_object(registration.manifest_source, "Scene due Lib")
            _exact(manifest, {"schema", "id", "revision", "lawdefs", "exports"}, "Scene due Lib")
            if (
                manifest["schema"] != "c0.lib.scene_due.v1"
                or type(manifest["id"]) is not str
                or not manifest["id"]
                or type(manifest["revision"]) is not str
                or not manifest["revision"]
            ):
                raise C0LawError("Scene due Lib has malformed identity")
            lawdefs = _object(manifest["lawdefs"], "Scene due LawDefs")
            if not lawdefs:
                raise C0LawError("Scene due Lib has no LawDef")
            for name, value in lawdefs.items():
                definition = _object(value, "Scene due LawDef")
                _exact(definition, {"opcode", "formals"}, "Scene due LawDef")
                if (
                    not name
                    or definition["opcode"] != _OPCODE
                    or definition["formals"] != list(_FORMALS)
                ):
                    raise C0LawError("Scene due LawDef is not a checked transition")
            exports = _object(manifest["exports"], "Scene due exports")
            if not exports or len(exports) != len(registration.ports):
                raise C0LawError("Scene due Lib omits a trusted export")
            resolved = {}
            for name, value in exports.items():
                row = _object(value, "Scene due export")
                _exact(
                    row,
                    {
                        "native",
                        "lawdef",
                        "scene_owner",
                        "law_key",
                        "trigger_source",
                        "trigger_event",
                        "result_source",
                        "result_event",
                        "carrier_id",
                        "transition",
                        "evidence_member_field",
                        "evidence_recipient_field",
                    },
                    "Scene due export",
                )
                native = row["native"]
                ports = registration.ports.get(native) if type(native) is str else None
                if ports is None or type(row["lawdef"]) is not str or row["lawdef"] not in lawdefs:
                    raise C0LawError("Scene due export has no trusted native/LawDef")
                _check_ports(ports)
                if (
                    row["scene_owner"] != ports.scene_owner.value
                    or row["law_key"] != ports.law_key.value
                    or row["trigger_source"] != ports.trigger_source.value
                    or row["trigger_event"] != ports.trigger_event.value
                    or row["result_source"] != ports.result_source.value
                    or row["result_event"] != ports.result_event.value
                    or row["carrier_id"] != ports.carrier_id
                    or row["transition"] != list(ports.transition)
                    or row["evidence_member_field"] != ports.evidence_member_field
                    or row["evidence_recipient_field"] != ports.evidence_recipient_field
                ):
                    raise C0LawError("Scene due export disagrees with trusted transition")
                resolved[name] = (ports, row["lawdef"])
            native_names = [row["native"] for row in exports.values()]
            if any(type(native) is not str for native in native_names) or set(native_names) != set(
                registration.ports
            ):
                raise C0LawError("Scene due Lib repeats or omits a native port")
            key = (manifest["id"], manifest["revision"])
            if key in libraries:
                raise C0LawError("Scene due Lib repeats an ID/revision")
            libraries[key] = MappingProxyType(resolved)
        self._libraries = MappingProxyType(libraries)

    def compile(self, source: str) -> tuple[C0SceneDueProgram, ...]:
        row = _source_object(source, "Scene due Source")
        _exact(row, {"schema", "lib", "events"}, "Scene due Source")
        if row["schema"] != "c0.source.scene_due.v1":
            raise C0LawError("Scene due Source schema is unsupported")
        lib = _object(row["lib"], "Scene due Lib reference")
        _exact(lib, {"id", "revision"}, "Scene due Lib reference")
        if any(type(value) is not str or not value for value in lib.values()):
            raise C0LawError("Scene due Lib reference is malformed")
        exports = self._libraries.get((lib["id"], lib["revision"]))
        if exports is None:
            raise C0LawError("Scene due Source imports an unavailable Lib")
        uses = row["events"]
        if type(uses) is not list or not uses:
            raise C0LawError("Scene due Source has no Event uses")
        programs = []
        names = set()
        for value in uses:
            use = _object(value, "Scene due Event use")
            _exact(use, {"export", "lawdef", "arguments", "when"}, "Scene due Event use")
            export = use["export"]
            if type(export) is not str or export not in exports or export in names:
                raise C0LawError("Scene due Source repeats or misses an export")
            names.add(export)
            ports, lawdef_name = exports[export]
            lawdef = _object(use["lawdef"], "Scene due LawDef reference")
            _exact(lawdef, {"ref"}, "Scene due LawDef reference")
            if lawdef["ref"] != lawdef_name:
                raise C0LawError("Scene due Source names a foreign LawDef")
            arguments = _object(use["arguments"], "Scene due arguments")
            _exact(arguments, set(_FORMALS), "Scene due arguments")
            if tuple(arguments[name] for name in _FORMALS) != (
                ports.carrier_id,
                *ports.transition,
            ):
                raise C0LawError("Scene due binding is not a complete trusted transition")
            when = _parse_when(use["when"], ports.clock_field)
            programs.append(
                C0SceneDueProgram(_BoundDue(ports, when), lib["id"], lib["revision"], export)
            )
        return tuple(programs)
