"""One checked Program; neither Assets nor executable layout belong here."""

from __future__ import annotations

from dataclasses import dataclass

from .actor_template_v1 import C0ActorTemplateIR
from .author_contract_v1 import C0LawError
from .control_ir_v1 import C0ControlIR
from .event_formation_ir_v2 import (
    EventFormationProgram,
    FormationMechanism,
    FormationTriggerKind,
)
from .nominal_types_v1 import IRValidationError
from .opening_construction_v1 import C0OpeningConstructionIR
from .visibility_ir_v1 import C0VisibilityIR
from .world_ir_v1 import C0WorldIR


@dataclass(frozen=True)
class C0ProgramIR:
    world: C0WorldIR
    control: C0ControlIR
    visibility: C0VisibilityIR
    event_formations: EventFormationProgram | None = None
    actor_templates: tuple[C0ActorTemplateIR, ...] = ()
    opening_constructions: tuple[C0OpeningConstructionIR, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.world) is not C0WorldIR
            or type(self.control) is not C0ControlIR
            or type(self.visibility) is not C0VisibilityIR
            or self.control.world is not self.world
            or self.visibility.world is not self.world
        ):
            raise C0LawError("Program partitions do not share one checked world")
        self.world.__post_init__()
        self.control.__post_init__()
        self.visibility.__post_init__()
        if (
            type(self.opening_constructions) is not tuple
            or any(type(item) is not C0OpeningConstructionIR for item in self.opening_constructions)
            or len({item.port.kind for item in self.opening_constructions})
            != len(self.opening_constructions)
            or any(
                item.port.kind not in self.world.selected_kinds
                for item in self.opening_constructions
            )
        ):
            raise C0LawError("Program opening constructions differ from the selected world")
        for construction in self.opening_constructions:
            construction.__post_init__()
        if (
            type(self.actor_templates) is not tuple
            or any(type(item) is not C0ActorTemplateIR for item in self.actor_templates)
            or tuple(item.kind for item in self.actor_templates) != self.world.selected_actor_kinds
            or (self.actor_templates and self.control.mode != "action_value_event_jump")
        ):
            raise C0LawError("Program Actor templates differ from the selected world/control")
        if tuple((s.symbol, s.actor, s.entries) for s in self.control.seats) != tuple(
            (s.symbol, s.actor, s.entries) for s in self.visibility.seats
        ):
            raise C0LawError("Program control and visibility disagree on seats or entries")
        outcomes = {item.outcome for item in self.control.world_stops}
        if any(
            outcome not in outcomes
            for seat in self.visibility.seats
            if seat.presentation is not None
            for _, outcome, _ in seat.presentation.finish_on_action
        ):
            raise C0LawError("Program presentation names an undeclared world stop")
        if self.event_formations is None:
            return
        if type(self.event_formations) is not EventFormationProgram:
            raise C0LawError("Program Event formation declaration is malformed")
        try:
            self.event_formations.__post_init__()
        except IRValidationError as error:
            raise C0LawError("Program Event formation declaration is invalid") from error
        entries = {item.symbol: item for item in self.world.transitions}
        for rule in self.event_formations.rules:
            result, trigger = entries.get(rule.result_entry), entries.get(rule.trigger_entry)
            if (
                result is None
                or trigger is None
                or result.kind == "action"
                or (trigger.kind == "action") != (rule.trigger_kind is FormationTriggerKind.ACTION)
            ):
                raise C0LawError("Program Event rule names an incompatible occurrence")
            if rule.mechanism is FormationMechanism.CAUSAL:
                valid = result.predecessor == trigger.occurrence
            else:
                valid = (
                    result.kind == "due"
                    and trigger.action is not None
                    and trigger.action.schedule is not None
                    and trigger.action.schedule.due == result.occurrence
                )
            if not valid:
                raise C0LawError("Program Event rule differs from its world formation")
