"""Pure, subject-owned memory snapshots; acquisition authority belongs to the caller."""

from dataclasses import dataclass, field, fields, replace
from itertools import chain
from math import inf
from typing import Literal

from pyrsistent import PVector, pmap, pvector

from .episode_index import extend_indexes, select_episodes
from .recall_index import RecordIndex
from .recall_proof import seal
from .recall_selection import select_records
from .state import Term


def _names(*values):
    if any(type(value) is not str or not value for value in values):
        raise ValueError("memory names must be nonempty strings")


def _cues(values):
    if type(values) is not frozenset or not values:
        raise ValueError("memory cues require a nonempty frozenset")
    _names(*values)


@dataclass(frozen=True)
class Context:
    domain: str
    episode: str

    def __post_init__(self):
        _names(self.domain, self.episode)


@dataclass(frozen=True)
class Source:
    context: Context
    producer: str
    channel: str
    recipient: str
    message: str
    occurrence: int | None

    def __post_init__(self):
        if type(self.context) is not Context:
            raise ValueError("memory source requires a Context")
        _names(self.producer, self.channel, self.recipient, self.message)
        if self.occurrence is not None and (
            type(self.occurrence) is not int or self.occurrence < 1
        ):
            raise ValueError("memory occurrence must be positive or absent")

    @property
    def publication(self):
        """Keep message identity while grouping parts of one acquired publication."""
        if self.occurrence is None:
            return self
        return self.context, self.producer, self.channel, self.recipient, self.occurrence


@dataclass(frozen=True)
class Episode:
    subject: str
    source: Source
    content: Term
    cues: frozenset[str]

    def __post_init__(self):
        _names(self.subject)
        if type(self.source) is not Source or type(self.content) is not Term:
            raise ValueError("episode requires a source and nominal content")
        _cues(self.cues)


@dataclass(frozen=True)
class Sample:
    """A revisable interpretation of a real trial and separately acquired evidence."""

    key: str
    revision: int
    trial: Source
    meaning: Term
    content: Term
    cues: frozenset[str]
    evidence: tuple[Source, ...]
    boundaries: tuple[Source, ...] = ()

    def __post_init__(self):
        _names(self.key)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("sample revision must be positive")
        if (
            type(self.trial) is not Source
            or type(self.content) is not Term
            or type(self.meaning) is not Term
        ):
            raise ValueError("sample requires a trial and nominal content")
        _cues(self.cues)
        if (
            type(self.evidence) is not tuple
            or type(self.boundaries) is not tuple
            or not (self.evidence or self.boundaries)
            or any(type(s) is not Source or s.context != self.trial.context for s in self.evidence)
            or len(set(self.evidence)) != len(self.evidence)
            or self.trial in self.evidence
            or any(
                type(s) is not Source or s.context != self.trial.context for s in self.boundaries
            )
            or len(set(self.boundaries)) != len(self.boundaries)
            or self.trial in self.boundaries
            or set(self.boundaries) & set(self.evidence)
        ):
            raise ValueError("sample requires distinct evidence in its trial context")

    @property
    def grounds(self):
        return (self.trial, *self.evidence, *self.boundaries)

    @property
    def weight_sources(self):
        """Observed data keeps its own weight; absence depends on a shared closure."""
        return self.evidence or self.boundaries

    @property
    def reference(self):
        return self.key, self.revision


@dataclass(frozen=True)
class Experience:
    key: str
    revision: int
    domain: str
    context: Context | None
    meaning: Term
    cues: frozenset[str]
    support: tuple[Source, ...]
    opposition: tuple[Source, ...]
    samples: tuple[tuple[str, int], ...] = ()
    grounds: tuple[Source, ...] = field(init=False, repr=False)

    def __post_init__(self):
        _names(self.key, self.domain)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("experience revision must be positive")
        if self.context is not None and (
            type(self.context) is not Context or self.context.domain != self.domain
        ):
            raise ValueError("experience context must belong to its domain")
        if type(self.meaning) is not Term:
            raise ValueError("experience meaning requires nominal content")
        _cues(self.cues)
        if (
            type(self.samples) is not tuple
            or any(
                type(ref) is not tuple
                or len(ref) != 2
                or type(ref[0]) is not str
                or not ref[0]
                or type(ref[1]) is not int
                or ref[1] < 1
                for ref in self.samples
            )
            or len(set(self.samples)) != len(self.samples)
        ):
            raise ValueError("experience needs distinct sample version references")
        for sources in (self.support, self.opposition):
            if type(sources) is not tuple or any(type(s) is not Source for s in sources):
                raise ValueError("experience grounds require source tuples")
            if len(set(sources)) != len(sources):
                raise ValueError("duplicate experience grounds")
        grounds = tuple(dict.fromkeys((*self.support, *self.opposition)))
        if not grounds or any(s.context.domain != self.domain for s in grounds):
            raise ValueError("experience needs grounds in its domain")
        if self.context is not None and any(s.context != self.context for s in grounds):
            raise ValueError("personal experience grounds must retain their context")
        object.__setattr__(self, "grounds", grounds)


