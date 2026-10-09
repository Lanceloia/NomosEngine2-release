"""Bounded, author-declared read projections for one controlled Actor seat."""

from __future__ import annotations

from dataclasses import dataclass

from .composable_value_v1 import C0ValuePorts, C0ValueProgram, C0ValueStateError


@dataclass(frozen=True)
class C0SeatReadPorts:
    symbol: str
    scene_owner: str
    actor: str
    collection_field: str
    current_field: str
    candidate_type: type
    candidate_key: str
    object_root: str
    object_kind: str
    value_ports: C0ValuePorts
    max_candidates: int


@dataclass(frozen=True)
class C0SeatReadProjection:
    ports: C0SeatReadPorts
    value: C0ValueProgram

    def project(self, scene: object, actor: object, selected_object: object) -> tuple[object, ...]:
        current = getattr(actor, self.ports.current_field)
        known = getattr(actor, self.ports.collection_field)
        if type(current) is not str or type(known) is not tuple:
            raise C0ValueStateError("seat read candidates have a foreign nominal shape")
        if len(known) > self.ports.max_candidates or any(
            type(candidate) is not self.ports.candidate_type for candidate in known
        ):
            raise C0ValueStateError("seat read candidates exceed their closed domain")
        keys = tuple(getattr(candidate, self.ports.candidate_key) for candidate in known)
        if any(type(key) is not str for key in keys) or len(set(keys)) != len(keys):
            raise C0ValueStateError("seat read candidates are repeated")
        if current not in keys:
            raise C0ValueStateError("seat read lacks the Actor's current candidate")
        rows = []
        for candidate in known:
            result = self.value.evaluate_admission_outputs(
                {
                    "scene": scene,
                    "actor": actor,
                    "candidate": candidate,
                    self.ports.object_root: selected_object,
                }
            )
            if result is not None:
                rows.append(
                    (getattr(candidate, self.ports.candidate_key), tuple(sorted(result.items())))
                )
        return tuple(rows)
