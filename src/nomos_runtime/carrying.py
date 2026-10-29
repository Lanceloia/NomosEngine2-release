"""Private proposal storage for generated possession rules, not legal ownership."""

from dataclasses import dataclass
from types import MappingProxyType

from .errors import SettlementDefect


@dataclass(frozen=True)
class CarryingDefinition:
    name: str
    item: str
    person: str
    holder: str
    ground: str
    position: str


@dataclass(frozen=True)
class ProposalKey:
    relation: str
    item: object


@dataclass(frozen=True)
class CarryOffer:
    giver: object
    recipient: object
    source: int


def opening_states(program, references):
    return {
        ProposalKey(plan.name, item): MappingProxyType({"offer": None})
        for plan in program.relations.values()
        for item in references.known(plan.item)
    }


def require_item(program, references, name, item):
    plan = program.relations.get(name)
    if plan is None:
        raise SettlementDefect("effect names no declared carrying relation")
    references.require(item, plan.item)
    return plan


def validate(program, references, states):
    for key, state in states.items():
        if type(key) is not ProposalKey:
            continue
        plan = require_item(program, references, key.relation, key.item)
        offer = state["offer"]
        if offer is not None:
            if type(offer) is not CarryOffer or type(offer.source) is not int or offer.source < 1:
                raise SettlementDefect("carrying proposal needs an actual occurrence")
            references.require(offer.giver, plan.person)
            references.require(offer.recipient, plan.person)
            if offer.giver == offer.recipient or states[key.item][plan.holder] != offer.giver:
                raise SettlementDefect("carrying proposal no longer belongs to the current holder")


def proposal(draft, name, item):
    require_item(draft.program, draft.references, name, item)
    return draft.before[ProposalKey(name, item)]["offer"]


def set_proposal(draft, name, item, offer):
    plan = require_item(draft.program, draft.references, name, item)
    if offer is not None:
        if type(offer) is not CarryOffer or offer.source != draft.occurrence:
            raise SettlementDefect("proposal source differs from the current occurrence")
        draft.references.require(offer.giver, plan.person)
        draft.references.require(offer.recipient, plan.person)
    key = (ProposalKey(name, item), "offer")
    if key in draft.changes:
        raise SettlementDefect("multiple effects write the same carrying proposal")
    draft.changes[key] = offer


def set_field(draft, name, item, field, value):
    plan = require_item(draft.program, draft.references, name, item)
    if field not in (plan.holder, plan.ground):
        raise SettlementDefect("carrying effect names no managed field")
    draft._set(item, dict(draft.program.schemas[item.sort].fields), field, value)
