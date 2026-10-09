"""Checked C0 law declarations before private K0 profile construction."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import get_type_hints

from nomos_kernel import K0OccurrenceFamily

from .actor_product_v1 import C0ActorProductIR, product_outputs
from .author_contract_v1 import C0LawError
from .composable_value_v1 import C0ValuePorts, C0ValueProgram, C0ValueStateError, _assignable
from .object_product_v1 import C0ObjectProductIR


@dataclass(frozen=True)
class C0StaticOwnerIR:
    root: str
    key: str
    state_type: type


@dataclass(frozen=True)
class C0SelectedOwnerIR:
    root: str
    selector: str
    payload_field: str
    state_type: type
    write: bool
    nullable: bool
    families: tuple[str, ...] = ()
    members: tuple[tuple[str, str], ...] = ()
    identity_field: str | None = None


@dataclass(frozen=True)
class C0FixedIndividualIR:
    root: str
    family: str
    state_type: type


class C0FormationKind(Enum):
    SUBMIT = "submit"
    AFTER_OCCURRENCE = "after_occurrence"
    DUE = "due"

    @property
    def when_false(self) -> str:
        return {
            C0FormationKind.SUBMIT: "not_admitted",
            C0FormationKind.AFTER_OCCURRENCE: "no_event",
            C0FormationKind.DUE: "defect",
        }[self]


@dataclass(frozen=True)
class C0OccurrenceContractIR:
    source_key: str
    event_type: str
    family: K0OccurrenceFamily
    envelope_type: type
    participants_type: type

    def __post_init__(self) -> None:
        if (
            type(self.source_key) is not str
            or not self.source_key
            or type(self.event_type) is not str
            or not self.event_type
            or type(self.family) is not K0OccurrenceFamily
            or not isinstance(self.envelope_type, type)
            or not isinstance(self.participants_type, type)
        ):
            raise C0LawError("occurrence contract IR lacks nominal carriers or identity")

    def matches(self, occurrence: object) -> bool:
        return (
            getattr(occurrence, "family", None) is self.family
            and getattr(getattr(occurrence, "source", None), "value", None) == self.source_key
            and getattr(getattr(occurrence, "classification", None), "value", None)
            == self.event_type
            and type(getattr(occurrence, "semantic_envelope", None)) is self.envelope_type
            and type(getattr(occurrence, "participants", None)) is self.participants_type
        )


@dataclass(frozen=True)
class C0CausalEdgeIR:
    causal_key: str
    predecessor: C0OccurrenceContractIR
    target_source: str

    def __post_init__(self) -> None:
        if (
            type(self.causal_key) is not str
            or not self.causal_key
            or type(self.predecessor) is not C0OccurrenceContractIR
            or type(self.target_source) is not str
            or not self.target_source
            or self.target_source == self.predecessor.source_key
        ):
            raise C0LawError("causal edge IR is malformed or self-triggering")


@dataclass(frozen=True)
class C0TransitionIR:
    source_key: str
    event_type: str
    value: C0ValueProgram
    effects: tuple[tuple[str, str, str], ...]
    owners: tuple[C0StaticOwnerIR, ...]
    formation: C0FormationKind
    actor_product: C0ActorProductIR | None = dc_field(default=None, kw_only=True)
    object_product: C0ObjectProductIR | None = dc_field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if (
            type(self.source_key) is not str
            or not self.source_key
            or type(self.event_type) is not str
            or not self.event_type
            or type(self.value) is not C0ValueProgram
            or type(self.formation) is not C0FormationKind
            or type(self.effects) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 3
                or any(type(name) is not str or not name for name in item)
                for item in self.effects
            )
            or len({(root, field) for root, field, _ in self.effects}) != len(self.effects)
            or type(self.owners) is not tuple
            or any(type(owner) is not C0StaticOwnerIR for owner in self.owners)
        ):
            raise C0LawError("transition IR is not a closed checked declaration")
        if self.actor_product is not None:
            if type(self.actor_product) is not C0ActorProductIR:
                raise C0LawError("transition contains a foreign Actor product")
            self.actor_product.check(self.value._ports.outputs)
        if self.object_product is not None:
            if type(self.object_product) is not C0ObjectProductIR:
                raise C0LawError("transition contains a foreign Object product")
            if self.formation is not C0FormationKind.AFTER_OCCURRENCE:
                raise C0LawError("Object product requires direct causal formation")
            self.object_product.check(self.value._ports.outputs)

    def condition(self, roots: dict[str, object], *, formed: bool = False) -> bool:
        accepted = self.value.admits(roots)
        if not accepted and (formed or self.formation.when_false == "defect"):
            raise C0ValueStateError("formed transition has no admitted effect")
        return accepted

    def evaluate(self, roots: dict[str, object], *, occurrence: object) -> dict[str, object]:
        result = self.value.evaluate(roots, occurrence=occurrence)
        if result is None:
            raise C0ValueStateError("formed transition lost its admitted basis")
        return result

    def check_causal_binding(
        self,
        *,
        source_key: str,
        event_type: str,
        value_ports: C0ValuePorts,
        owners: tuple[C0StaticOwnerIR, ...],
        write_root: str,
        protected_fields: frozenset[str] = frozenset(),
    ) -> None:
        if (
            self.formation is not C0FormationKind.AFTER_OCCURRENCE
            or self.source_key != source_key
            or self.event_type != event_type
            or self.value._ports != value_ports
            or self.owners != owners
            or (not self.effects and self.actor_product is None and self.object_product is None)
            or {output for _, _, output in self.effects}
            | product_outputs(self.actor_product)
            | product_outputs(self.object_product)
            != set(value_ports.outputs)
            or {output for _, _, output in self.effects}
            & (product_outputs(self.actor_product) | product_outputs(self.object_product))
            or product_outputs(self.actor_product) & product_outputs(self.object_product)
            or len({output for _, _, output in self.effects}) != len(self.effects)
        ):
            raise C0LawError("causal transition IR differs from its checked ports")
        state_type = next(owner.state_type for owner in owners if owner.root == write_root)
        fields = get_type_hints(state_type)
        for root, field, output in self.effects:
            if (
                root != write_root
                or field in protected_fields
                or field not in value_ports.writable_fields.get(state_type, frozenset())
                or f"{root}.{field}" not in value_ports.writable_paths
                or not _assignable(value_ports.outputs[output], fields.get(field))
            ):
                raise C0LawError("causal transition IR crosses a typed owner write port")


@dataclass(frozen=True)
class C0ScheduleEffectIR:
    due_source: str
    one_shot_field: str
    marker_output: str
    subject_output: str
    delay_output: str

    def __post_init__(self) -> None:
        if (
            any(
                type(name) is not str or not name
                for name in (
                    self.due_source,
                    self.one_shot_field,
                    self.marker_output,
                    self.subject_output,
                    self.delay_output,
                )
            )
            or len({self.marker_output, self.subject_output, self.delay_output}) != 3
        ):
            raise C0LawError("scheduling effect IR lacks distinct bound outputs")


@dataclass(frozen=True)
class C0ObjectFormationEffectIR:
    family: str
    state_type: type
    initial_output: str

    def __post_init__(self) -> None:
        if (
            type(self.family) is not str
            or not self.family
            or not isinstance(self.state_type, type)
            or type(self.initial_output) is not str
            or not self.initial_output
        ):
            raise C0LawError("Object formation effect IR lacks nominal family/state/output")


@dataclass(frozen=True)
class C0ActionLawIR(C0TransitionIR):
    envelope_fields: tuple[tuple[str, str], ...]
    selected: tuple[C0SelectedOwnerIR, ...]
    target_mode: bool
    schedule: C0ScheduleEffectIR | None
    form: C0ObjectFormationEffectIR | None
    self_actor: tuple[str, type] | None = dc_field(default=None, kw_only=True)
    actor_domains: tuple = dc_field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.formation is not C0FormationKind.SUBMIT:
            raise C0LawError("Action IR needs Submit formation")
        if self.self_actor is not None and (
            type(self.self_actor) is not tuple
            or len(self.self_actor) != 2
            or type(self.self_actor[0]) is not str
            or not self.self_actor[0]
            or not isinstance(self.self_actor[1], type)
            or any(owner.root == "actor" for owner in self.owners)
        ):
            raise C0LawError("Action self must use an instance-relative nominal kind")
        if self.schedule is not None:
            schedule = self.schedule
            if type(schedule) is not C0ScheduleEffectIR:
                raise C0LawError("Action IR has a foreign scheduling effect")
            marker = self.value._tree["outputs"].get(schedule.marker_output)
            if (
                ("actor", schedule.one_shot_field, schedule.marker_output) not in self.effects
                or marker is None
                or set(marker) != {"ref"}
                or marker["ref"] != "occurrence"
                or schedule.delay_output not in self.value._admission_outputs
                or self.value._ports.outputs.get(schedule.subject_output) is not str
                or self.value._ports.outputs.get(schedule.delay_output) is not int
            ):
                raise C0LawError("Action IR one-shot marker must bind its own occurrence")
        if self.form is not None and (
            type(self.form) is not C0ObjectFormationEffectIR
            or self.value._ports.outputs.get(self.form.initial_output) is not self.form.state_type
        ):
            raise C0LawError("Action IR has a foreign Object formation effect")


@dataclass(frozen=True)
class C0DueLawIR(C0TransitionIR):
    fixed_individuals: tuple[C0FixedIndividualIR, ...]
    actor_domains: tuple = dc_field(default=(), kw_only=True)
    read_object_domains: tuple = dc_field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.formation is not C0FormationKind.DUE:
            raise C0LawError("due IR needs Due formation")


@dataclass(frozen=True)
class C0PeriodicFormationIR:
    name: str
    due: str
    interval: int
    max_occurrences: int | None
    subject: str


@dataclass(frozen=True)
class C0TemporalProgramIR:
    mechanism: str
    due_laws: tuple[tuple[str, C0DueLawIR], ...]
    order: tuple[str, ...]
    max_pending: int
    periodic: tuple[C0PeriodicFormationIR, ...]
    scheduled_sources: tuple[str, ...]
    advance_seats: tuple[str, ...]

    def check(self) -> None:
        if (
            self.mechanism not in ("ordered_due_microsteps", "action_value_event_jump")
            or type(self.due_laws) is not tuple
            or any(type(item) is not tuple or len(item) != 2 for item in self.due_laws)
            or any(
                type(name) is not str
                or not name
                or type(law) is not C0DueLawIR
                or type(law.source_key) is not str
                or not law.source_key
                or type(law.event_type) is not str
                or not law.event_type
                for name, law in self.due_laws
            )
            or len({name for name, _ in self.due_laws}) != len(self.due_laws)
            or type(self.order) is not tuple
            or any(type(name) is not str or not name for name in self.order)
            or len(self.order) != len(self.due_laws)
            or len(set(self.order)) != len(self.order)
            or set(self.order) != {name for name, _ in self.due_laws}
            or type(self.max_pending) is not int
            or not 0 <= self.max_pending <= len(self.due_laws)
            or (not self.due_laws) != (self.max_pending == 0)
            or type(self.periodic) is not tuple
            or type(self.scheduled_sources) is not tuple
            or any(type(source) is not str or not source for source in self.scheduled_sources)
            or len(set(self.scheduled_sources)) != len(self.scheduled_sources)
            or type(self.advance_seats) is not tuple
            or any(type(seat) is not str or not seat for seat in self.advance_seats)
        ):
            raise ValueError("temporal Program IR has an invalid due selection")
        if len({law.source_key for _, law in self.due_laws}) != len(self.due_laws):
            raise ValueError("temporal Program IR source keys alias")
        due_sources = {law.source_key for _, law in self.due_laws}
        periodic_sources = []
        names = set()
        due_by_name = dict(self.due_laws)
        for plan in self.periodic:
            if (
                type(plan) is not C0PeriodicFormationIR
                or type(plan.name) is not str
                or not plan.name
                or plan.name in names
                or type(plan.due) is not str
                or plan.due not in due_by_name
                or type(plan.interval) is not int
                or plan.interval < 1
                or (
                    plan.max_occurrences is not None
                    and (
                        type(plan.max_occurrences) is not int
                        or not 1 <= plan.max_occurrences <= 1024
                    )
                )
                or type(plan.subject) is not str
                or not plan.subject
            ):
                raise ValueError("temporal Program IR has an invalid periodic formation")
            names.add(plan.name)
            periodic_sources.append(due_by_name[plan.due].source_key)
        if self.mechanism == "ordered_due_microsteps":
            if (
                not self.due_laws
                or self.periodic
                or not self.advance_seats
                or len(set(self.advance_seats)) != len(self.advance_seats)
                or set(self.scheduled_sources) != due_sources
            ):
                raise ValueError("microstep temporal IR needs one scheduling Action per due Event")
        elif (
            self.advance_seats
            or len(self.periodic) > self.max_pending
            or len(set(periodic_sources)) != len(periodic_sources)
            or set(periodic_sources) & set(self.scheduled_sources)
            or set(periodic_sources) | set(self.scheduled_sources) != due_sources
        ):
            raise ValueError("event-jump temporal IR has incomplete formation")
