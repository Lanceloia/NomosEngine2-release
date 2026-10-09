"""Compile a bounded authored Scene Action into an existing private K0 profile."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields, is_dataclass, replace
from types import MappingProxyType
from typing import get_type_hints

from nomos_kernel import (
    K0EventTypeKey,
    K0OccurrenceFamily,
    K0OwnerKey,
    K0ProfileError,
    K0SourceSpecKey,
)
from nomos_kernel._admission_abi import _K0AdmissionProjection
from nomos_kernel._atomic_inmemory_session import (
    _K0InMemoryEvaluation,
    _K0InMemoryRuleInput,
    _K0InMemorySourceSpec,
)
from nomos_kernel._owner_abi import (
    _K0CapabilityRef,
    _K0OwnerView,
    _validate_closed_host_object,
)
from nomos_kernel._rule_products_abi import K0RuleResult

from .author_contract_v1 import C0LawError, _exact, _object, _source_object


@dataclass(frozen=True)
class C0SceneActionPorts:
    """Trusted nominal carriers and identity for one repeatable Scene action."""

    scene_owner: K0OwnerKey
    source_key: K0SourceSpecKey
    event_type: K0EventTypeKey
    scene_type: type
    payload: object
    evidence_type: type
    participants_type: type
    envelope_type: type
    contribution_type: type
    scene_field: str
    increment: int
    phase: str


@dataclass(frozen=True)
class C0SceneActionLibraryRegistration:
    manifest_source: str
    ports: dict[str, C0SceneActionPorts]


def _check_fields(carrier: type, required: dict[str, object], label: str) -> None:
    if not isinstance(carrier, type) or not is_dataclass(carrier):
        raise C0LawError(f"{label} must be a nominal dataclass")
    hints = get_type_hints(carrier)
    declared = {item.name: item for item in fields(carrier)}
    for name, annotation in required.items():
        if name not in declared or hints.get(name) != annotation:
            raise C0LawError(f"{label} lacks a required typed field")
    if any(not item.init for item in declared.values()):
        raise C0LawError(f"{label} has an unconstructible field")


def _check_ports(ports: C0SceneActionPorts) -> None:
    if (
        type(ports) is not C0SceneActionPorts
        or type(ports.scene_owner) is not K0OwnerKey
        or type(ports.source_key) is not K0SourceSpecKey
        or type(ports.event_type) is not K0EventTypeKey
        or type(ports.scene_field) is not str
        or not ports.scene_field
        or type(ports.increment) is not int
        or ports.increment < 1
        or type(ports.phase) is not str
        or not ports.phase
    ):
        raise C0LawError("Scene Action has malformed trusted ports")
    _check_fields(ports.scene_type, {ports.scene_field: int}, "Scene")
    _check_fields(type(ports.payload), {"actor": str, "kind": str}, "payload")
    _check_fields(
        ports.evidence_type,
        {"phase": str, "scene": ports.scene_type, "actor": str, "kind": str},
        "evidence",
    )
    _check_fields(ports.participants_type, {"actor": str}, "participants")
    _check_fields(ports.envelope_type, {"phase": str, "tick": int}, "envelope")
    _check_fields(ports.contribution_type, {"owner": K0OwnerKey}, "contribution")
    if not hasattr(ports.payload, "validate_for_k0"):
        raise C0LawError("Scene Action payload has no K0 validation")
    try:
        _validate_closed_host_object(ports.payload, "Scene Action payload")
    except K0ProfileError as error:
        raise C0LawError("Scene Action payload must be recursively frozen") from error
    ports.payload.validate_for_k0()
    if any(type(getattr(ports.payload, name, None)) is not str for name in ("actor", "kind")):
        raise C0LawError("Scene Action payload has no closed identity")
    _check_carriers(ports)


def _make_evidence(ports: C0SceneActionPorts, scene: object) -> object:
    return ports.evidence_type(
        phase=ports.phase,
        scene=scene,
        actors=(),
        actor=ports.payload.actor,
        kind=ports.payload.kind,
    )


def _check_carriers(ports: C0SceneActionPorts) -> None:
    for carrier, values in (
        (ports.evidence_type, {"phase", "scene", "actors", "actor", "kind"}),
        (ports.participants_type, {"actor"}),
        (ports.envelope_type, {"phase", "tick", "content"}),
        (ports.contribution_type, {"owner", "state"}),
    ):
        declared = {item.name: item for item in fields(carrier)}
        if not values <= declared.keys() or any(
            item.default is MISSING and item.default_factory is MISSING
            for name, item in declared.items()
            if name not in values
        ):
            raise C0LawError("Scene Action carrier has unbound required fields")


@dataclass(frozen=True)
class _BoundAction:
    ports: C0SceneActionPorts
    when: tuple[str, bool | int]

    def permits(self, scene: object) -> bool:
        if self.when[0] == "const":
            return self.when[1] is True
        value = getattr(scene, self.ports.scene_field)
        if type(value) is not int:
            return False
        return value > self.when[1] if self.when[0] == "gt" else value < self.when[1]

    def evidence(self, scene: object) -> object:
        return _make_evidence(self.ports, scene)

    def check_evidence(self, rule_input: _K0InMemoryRuleInput) -> object:
        evidence = rule_input.evidence
        scene = getattr(evidence, "scene", None)
        if (
            rule_input.source != self.ports.source_key
            or rule_input.trigger is not None
            or type(evidence) is not self.ports.evidence_type
            or type(scene) is not self.ports.scene_type
            or evidence != self.evidence(scene)
            or rule_input.participants
            != self.ports.participants_type(actor=self.ports.payload.actor)
            or not self.permits(scene)
        ):
            raise K0ProfileError("compiled Scene Action lost its admitted evidence")
        return scene


@dataclass(frozen=True)
class _Admission:
    bound: _BoundAction
    capability_ref: _K0CapabilityRef

    def admit(
        self, payload: object, views: tuple[_K0OwnerView, ...]
    ) -> _K0AdmissionProjection | None:
        ports = self.bound.ports
        if type(payload) is not type(ports.payload):
            raise K0ProfileError("compiled Scene Action has a foreign payload")
        payload.validate_for_k0()
        if (
            len(views) != 1
            or views[0].owner != ports.scene_owner
            or type(views[0].view) is not ports.scene_type
        ):
            raise K0ProfileError("compiled Scene Action read a foreign owner")
        if payload != ports.payload or not self.bound.permits(views[0].view):
            return None
        return _K0AdmissionProjection(
            self.bound.evidence(views[0].view),
            ports.participants_type(actor=ports.payload.actor),
            (),
        )


@dataclass(frozen=True)
class _Rule:
    bound: _BoundAction
    capability_ref: _K0CapabilityRef

    def evaluate(self, rule_input: _K0InMemoryRuleInput) -> _K0InMemoryEvaluation:
        scene = self.bound.check_evidence(rule_input)
        ports = self.bound.ports
        current = getattr(scene, ports.scene_field)
        if type(current) is not int:
            raise K0ProfileError("compiled Scene Action read a non-integer field")
        state = replace(scene, **{ports.scene_field: current + ports.increment})
        state.validate_for_k0()
        result = K0RuleResult((ports.contribution_type(owner=ports.scene_owner, state=state),), ())
        envelope = ports.envelope_type(
            phase=ports.phase,
            tick=getattr(scene, ports.scene_field) + ports.increment,
            content=None,
        )
        return _K0InMemoryEvaluation(result, envelope)


@dataclass(frozen=True)
class C0SceneActionProgram:
    _bound: _BoundAction
    lib_id: str
    revision: str
    export: str

    def source_spec(self) -> _K0InMemorySourceSpec:
        ports = self._bound.ports
        prefix = f"c0.scene_action.{self.lib_id}.{self.revision}.{self.export}"
        return _K0InMemorySourceSpec(
            ports.source_key,
            K0OccurrenceFamily.ACTION,
            ports.event_type,
            type(ports.payload),
            ports.evidence_type,
            ports.participants_type,
            (ports.scene_owner,),
            (ports.scene_owner,),
            (),
            (),
            _Admission(self._bound, _K0CapabilityRef(f"{prefix}.admission")),
            _Rule(self._bound, _K0CapabilityRef(f"{prefix}.rule")),
            ports.envelope_type,
        )


class C0SceneActionCatalog:
    """One immutable in-process catalog of versioned trusted Scene Actions."""

    def __init__(self, registrations: tuple[C0SceneActionLibraryRegistration, ...]) -> None:
        if type(registrations) is not tuple:
            raise C0LawError("Scene Action libraries must be a tuple")
        libraries = {}
        for registration in registrations:
            if type(registration) is not C0SceneActionLibraryRegistration:
                raise C0LawError("Scene Action registration is not trusted")
            manifest = _source_object(registration.manifest_source, "Scene Action Lib")
            _exact(manifest, {"schema", "id", "revision", "exports"}, "Scene Action Lib")
            if (
                manifest["schema"] != "c0.lib.scene_action.v1"
                or type(manifest["id"]) is not str
                or not manifest["id"]
                or type(manifest["revision"]) is not str
                or not manifest["revision"]
                or type(registration.ports) is not dict
            ):
                raise C0LawError("Scene Action Lib has malformed identity")
            exports = _object(manifest["exports"], "Scene Action exports")
            if not exports or len(exports) != len(registration.ports):
                raise C0LawError("Scene Action Lib does not close its native ports")
            resolved = {}
            for name, value in exports.items():
                row = _object(value, "Scene Action export")
                _exact(
                    row,
                    {"native", "scene_owner", "source_key", "event_type", "field", "increment"},
                    "Scene Action export",
                )
                native = row["native"]
                ports = registration.ports.get(native) if type(native) is str else None
                if ports is None:
                    raise C0LawError("Scene Action export has no trusted native port")
                _check_ports(ports)
                if (
                    row["scene_owner"] != ports.scene_owner.value
                    or row["source_key"] != ports.source_key.value
                    or row["event_type"] != ports.event_type.value
                    or row["field"] != ports.scene_field
                    or type(row["increment"]) is not int
                    or row["increment"] != ports.increment
                ):
                    raise C0LawError("Scene Action export disagrees with trusted identity")
                resolved[name] = ports
            if {row["native"] for row in exports.values()} != set(registration.ports):
                raise C0LawError("Scene Action Lib omits a native port")
            key = (manifest["id"], manifest["revision"])
            if key in libraries:
                raise C0LawError("Scene Action Lib repeats an ID/revision")
            libraries[key] = MappingProxyType(resolved)
        self._libraries = MappingProxyType(libraries)

    def compile(self, source: str) -> C0SceneActionProgram:
        row = _source_object(source, "Scene Action Source")
        _exact(row, {"schema", "lib", "action"}, "Scene Action Source")
        if row["schema"] != "c0.source.scene_action.v1":
            raise C0LawError("Scene Action Source schema is unsupported")
        lib = _object(row["lib"], "Scene Action Lib reference")
        _exact(lib, {"id", "revision"}, "Scene Action Lib reference")
        if any(type(value) is not str or not value for value in lib.values()):
            raise C0LawError("Scene Action Lib reference is malformed")
        exports = self._libraries.get((lib["id"], lib["revision"]))
        if exports is None:
            raise C0LawError("Scene Action Source imports an unavailable Lib")
        action = _object(row["action"], "Scene Action use")
        _exact(action, {"export", "when", "set"}, "Scene Action use")
        export = action["export"]
        if type(export) is not str or export not in exports:
            raise C0LawError("Scene Action Source names no Lib export")
        ports = exports[export]
        when = _parse_when(action["when"], ports.scene_field)
        update = _object(action["set"], "Scene Action update")
        _exact(update, {ports.scene_field}, "Scene Action update")
        _parse_add(update[ports.scene_field], ports.scene_field, ports.increment)
        return C0SceneActionProgram(_BoundAction(ports, when), lib["id"], lib["revision"], export)


def _parse_when(value: object, field: str) -> tuple[str, bool | int]:
    row = _object(value, "Scene Action condition")
    if set(row) == {"const"} and type(row["const"]) is bool:
        return ("const", row["const"])
    for operator in ("gt", "lt"):
        if set(row) == {operator} and type(row[operator]) is list and len(row[operator]) == 2:
            left, right = row[operator]
            if (
                left == {"ref": f"scene.{field}"}
                and type(right) is dict
                and set(right) == {"const"}
                and type(right["const"]) is int
            ):
                return (operator, right["const"])
    raise C0LawError("Scene Action condition has an undeclared or mistyped port")


def _parse_add(value: object, field: str, increment: int) -> None:
    row = _object(value, "Scene Action effect")
    if set(row) != {"add"} or type(row["add"]) is not list or len(row["add"]) != 2:
        raise C0LawError("Scene Action effect must add to its declared field")
    left, right = row["add"]
    if left != {"ref": f"scene.{field}"} or right != {"const": increment}:
        raise C0LawError("Scene Action effect disagrees with the Lib increment")
