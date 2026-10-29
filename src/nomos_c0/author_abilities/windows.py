"""Finite captured response windows; policy never depends on secret capabilities."""

from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError


@dataclass(frozen=True)
class WindowPlan:
    participants: str
    order: str
    successor: str

    def roster(self, captures):
        return captures[self.participants].value

    def available(self, captures, responded):
        remaining = tuple(actor for actor in self.roster(captures) if actor not in responded)
        return remaining[:1] if self.order == "declared" else remaining


def compile_window(declaration, bindings, actor_type, table, entities, successors, path):
    from .frontend import row

    row(declaration, {"participants", "order", "responses"}, path=path)
    name, order = declaration["participants"], declaration["order"]
    if type(name) is not str or name not in bindings:
        raise C0LawError(f"{path}.participants: captured roster binding required")
    if order not in ("independent", "declared") or declaration["responses"] != "once_each":
        raise C0LawError(f"UnsupportedFeature: {path}: explicit order and once_each required")
    roster, chooser = table[bindings[name]], table[actor_type]
    if (
        roster.kind != ("set" if order == "independent" else "sequence")
        or roster.element.type_id != chooser.type_id
        or chooser.kind != "ref"
        or dict(entities.entities)[chooser.sort].kind != "person"
        or dict(entities.entities)[chooser.sort].reference != "public"
    ):
        raise C0LawError(f"{path}: public Person Set/Sequence must match the chooser type")
    if len(successors) != 1:
        raise C0LawError(f"{path}: all responses must share one declared successor")
    return WindowPlan(name, order, next(iter(successors)))
