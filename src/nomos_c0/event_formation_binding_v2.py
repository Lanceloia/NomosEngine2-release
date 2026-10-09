"""Bind checked Event formations to exact selected backend ports."""

from __future__ import annotations

from dataclasses import dataclass

from .event_formation_ir_v2 import (
    EventFormationProgram,
    FormationMechanism,
    FormationTriggerKind,
)
from .nominal_types_v1 import EventSortRef


class EventFormationPlanError(ValueError):
    """A checked formation rule cannot bind to the selected ports."""


@dataclass(frozen=True)
class EventFormationPort:
    result_entry: str
    result_source: str
    result_event_type: str
    trigger_entry: str
    trigger_source: str
    trigger_event_type: str
    causal_law: str | None

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value
            for name, value in vars(self).items()
            if name != "causal_law"
        ) or (
            self.causal_law is not None
            and (type(self.causal_law) is not str or not self.causal_law)
        ):
            raise EventFormationPlanError("Event formation port has an empty or malformed field")


@dataclass(frozen=True)
class BoundEventFormation:
    result_sort: EventSortRef
    trigger_kind: FormationTriggerKind
    mechanism: FormationMechanism
    port: EventFormationPort


@dataclass(frozen=True)
class EventFormationPlan:
    semantic_program: EventFormationProgram
    edges: tuple[BoundEventFormation, ...]


def bind_event_formation_ports(
    semantic_program: EventFormationProgram,
    ports: tuple[EventFormationPort, ...],
) -> EventFormationPlan:
    if type(semantic_program) is not EventFormationProgram or type(ports) is not tuple:
        raise EventFormationPlanError("formation binding needs exact semantic and port inputs")
    if any(type(port) is not EventFormationPort for port in ports):
        raise EventFormationPlanError("formation binding has a foreign port")
    bound = {port.result_entry: port for port in ports}
    if len(bound) != len(ports) or set(bound) != {
        rule.result_entry for rule in semantic_program.rules
    }:
        raise EventFormationPlanError("formation ports do not cover exactly the checked rules")
    edges = []
    sort_by_source: dict[str, EventSortRef] = {}
    mechanism_by_source: dict[str, FormationMechanism] = {}
    formation_keys: set[tuple[str, str | None]] = set()
    for rule in semantic_program.rules:
        port = bound[rule.result_entry]
        if port.trigger_entry != rule.trigger_entry:
            raise EventFormationPlanError("formation port changes the checked trigger")
        if (rule.mechanism is FormationMechanism.CAUSAL) != (port.causal_law is not None):
            raise EventFormationPlanError("formation port changes the checked mechanism")
        prior = sort_by_source.setdefault(port.result_source, rule.result_sort)
        if prior != rule.result_sort:
            raise EventFormationPlanError("shared Event source has conflicting Event sorts")
        prior_mechanism = mechanism_by_source.setdefault(port.result_source, rule.mechanism)
        if prior_mechanism is not rule.mechanism:
            raise EventFormationPlanError("shared Event source has conflicting mechanisms")
        formation_key = (port.result_source, port.causal_law)
        if formation_key in formation_keys:
            raise EventFormationPlanError("formation port repeats one runtime formation basis")
        formation_keys.add(formation_key)
        if rule.trigger_kind is FormationTriggerKind.EVENT:
            trigger = bound.get(rule.trigger_entry)
            if (
                trigger is None
                or trigger.result_source != port.trigger_source
                or trigger.result_event_type != port.trigger_event_type
            ):
                raise EventFormationPlanError("Event trigger binding is not closed")
        edges.append(BoundEventFormation(rule.result_sort, rule.trigger_kind, rule.mechanism, port))
    return EventFormationPlan(semantic_program, tuple(edges))
