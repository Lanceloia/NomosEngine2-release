"""Pure empirical appraisal over declared action meanings and personal feedback."""

from dataclasses import dataclass, field, replace
from fractions import Fraction
from hashlib import sha256
from json import dumps

from .consolidation_index import ConsolidationIndex
from .memory import (
    Context,
    Episode,
    Experience,
    Memory,
    Recall,
    RecallQuery,
    Sample,
    _with_consolidation,
    revise_experiences,
)
from .recall_proof import memory_for
from .state import Term


def _name(value):
    if type(value) is not str or not value:
        raise ValueError("appraisal names must be nonempty strings")


def _vector(value, *, positive=False):
    if type(value) is not tuple:
        raise ValueError("appraisal vectors must be immutable tuples")
    names = set()
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("appraisal vectors need name/value pairs")
        name, number = pair
        _name(name)
        if name in names or type(number) is not int or positive and number < 1:
            raise ValueError("appraisal vector has duplicate or invalid values")
        names.add(name)


def _digest(value):
    return sha256(dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Model:
    name: str
    domain: str
    features: tuple[str, ...]
    outcomes: tuple[str, ...]
    prior_weight: int = 1
    applicability: tuple[tuple[str, tuple[str, ...]], ...] = ()
    appraisal: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = ()
    signature: str = field(init=False)

    def __post_init__(self):
        _name(self.name)
        _name(self.domain)
        for names in (self.features, self.outcomes):
            if type(names) is not tuple or not names:
                raise ValueError("model needs declared features and outcomes")
            for name in names:
                _name(name)
            if len(set(names)) != len(names):
                raise ValueError("model has duplicate dimensions")
        if type(self.prior_weight) is not int or self.prior_weight < 1:
            raise ValueError("model prior weight must be positive")
        if type(self.applicability) is not tuple:
            raise ValueError("applicability requires immutable axis/feature rules")
        axes = set()
        for rule in self.applicability:
            if type(rule) is not tuple or len(rule) != 2:
                raise ValueError("applicability requires axis/feature pairs")
            axis, selectors = rule
            if (
                type(axis) is not str
                or axis not in self.outcomes
                or axis in axes
                or type(selectors) is not tuple
                or not selectors
                or any(type(s) is not str or s not in self.features for s in selectors)
                or len(set(selectors)) != len(selectors)
            ):
                raise ValueError("applicability requires distinct declared axes and features")
            axes.add(axis)
        object.__setattr__(
            self,
            "applicability",
            tuple(sorted((a, tuple(sorted(s))) for a, s in self.applicability)),
        )
        if type(self.appraisal) is not tuple:
            raise ValueError("appraisal traits require immutable declarations")
        traits = set()
        normalized = []
        for rule in self.appraisal:
            if type(rule) is not tuple or len(rule) != 3:
                raise ValueError("appraisal traits require name/seek/avoid triples")
            name, seek, avoid = rule
            if (
                type(name) is not str
                or not name
                or name in traits
                or name in self.outcomes
                or type(seek) is not tuple
                or type(avoid) is not tuple
                or not (seek or avoid)
                or any(
                    type(feature) is not str or feature not in self.features
                    for feature in (*seek, *avoid)
                )
                or len(set((*seek, *avoid))) != len((*seek, *avoid))
            ):
                raise ValueError("appraisal traits require distinct declared feature directions")
            traits.add(name)
            normalized.append((name, tuple(sorted(seek)), tuple(sorted(avoid))))
        object.__setattr__(self, "appraisal", tuple(sorted(normalized)))
        object.__setattr__(
            self,
            "signature",
            _digest(
                (
                    "appraisal-feedback-v1",
                    self.domain,
                    tuple(sorted(self.features)),
                    tuple(sorted(self.outcomes)),
                    self.appraisal,
                )
            ),
        )


@dataclass(frozen=True)
class Candidate:
    key: str
    features: tuple[tuple[str, int], ...]
    prior: tuple[tuple[str, int], ...]
    target: Term | None = None
    known: frozenset[str] = frozenset()
    valuation: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        _name(self.key)
        _vector(self.features, positive=True)
        _vector(self.prior)
        _vector(self.valuation)
        if any(value < 0 for _, value in self.valuation):
            raise ValueError("valuation factors require nonnegative integers")
        if not self.features or self.target is not None and type(self.target) is not Term:
            raise ValueError("candidate needs features and a nominal optional target")
        if type(self.known) is not frozenset:
            raise ValueError("known outcome axes require a frozenset")
        for name in self.known:
            _name(name)


def _bound(model, vector, *, features=False, complete=False):
    _vector(vector, positive=features)
    declared = model.features if features else model.outcomes
    names = {name for name, _ in vector}
    if not names <= set(declared) or complete and names != set(declared):
        raise ValueError("appraisal vector disagrees with declared dimensions")
    return tuple(sorted(vector))


def _target_wire(target):
    return None if target is None else (target.name, target.signature, target.wire)


def _tags(model, features):
    return frozenset(f"{model.signature}:{name}" for name, _ in features)


def _candidate(model, candidate):
    if type(model) is not Model or type(candidate) is not Candidate:
        raise ValueError("appraisal requires a Model and Candidates")
    _bound(model, candidate.features, features=True)
    _bound(model, candidate.prior, complete=True)
    if not candidate.known <= set(model.outcomes):
        raise ValueError("known outcomes disagree with declared dimensions")
    _bound(model, candidate.valuation)
    if any(value < 0 for _, value in candidate.valuation):
        raise ValueError("valuation factors require nonnegative integers")


def feedback(
    model,
    trial,
    evidence,
    candidate,
    outcomes,
    *,
    policy,
    revision=1,
    personal=False,
    boundaries=(),
):
    """Interpret acquired episodes without inventing a new raw receipt or occurrence."""
    _candidate(model, candidate)
    _name(policy)
    if type(trial) is not Episode or trial.source.context.domain != model.domain:
        raise ValueError("feedback trial has a foreign domain")
    if (
        type(evidence) is not tuple
        or type(boundaries) is not tuple
        or not (evidence or boundaries)
        or any(
            type(e) is not Episode or e.subject != trial.subject for e in (*evidence, *boundaries)
        )
    ):
        raise ValueError("feedback needs this subject's acquired evidence")
    if type(personal) is not bool or personal and candidate.target is None:
        raise ValueError("personal feedback requires an explicit target")
    outcomes = _bound(model, outcomes)
    if not outcomes:
        raise ValueError("feedback needs at least one observed outcome")
    meaning = (
        _bound(model, candidate.features, features=True),
        _target_wire(candidate.target) if personal else None,
    )
    source = trial.source
    key = _digest(
        (
            model.signature,
            policy,
            source.context.episode,
            source.producer,
            source.channel,
            source.recipient,
            source.message,
            source.occurrence,
        )
    )
    return Sample(
        "feedback:" + key,
        revision,
        source,
        Term("ActionMeaning", model.signature, meaning),
        Term("ActionFeedback", model.signature, outcomes),
        _tags(model, candidate.features),
        tuple(e.source for e in evidence),
        tuple(e.source for e in boundaries),
    )


@dataclass(frozen=True)
class Limits:
    work: int | None = None
    candidates: int | None = None
    cases: int | None = None

    def __post_init__(self):
        if any(
            n is not None and (type(n) is not int or n < 1)
            for n in (self.work, self.candidates, self.cases)
        ):
            raise ValueError("appraisal limits must be positive integers or None")


class AppraisalBudget(ValueError):
    pass


class _PendingExperience(ValueError):
    pass


class _Meter:
    def __init__(self, limits):
        if type(limits) is not Limits:
            raise ValueError("appraisal requires checked limits")
        self.limits, self.work = limits, 0

    def spend(self, count=1):
        if self.limits.work is not None and count > self.limits.work - self.work:
            raise AppraisalBudget("appraisal work budget exhausted")
        self.work += count

    def units(self, count):
        """Charge repeated proven one-unit checks, including the exact failure prefix."""
        if self.limits.work is not None and count > self.limits.work - self.work:
            self.work = self.limits.work
            raise AppraisalBudget("appraisal work budget exhausted")
        self.work += count


def _decode(model, sample, meter):
    meter.spend()
    if sample.content.name != "ActionFeedback" or sample.content.signature != model.signature:
        return None
    if sample.trial.context.domain != model.domain:
        raise ValueError("feedback has a foreign domain")
    wire = sample.meaning.wire
    if (
        sample.meaning.name != "ActionMeaning"
        or sample.meaning.signature != model.signature
        or type(wire) is not tuple
        or len(wire) != 2
    ):
        raise ValueError("malformed action feedback")
    features, target = wire
    outcomes = sample.content.wire
    if type(features) is not tuple or type(outcomes) is not tuple:
        raise ValueError("malformed action feedback vectors")
    meter.spend(len(features) + len(outcomes))
    features, outcomes = _bound(model, features, features=True), _bound(model, outcomes)
    if not features or not outcomes:
        raise ValueError("feedback must have features and outcomes")
    if target is not None:
        if type(target) is not tuple or len(target) != 3:
            raise ValueError("malformed feedback target")
        target = Term(*target)
    return features, outcomes, target


def _summary(cases):
    totals = {}
    for _, outcomes, _ in cases:
        for axis, value in outcomes:
            total, count = totals.get(axis, (0, 0))
            totals[axis] = total + value, count + 1
    return tuple((axis, total, count) for axis, (total, count) in sorted(totals.items()))


def consolidate(model, memory, *, limits=Limits()):
    """Update affected sourced summaries; preserve full logical budget accounting."""
    learned, index = _consolidation(model, memory, limits)
    return memory if learned is memory else _with_consolidation(learned, model.signature, index)


def prepare_consolidation(model, memory):
    """Prepare derived progress without appending or relearning an old experience."""
    learned, index = _consolidation(model, memory, Limits())
    if learned is not memory:
        raise ValueError("stored summaries disagree with the selected feedback model")
    return (
        memory
        if memory._consolidations.get(model.signature) == index
        else _with_consolidation(memory, model.signature, index)
    )


def _consolidation(model, memory, limits):
    if type(model) is not Model or type(memory) is not Memory:
        raise ValueError("consolidation requires a Model and Memory")
    meter = _Meter(limits)
    prior = memory._consolidations.get(model.signature)
    index = ConsolidationIndex() if prior is None else prior
    # Delta detection needs only keys, even when a model's unchanged cursor is cold.
    changed = dict.fromkeys(memory._sample_history_keys[index.sample_cursor :])
    dirty = set()
    # Explicit limits retain the original full logical scan and diagnostic order.
    if limits.work is not None or limits.cases is not None:
        names = memory._sample_keys
    else:
        positions = {key: len(index.slots) + offset for offset, key in enumerate(changed)}
        names = sorted(
            changed,
            key=lambda key: index.slots[key].position if key in index.slots else positions[key],
        )
    count = 0
    for name in names:
        sample = memory._samples[name]
        slot = index.slots.get(name)
        if slot is not None and slot.sample is sample:
            meter.spend(slot.work)
            case = slot.case
        else:
            before = meter.work
            case = _decode(model, sample, meter)
            key = (
                None
                if case is None
                else "appraisal:"
                + _digest(
                    (
                        model.signature,
                        case[0],
                        _target_wire(case[2]),
                        (sample.trial.context.domain, sample.trial.context.episode),
                    )
                )
            )
            if slot is not None and slot.group is not None:
                dirty.add(slot.group)
            if key is not None:
                dirty.add(key)
            index = index.changed(sample, case, meter.work - before, key)
        if case is not None:
            count += 1
            if limits.cases is not None and count > limits.cases:
                raise AppraisalBudget("appraisal case budget exhausted")
    if prior is not None:
        dirty.update(
            key
            for key in memory._experience_history_keys[prior.experience_cursor :]
            if key in index.groups
        )
    if limits.work is not None:
        for group in sorted(index.groups.values(), key=lambda group: group.first):
            meter.spend(group.work)
    updates = []
    for key in sorted(
        (key for key in dirty if key in index.groups), key=lambda key: index.groups[key].first
    ):
        group = index.groups[key]
        features, target, origin = group.features, group.target, group.origin
        samples = group.samples()
        context = origin if target is not None else None
        old = memory._latest.get(key)
        meaning = Term(
            "ActionExperience",
            model.signature,
            (
                features,
                group.summary(),
                _target_wire(target),
            ),
        )
        current = Experience(
            key,
            1 if old is None else old.revision + 1,
            model.domain,
            context,
            meaning,
            _tags(model, features),
            tuple(dict.fromkeys(source for sample in samples for source in sample.grounds)),
            (),
            tuple(sample.reference for sample in samples),
        )
        if old is None or replace(current, revision=old.revision) != old:
            updates.append(current)
    if not updates:
        prepared = replace(
            index,
            sample_cursor=len(memory.samples),
            experience_cursor=len(memory.experiences),
            outputs=index.outputs.update(
                {key: memory._latest[key] for key in index.groups if key in memory._latest}
            ),
        )
        return memory, prepared
    learned = revise_experiences(memory, tuple(updates))
    index = replace(
        index,
        sample_cursor=len(memory.samples),
        experience_cursor=len(learned.experiences),
        outputs=index.outputs.update({e.key: e for e in updates}),
    )
    return learned, index


def query_for(model, subject, context, past, candidates):
    """Use the union of candidate cues for one recall shared by the whole decision."""
    validate_candidates(model, candidates)
    if not candidates:
        raise ValueError("recall query needs at least one candidate")
    if type(context) is not Context or context.domain != model.domain:
        raise ValueError("query context has a foreign domain")
    return RecallQuery(
        subject,
        context,
        past,
        frozenset(tag for c in candidates for tag in _tags(model, c.features)),
    )


def query_for_model(model, subject, context, past):
    """Recall a declared vocabulary before complete action candidates exist."""
    if type(model) is not Model:
        raise ValueError("query requires the model's declared context")
    return query_for_features(model, subject, context, past, model.features)


def query_for_features(model, subject, context, past, features):
    """Recall a proven vocabulary; selection still closes all evidence dependencies."""
    if type(model) is not Model or type(context) is not Context or context.domain != model.domain:
        raise ValueError("query requires the model's declared context")
    if type(features) not in (tuple, frozenset) or any(f not in model.features for f in features):
        raise ValueError("recall vocabulary must use declared model features")
    return RecallQuery(
        subject, context, past, frozenset(f"{model.signature}:{name}" for name in features)
    )


def validate_candidates(model, candidates):
    """Validate a complete immutable candidate set against its semantic dimensions."""
    if type(model) is not Model or type(candidates) is not tuple:
        raise ValueError("appraisal candidates require a Model and tuple")
    for candidate in candidates:
        _candidate(model, candidate)
    if len({c.key for c in candidates}) != len(candidates):
        raise ValueError("candidate keys must be distinct")


def validate_weights(model, weights):
    """Check personality or current goals against one declared outcome vocabulary."""
    if type(model) is not Model:
        raise ValueError("weights require a Model")
    return _bound(model, weights)


def validate_personality(model, weights):
    """Personality may value learned outcomes and declared subjective traits."""
    if type(model) is not Model:
        raise ValueError("personality requires a Model")
    _vector(weights)
    names = {name for name, _ in weights}
    allowed = set(model.outcomes) | {name for name, _, _ in model.appraisal}
    if not names <= allowed:
        raise ValueError(
            "personality dimensions disagree with declared outcomes or appraisal traits"
        )
    return tuple(sorted(weights))


@dataclass(frozen=True)
class Contribution:
    sample: tuple
    grounds: tuple
    similarity: Fraction
    outcomes: tuple
    independence: tuple


@dataclass(frozen=True)
class Estimate:
    candidate: Candidate
    expected: tuple
    contributions: tuple[Contribution, ...]


@dataclass(frozen=True)
class Assessment:
    model: Model
    recalled: Recall
    estimates: tuple[Estimate, ...]
    status: str
    reason: str | None
    work: int


def _input_case(model, sample, meter, index):
    slot = None if index is None else index.slots.get(sample.key)
    if slot is None or slot.sample is not sample:
        return _decode(model, sample, meter)
    meter.spend()
    if slot.work > 1:
        meter.spend(slot.work - 1)
    return slot.case


def _cases(model, recalled, meter):
    memory = memory_for(recalled)
    index = None if memory is None else memory._consolidations.get(model.signature)
    grounds, decoded, cases = {}, {}, {}
    if memory is None:
        for episode in recalled.grounds:
            if type(episode) is not Episode or episode.subject != recalled.subject:
                raise ValueError("appraisal ground belongs to a different subject")
            if episode.source in grounds:
                raise ValueError("appraisal grounds must be unique")
            meter.spend()
            grounds[episode.source] = episode
    else:
        meter.units(len(recalled.grounds))
    samples = {}
    for sample in recalled.samples:
        meter.spend(1 + len(sample.grounds))
        if memory is None and (type(sample) is not Sample or sample.reference in samples):
            raise ValueError("appraisal samples must be distinct")
        if memory is None and any(s not in grounds for s in sample.grounds):
            raise ValueError("sample has an absent appraisal ground")
        samples[sample.reference] = sample
    stale = set()
    by_key = {sample.key: sample for sample in samples.values()}
    for item in recalled.experiences:
        meter.spend()
        if item.meaning.name != "ActionExperience" or item.meaning.signature != model.signature:
            continue
        if item.domain != model.domain or item.opposition:
            raise ValueError("incompatible empirical experience")
        if item.context not in (None, recalled.context):
            raise ValueError("personal experience has a foreign context")
        selected = []
        if type(item.meaning.wire) is not tuple or len(item.meaning.wire) != 3:
            raise ValueError("malformed empirical experience")
        references = item.samples
        missing = tuple(ref for ref in references if ref not in samples)
        meter.spend(len(references))
        if missing:
            if any(
                key not in by_key or revision >= by_key[key].revision for key, revision in missing
            ):
                raise _PendingExperience("stale_or_missing_samples")
            stale.update(key for key, _ in missing)
            continue
        verified = index is not None and index.outputs.get(item.key) is item
        support = None if verified else set()
        for reference in references:
            meter.spend(1 + len(samples[reference].grounds))
            sample = samples.get(reference)
            if not verified:
                support.update(sample.grounds)
            if reference not in decoded:
                decoded[reference] = _input_case(model, sample, meter, index)
            case = decoded[reference]
            if case is None:
                raise ValueError("experience cites incompatible feedback")
            features, _, target = case
            expected_context = sample.trial.context if target is not None else None
            if item.context != expected_context:
                raise ValueError("feedback applicability was changed")
            if selected and (features, target) != (selected[0][0], selected[0][2]):
                raise ValueError("experience mixes different action meanings")
            meter.spend(len(case[1]))
            selected.append(case)
            cases[reference] = sample, case
            if meter.limits.cases is not None and len(cases) > meter.limits.cases:
                raise AppraisalBudget("appraisal case budget exhausted")
        if not selected:
            raise ValueError("empirical experience needs supporting feedback")
        if not verified:
            expected = (
                selected[0][0],
                _summary(selected),
                _target_wire(selected[0][2]),
            )
            if item.meaning.wire != expected or support != set(item.support):
                raise ValueError("experience summary disagrees with its original feedback")
    if not stale <= {key for key, _ in cases}:
        raise _PendingExperience("stale_or_missing_samples")
    for reference, sample in samples.items():
        if reference not in decoded:
            decoded[reference] = _input_case(model, sample, meter, index)
        case = decoded[reference]
        if case is not None and reference not in cases:
            if case[2] is None or sample.trial.context == recalled.context:
                raise _PendingExperience("feedback_not_consolidated")
    return cases, tuple(
        (ref, samples[ref], case[0], case[1]) for ref, case in decoded.items() if case is not None
    )


def _independence(cases, meter):
    """One unit of weight per connected shared-result component, separately per axis."""
    factors = {ref: {} for ref, *_ in cases}
    axes = sorted({axis for _, _, _, outcomes in cases for axis, _ in outcomes})
    for axis in axes:
        parents, owners = {}, {}

        def root(key):
            while parents[key] != key:
                meter.spend()
                key = parents[key]
            return key

        for ref, sample, _, outcomes in cases:
            meter.spend(1 + len(outcomes))
            if axis not in dict(outcomes):
                continue
            parents[ref] = ref
            for source in sample.weight_sources:
                meter.spend()
                publication = source.publication
                if publication in owners:
                    parents[root(ref)] = root(owners[publication])
                else:
                    owners[publication] = ref
        groups = {}
        for ref in parents:
            groups.setdefault(root(ref), []).append(ref)
        for group in groups.values():
            for ref in group:
                factors[ref][axis] = Fraction(1, len(group))
    return factors


class _Applicability:
    """Index exact outcome scopes once; shared-result weights follow each scope."""

    def __init__(self, model, dependencies, meter):
        self.rules = dict(model.applicability)
        self.groups, self.weights = {}, {}
        for reference, sample, features, outcomes in dependencies:
            meter.spend(1 + len(features))
            previous = dict(features)
            for axis, value in outcomes:
                names = self.rules.get(axis, ())
                meter.spend(1 + len(names))
                key = tuple(previous.get(name, 0) for name in names)
                self.groups.setdefault(axis, {}).setdefault(key, []).append(
                    (reference, sample, None, ((axis, value),))
                )

    def for_features(self, actual, meter):
        eligible, independence = {}, {}
        for axis in sorted(self.groups):
            names = self.rules.get(axis, ())
            meter.spend(1 + len(names))
            key = tuple(actual.get(name, 0) for name in names)
            group = self.groups[axis].get(key, ())
            cache = axis, key
            if cache not in self.weights:
                self.weights[cache] = _independence(group, meter)
            factors = self.weights[cache]
            for reference, _, _, outcomes in group:
                meter.spend(1 + len(outcomes))
                eligible.setdefault(reference, []).extend(outcomes)
                independence.setdefault(reference, {})[axis] = factors[reference][axis]
        return {key: tuple(outcomes) for key, outcomes in eligible.items()}, independence


class AppraisalFrame:
    """Lazy pure preparation shared only by this exact captured model and recall."""

    def __init__(self, model, recalled):
        if (
            type(model) is not Model
            or type(recalled) is not Recall
            or recalled.context.domain != model.domain
        ):
            raise ValueError("assessment requires recall in its declared domain")
        self._model, self._recalled = model, recalled
        self._prepared = False
        self._cases_ready = False
        self._cases = self._applicability = None
        self._dependencies = None
        self._selectors, self._personal = (), False
        self._contexts, self._features, self._contributions = {}, {}, {}

    @property
    def model(self):
        return self._model

    @property
    def recalled(self):
        return self._recalled

    def _prepare(self, meter):
        if self._cases_ready:
            meter.spend()
            if meter.limits.cases is not None and len(self._cases) > meter.limits.cases:
                raise AppraisalBudget("appraisal case budget exhausted")
        else:
            self._cases, self._dependencies = _cases(self.model, self.recalled, meter)
            self._cases_ready = True
        if self._prepared:
            return
        cases = self._cases
        applicability = _Applicability(self.model, self._dependencies, meter) if cases else None
        selectors = tuple(sorted({n for _, names in self.model.applicability for n in names}))
        self._cases, self._applicability, self._selectors = cases, applicability, selectors
        self._personal = any(case[2] is not None for _, case in cases.values())
        self._dependencies = None
        self._prepared = True

    def assess(self, candidates, *, limits=Limits()):
        return _assess(self, candidates, limits)


def assess(model, recalled, candidates, *, limits=Limits()):
    """One-shot evaluation; explicit frames share completed pure preparation."""
    return AppraisalFrame(model, recalled).assess(candidates, limits=limits)


class _Contributions:
    """Own a pure scan/aggregate continuation without exposing partial results."""

    def __init__(self, cases, context, actual, target, eligible, independence):
        self._iterator = self._calculate(cases, context, actual, target, eligible, independence)
        self._pending = self._result = None
        self._ready = self._failed = False

    @staticmethod
    def _calculate(cases, context, actual, candidate_target, eligible, independence):
        contributions = []
        for reference, (sample, (features, _, target)) in cases.items():
            yield 1
            outcomes = eligible.get(reference, ())
            if not outcomes:
                continue
            yield len(features) + len(actual) + len(outcomes)
            if target is not None and (
                sample.trial.context != context or target != candidate_target
            ):
                continue
            previous = dict(features)
            axes = previous.keys() | actual.keys()
            overlap = sum(min(previous.get(k, 0), actual.get(k, 0)) for k in axes)
            if not overlap:
                continue
            similarity = Fraction(
                overlap, sum(max(previous.get(k, 0), actual.get(k, 0)) for k in axes)
            )
            contributions.append(
                Contribution(
                    reference,
                    sample.grounds,
                    similarity,
                    outcomes,
                    tuple(independence[reference].items()),
                )
            )
        totals, weights = {}, {}
        for contribution in contributions:
            yield 1 + len(contribution.outcomes)
            factors = dict(contribution.independence)
            for axis, value in contribution.outcomes:
                weight = contribution.similarity * factors[axis]
                totals[axis] = totals.get(axis, 0) + weight * value
                weights[axis] = weights.get(axis, 0) + weight
        return tuple(contributions), totals, weights

    def _release(self):
        iterator, self._iterator = self._iterator, None
        self._pending = None
        if iterator is not None:
            iterator.close()

    def _advance(self):
        try:
            self._pending = next(self._iterator)
        except StopIteration as complete:
            self._result, self._ready = complete.value, True
            self._release()
        except BaseException:
            self._failed = True
            self._release()
            raise

    def finish(self, meter):
        if self._failed:
            raise ValueError("failed contribution calculation cannot continue")
        if not self._ready and self._pending is None:
            self._advance()
        while not self._ready:
            try:
                meter.spend(self._pending)
            except AppraisalBudget:
                raise
            except BaseException:
                self._failed = True
                self._release()
                raise
            self._advance()
        return self._result


def _assess(frame, candidates, limits):
    """Estimate consequences once per candidate; incomplete work publishes no ranking."""
    model, recalled = frame.model, frame.recalled
    validate_candidates(model, candidates)
    if type(recalled) is not Recall or recalled.context.domain != model.domain:
        raise ValueError("assessment requires recall in its declared domain")
    needed = frozenset(tag for c in candidates for tag in _tags(model, c.features))
    if not needed <= recalled.query.cues:
        raise ValueError("recall does not cover the candidate semantics")
    if recalled.status not in {"complete", "limited"}:
        raise ValueError("unknown recall status")
    meter, estimates = _Meter(limits), []

    def result(reason=None):
        return Assessment(
            model,
            recalled,
            tuple(estimates) if reason is None else (),
            "complete" if reason is None else "limited",
            reason,
            meter.work,
        )

    if recalled.status == "limited":
        return result(f"recall:{recalled.reason}")
    if limits.candidates is not None and len(candidates) > limits.candidates:
        return result("candidates")
    try:
        frame._prepare(meter)
        cases = frame._cases
        if not cases:
            for candidate in candidates:
                meter.spend(1 + len(candidate.features) + len(candidate.prior))
                prior = dict(candidate.prior)
                estimates.append(
                    Estimate(
                        candidate,
                        tuple((axis, Fraction(prior[axis])) for axis in model.outcomes),
                        (),
                    )
                )
            return result()
        selectors, applicability = frame._selectors, frame._applicability
        contexts, feature_inputs, contribution_cache = (
            frame._contexts,
            frame._features,
            frame._contributions,
        )
        personal = frame._personal
        for candidate in candidates:
            meter.spend(1 + len(candidate.features) + len(candidate.prior))
            feature_key = tuple(sorted(candidate.features))
            if feature_key not in feature_inputs:
                meter.spend(len(selectors))
                actual = dict(candidate.features)
                feature_inputs[feature_key] = (
                    actual,
                    tuple(actual.get(name, 0) for name in selectors),
                )
            actual, key = feature_inputs[feature_key]
            if key not in contexts:
                contexts[key] = applicability.for_features(actual, meter)
            eligible, independence = contexts[key]
            # Relevance depends on features and personal targets, not priors or known axes.
            contribution_key = feature_key, candidate.target if personal else None
            if contribution_key not in contribution_cache:
                contribution_cache[contribution_key] = _Contributions(
                    cases, recalled.context, actual, candidate.target, eligible, independence
                )
            contributions, totals, weights = contribution_cache[contribution_key].finish(meter)
            prior = dict(candidate.prior)
            meter.spend(len(model.outcomes))
            estimates.append(
                Estimate(
                    candidate,
                    tuple(
                        (
                            axis,
                            Fraction(prior[axis])
                            if axis in candidate.known or axis not in weights
                            else (model.prior_weight * prior[axis] + totals[axis])
                            / (model.prior_weight + weights[axis]),
                        )
                        for axis in model.outcomes
                    ),
                    contributions,
                )
            )
    except (AppraisalBudget, _PendingExperience) as error:
        return result(str(error))
    return result()


@dataclass(frozen=True)
class Score:
    candidate: str
    total: Fraction
    parts: tuple
    valuation: tuple
    appraisal: tuple = ()


@dataclass(frozen=True)
class Decision:
    assessment: Assessment
    personality: tuple
    goals: tuple
    scores: tuple[Score, ...]
    status: str
    choice: str | None


def choose(assessment, *, personality, goals):
    """Keep the estimator separate from current goals, personality, and exact ties."""
    if type(assessment) is not Assessment:
        raise ValueError("choice requires an Assessment")
    personality = validate_personality(assessment.model, personality)
    goals = validate_weights(assessment.model, goals)
    traits, aims = dict(personality), dict(goals)
    scores = []
    if assessment.status == "complete":
        for estimate in assessment.estimates:
            factors = dict(estimate.candidate.valuation)
            features = dict(estimate.candidate.features)
            parts = tuple(
                (
                    axis,
                    value,
                    traits.get(axis, 0),
                    aims.get(axis, 0),
                    value * factors.get(axis, 1) * (traits.get(axis, 0) + aims.get(axis, 0)),
                )
                for axis, value in estimate.expected
            )
            appraisal = tuple(
                (
                    name,
                    tuple((feature, features.get(feature, 0)) for feature in seek),
                    tuple((feature, features.get(feature, 0)) for feature in avoid),
                    traits.get(name, 0),
                    traits.get(name, 0)
                    * (
                        sum(features.get(feature, 0) for feature in seek)
                        - sum(features.get(feature, 0) for feature in avoid)
                    ),
                )
                for name, seek, avoid in assessment.model.appraisal
                if traits.get(name, 0)
            )
            scores.append(
                Score(
                    estimate.candidate.key,
                    sum(p[-1] for p in parts) + sum(part[-1] for part in appraisal),
                    parts,
                    tuple(
                        (axis, factors.get(axis, 1), value * factors.get(axis, 1))
                        for axis, value in estimate.expected
                    ),
                    appraisal,
                )
            )
    if assessment.status != "complete":
        status, choice = "incomplete", None
    elif not scores:
        status, choice = "no_candidate", None
    else:
        best = max(score.total for score in scores)
        winners = [score.candidate for score in scores if score.total == best]
        status, choice = ("selected", winners[0]) if len(winners) == 1 else ("tie", None)
    return Decision(assessment, personality, goals, tuple(scores), status, choice)
