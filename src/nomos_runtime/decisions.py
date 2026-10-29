"""Issued local semantic frames and real selections, separate from empirical ranking."""

from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from .actions import ActionResult
from .candidates import enumerate_candidates, selected_strategy
from .consideration import ConsiderationReport, shortlist
from .errors import AdmissionError, SettlementDefect


@dataclass(frozen=True, eq=False)
class CandidateFrame:
    model: object
    candidates: tuple
    status: str
    work: int
    timing: object
    consideration: object


@dataclass(frozen=True)
class DescriptionTiming:
    semantics_ms: float
    metadata_ms: float
    explanations_ms: float


@dataclass(frozen=True)
class ConstructionTiming:
    enumeration_ms: float
    preparation_ms: float
    semantics_ms: float
    metadata_ms: float
    explanations_ms: float
    validation_ms: float
    screening_ms: float


@dataclass(frozen=True)
class CandidateDescription:
    candidate: object
    metadata: object
    explain: object
    timing: DescriptionTiming


@dataclass(frozen=True)
class CandidateMetadata:
    correlation: tuple
    capture: tuple


@dataclass(frozen=True)
class PreparedCandidateRule:
    screen: object
    describe: object
    meaning: object
    projection: object | None = None


@dataclass(frozen=True)
class PartialFeatureProjection:
    """Generated Actor-local additive view used only while refining one subset."""

    signature: str
    input: str
    evaluate: object
    offsets: tuple = ()
    features: tuple = ()

    def __post_init__(self):
        if (
            type(self.signature) is not str
            or not self.signature
            or type(self.input) is not str
            or not self.input
            or not callable(self.evaluate)
            or type(self.offsets) is not tuple
            or type(self.features) is not tuple
            or not self.features
            or any(type(name) is not str or not name for name in self.features)
            or len(set(self.features)) != len(self.features)
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not int
                or item[1] < 0
                for item in self.offsets
            )
            or {name for name, _ in self.offsets} != set(self.features)
        ):
            raise ValueError("partial feature projection needs a signature, input and evaluator")


@dataclass(eq=False)
class IssuedCandidate:
    candidate: object
    description: CandidateDescription
    metadata: CandidateMetadata | None = None
    explanations: tuple | None = None


@dataclass(frozen=True)
class DecisionAlternative:
    key: str
    ability: str
    inputs: tuple
    explanations: tuple
    count: int
    detailed: bool


@dataclass(frozen=True)
class IssuedFrame:
    controller: object
    strategy: object
    basis: tuple
    at: int | None
    model: tuple
    candidates: tuple
    status: str
    work: int
    entries: tuple
    consideration: tuple
    receipts: object
    local_inputs: object
    limits: object


@dataclass(frozen=True)
class ChoiceDraft:
    semantics: object
    inputs: tuple
    profile: str
    correlation: tuple
    input_terms: tuple
    capture: tuple


@dataclass(frozen=True)
class PublishedChoice:
    source: str
    occurrence: int
    ability: str
    inputs: tuple
    epoch: object
    semantics: object
    profile: str
    correlation: tuple
    input_terms: tuple
    capture: tuple


def _basis(session):
    return (
        session._states,
        session._history,
        session._processes,
        session._scheduling,
        session._minds,
        session.controllers,
    )


def _model_wire(model):
    return (
        model.name,
        model.domain,
        model.features,
        model.outcomes,
        model.prior_weight,
        model.signature,
        model.applicability,
        model.appraisal,
    )


def _candidate_wire(candidate):
    target = candidate.target
    return (
        candidate.key,
        candidate.features,
        candidate.prior,
        candidate.known,
        candidate.valuation,
        None if target is None else (target.name, target.signature, target.wire),
    )


