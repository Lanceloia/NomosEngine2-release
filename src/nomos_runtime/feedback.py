"""Checked data-only feedback association over committed recipient-local inputs."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, fields
from types import MappingProxyType

from nomos_cognition.appraisal import feedback
from nomos_cognition.memory import Context, Episode, Memory, Source, retain, revise_samples
from nomos_cognition.state import Term

from .candidates import selected_strategy
from .entities import ReadContext, ReferenceDomain
from .errors import AdmissionError
from .feedback_index import FeedbackIndex
from .terminals import CheckpointBasis, OpeningBasis


@dataclass(frozen=True)
class FeedbackRelation:
    key: object
    link: object
    roots: object
    depth: int
    projection: tuple

    def __post_init__(self):
        if (
            type(self.depth) is not int
            or not 1 <= self.depth <= 16
            or type(self.projection) is not tuple
            or len(self.projection) != 2
            or any(type(key) is not str or not key for key in self.projection)
            or any(not callable(value) for value in (self.key, self.link, self.roots))
        ):
            raise ValueError("typed receipt projections and a bounded relation depth required")


@dataclass(frozen=True)
class FeedbackPort:
    name: str
    kind: str
    channel: str
    source: str
    type_name: str
    match: object
    collection_type: str | None
    item: str | None
    until: str | None
    accept: object
    boundary: bool
    relation: FeedbackRelation | None


@dataclass(frozen=True)
class FeedbackRule:
    name: str
    ability: str
    inputs: tuple
    ports: tuple
    evaluate: object
    personal: bool


@dataclass(frozen=True)
class FeedbackUpdate:
    memory: Memory
    cursor: object
    pending: tuple
    samples: tuple
    work: int
    checkpoint: object


def pack(codecs, kind, value):
    signature, encode, _, _ = codecs[kind]
    return Term(kind, signature, encode(value))


def _wire(term):
    return term.name, term.signature, term.wire


def _basis(value):
    if type(value) not in (OpeningBasis, CheckpointBasis):
        raise ValueError("terminal input requires an explicit published basis")
    return type(value).__name__, tuple(getattr(value, f.name) for f in fields(value))


def _episode(subject, context, item, codecs):
    identity, payload = item.identity, item.payload
    if identity.kind == "choice":
        semantic = payload.semantics
        target = None if semantic.target is None else _wire(semantic.target)
        wire = (
            payload.ability,
            payload.profile,
            semantic.features,
            semantic.prior,
            tuple(sorted(semantic.known)),
            target,
            tuple((k, _wire(v)) for k, v in payload.input_terms),
            tuple((k, _wire(v)) for k, v in payload.correlation),
            tuple((k, _wire(v)) for k, v in payload.capture),
            None
            if payload.epoch is None
            else _wire(pack(codecs, payload.epoch.type_name, payload.epoch.value)),
            semantic.valuation,
        )
    elif identity.kind in ("opening", "delivery"):
        wire = (payload.sample, _wire(pack(codecs, payload.type_name, payload.value)))
    elif identity.kind == "terminal":
        wire = (
            _basis(payload.trigger),
            _basis(payload.closed),
            _wire(pack(codecs, payload.type_name, payload.value)),
        )
    else:
        raise ValueError("unknown local input kind")
    return Episode(
        subject,
        _source(context, item),
        Term("RuntimeInput", "actor-local-input-v3", (identity.kind, wire)),
        frozenset({"input"}),
    )


def _source(context, item):
    identity, payload = item.identity, item.payload
    channel = (
        "choice"
        if identity.kind == "choice"
        else "terminal"
        if identity.kind == "terminal"
        else payload.channel
    )
    return Source(
        context,
        payload.source,
        channel,
        f"{identity.recipient.sort}:{identity.recipient.ordinal}",
        f"{identity.kind}:{identity.sequence}",
        None if identity.kind == "terminal" else payload.occurrence,
    )


def _related(port, bucket, positions, lower, upper, saved, reads, limits, indices, tick):
    relation = port.relation
    identity = port.kind, port.channel, port.source, port.type_name, port.item, relation.projection
    tick()
    roots = set(relation.roots(saved, reads, limits))
    if not roots:
        return ()
    cursor, index = indices.get(identity, (0, {}))
    start, stop = bisect_right(positions, lower), bisect_left(positions, upper)
    # Later choices cannot ask for an earlier lower bound. Skip gaps between windows.
    for delivery in bucket[max(cursor, start) : stop]:
        tick(2)
        environment = {port.item: delivery.payload.value}
        key = relation.key(environment, reads, limits)
        link = relation.link(environment, reads, limits)
        if link is not None:
            positions, rows = index.setdefault(link, ([], []))
            positions.append(delivery.identity.sequence)
            rows.append((key, delivery))
    indices[identity] = max(cursor, stop), index
    expanded, selected = set(), {}
    for _ in range(relation.depth):
        following = set()
        for root in roots - expanded:
            tick()
            expanded.add(root)
            positions, rows = index.get(root, ((), ()))
            start, stop = bisect_right(positions, lower), bisect_left(positions, upper)
            for key, delivery in rows[start:stop]:
                tick()
                selected[delivery.identity] = delivery
                following.add(key)
        roots = following
        if not roots:
            break
    return tuple(sorted(selected.values(), key=lambda item: item.identity.sequence))


def feedback_memory(session, actor, memory, *, budget=None, checkpoint=None):
    if type(memory) is not Memory or (
        budget is not None and (type(budget) is not int or budget < 1)
    ):
        raise ValueError("feedback requires a Memory and optional positive work budget")
    strategy = selected_strategy(session, actor)
    if strategy is None or strategy.semantics is None:
        raise AdmissionError("NoCandidateSemantics", "Actor has no selected semantic strategy")
    recipient = session._actor(actor)
    index = FeedbackIndex(session, recipient, strategy, memory, checkpoint)
    model, codecs = strategy.semantics, session.controllers.terms
    context, work = Context(model.domain, recipient.scope), 0

    def tick(count=1):
        nonlocal work
        if budget is not None and count > budget - work:
            raise AdmissionError("FeedbackBudget", "feedback association budget exhausted")
        work += count

    episodes, deliveries = [], {}
    while True:
        batch = session.local_inputs(actor, after=index.cursor, limit=256)
        for item in batch.items:
            tick()
            payload = item.payload
            if item.identity.kind == "choice" and payload.profile != model.domain:
                continue
            episodes.append(_episode(memory.subject, context, item, codecs))
            if item.identity.kind == "choice":
                for _, term in (*payload.input_terms, *payload.correlation, *payload.capture):
                    signature, _, decode, _ = codecs[term.name]
                    if signature != term.signature:
                        raise ValueError("saved choice term has a foreign nominal signature")
                    index.known = index.known.update(
                        session.program.reference_readers[term.name](decode(term.wire))
                    )
                for rule in strategy.feedback:
                    if rule.ability != payload.ability:
                        continue
                    tick()
                    if len({port.name for port in rule.ports}) != len(rule.ports):
                        raise AdmissionError(
                            "AliasedFeedback", "receipt port names must be distinct"
                        )
                    index.register(item, rule)
            else:
                index.known = index.known.update(
                    session.program.reference_readers[payload.type_name](payload.value)
                )
                if item.identity.kind in ("delivery", "terminal"):
                    channel = payload.channel if item.identity.kind == "delivery" else "terminal"
                    key = item.identity.kind, channel, payload.source, payload.type_name
                    deliveries.setdefault(key, []).append(item)
        index.cursor = batch.cursor
        if batch.complete:
            break
    reads = ReadContext(
        session.program.schema_id,
        ReferenceDomain(session.program.schemas, (), references=index.known),
        MappingProxyType({}),
        "actor",
        session.program.reference_readers,
    )
    index.extend(deliveries, reads, session.limits.value, tick)
    updated = retain(memory, tuple(episodes))
    updates, relations = [], {}
    for key in index.affected():
        choice, rule = index.trials[key]
        tick()
        environment = {
            name: codecs[term.name][2](term.wire)
            for name, term in (
                *choice.payload.input_terms,
                *choice.payload.correlation,
                *choice.payload.capture,
            )
        }
        selected = {}
        for port in rule.ports:
            if port.collection_type is not None:
                continue
            item = index.selected(choice, port, tick)
            if item is None:
                break
            selected[port.name] = (item,)
            environment[port.name] = item.payload.value
        if len(selected) != sum(port.collection_type is None for port in rule.ports):
            index.pending = index.pending.add(key)
            continue
        index.pending = index.pending.discard(key)
        saved = dict(environment)
        for port in rule.ports:
            if port.collection_type is None:
                continue
            anchor = selected[port.until][0]
            matching = []
            channel = port.kind, port.channel, port.source, port.type_name
            bucket = index.deliveries.get(channel, ())
            positions = index.sequences.get(channel, ())
            tick()
            start = bisect_right(positions, choice.identity.sequence)
            stop = bisect_left(positions, anchor.identity.sequence)
            interval = tuple(bucket[i].payload.value for i in range(start, stop))
            eligible = (
                bucket[start:stop]
                if port.relation is None
                else _related(
                    port,
                    bucket,
                    positions,
                    choice.identity.sequence,
                    anchor.identity.sequence,
                    saved,
                    reads,
                    session.limits.value,
                    relations,
                    tick,
                )
            )
            for delivery in eligible:
                tick()
                local = {**saved, port.name: interval, port.item: delivery.payload.value}
                if port.accept(local, reads, session.limits.value):
                    matching.append(delivery)
            selected[port.name] = tuple(matching)
            environment[port.name] = tuple(i.payload.value for i in matching)
        evidence = tuple(i for port in rule.ports if not port.boundary for i in selected[port.name])
        boundaries = tuple(i for port in rule.ports if port.boundary for i in selected[port.name])
        if len({i.identity for i in (*evidence, *boundaries)}) != len(evidence) + len(boundaries):
            raise AdmissionError("AliasedFeedback", "distinct receipt ports reused one input")
        outcomes = rule.evaluate(environment, reads, session.limits.value)
        if outcomes is None:
            continue
        sample = feedback(
            model,
            updated._sources[_source(context, choice)],
            tuple(updated._sources[_source(context, item)] for item in evidence),
            choice.payload.semantics,
            outcomes,
            policy=rule.name,
            personal=rule.personal,
            boundaries=tuple(updated._sources[_source(context, item)] for item in boundaries),
        )
        updates.append(sample)
        index.results = index.results.set(key, sample.reference)
    updated = revise_samples(updated, tuple(updates))
    return FeedbackUpdate(
        updated,
        index.cursor,
        tuple(key for key in index.trial_order if key in index.pending),
        tuple(index.results[key] for key in index.trial_order if key in index.results),
        work,
        index.seal(session, updated),
    )
