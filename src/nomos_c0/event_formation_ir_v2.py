"""Possible causal and due Event formations, without machine ports or occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .nominal_types_v1 import EventSortRef, IRValidationError

EVENT_FORMATION_VERSION = "c0.event_formation.v2"


class FormationTriggerKind(StrEnum):
    ACTION = "action"
    EVENT = "event"


class FormationMechanism(StrEnum):
    CAUSAL = "causal"
    DUE = "due"


@dataclass(frozen=True)
class EventFormationRule:
    result_entry: str
    result_sort: EventSortRef
    trigger_entry: str
    trigger_kind: FormationTriggerKind
    mechanism: FormationMechanism
    trigger_sort: EventSortRef | None = None

    def __post_init__(self) -> None:
        if (
            type(self.result_entry) is not str
            or not self.result_entry
            or type(self.trigger_entry) is not str
            or not self.trigger_entry
            or self.result_entry == self.trigger_entry
            or type(self.result_sort) is not EventSortRef
            or type(self.trigger_kind) is not FormationTriggerKind
            or type(self.mechanism) is not FormationMechanism
        ):
            raise IRValidationError("Event formation rule has malformed entries or sort")
        if (
            self.mechanism is FormationMechanism.DUE
            and self.trigger_kind is not FormationTriggerKind.ACTION
        ):
            raise IRValidationError("due Event formation needs an Action scheduler")
        if self.trigger_kind is FormationTriggerKind.ACTION:
            if self.trigger_sort is not None:
                raise IRValidationError("Action-triggered Event cannot claim an Event trigger sort")
        elif type(self.trigger_sort) is not EventSortRef:
            raise IRValidationError("Event-triggered formation needs an Event trigger sort")


@dataclass(frozen=True)
class EventFormationProgram:
    event_sorts: tuple[EventSortRef, ...]
    rules: tuple[EventFormationRule, ...]

    def __post_init__(self) -> None:
        if (
            type(self.event_sorts) is not tuple
            or not self.event_sorts
            or any(type(sort) is not EventSortRef for sort in self.event_sorts)
            or self.event_sorts != tuple(sorted(set(self.event_sorts)))
            or type(self.rules) is not tuple
        ):
            raise IRValidationError("Event formation program has malformed declarations")
        if not self.rules or any(type(rule) is not EventFormationRule for rule in self.rules):
            raise IRValidationError("Event formation program needs exact rules")
        if tuple(sorted(self.rules, key=lambda rule: rule.result_entry)) != self.rules:
            raise IRValidationError("Event formation rules must be canonically sorted")
        entries = {rule.result_entry: rule for rule in self.rules}
        if len(entries) != len(self.rules):
            raise IRValidationError("Event formation result entries must be unique")
        if {rule.result_sort for rule in self.rules} != set(self.event_sorts):
            raise IRValidationError("Event formation sorts must be exactly the declared sorts")
        for rule in self.rules:
            if rule.trigger_kind is FormationTriggerKind.EVENT:
                trigger = entries.get(rule.trigger_entry)
                if trigger is None or trigger.result_sort != rule.trigger_sort:
                    raise IRValidationError("Event formation trigger sort is not closed")

    def canonical_projection(
        self,
    ) -> tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]]:
        return (
            EVENT_FORMATION_VERSION,
            tuple(ref.identity.value for ref in self.event_sorts),
            tuple(
                (
                    rule.result_entry,
                    rule.result_sort.identity.value,
                    rule.trigger_entry,
                    rule.trigger_kind.value,
                    rule.mechanism.value,
                    "" if rule.trigger_sort is None else rule.trigger_sort.identity.value,
                )
                for rule in self.rules
            ),
        )
