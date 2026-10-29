"""Compile author source ordering without exposing native owner permissions."""

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class SettlementStep:
    reaction: str
    source: str
    required: bool


@dataclass(frozen=True)
class SettlementPlan:
    trigger: str
    source: str
    steps: tuple
    key: str


def compile_settlements(declaration, abilities, reactions, world_name):
    from .frontend import row

    row(declaration, {"default"}, {"ordered"}, path="settlement")
    if declaration["default"] != "wave":
        raise C0LawError("settlement.default: supported default is wave")
    ordered = declaration.get("ordered", {})
    if not isinstance(ordered, Mapping):
        raise C0LawError("settlement.ordered needs a mapping of actual use names")
    triggers = {p.name: p for p in (*abilities, *reactions)}
    subscriptions = {p.name: p for p in reactions}
    result = []
    for name, steps in ordered.items():
        trigger = triggers.get(name)
        if trigger is None or type(steps) is not list or not steps:
            raise C0LawError(
                f"settlement.ordered.{name}: selected trigger and nonempty steps required"
            )
        bound = []
        for index, step in enumerate(steps):
            path = f"settlement.ordered.{name}[{index}]"
            row(step, {"reaction", "required"}, path=path)
            if type(step["reaction"]) is not str or type(step["required"]) is not bool:
                raise C0LawError(path + ": exact reaction name and boolean required needed")
            reaction = subscriptions.get(step["reaction"])
            if reaction is None or trigger.source not in reaction.triggers:
                raise C0LawError(path + ": Reaction must subscribe to this actual trigger")
            bound.append(
                SettlementStep(
                    reaction.name,
                    reaction.source,
                    step["required"],
                )
            )
        expected = {p.name for p in reactions if trigger.source in p.triggers}
        if {p.reaction for p in bound} != expected or len(bound) != len(expected):
            raise C0LawError(
                f"settlement.ordered.{name}: cover each direct subscription exactly once"
            )
        result.append(
            SettlementPlan(
                name,
                trigger.source,
                tuple(bound),
                f"author.{world_name}.{name}.ordered",
            )
        )
    return tuple(result)