def candidate_frame(session, actor, *, budget, actions, exhaustive=False):
    from nomos_cognition.appraisal import validate_candidates

    strategy = selected_strategy(session, actor)
    if strategy is None or strategy.semantics is None:
        raise AdmissionError("NoCandidateSemantics", "Actor has no selected semantic strategy")
    basis = _basis(session)
    receipts, local_inputs, limits, at = (
        session._receipts,
        session._local_inputs,
        session.limits,
        session._time,
    )
    began = perf_counter()
    enumeration = enumerate_candidates(session, actor, budget, actions)
    enumeration_ms = (perf_counter() - began) * 1000
    preparation_ms = semantics_ms = metadata_ms = explanations_ms = validation_ms = 0
    candidates, entries = [], []
    prepared = {}
    frame_key = uuid4().hex

    def prepare(entry):
        nonlocal preparation_ms
        scope = entry.rule, entry.opportunity
        if scope not in prepared:
            began = perf_counter()
            rule = strategy.candidates[entry.rule]
            value = rule.prepare(session, enumeration.controller, entry.record)
            if type(value) is not PreparedCandidateRule:
                raise AdmissionError("InvalidCandidateSemantics", "typed preparation required")
            prepared[scope] = value
            preparation_ms += (perf_counter() - began) * 1000
        return prepared[scope]

    def screen(entry):
        function = prepare(entry).screen
        if function is None:
            raise AdmissionError("InvalidConsideration", "selected policy lacks a screen")
        return function(entry.values)

    unique = {}
    for entry in enumeration.items:
        unique.setdefault(entry.key, entry)
    screening_at = perf_counter()
    considered, coverage = shortlist(
        tuple(unique.values()), screen, strategy.consideration, exhaustive=exhaustive
    )
    screening_ms = max(0, (perf_counter() - screening_at) * 1000 - preparation_ms)
    for entry in considered:
        key = f"{frame_key}:{len(candidates) + 1}"
        try:
            description = prepare(entry).describe(entry.values, key)
            if type(description) is not CandidateDescription:
                raise ValueError("typed candidate description required")
            candidate = description.candidate
            semantics_ms += description.timing.semantics_ms
            metadata_ms += description.timing.metadata_ms
            explanations_ms += description.timing.explanations_ms
            began = perf_counter()
            validate_candidates(strategy.semantics, (candidate,))
            validation_ms += (perf_counter() - began) * 1000
        except ValueError as error:
            raise AdmissionError("InvalidCandidateSemantics", str(error)) from error
        if candidate.key != key:
            raise AdmissionError("InvalidCandidateSemantics", "semantic key differs from its frame")
        candidates.append(candidate)
        entries.append(
            (
                key,
                IssuedCandidate(entry, description),
            )
        )
    candidates = tuple(candidates)
    began = perf_counter()
    validate_candidates(strategy.semantics, candidates)
    validation_ms += (perf_counter() - began) * 1000
    if (
        any(current is not prior for current, prior in zip(_basis(session), basis, strict=True))
        or session._receipts is not receipts
        or session._local_inputs is not local_inputs
        or session.limits is not limits
        or session._time != at
        or session._fatal
    ):
        raise AdmissionError("StaleCandidateFrame", "world changed during candidate construction")
    timing = ConstructionTiming(
        enumeration_ms,
        preparation_ms,
        semantics_ms,
        metadata_ms,
        explanations_ms,
        validation_ms,
        screening_ms,
    )
    frame = CandidateFrame(
        strategy.semantics, candidates, enumeration.status, enumeration.work, timing, coverage
    )
    session._candidate_frames[frame] = IssuedFrame(
        enumeration.controller,
        strategy,
        basis,
        at,
        _model_wire(frame.model),
        tuple(_candidate_wire(c) for c in candidates),
        frame.status,
        frame.work,
        tuple(entries),
        coverage.wire,
        receipts,
        local_inputs,
        limits,
    )
    return frame


def _issued(session, actor, frame):
    from nomos_cognition.appraisal import Model, validate_candidates

    controller = session._actor(actor)
    saved = session._candidate_frames.get(frame) if type(frame) is CandidateFrame else None
    if saved is None:
        raise AdmissionError("UnknownCandidateFrame", "unknown or consumed candidate frame")
    if saved.controller != controller:
        raise AdmissionError("WrongController", "candidate frame belongs to another Actor")
    try:
        validate_candidates(frame.model, frame.candidates)
    except (ValueError, AttributeError, TypeError) as error:
        raise AdmissionError(
            "InvalidCandidateFrame", "invalid issued candidate semantics"
        ) from error
    if (
        type(frame.model) is not Model
        or type(frame.work) is not int
        or type(frame.status) is not str
        or _model_wire(frame.model) != saved.model
        or tuple(_candidate_wire(c) for c in frame.candidates) != saved.candidates
        or (frame.status, frame.work) != (saved.status, saved.work)
        or type(frame.consideration) is not ConsiderationReport
        or frame.consideration.wire != saved.consideration
    ):
        raise AdmissionError("InvalidCandidateFrame", "issued candidate frame was modified")
    return saved


def candidate_details(session, actor, frame, key):
    saved = _issued(session, actor, frame)
    entry = next((entry for name, entry in saved.entries if name == key), None)
    if type(key) is not str or entry is None:
        raise AdmissionError("UnknownCandidate", "key does not belong to this frame")
    return _candidate_details(session, saved, entry, None)


def candidate_frame_details(session, actor, frame):
    """Read every issued candidate after one complete frame authority check."""
    saved = _issued(session, actor, frame)
    copy_memo = {}
    return {
        key: _candidate_details(session, saved, entry, copy_memo) for key, entry in saved.entries
    }


