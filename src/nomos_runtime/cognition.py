"""Atomic personal revision from actual receipts and generated pure functions."""

from dataclasses import dataclass, replace
from types import MappingProxyType

from .entities import ReadContext, Reference, ReferenceDomain
from .errors import AdmissionError, SettlementDefect
from .expressions import ExpressionError, ValueBindingError, ValueBudget


@dataclass(frozen=True)
class RevisionRule:
    name: str
    channel: str
    source: str
    type_name: str
    evaluate: object


@dataclass(frozen=True)
class Derivation:
    rule: object
    constants: tuple
    resolve: object


@dataclass(frozen=True)
class CognitionDefinition:
    name: str
    digest: str
    selector: str
    target: str
    families: tuple
    budget: int
    revisions: tuple
    derivations: tuple
    inference_limits: object
    view: object
    analysis: object
    analysis_kind: str | None
    channels: tuple


@dataclass(frozen=True)
class CognitionLibrary:
    definitions: tuple
    terms: object


@dataclass(frozen=True)
class CognitionSlot:
    name: str
    actor: Reference
    state: object
    basis: object
    view: object
    inputs: tuple
    references: frozenset
    known: frozenset


class Terms:
    def __init__(self, session, references):
        self.session, self.references = session, references
        self.codecs = session.program.cognition.terms

    def term(self, name, value):
        from nomos_cognition import Term

        signature, pack, _, check = self.codecs[name]
        self.validate(name, value)
        return Term(name, signature, pack(value))

    def validate(self, name, value):
        return self.codecs[name][3](
            value, ValueBudget(self.session.limits.value, self.references), ()
        )

    def value(self, term):
        signature, _, unpack, check = self.codecs[term.name]
        if signature != term.signature:
            raise ValueError("cognition term has a foreign nominal signature")
        return check(unpack(term.wire), ValueBudget(self.session.limits.value, self.references), ())


def personal_terms(session, states, actor, receipts):
    references = session.references.at(states)
    known = {
        ref
        for ref in references.references
        if session.program.schemas[ref.sort].reference == "public"
    }
    known.add(actor)
    for receipt in receipts:
        if receipt.recipient != actor:
            raise ValueError("cognition receipt belongs to another Actor")
        known.update(session.program.reference_readers[receipt.type_name](receipt.value))
    return Terms(
        session,
        ReferenceDomain(
            references.schemas,
            references.symbols,
            references=references.references,
            allowed=known,
        ),
    )


def read_context(session, codec, actor, *, mode="actor"):
    return ReadContext(
        session.program.schema_id,
        codec.references,
        MappingProxyType({}),
        mode,
        session.program.reference_readers,
        controller=actor,
    )


def holder(actor):
    return f"{actor.sort}:{actor.ordinal}"


def ground(actor, receipt):
    from nomos_cognition import Evidence

    return Evidence(actor.scope, receipt.source, receipt.channel, holder(actor), receipt.occurrence)


def selected(session, actor):
    library = session.program.cognition
    if library is None:
        return None
    symbols = dict(session.symbols)
    return next(
        (
            definition
            for definition in library.definitions
            if actor.sort in definition.families
            and (definition.selector == "kind" or symbols.get(definition.target) == actor)
        ),
        None,
    )


def derive(definition, state, codec, actor):
    from nomos_cognition.reasoning import evaluate

    plans = {plan.rule.name: plan for plan in definition.derivations}
    constants = {}

    def constant(name, index):
        if (name, index) not in constants:
            constants[name, index] = plans[name].constants[index](codec.session, codec, actor)
        return constants[name, index]

    return evaluate(
        definition.digest,
        (actor.scope, holder(actor)),
        state.frames,
        tuple(plan.rule for plan in definition.derivations),
        constant=constant,
        resolve=lambda name, bindings, meter: plans[name].resolve(
            codec.session, codec, actor, bindings, meter
        ),
        limits=definition.inference_limits,
    )


