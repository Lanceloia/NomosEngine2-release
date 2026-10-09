"""Checked startup assertions and control declarations, without backend layout."""

from __future__ import annotations

from dataclasses import dataclass

from .author_contract_v1 import C0LawError
from .checked_value_binding_v1 import C0CheckedValueIR
from .world_ir_v1 import C0WorldIR


@dataclass(frozen=True)
class C0ControlSeatIR:
    symbol: str
    actor: str
    entries: tuple[str, ...]


@dataclass(frozen=True)
class C0ActionValueSeatIR:
    seat: str
    projection: C0CheckedValueIR
    costs: tuple[tuple[str, C0CheckedValueIR], ...]


@dataclass(frozen=True)
class C0WorldStopIR:
    outcome: str
    owners: tuple[str, ...]
    predicate: C0CheckedValueIR


@dataclass(frozen=True)
class C0AppraisalRuleIR:
    entry: str
    mode: str
    value: C0CheckedValueIR | None


@dataclass(frozen=True)
class C0AppraisalProfileIR:
    name: str
    seat: str
    fallback_entry: str
    tie_order: tuple[str, ...]
    rules: tuple[C0AppraisalRuleIR, ...]


@dataclass(frozen=True)
class C0ControlIR:
    world: C0WorldIR
    seats: tuple[C0ControlSeatIR, ...]
    mode: str
    controlled: tuple[str, ...]
    end_at: int | None
    wake_at: tuple[int, ...]
    max_same_time_actions: int | None
    action_values: tuple[C0ActionValueSeatIR, ...]
    world_stops: tuple[C0WorldStopIR, ...]
    appraisals: tuple[C0AppraisalProfileIR, ...]
    opening: C0CheckedValueIR | None

    def __post_init__(self) -> None:
        if type(self.world) is not C0WorldIR or self.mode not in (
            "manual",
            "event_jump_stop",
            "action_value_event_jump",
        ):
            raise C0LawError("control IR lacks its checked world or selected mode")
        owners = {item.symbol for item in self.world.signatures.owners}
        actions = {item.symbol for item in self.world.transitions if item.kind == "action"}
        if (
            type(self.seats) is not tuple
            or not self.seats
            or any(type(seat) is not C0ControlSeatIR for seat in self.seats)
            or len({seat.symbol for seat in self.seats}) != len(self.seats)
            or len({seat.actor for seat in self.seats}) != len(self.seats)
            or any(
                seat.actor not in owners
                or not seat.entries
                or len(set(seat.entries)) != len(seat.entries)
                or not set(seat.entries) <= actions
                for seat in self.seats
            )
            or type(self.controlled) is not tuple
            or len(set(self.controlled)) != len(self.controlled)
            or not set(self.controlled) <= {seat.symbol for seat in self.seats}
        ):
            raise C0LawError("control IR has an undeclared or aliased seat/entry")
        if (
            (
                self.end_at is not None
                and (type(self.end_at) is not int or not 0 <= self.end_at <= (1 << 63) - 1)
            )
            or (
                type(self.wake_at) is not tuple
                or any(
                    type(at) is not int or self.end_at is None or not 0 <= at <= self.end_at
                    for at in self.wake_at
                )
                or self.wake_at != tuple(sorted(set(self.wake_at)))
            )
            or (self.mode == "event_jump_stop" and self.end_at is None)
            or (
                self.mode == "action_value_event_jump"
                and (
                    self.end_at == 0
                    or type(self.max_same_time_actions) is not int
                    or not 1 <= self.max_same_time_actions <= 1024
                )
            )
        ):
            raise C0LawError("control IR has invalid time or scheduling bounds")
        if (
            type(self.action_values) is not tuple
            or any(type(item) is not C0ActionValueSeatIR for item in self.action_values)
            or type(self.world_stops) is not tuple
            or any(type(item) is not C0WorldStopIR for item in self.world_stops)
            or len({item.outcome for item in self.world_stops}) != len(self.world_stops)
            or type(self.appraisals) is not tuple
            or any(type(item) is not C0AppraisalProfileIR for item in self.appraisals)
            or len({item.name for item in self.appraisals}) != len(self.appraisals)
        ):
            raise C0LawError("control IR has malformed or aliased projections")
        values = [self.opening] if self.opening is not None else []
        values.extend(
            value
            for item in self.action_values
            for value in (item.projection, *(v for _, v in item.costs))
        )
        values.extend(item.predicate for item in self.world_stops)
        values.extend(
            rule.value for item in self.appraisals for rule in item.rules if rule.value is not None
        )
        if any(
            type(value) is not C0CheckedValueIR or value.signatures is not self.world.signatures
            for value in values
        ):
            raise C0LawError("control value differs from its world signatures")