def _same_record(first, second):
    """Replay identity retains primitive wire types, unlike Python's True == 1."""
    if first is second:
        return True
    if type(first) is not type(second):
        return False
    if type(first) is tuple:
        return len(first) == len(second) and all(
            _same_record(a, b) for a, b in zip(first, second, strict=True)
        )
    if type(first) in (Term, Episode, Sample, Experience):
        return all(
            _same_record(getattr(first, f.name), getattr(second, f.name)) for f in fields(first)
        )
    return first == second


@dataclass(frozen=True)
class _HistoryPrefix:
    parent: object
    count: int


def _extends_history(before, after):
    for previous, current in zip(before._history_prefixes, after._history_prefixes, strict=True):
        while current.count > previous.count:
            current = current.parent
        if current is not previous:
            return False
    return True


@dataclass(frozen=True)
class Memory:
    subject: str
    episodes: PVector = field(default_factory=pvector)
    experiences: PVector = field(default_factory=pvector)
    samples: PVector = field(default_factory=pvector)
    _sources: object = field(init=False, repr=False, compare=False)
    _versions: object = field(init=False, repr=False, compare=False)
    _latest: object = field(init=False, repr=False, compare=False)
    _sample_versions: object = field(init=False, repr=False, compare=False)
    _samples: object = field(init=False, repr=False, compare=False)
    _sample_keys: object = field(init=False, repr=False, compare=False)
    _sample_history_keys: object = field(init=False, repr=False, compare=False)
    _experience_history_keys: object = field(init=False, repr=False, compare=False)
    _experience_positions: object = field(init=False, repr=False, compare=False)
    _consolidations: object = field(init=False, repr=False, compare=False)
    _episode_contexts: object = field(init=False, repr=False, compare=False)
    _episode_cues: object = field(init=False, repr=False, compare=False)
    _record_index: RecordIndex = field(init=False, repr=False, compare=False)
    _history_prefixes: tuple = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _names(self.subject)
        if any(
            type(values) is not tuple and not isinstance(values, PVector)
            for values in (self.episodes, self.experiences, self.samples)
        ):
            raise ValueError("memory history requires immutable sequences")
        checked = _append(
            _empty(self.subject),
            episodes=self.episodes,
            samples=self.samples,
            experiences=self.experiences,
        )
        for item in fields(self):
            object.__setattr__(self, item.name, getattr(checked, item.name))

    @property
    def version(self):
        """A local progress counter, not a globally unique snapshot identifier."""
        return len(self.episodes) + len(self.experiences) + len(self.samples)

    @property
    def active(self):
        return tuple(
            self._latest[key]
            for key in sorted(self._latest, key=self._experience_positions.__getitem__)
        )

    @property
    def current_samples(self):
        return tuple(self._samples[key] for key in self._sample_keys)


def _empty(subject):
    value = object.__new__(Memory)
    object.__setattr__(value, "subject", subject)
    for name in (
        "episodes",
        "experiences",
        "samples",
        "_sample_keys",
        "_sample_history_keys",
        "_experience_history_keys",
    ):
        object.__setattr__(value, name, pvector())
    for name in (
        "_sources",
        "_versions",
        "_latest",
        "_sample_versions",
        "_samples",
        "_experience_positions",
        "_consolidations",
        "_episode_contexts",
        "_episode_cues",
    ):
        object.__setattr__(value, name, pmap())
    object.__setattr__(value, "_record_index", RecordIndex())
    object.__setattr__(value, "_history_prefixes", tuple(_HistoryPrefix(None, 0) for _ in range(3)))
    return value