def revise_person(session, definition, state, actor, receipts, codec):
    from nomos_cognition import revise
    from nomos_cognition.reasoning import ReasoningBudget
    from nomos_cognition.state import install_reasoning

    groups = {}
    for receipt in receipts:
        evidence = ground(actor, receipt)
        rules = tuple(
            rule
            for rule in definition.revisions
            if (rule.source, rule.channel) == (receipt.source, receipt.channel)
        )
        if rules and evidence not in state.consumed:
            groups.setdefault(evidence, ([], rules))[0].append(receipt)
    candidates = [(tuple(items), evidence, rules) for evidence, (items, rules) in groups.items()]
    candidates.sort(
        key=lambda item: (
            item[1].occurrence is not None,
            item[1].occurrence or 0,
            item[1].producer,
            item[1].slot,
        )
    )
    try:
        for items, evidence, rules in candidates[: definition.budget]:
            if any(receipt.type_name != rule.type_name for receipt in items for rule in rules):
                raise ValueError("cognition received a foreign nominal evidence type")
            # One publication/slot can carry several values. Consume its ground
            # once, retaining the last revision of each declared cognitive slot.
            frames = tuple(
                {
                    (frame.rule, frame.slot): frame
                    for receipt in items
                    for rule in rules
                    if (
                        frame := rule.evaluate(
                            session, codec, actor, state, receipt.value, evidence
                        )
                    )
                    is not None
                }.values()
            )
            state = revise(state, (evidence,), frames, pending=False)
        state = revise(state, (), (), pending=len(candidates) > definition.budget)
        if not state.pending or len(candidates) <= definition.budget:
            state = install_reasoning(state, derive(definition, state, codec, actor))
    except ReasoningBudget:
        state = revise(state, (), (), pending=True)
    except (ExpressionError, ValueBindingError) as error:
        if error.diagnostic.code not in ("ExpressionBudget", "ValueBudget"):
            raise
        state = revise(state, (), (), pending=True)
    base = state
    analysis = None
    if definition.analysis is not None:
        from nomos_cognition.state import install_analysis, install_local

        install = install_local if definition.analysis_kind == "local" else install_analysis
        analysis = definition.analysis(session, codec, actor, receipts)
        state = install(base, analysis)
    try:
        view = definition.view(session, codec, state, False)
    except (ExpressionError, ValueBindingError) as error:
        if error.diagnostic.code not in ("ExpressionBudget", "ValueBudget"):
            raise
        state = revise(base, (), (), pending=True)
        if analysis is not None:
            if definition.analysis_kind == "local":
                analysis = replace(
                    analysis, status="pending", bounds=(), conflict=(), reason="ValueBudget"
                )
            else:
                analysis = replace(
                    analysis, status="pending", models=(), answers=(), reason="ValueBudget"
                )
            state = install(state, analysis)
        view = definition.view(session, codec, state, False)
    return state, view


def checkpoint(session, states, receipts, basis, previous):
    if session.program.cognition is None:
        return previous
    from nomos_cognition import State

    result = dict(previous)
    for actor in sorted(
        (
            ref
            for ref in states
            if type(ref) is Reference and session.program.schemas[ref.sort].kind == "person"
        ),
        key=lambda ref: ref.ordinal,
    ):
        definition = selected(session, actor)
        if definition is None:
            continue
        reports = tuple(
            receipt
            for receipt in (*session._opening_receipts, *receipts)
            if receipt.recipient == actor
        )
        codec = personal_terms(session, states, actor, reports)
        old = previous.get(actor)
        if old is not None and old.state.model != definition.digest:
            raise ValueError("cognition model changed during a Session")
        inputs = tuple(
            receipt
            for receipt in reports
            if (receipt.source, receipt.channel) in definition.channels
        )
        unchanged = (
            old is not None
            and old.view.complete
            and old.inputs == inputs
            and old.references == codec.references.references
            and old.known == codec.references.allowed
        )
        if unchanged:
            result[actor] = replace(old, basis=basis)
            continue
        state = State(definition.digest) if old is None else old.state
        if old is None:
            definition.view(session, codec, state, False)
        state, view = revise_person(session, definition, state, actor, reports, codec)
        result[actor] = CognitionSlot(
            definition.name,
            actor,
            state,
            basis,
            view,
            inputs,
            codec.references.references,
            codec.references.allowed,
        )
    return MappingProxyType(result)


def current(session, actor, name=None):
    if session._busy or session._fatal:
        raise SettlementDefect("cognition is unavailable during settlement or after fatal")
    reference = actor if type(actor) is Reference else session._actor(actor)
    slot = session._minds.get(reference)
    if slot is None or name is not None and slot.name != name:
        raise AdmissionError("NoCognition", "Actor has no such selected cognition")
    return slot


def explanation(session, actor, encode):
    from nomos_cognition.explanation import explain

    slot = current(session, session._actor(actor))
    definition = selected(session, slot.actor)
    receipts = tuple(
        receipt
        for receipt in (*session._opening_receipts, *session._receipts)
        if receipt.recipient == slot.actor
    )
    codec = personal_terms(session, session._states, slot.actor, receipts)
    if encode is None:
        encode = session.values(actor).encode
    return {
        "binding": slot.name,
        "revision": slot.state.revision,
        **explain(
            slot.state,
            encode=lambda term: encode(term.name, codec.value(term)),
            limits=definition.inference_limits,
            analysis_kind=definition.analysis_kind,
        ),
    }
