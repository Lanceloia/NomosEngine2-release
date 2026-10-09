"""Compile author-ordered Scene due steps into one private K0 policy."""

from __future__ import annotations

import json
from dataclasses import dataclass

from nomos_kernel import K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0OrderedStep
from nomos_kernel._owner_abi import _K0CapabilityRef

from .author_contract_v1 import C0LawError, _exact, _object, _source_object
from .scene_due_v1 import (
    C0SceneDueCatalog,
    C0SceneDueLibraryRegistration,
    C0SceneDuePorts,
    C0SceneDueProgram,
)

_ORDER_LAW = "ordered_current_recheck.v1"


@dataclass(frozen=True)
class C0SceneDueOrderedRegistration:
    manifest_source: str
    ports: dict[str, C0SceneDuePorts]


@dataclass(frozen=True)
class _DueOrderedPolicy:
    programs: tuple[C0SceneDueProgram, C0SceneDueProgram]
    required: tuple[bool, bool]
    capability_ref: _K0CapabilityRef

    @property
    def owner(self):
        return self.programs[0]._bound.ports.scene_owner

    @property
    def trigger_source(self):
        return self.programs[0]._bound.ports.trigger_source

    @property
    def trigger_event(self):
        return self.programs[0]._bound.ports.trigger_event

    @property
    def steps(self):
        return tuple(
            _K0OrderedStep(
                program._bound.ports.law_key,
                program._bound.ports.result_source,
                required,
            )
            for program, required in zip(self.programs, self.required, strict=True)
        )

    def validate_current_basis(self, step, activation, views) -> None:
        matching = tuple(
            program
            for program in self.programs
            if program._bound.ports.result_source == step.source
            and program._bound.ports.law_key == step.law_key
        )
        current = tuple(view.view for view in views if view.owner == self.owner)
        if len(matching) != 1 or len(current) != 1:
            raise K0ProfileError("ordered step lacks its current owner view")
        bound = matching[0]._bound
        scene = current[0]
        member = bound.member(scene)
        if not bound.permits(scene, member) or activation.evidence != bound.evidence(scene, member):
            raise K0ProfileError("ordered step returned stale or forged current basis")


@dataclass(frozen=True)
class C0SceneDueOrderedBundle:
    programs: tuple[C0SceneDueProgram, C0SceneDueProgram]
    required: tuple[bool, bool]

    def bind(self):
        bound = tuple(program.bind() for program in self.programs)
        return (
            tuple(item[0] for item in bound),
            tuple(item[1] for item in bound),
            _DueOrderedPolicy(
                self.programs,
                self.required,
                _K0CapabilityRef("c0.scene_due.ordered_current_recheck.v1"),
            ),
        )


class C0SceneDueOrderedCatalog:
    """One trusted ordered LawDef over two complete Event exports."""

    def __init__(self, registration: C0SceneDueOrderedRegistration) -> None:
        if (
            type(registration) is not C0SceneDueOrderedRegistration
            or type(registration.ports) is not dict
        ):
            raise C0LawError("ordered Scene due registration is not trusted")
        manifest = _source_object(registration.manifest_source, "ordered Scene due Lib")
        _exact(
            manifest,
            {"schema", "id", "revision", "lawdefs", "exports", "order_lawdef"},
            "ordered Scene due Lib",
        )
        if manifest["schema"] != "c0.lib.scene_due_ordered.v1":
            raise C0LawError("ordered Scene due Lib schema is unsupported")
        exports = _object(manifest["exports"], "ordered Scene due exports")
        if len(exports) != 2 or set(exports) != set(registration.ports):
            raise C0LawError("ordered Scene due Lib needs two exact exports")
        ports = tuple(registration.ports[name] for name in exports)
        first = ports[0]
        if any(
            item.scene_owner != first.scene_owner
            or item.scene_type is not first.scene_type
            or item.collection_field != first.collection_field
            or item.trigger_source != first.trigger_source
            or item.trigger_event != first.trigger_event
            or item.contribution_type is not first.contribution_type
            or item.result_event == first.trigger_event
            for item in ports
        ):
            raise C0LawError("ordered Scene due ports disagree on Scene or trigger")
        lawdef = _object(manifest["order_lawdef"], "ordered Scene due LawDef")
        _exact(
            lawdef,
            {"ref", "opcode", "owner", "trigger_source", "trigger_event", "exports"},
            "ordered Scene due LawDef",
        )
        if lawdef != {
            "ref": _ORDER_LAW,
            "opcode": _ORDER_LAW,
            "owner": first.scene_owner.value,
            "trigger_source": first.trigger_source.value,
            "trigger_event": first.trigger_event.value,
            "exports": list(exports),
        }:
            raise C0LawError("ordered Scene due LawDef disagrees with trusted ports")
        legacy = dict(manifest)
        legacy["schema"] = "c0.lib.scene_due.v1"
        del legacy["order_lawdef"]
        self._catalog = C0SceneDueCatalog(
            (C0SceneDueLibraryRegistration(json.dumps(legacy), registration.ports),)
        )
        self._lib_ref = {"id": manifest["id"], "revision": manifest["revision"]}
        self._exports = tuple(exports)

    def compile(self, source: str) -> C0SceneDueOrderedBundle:
        row = _source_object(source, "ordered Scene due Source")
        _exact(row, {"schema", "lib", "events", "settlement"}, "ordered Scene due Source")
        if row["schema"] != "c0.source.scene_due_ordered.v1" or row["lib"] != self._lib_ref:
            raise C0LawError("ordered Scene due Source imports an unavailable Lib")
        settlement = _object(row["settlement"], "ordered Scene due settlement")
        _exact(settlement, {"lawdef", "steps"}, "ordered Scene due settlement")
        lawdef = _object(settlement["lawdef"], "ordered Scene due LawDef reference")
        _exact(lawdef, {"ref"}, "ordered Scene due LawDef reference")
        if lawdef["ref"] != _ORDER_LAW:
            raise C0LawError("ordered Scene due Source names a foreign LawDef")
        steps = settlement["steps"]
        if type(steps) is not list or len(steps) != 2:
            raise C0LawError("ordered Scene due Source needs two steps")
        names = []
        required = []
        for value in steps:
            step = _object(value, "ordered Scene due step")
            _exact(step, {"export", "required"}, "ordered Scene due step")
            if type(step["export"]) is not str or type(step["required"]) is not bool:
                raise C0LawError("ordered Scene due step is malformed")
            names.append(step["export"])
            required.append(step["required"])
        if set(names) != set(self._exports) or len(set(names)) != 2:
            raise C0LawError("ordered Scene due step order repeats or omits an export")
        legacy = dict(row)
        legacy["schema"] = "c0.source.scene_due.v1"
        del legacy["settlement"]
        programs = self._catalog.compile(json.dumps(legacy))
        by_export = {program.export: program for program in programs}
        if set(by_export) != set(self._exports) or len(programs) != 2:
            raise C0LawError("ordered Scene due Event pair is incomplete")
        return C0SceneDueOrderedBundle(
            (by_export[names[0]], by_export[names[1]]),
            (required[0], required[1]),
        )