def _append(memory, *, episodes=(), samples=(), experiences=()):
    """Validate only new immutable records against the old immutable indices."""
    if not (episodes or samples or experiences):
        return memory
    sources, sample_versions, latest_samples, versions, latest, positions = {}, {}, {}, {}, {}, {}
    record_index = memory._record_index
    keys = []
    for episode in episodes:
        if type(episode) is not Episode or episode.subject != memory.subject:
            raise ValueError("episode belongs to a different subject")
        if episode.source in sources or episode.source in memory._sources:
            raise ValueError("duplicate episode source")
        sources[episode.source] = episode
    for sample in samples:
        if type(sample) is not Sample:
            raise ValueError("memory samples require Samples")
        previous = latest_samples.get(sample.key, memory._samples.get(sample.key))
        _next_sample(previous, sample)
        if previous is not None and _same_record(
            replace(sample, revision=previous.revision), previous
        ):
            raise ValueError("sample history contains an unchanged revision")
        if any(s not in sources and s not in memory._sources for s in sample.grounds):
            raise ValueError("sample cites an unretained episode")
        record_index = record_index.with_sample(
            previous, sample, len(memory._sample_keys) + len(keys) if previous is None else None
        )
        if previous is None:
            keys.append(sample.key)
        sample_versions[sample.reference] = sample
        latest_samples[sample.key] = sample
    for offset, experience in enumerate(experiences):
        if type(experience) is not Experience:
            raise ValueError("memory experiences require Experiences")
        previous = latest.get(experience.key, memory._latest.get(experience.key))
        _next_experience(previous, experience)
        if previous is not None and _same_record(
            replace(experience, revision=previous.revision), previous
        ):
            raise ValueError("experience history contains an unchanged revision")
        if any(s not in sources and s not in memory._sources for s in experience.grounds):
            raise ValueError("experience cites an unretained episode")
        retained = set(experience.grounds)
        for reference in experience.samples:
            sample = sample_versions.get(reference, memory._sample_versions.get(reference))
            if sample is None or not set(sample.grounds) <= retained:
                raise ValueError("experience cites an absent sample or its grounds")
        versions[experience.key, experience.revision] = experience
        record_index = record_index.with_experience(previous, experience)
        latest[experience.key] = experience
        positions[experience.key] = len(memory.experiences) + offset
    value = object.__new__(Memory)
    episode_contexts, episode_cues = (
        extend_indexes(
            memory._episode_contexts, memory._episode_cues, episodes, len(memory.episodes)
        )
        if episodes
        else (memory._episode_contexts, memory._episode_cues)
    )
    state = {
        "subject": memory.subject,
        "episodes": memory.episodes.extend(episodes) if episodes else memory.episodes,
        "samples": memory.samples.extend(samples) if samples else memory.samples,
        "experiences": memory.experiences.extend(experiences)
        if experiences
        else memory.experiences,
        "_sample_keys": memory._sample_keys.extend(keys),
        "_sample_history_keys": memory._sample_history_keys.extend(s.key for s in samples),
        "_experience_history_keys": memory._experience_history_keys.extend(
            e.key for e in experiences
        ),
        "_sources": memory._sources.update(sources),
        "_sample_versions": memory._sample_versions.update(sample_versions),
        "_samples": memory._samples.update(latest_samples),
        "_versions": memory._versions.update(versions),
        "_latest": memory._latest.update(latest),
        "_experience_positions": memory._experience_positions.update(positions),
        "_consolidations": memory._consolidations,
        "_episode_contexts": episode_contexts,
        "_episode_cues": episode_cues,
        "_record_index": record_index,
        "_history_prefixes": tuple(
            _HistoryPrefix(previous, previous.count + len(additions)) if additions else previous
            for previous, additions in zip(
                memory._history_prefixes, (episodes, samples, experiences), strict=True
            )
        ),
    }
    for name, content in state.items():
        object.__setattr__(value, name, content)
    return value


def _with_consolidation(memory, signature, index):
    """Attach derived immutable progress only to this validated Memory lineage."""
    value = object.__new__(Memory)
    for item in fields(memory):
        content = getattr(memory, item.name)
        if item.name == "_consolidations":
            content = content.set(signature, index)
        object.__setattr__(value, item.name, content)
    return value