def _current(session, saved):
    return (
        all(current is prior for current, prior in zip(_basis(session), saved.basis, strict=True))
        and session._time == saved.at
        and session._receipts is saved.receipts
        and session._local_inputs is saved.local_inputs
        and session.limits is saved.limits
        and not session._busy
        and not session._fatal
    )


def _materialize(session, saved, entry, field):
    value = getattr(entry, field)
    if value is not None:
        return value
    if not _current(session, saved):
        raise AdmissionError("StaleCandidateFrame", "cannot expand an unmaterialized old frame")
    callback = entry.description.metadata if field == "metadata" else entry.description.explain
    value = callback()
    if not _current(session, saved):
        raise AdmissionError("StaleCandidateFrame", "world changed during deferred expansion")
    if (
        field == "metadata"
        and type(value) is not CandidateMetadata
        or (field == "explanations" and type(value) is not tuple)
    ):
        raise AdmissionError("InvalidCandidateSemantics", "invalid deferred candidate data")
    setattr(entry, field, value)
    return value


def _candidate_details(session, saved, entry, copy_memo):
    metadata = _materialize(session, saved, entry, "metadata")
    return {
        "ability": entry.candidate.ability,
        "inputs": dict(entry.candidate.choices),
        "epoch": entry.candidate.epoch,
        "correlation": metadata.correlation,
        "explanations": deepcopy(_materialize(session, saved, entry, "explanations"), copy_memo),
        "basis": len(saved.basis[1]),
        "capture": metadata.capture,
    }


def decision_alternatives(session, actor, frame, decision, selection):
    """Freeze every binding and retain rich explanations for leading options."""
    saved = _issued(session, actor, frame)
    scores = {score.candidate: score.total for score in decision.scores}
    best, counts = {}, {}
    for key, entry in saved.entries:
        ability = entry.candidate.ability
        counts[ability] = counts.get(ability, 0) + 1
        options = best.setdefault(ability, [])
        options.append((key, entry))
    for options in best.values():
        options.sort(key=lambda item: (-scores[item[0]], item[0] != selection))
    return tuple(
        DecisionAlternative(
            key,
            ability,
            deepcopy(entry.candidate.choices),
            deepcopy(
                tuple(
                    item
                    for item in _materialize(session, saved, entry, "explanations")
                    if item[0] != "information"
                )
            )
            if rank < 2 or key == selection
            else (),
            counts[ability],
            rank < 2 or key == selection,
        )
        for ability, options in best.items()
        for rank, (key, entry) in enumerate(options)
    )


def canonical_candidate_order(session, actor, frame):
    """Order the complete issued frame independently of Session scopes and opaque keys."""
    saved = _issued(session, actor, frame)
    return tuple(
        key
        for key, _ in sorted(
            saved.entries, key=lambda item: (item[1].candidate.rule, item[1].candidate.key)
        )
    )


def canonical_selection(session, actor, frame, decision):
    """Resolve an actual exact tie using the selected authored control policy."""
    saved = _issued(session, actor, frame)
    if saved.strategy.tie != "canonical" or decision.status != "tie":
        raise ValueError("canonical selection requires an explicit policy and exact tie")
    best = max(score.total for score in decision.scores)
    winners = {score.candidate for score in decision.scores if score.total == best}
    return min(
        ((key, entry.candidate) for key, entry in saved.entries if key in winners),
        key=lambda item: (item[1].rule, item[1].key),
    )[0]


def submit_candidate(session, actor, frame, key, *, authority=None):
    from .controllers import require_writer

    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot submit during settlement or after fatal")
    require_writer(session, session._actor(actor), authority)
    saved = _issued(session, actor, frame)
    if frame.status != "complete":
        raise AdmissionError("IncompleteCandidateFrame", "frame has no complete candidate set")
    entry = next((entry for name, entry in saved.entries if name == key), None)
    if type(key) is not str or entry is None:
        raise AdmissionError("UnknownCandidate", "key does not belong to this frame")
    if not _current(session, saved) or selected_strategy(session, actor) is not saved.strategy:
        return ActionResult("rejected", code="StaleCandidateFrame")
    candidate = next(c for c in frame.candidates if c.key == key)
    metadata = _materialize(session, saved, entry, "metadata")
    correlation, captured, entry = metadata.correlation, metadata.capture, entry.candidate
    from .feedback import pack

    input_types = dict(saved.strategy.candidates[entry.rule].input_types)
    terms = tuple(
        (name, pack(session.controllers.terms, input_types[name], value))
        for name, value in entry.choices
    )
    del session._candidate_frames[frame]
    return session._submit_selected(
        actor,
        entry.ability,
        dict(entry.choices),
        entry.binding,
        entry.epoch,
        selection=ChoiceDraft(
            candidate, entry.choices, frame.model.domain, correlation, terms, captured
        ),
        authority=authority,
    )
