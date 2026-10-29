"""Process-local, copy-on-write indices for recipient feedback checkpoints."""

from bisect import bisect_right
from dataclasses import dataclass
from weakref import WeakKeyDictionary, ref

from pyrsistent import pmap, pset, pvector

from .errors import AdmissionError
from .local_inputs import InputCursor


@dataclass(frozen=True, eq=False)
class FeedbackCheckpoint:
    """Opaque progress, valid only with its original input and memory prefixes."""


@dataclass(frozen=True)
class _Saved:
    session: object
    program: object
    library: object
    strategy: object
    value_limits: object
    subject: str
    episodes: object
    sample_prefix: object
    index: object
    tail: object


_issued = WeakKeyDictionary()


class FeedbackIndex:
    """One private transaction draft; saved maps and rows are never mutated."""

    def __init__(self, session, recipient, strategy, memory, checkpoint):
        self.recipient = recipient
        self.strategy = strategy
        self.ports = {
            id(port): port
            for rule in strategy.feedback
            for port in rule.ports
            if port.collection_type is None
        }
        saved = _issued.get(checkpoint) if type(checkpoint) is FeedbackCheckpoint else None
        if checkpoint is not None:
            stream = session._local_inputs.get(recipient, ())
            if (
                saved is None
                or saved.session() is not session
                or saved.program is not session.program
                or saved.library is not session.controllers
                or saved.strategy is not strategy
                or saved.value_limits != session.limits.value
                or saved.subject != memory.subject
                or saved.episodes is not memory.episodes
                or saved.sample_prefix is not memory._history_prefixes[1]
                or saved.index.recipient != recipient
                or saved.index.cursor.sequence > len(stream)
                or saved.index.cursor.sequence
                and stream[saved.index.cursor.sequence - 1] is not saved.tail
            ):
                raise AdmissionError(
                    "WrongFeedbackCheckpoint",
                    "checkpoint requires its original visit and raw memory",
                )
        prior = None if saved is None else saved.index
        self.cursor = InputCursor(recipient, 0) if prior is None else prior.cursor
        self.known = pset((recipient,)) if prior is None else prior.known
        for name in (
            "deliveries",
            "sequences",
            "matches",
            "starts",
            "watchers",
            "trials",
            "results",
        ):
            setattr(self, name, pmap() if prior is None else getattr(prior, name))
        self.trial_order = pvector() if prior is None else prior.trial_order
        self.pending = pset() if prior is None else prior.pending
        self.dirty = set()

    def register(self, choice, rule):
        key = choice.identity, rule.name
        self.trials = self.trials.set(key, (choice, rule))
        self.trial_order = self.trial_order.append(key)
        self.dirty.add(key)
        correlation = tuple(sorted(choice.payload.correlation))
        for port in rule.ports:
            if port.collection_type is not None:
                continue
            identity = id(port)
            if identity not in self.starts:
                self.starts = self.starts.set(identity, choice.identity.sequence)
            watch = self.watchers.get(identity, pmap())
            match = () if port.kind == "terminal" else correlation
            self.watchers = self.watchers.set(
                identity, watch.set(match, watch.get(match, pvector()).append(key))
            )

    def extend(self, deliveries, reads, limits, tick):
        for channel, additions in deliveries.items():
            self.deliveries = self.deliveries.set(
                channel, self.deliveries.get(channel, pvector()).extend(additions)
            )
            self.sequences = self.sequences.set(
                channel,
                self.sequences.get(channel, pvector()).extend(
                    item.identity.sequence for item in additions
                ),
            )
        for identity, port in self.ports.items():
            channel = port.kind, port.channel, port.source, port.type_name
            additions = deliveries.get(channel, ())
            if not additions or identity not in self.starts:
                continue
            matches = self.matches.get(identity, pmap())
            changed = {}
            for item in additions:
                if item.identity.sequence <= self.starts[identity]:
                    continue
                tick()
                key = tuple(sorted(port.match({port.name: item.payload.value}, reads, limits)))
                changed.setdefault(key, []).append(item)
                for trial in self.watchers.get(identity, {}).get(key, ()):
                    tick()
                    if trial[0].sequence < item.identity.sequence:
                        self.dirty.add(trial)
            for key, items in changed.items():
                positions, previous = matches.get(key, (pvector(), pvector()))
                matches = matches.set(
                    key,
                    (
                        positions.extend(item.identity.sequence for item in items),
                        previous.extend(items),
                    ),
                )
            self.matches = self.matches.set(identity, matches)

    def selected(self, choice, port, tick):
        tick()
        key = () if port.kind == "terminal" else tuple(sorted(choice.payload.correlation))
        positions, values = self.matches.get(id(port), {}).get(key, ((), ()))
        start = bisect_right(positions, choice.identity.sequence)
        count = len(values) - start
        if count > 1:
            raise AdmissionError("AmbiguousFeedback", "receipt port matched multiple inputs")
        return None if count == 0 else values[start]

    def affected(self):
        order = {rule.name: index for index, rule in enumerate(self.strategy.feedback)}
        return sorted(self.dirty, key=lambda key: (key[0].sequence, order[key[1]]))

    def seal(self, session, memory):
        token = FeedbackCheckpoint()
        stream = session._local_inputs.get(self.recipient, ())
        tail = None if not self.cursor.sequence else stream[self.cursor.sequence - 1]
        _issued[token] = _Saved(
            ref(session),
            session.program,
            session.controllers,
            self.strategy,
            session.limits.value,
            memory.subject,
            memory.episodes,
            memory._history_prefixes[1],
            self,
            tail,
        )
        return token