def _next_experience(previous, experience):
    expected = 1 if previous is None else previous.revision + 1
    if experience.revision != expected:
        raise ValueError("experience revisions must be consecutive")
    if previous is not None and (experience.domain, experience.context) != (
        previous.domain,
        previous.context,
    ):
        raise ValueError("experience applicability cannot change under the same key")


def _next_sample(previous, sample):
    if sample.revision != (1 if previous is None else previous.revision + 1):
        raise ValueError("sample revisions must be consecutive")
    if previous is not None:
        if not _same_record(
            (sample.trial, sample.meaning, sample.cues),
            (previous.trial, previous.meaning, previous.cues),
        ):
            raise ValueError("sample trial, meaning and cues cannot change under the same key")
        if not set(previous.evidence) <= set(sample.evidence):
            raise ValueError("sample revisions must retain prior evidence")
        if not set(previous.boundaries) <= set(sample.boundaries):
            raise ValueError("sample revisions must retain prior boundaries")


def revise_sample(memory, sample):
    """Publish one interpretation; replay never changes its weight or rolls it back."""
    if type(memory) is not Memory or type(sample) is not Sample:
        raise ValueError("sample revision requires a Memory and Sample")
    return revise_samples(memory, (sample,))


def revise_samples(memory, samples):
    """Check ordered revisions, then publish one immutable snapshot for the batch."""
    if type(memory) is not Memory or type(samples) is not tuple:
        raise ValueError("sample batch requires a Memory and sample tuple")
    versions, latest, additions = {}, {}, []
    for sample in samples:
        if type(sample) is not Sample:
            raise ValueError("sample batch requires Samples")
        existing = versions.get(sample.reference, memory._sample_versions.get(sample.reference))
        if existing is not None:
            if not _same_record(existing, sample):
                raise ValueError("sample revision was reused with different content")
            continue
        previous = latest.get(sample.key, memory._samples.get(sample.key))
        _next_sample(previous, sample)
        if previous is not None and _same_record(
            replace(sample, revision=previous.revision), previous
        ):
            continue
        versions[sample.reference] = sample
        latest[sample.key] = sample
        additions.append(sample)
    if not additions:
        return memory
    return _append(memory, samples=tuple(additions))


def retain(memory, episodes):
    """Add a whole batch or leave the original snapshot unchanged on error."""
    if type(memory) is not Memory or type(episodes) is not tuple:
        raise ValueError("retention requires a Memory and episode tuple")
    additions = {}
    for episode in episodes:
        if type(episode) is not Episode or episode.subject != memory.subject:
            raise ValueError("retention requires this subject's episodes")
        previous = additions.get(episode.source, memory._sources.get(episode.source))
        if previous is not None and not _same_record(previous, episode):
            raise ValueError("episode source was reused with different content or cues")
        if previous is None:
            additions[episode.source] = episode
    if not additions:
        return memory
    return _append(memory, episodes=tuple(additions.values()))


def revise_experience(memory, experience):
    """Install a sourced interpretation; replaying an old revision never rolls it back."""
    if type(memory) is not Memory or type(experience) is not Experience:
        raise ValueError("revision requires a Memory and Experience")
    existing = memory._versions.get((experience.key, experience.revision))
    if existing is not None:
        if not _same_record(existing, experience):
            raise ValueError("experience revision was reused with different content")
        return memory
    previous = memory._latest.get(experience.key)
    _next_experience(previous, experience)
    if previous is not None and _same_record(
        replace(experience, revision=previous.revision), previous
    ):
        return memory
    return _append(memory, experiences=(experience,))


def revise_experiences(memory, experiences):
    """Publish ordered interpretation updates in one checked persistent snapshot."""
    if type(memory) is not Memory or type(experiences) is not tuple:
        raise ValueError("revision requires a Memory and experience tuple")
    value = memory
    for experience in experiences:
        value = revise_experience(value, experience)
    return value


