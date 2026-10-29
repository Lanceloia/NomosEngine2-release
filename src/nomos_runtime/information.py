"""Current queries and immutable acquired information for generated sessions."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from types import MappingProxyType

from .errors import SettlementDefect
from .expressions import fail_value
from .records import Receipt
from .report_inputs import ReportInputBatch


@dataclass(frozen=True)
class ContextDefinition:
    name: str
    bind: object
    check: object
    fields: tuple
    public: tuple
    world_parameters: tuple


@dataclass(frozen=True)
class ContextKey:
    """Internal protocol storage key, never an individual or an Actor input reference."""

    name: str


def opening_states(program, assets, references, limits):
    from .expressions import ValueBudget

    selected = {plan.name: plan for plan in program.contexts if plan.fields}
    wire = assets["contexts"] if selected else {}
    if type(wire) is not dict or set(wire) != set(selected):
        raise ValueError("opening contexts differ from Source")
    states = {}
    for name, plan in selected.items():
        value = wire[name]
        if type(value) is not dict or set(value) != set(dict(plan.fields)):
            raise ValueError("context opening requires exact declared fields")
        states[ContextKey(name)] = MappingProxyType(
            {
                field: program.decoders[kind](value[field], ValueBudget(limits, references), ())
                for field, kind in plan.fields
            }
        )
    return states


@dataclass(frozen=True)
class ProjectionDefinition:
    name: str
    viewer_sort: str
    type_name: str
    evaluate: object
    grants_identity: bool


@dataclass(frozen=True)
class InformationDefinition:
    name: str
    viewer_sort: str
    type_name: str
    evaluate: object
    certify: object


@dataclass(frozen=True)
class OpeningReceipt:
    source: str
    channel: str
    recipient: object
    type_name: str
    value: object
    guarantees: tuple
    constraints: tuple

    @property
    def occurrence(self):
        return None

    @property
    def sample(self):
        return "opening"


def bind_contexts(session):
    program = session.program
    contexts = {}
    for definition in program.contexts:
        values = definition.bind(session)
        contexts[definition.name] = MappingProxyType(values)
    session._contexts = MappingProxyType(contexts)


def initialize(session):
    program = session.program
    # All opening assertions precede any delivery; no partially initialized Session escapes.
    for definition in program.contexts:
        definition.check(session)
    opening = []
    for definition in program.information.values():
        for _, viewer in session.symbols:
            if program.schemas[viewer.sort].kind != "person" or not session.references.accepts(
                definition.viewer_sort, viewer.sort
            ):
                continue
            available, value = definition.evaluate(session, session._states, viewer)
            if available:
                if len(opening) >= session.limits.value.items:
                    fail_value(
                        "opening", (), "ValueBudget", "bounded opening reports", "receipt capacity"
                    )
                claims, constraints = definition.certify(
                    value, session.context(session._states, controller=viewer), session.limits.value
                )
                opening.append(
                    OpeningReceipt(
                        "author." + program.name + ".opening-information",
                        definition.name,
                        viewer,
                        definition.type_name,
                        value,
                        claims,
                        constraints,
                    )
                )
    session._opening_receipts = tuple(opening)


def deliver(session, draft, row, before, after):
    receipts = []
    for delivery in draft.deliveries:
        reads = session.context(before)
        if delivery.sample == "after":
            reads = replace(reads, states=after)
        recipients, value, claims, constraints = delivery.project(
            delivery.arguments, reads, session.limits.value
        )
        for recipient in sorted(recipients, key=lambda ref: ref.ordinal):
            reads.references.require(recipient, recipient.sort)
            if session.program.schemas[recipient.sort].kind != "person":
                raise SettlementDefect("disclosure recipient is not an Actor")
            receipts.append(
                Receipt(
                    row.reference,
                    row.source,
                    delivery.channel,
                    recipient,
                    delivery.type_name,
                    value,
                    delivery.sample,
                    claims,
                    constraints,
                )
            )
    return tuple(receipts)


def acquired_references(readers, opening, receipts, controller):
    allowed = set()
    for group in (opening, receipts):
        for receipt in group:
            if receipt.recipient == controller:
                allowed.update(readers[receipt.type_name](receipt.value))
    return frozenset(allowed)


class AcquiredReferenceBatch:
    """One immutable receipt extraction, never a cached current permission domain."""

    def __init__(self):
        self.inputs = None
        self.references = None

    def read(self, readers, opening, receipts, controller):
        inputs = readers, opening, receipts, controller
        if self.inputs is None or any(
            current is not prior for current, prior in zip(inputs, self.inputs, strict=True)
        ):
            references = acquired_references(*inputs)
            self.inputs, self.references = inputs, references
        return self.references


@contextmanager
def candidate_input_batch(session):
    prior = session._acquired_reference_batch, session._report_input_batch
    session._acquired_reference_batch = AcquiredReferenceBatch()
    reports = session._report_input_batch = ReportInputBatch()
    try:
        yield
    finally:
        reports.input_proofs.close()
        session._acquired_reference_batch, session._report_input_batch = prior


def visible_references(session, states, controller, receipts, *, acquired=None):
    references = session.references.at(states)
    allowed = {
        ref
        for ref in references.references
        if session.program.schemas[ref.sort].reference == "public"
    }
    allowed.add(controller)
    for plan in session.program.contexts:
        fields = dict(plan.fields)
        for name in plan.public:
            value = states[ContextKey(plan.name)][name]
            allowed.update(session.program.reference_readers[fields[name]](value))
    extract = acquired_references if acquired is None else acquired.read
    allowed.update(
        extract(session.program.reference_readers, session._opening_receipts, receipts, controller)
    )
    for definition in session.program.projections.values():
        if not definition.grants_identity or not references.accepts(
            definition.viewer_sort, controller.sort
        ):
            continue
        available, value = definition.evaluate(session, states, controller)
        if available:
            allowed.update(session.program.reference_readers[definition.type_name](value))
    visible = references.restricted(allowed)
    visible.schemas = session.program.schemas
    return visible
