"""Bounded, author-declared read projections for one controlled Actor seat."""

from __future__ import annotations

import keyword
from collections.abc import Mapping
from dataclasses import dataclass

from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .author_contract_v1 import C0LawError
from .composable_value_v1 import C0ValuePorts, C0ValueProgram, C0ValueStateError

SEAT_READ_OUTPUT_TYPES = (str, int, bool, _K0IndividualRef, _K0IndividualRef | None)


def check_fixed_projection_roots(
    object_root: str,
    object_kind: str,
    actor: str,
    fixed_actor_roots: tuple[tuple[str, str], ...],
    additional_fixed_individual_roots: tuple[tuple[str, str], ...],
    actor_symbols: frozenset[str],
    object_kinds: frozenset[str],
) -> None:
    if (
        type(object_root) is not str
        or not object_root.isidentifier()
        or object_root.startswith("_")
        or keyword.iskeyword(object_root)
        or object_root in {"scene", "actor", "candidate"}
        or type(object_kind) is not str
        or object_kind not in object_kinds
        or type(actor) is not str
    ):
        raise C0LawError("seat read fixed roots have a foreign primary Actor/Object selection")
    selections = (fixed_actor_roots, additional_fixed_individual_roots)
    if any(
        type(selection) is not tuple
        or len(selection) > 32
        or any(
            type(item) is not tuple
            or len(item) != 2
            or any(
                type(value) is not str
                or not value.isidentifier()
                or value.startswith("_")
                or keyword.iskeyword(value)
                for value in item
            )
            for item in selection
        )
        for selection in selections
    ):
        raise C0LawError("seat read fixed roots are not a closed finite selection")
    names = tuple(name for selection in selections for name, _ in selection)
    actors = tuple(symbol for _, symbol in fixed_actor_roots)
    kinds = tuple(kind for _, kind in additional_fixed_individual_roots)
    object_names = (object_root, *(name for name, _ in additional_fixed_individual_roots))
    ref_names = {f"{name}_ref" for name in object_names}
    if (
        len(names) > 32
        or len(set(names)) != len(names)
        or set(names) & {"scene", "actor", "candidate", object_root}
        or len(set(actors)) != len(actors)
        or actor in actors
        or not set(actors) <= actor_symbols
        or len(set(kinds)) != len(kinds)
        or object_kind in kinds
        or not set(kinds) <= object_kinds
        or ref_names & {"scene", "actor", "candidate", object_root, *names}
    ):
        raise C0LawError("seat read fixed roots alias or have a foreign Actor/Object selection")


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
    fixed_actor_roots: tuple[tuple[str, str], ...] = ()
    additional_fixed_individual_roots: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class C0SeatReadProjection:
    ports: C0SeatReadPorts
    value: C0ValueProgram

    def project(
        self,
        scene: object,
        actor: object,
        selected_object: object,
        *,
        fixed_roots: Mapping[str, object] | None = None,
        individual_refs: Mapping[str, _K0IndividualRef],
    ) -> tuple[object, ...]:
        fixed_roots = {} if fixed_roots is None else dict(fixed_roots)
        if set(fixed_roots) != {
            name
            for name, _ in (
                *self.ports.fixed_actor_roots,
                *self.ports.additional_fixed_individual_roots,
            )
        }:
            raise C0ValueStateError("seat read lacks its exact fixed inputs")
        if set(individual_refs) != {
            f"{name}_ref"
            for name in (
                self.ports.object_root,
                *(root for root, _ in self.ports.additional_fixed_individual_roots),
            )
        }:
            raise C0ValueStateError("seat read lacks its exact individual inputs")
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
                    **fixed_roots,
                    **individual_refs,
                }
            )
            if result is not None:
                rows.append(
                    (getattr(candidate, self.ports.candidate_key), tuple(sorted(result.items())))
                )
        return tuple(rows)