@dataclass(frozen=True)
class RecallQuery:
    subject: str
    context: Context
    past: frozenset[Context]
    cues: frozenset[str]

    def __post_init__(self):
        _names(self.subject)
        if type(self.context) is not Context or type(self.past) is not frozenset:
            raise ValueError("recall requires a context and explicit past contexts")
        if any(type(c) is not Context or c.domain != self.context.domain for c in self.past):
            raise ValueError("recall past must belong to the current domain")
        if type(self.cues) is not frozenset:
            raise ValueError("query cues require a frozenset")
        if self.cues:
            _cues(self.cues)


@dataclass(frozen=True)
class RecallLimits:
    work: int | None = None
    items: int | None = None
    grounds: int | None = None

    def __post_init__(self):
        if any(
            v is not None and (type(v) is not int or v < 1)
            for v in (self.work, self.items, self.grounds)
        ):
            raise ValueError("recall limits must be positive integers or None")


@dataclass(frozen=True)
class Recall:
    query: RecallQuery
    version: int
    episodes: tuple[Episode, ...]
    experiences: tuple[Experience, ...]
    grounds: tuple[Episode, ...]
    status: Literal["complete", "limited"]
    reason: str | None
    work: int
    samples: tuple[Sample, ...] = ()

    @property
    def subject(self):
        return self.query.subject

    @property
    def context(self):
        return self.query.context


def recall(memory, query, *, limits=RecallLimits()):
    """Recall cue matches and their evidence dependencies, then recent episodes."""
    if type(memory) is not Memory or type(query) is not RecallQuery:
        raise ValueError("recall requires a Memory and RecallQuery")
    recalled = _recall_from(memory, query, limits=limits)
    return seal(recalled, memory) if recalled.status == "complete" else recalled


def _recall_from(memory, query, *, limits=RecallLimits()):
    """Shared selection policy; a detached reader receives no Memory provenance seal."""
    if type(query) is not RecallQuery:
        raise ValueError("recall requires a RecallQuery")
    if query.subject != memory.subject or type(limits) is not RecallLimits:
        raise ValueError("recall requires this subject and checked limits")
    allowed = query.past | {query.context}
    work_limit = inf if limits.work is None else limits.work
    item_limit = inf if limits.items is None else limits.items
    ground_limit = inf if limits.grounds is None else limits.grounds
    episodes, experiences, samples, grounds, work = [], [], [], {}, 0

    def result(reason=None):
        recalled = Recall(
            query,
            memory.version,
            tuple(episodes),
            tuple(experiences),
            tuple(grounds.values()),
            "complete" if reason is None else "limited",
            reason,
            work,
            tuple(samples),
        )
        return recalled

    records = select_records(
        memory._record_index,
        memory._samples,
        memory._latest,
        memory._experience_positions,
        query,
        allowed,
        work_limit=work_limit - work,
    )
    work += records.work
    if not records.complete:
        return result("work")

    def consume(items):
        nonlocal work
        for item in items:
            if work >= work_limit:
                return "work"
            work += 1
            if type(item) is Experience and (
                item.domain != query.context.domain or item.context not in (None, query.context)
            ):
                continue
            ground_count = (
                1 + len(item.evidence) + len(item.boundaries)
                if type(item) is Sample
                else len(item.grounds)
            )
            if ground_count > work_limit - work:
                return "work"
            work += ground_count
            retained = item.grounds
            if any(source.context not in allowed for source in retained):
                continue
            if len(episodes) + len(experiences) + len(samples) >= item_limit:
                return "items"
            additions = tuple(s for s in retained if s not in grounds)
            if len(grounds) + len(additions) > ground_limit:
                return "grounds"
            grounds.update((s, memory._sources[s]) for s in additions)
            (experiences if type(item) is Experience else samples).append(item)
        return None

    reason = consume(chain(records.experiences, records.samples))
    if reason is not None:
        return result(reason)
    selected = select_episodes(
        memory._episode_contexts,
        memory._episode_cues,
        allowed,
        query.cues,
        work_limit=work_limit - work,
    )
    work += selected.work
    if not selected.complete:
        return result("work")
    while selected.episodes:
        if work >= work_limit:
            return result("work")
        work += 1
        item = selected.episodes.take()
        if (
            not item.cues & query.cues
            or item.source.context not in allowed
            or item.source in grounds
        ):
            continue
        if len(episodes) + len(experiences) + len(samples) >= item_limit:
            return result("items")
        if len(grounds) >= ground_limit:
            return result("grounds")
        grounds[item.source] = item
        episodes.append(item)
    return result()
