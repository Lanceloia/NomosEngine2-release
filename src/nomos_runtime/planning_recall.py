"""Recipient-scoped report memory for one planning problem, without Subject lifecycle changes."""

from dataclasses import dataclass, replace

from nomos_cognition.memory import (
    Context,
    Episode,
    Memory,
    RecallLimits,
    RecallQuery,
    Source,
    recall,
    retain,
)
from nomos_cognition.planning.search import _Stop
from nomos_cognition.state import Term

from .errors import AdmissionError
from .expressions import ValueBudget


@dataclass(frozen=True)
class RecallPort:
    alias: str
    type_name: str
    channel: str
    source: str


@dataclass(frozen=True)
class CompiledGuidance:
    ports: tuple
    exploration: int
    actions: tuple
    members: tuple
    codecs: object


@dataclass(frozen=True)
class RecallSnapshot:
    memory: Memory
    recalled: object
    values: tuple
    sources: tuple

    def reads(self, base):
        return replace(
            base, local_values={alias: (lambda value=value: value) for alias, value in self.values}
        )


def capture_reports(session, actor, guidance, work):
    """Read only actual local input streams; a projection is not an acquired memory."""
    controller = session._actor(actor)
    ports = {(p.channel, p.source): p for p in guidance.ports}
    cursor, records = None, []
    while True:
        batch = session.local_inputs(actor, after=cursor, limit=128)
        for item in batch.items:
            work.spend()
            if item.identity.kind not in {"opening", "delivery"}:
                continue
            payload = item.payload
            port = ports.get((payload.channel, payload.source))
            if port is None:
                continue
            if item.identity.recipient != controller or payload.recipient != controller:
                raise AdmissionError(
                    "PlanningRecallRecipient", "report is not addressed to this Actor"
                )
            actual = guidance.codecs.get(payload.type_name)
            if actual is None or actual[0] != guidance.codecs[port.type_name][0]:
                raise AdmissionError(
                    "PlanningRecallType", "report differs from its nominal recall port"
                )
            records.append((port.alias, item))
        if batch.complete:
            return tuple(records)
        cursor = batch.cursor


def _charge_wire(wire, work):
    work.spend()
    if type(wire) is tuple:
        for child in wire:
            _charge_wire(child, work)


def remember(definition, records, controller, reads, value_limits, work):
    guidance = definition.guidance
    context = Context("planning:" + definition.signature, controller.scope)
    subject = f"actor:{controller.scope}/{controller.ordinal}"
    ports = {p.alias: p for p in guidance.ports}
    episodes, values = [], {}
    for alias, item in records:
        work.spend()
        port, payload = ports[alias], item.payload
        signature, encode, _, validator = guidance.codecs[port.type_name]
        value = validator(payload.value, ValueBudget(value_limits, reads.references), ())
        wire = encode(value)
        _charge_wire(wire, work)
        source = Source(
            context,
            payload.source,
            payload.channel,
            f"{controller.sort}:{controller.ordinal}",
            f"{item.identity.kind}:{item.identity.sequence}",
            payload.occurrence,
        )
        episodes.append(
            Episode(subject, source, Term(port.type_name, signature, wire), frozenset({alias}))
        )
        values[source] = alias, value
    memory = retain(Memory(subject), tuple(episodes))
    remaining = work.until - work.used
    if remaining < 1:
        raise _Stop
    recalled = recall(
        memory,
        RecallQuery(subject, context, frozenset(), frozenset(ports)),
        limits=RecallLimits(work=remaining),
    )
    work.spend(max(1, recalled.work))
    if recalled.status != "complete":
        raise _Stop
    selected = {episode.source for episode in recalled.episodes}
    # Keep report histories in their actual delivery order, not reverse recall rank.
    sources = tuple(episode.source for episode in episodes if episode.source in selected)
    recalled_values = tuple(
        (p.alias, tuple(values[source][1] for source in sources if values[source][0] == p.alias))
        for p in guidance.ports
    )
    work.spend(max(1, len(episodes) + len(sources)))
    return RecallSnapshot(memory, recalled, recalled_values, sources)


def remember_subject(definition, memory, context, controller, reads, value_limits, work):
    """Decode selected actual report episodes from an already synchronized Subject."""
    remaining = work.until - work.used
    if remaining < 1:
        raise _Stop
    recalled = recall(
        memory,
        RecallQuery(memory.subject, context, frozenset(), frozenset({"input"})),
        limits=RecallLimits(work=remaining),
    )
    work.spend(max(1, recalled.work))
    if recalled.status != "complete":
        raise _Stop
    guidance = definition.guidance
    ports = {(p.channel, p.source): p for p in guidance.ports}
    values, sources = {p.alias: [] for p in guidance.ports}, []
    # Recall orders episodes newest first; decode only those selected episodes,
    # restoring their original acquisition order without rescanning raw memory.
    for episode in reversed(recalled.episodes):
        work.spend()
        source, content = episode.source, episode.content
        port = ports.get((source.channel, source.producer))
        if source.context != context or port is None:
            continue
        if source.recipient != f"{controller.sort}:{controller.ordinal}":
            raise AdmissionError(
                "PlanningRecallRecipient", "memory report belongs to another Actor"
            )
        if (content.name, content.signature) != ("RuntimeInput", "actor-local-input-v3"):
            raise AdmissionError("PlanningRecallType", "memory report is not a runtime input")
        kind, wire = content.wire
        if kind not in {"opening", "delivery"}:
            continue
        _, term = wire
        name, signature, encoded = term
        codec = guidance.codecs[port.type_name]
        if (
            name not in guidance.codecs
            or guidance.codecs[name][0] != codec[0]
            or signature != codec[0]
        ):
            raise AdmissionError(
                "PlanningRecallType", "memory report differs from its nominal port"
            )
        _charge_wire(encoded, work)
        value = codec[3](codec[2](encoded), ValueBudget(value_limits, reads.references), ())
        values[port.alias].append(value)
        sources.append(source)
    return RecallSnapshot(
        memory,
        recalled,
        tuple((p.alias, tuple(values[p.alias])) for p in guidance.ports),
        tuple(sources),
    )
