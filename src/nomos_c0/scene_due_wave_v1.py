"""Author-selected, bounded same-wave settlement for Scene due Events."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from nomos_kernel import K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0SameWaveProposal
from nomos_kernel._owner_abi import _K0CapabilityRef

from .author_contract_v1 import C0LawError, _exact, _object, _source_object
from .scene_due_v1 import (
    C0SceneDueCatalog,
    C0SceneDueLibraryRegistration,
    C0SceneDuePorts,
    C0SceneDueProgram,
    _Rule,
)

_MERGE = "merge_distinct_due_members.v1"
_REJECT = "reject_unproven_same_wave.v1"


@dataclass(frozen=True)
class C0SceneDueWaveRegistration:
    manifest_source: str
    ports: dict[str, C0SceneDuePorts]


@dataclass(frozen=True)
class _DueWavePolicy:
    programs: tuple[C0SceneDueProgram, C0SceneDueProgram]
    strategy: str
    capability_ref: _K0CapabilityRef

    @property
    def owner(self):
        return self.programs[0]._bound.ports.scene_owner

    @property
    def sources(self):
        return tuple(program._bound.ports.result_source for program in self.programs)

    @property
    def law_keys(self):
        return tuple(program._bound.ports.law_key for program in self.programs)

    @property
    def trigger_source(self):
        return self.programs[0]._bound.ports.trigger_source

    @property
    def trigger_event(self):
        return self.programs[0]._bound.ports.trigger_event

    def merge(self, prior_state: object, proposals: tuple[_K0SameWaveProposal, ...]) -> object:
        if self.strategy == _REJECT:
            raise K0ProfileError("author selected same-wave rejection")
        if type(prior_state) is not self.programs[0]._bound.ports.scene_type or len(proposals) != 2:
            raise K0ProfileError("same-wave Scene/batch is malformed")
        by_source = {item.source: item for item in proposals}
        if len(by_source) != 2 or set(by_source) != set(self.sources):
            raise K0ProfileError("same-wave batch has wrong Event sources")
        scene = prior_state
        targets: set[str] = set()
        collection = self.programs[0]._bound.ports.collection_field
        id_field = self.programs[0]._bound.ports.member_id_field
        members = list(getattr(scene, collection))
        for program in self.programs:
            bound = program._bound
            ports = bound.ports
            proposal = by_source[ports.result_source]
            if proposal.rule_input.evidence.scene != scene:
                raise K0ProfileError("same-wave proposal has stale or foreign basis")
            _, member = bound.checked_scene_and_member(proposal.rule_input)
            target_id = getattr(member, id_field)
            if target_id in targets:
                raise K0ProfileError("same-wave Events target one member twice")
            targets.add(target_id)
            expected = (
                _Rule(bound, _K0CapabilityRef("c0.scene_due.wave.verify"))
                .evaluate(proposal.rule_input)
                .result
            )
            if proposal.result != expected:
                raise K0ProfileError("same-wave proposal changed undeclared fields")
            if len(proposal.result.contributions) != 1:
                raise K0ProfileError("same-wave Event has no exact Scene contribution")
            replacement_state = proposal.result.contributions[0].state
            replacement_member = next(
                item
                for item in getattr(replacement_state, collection)
                if getattr(item, id_field) == target_id
            )
            positions = [
                i for i, item in enumerate(members) if getattr(item, id_field) == target_id
            ]
            if len(positions) != 1:
                raise K0ProfileError("same-wave Scene member identity is not unique")
            members[positions[0]] = replacement_member
        combined = replace(scene, **{collection: tuple(members)})
        combined.validate_for_k0()
        return combined


@dataclass(frozen=True)
class C0SceneDueWaveBundle:
    programs: tuple[C0SceneDueProgram, C0SceneDueProgram]
    strategy: str

    def bind(self):
        bound = tuple(program.bind() for program in self.programs)
        return (
            tuple(item[0] for item in bound),
            tuple(item[1] for item in bound),
            _DueWavePolicy(
                self.programs,
                self.strategy,
                _K0CapabilityRef(f"c0.scene_due.wave.{self.strategy}"),
            ),
        )


class C0SceneDueWaveCatalog:
    """Compile a v2 Source and one trusted two-Event settlement declaration."""

    def __init__(self, registration: C0SceneDueWaveRegistration) -> None:
        if type(registration) is not C0SceneDueWaveRegistration:
            raise C0LawError("Scene due wave registration is not trusted")
        manifest = _source_object(registration.manifest_source, "Scene due wave Lib")
        _exact(
            manifest,
            {"schema", "id", "revision", "lawdefs", "exports", "wave_lawdefs"},
            "Scene due wave Lib",
        )
        if manifest["schema"] != "c0.lib.scene_due.v2":
            raise C0LawError("Scene due wave Lib schema is unsupported")
        waves = _object(manifest["wave_lawdefs"], "Scene due wave LawDefs")
        if set(waves) != {_MERGE, _REJECT}:
            raise C0LawError("Scene due wave Lib lacks exact versioned strategies")
        exports = _object(manifest["exports"], "Scene due wave exports")
        if len(exports) != 2 or set(exports) != set(registration.ports):
            raise C0LawError("Scene due wave Lib needs two trusted exports")
        ports = tuple(registration.ports[name] for name in exports)
        first = ports[0]
        if any(
            item.scene_owner != first.scene_owner
            or item.scene_type is not first.scene_type
            or item.collection_field != first.collection_field
            or item.member_id_field != first.member_id_field
            or item.trigger_source != first.trigger_source
            or item.trigger_event != first.trigger_event
            or item.contribution_type is not first.contribution_type
            for item in ports
        ):
            raise C0LawError("Scene due wave ports do not share one trigger/Scene owner")
        for name, row in waves.items():
            definition = _object(row, "Scene due wave LawDef")
            _exact(
                definition,
                {"opcode", "owner", "collection", "member_id", "events"},
                "Scene due wave LawDef",
            )
            if (
                definition["opcode"] != name
                or definition["owner"] != first.scene_owner.value
                or definition["collection"] != first.collection_field
                or definition["member_id"] != first.member_id_field
                or definition["events"] != list(exports)
            ):
                raise C0LawError("Scene due wave LawDef disagrees with trusted ports")
        legacy = dict(manifest)
        legacy["schema"] = "c0.lib.scene_due.v1"
        del legacy["wave_lawdefs"]
        self._catalog = C0SceneDueCatalog(
            (C0SceneDueLibraryRegistration(json.dumps(legacy), registration.ports),)
        )
        self._manifest = manifest
        self._exports = tuple(exports)
        self._ports = first

    def compile(self, source: str) -> C0SceneDueWaveBundle:
        row = _source_object(source, "Scene due wave Source")
        _exact(row, {"schema", "lib", "events", "settlement"}, "Scene due wave Source")
        if row["schema"] != "c0.source.scene_due.v2":
            raise C0LawError("Scene due wave Source schema is unsupported")
        settlement = _object(row["settlement"], "Scene due wave settlement")
        _exact(
            settlement,
            {"instant", "events", "lawdef", "arguments"},
            "Scene due wave settlement",
        )
        lawdef = _object(settlement["lawdef"], "Scene due wave LawDef reference")
        _exact(lawdef, {"ref"}, "Scene due wave LawDef reference")
        arguments = _object(settlement["arguments"], "Scene due wave arguments")
        _exact(arguments, {"owner", "collection", "member_id"}, "Scene due wave arguments")
        exports = self._exports
        ports = self._ports
        if (
            settlement["instant"] != "same_trigger_wave"
            or settlement["events"] != list(exports)
            or lawdef["ref"] not in (_MERGE, _REJECT)
            or arguments
            != {
                "owner": ports.scene_owner.value,
                "collection": ports.collection_field,
                "member_id": ports.member_id_field,
            }
            or row["lib"]
            != {
                "id": self._manifest["id"],
                "revision": self._manifest["revision"],
            }
        ):
            raise C0LawError("Scene due wave settlement is not fully bound")
        legacy = dict(row)
        legacy["schema"] = "c0.source.scene_due.v1"
        del legacy["settlement"]
        programs = self._catalog.compile(json.dumps(legacy))
        if len(programs) != 2 or tuple(item.export for item in programs) != exports:
            raise C0LawError("Scene due wave Source omits its Event pair")
        return C0SceneDueWaveBundle((programs[0], programs[1]), lawdef["ref"])
