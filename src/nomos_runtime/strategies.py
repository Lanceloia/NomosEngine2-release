"""Direct score ranking, prediction checks and issued strategy proposals."""

import math
from dataclasses import dataclass

from . import candidates
from .errors import AdmissionError


@dataclass(frozen=True, eq=False)
class StrategyProposal:
    actor: object
    ability: str
    score: int
    parts: tuple


@dataclass(frozen=True)
class StrategyDecision:
    status: str
    proposal: StrategyProposal | None = None
    candidates: int = 0


@dataclass(frozen=True)
class StrategyScore:
    """One complete local-policy score, exposed only through trusted diagnostics."""

    ability: str
    score: int
    parts: tuple
    inputs: tuple
    priority: int = 0


@dataclass(frozen=True)
class _ScoredStrategyEntry:
    score: StrategyScore
    rule: int
    key: tuple
    choices: tuple
    request: object
    values: object
    record: object
    prediction: object


@dataclass(frozen=True)
class StrategyScoreFrame:
    """Immutable complete score snapshot for one unchanged controller opportunity."""

    status: str
    minimum: int | None = None
    entries: tuple = ()

    @property
    def candidates(self):
        return len(self.entries)


def score_frame(session, actor, budget, actions):
    """Evaluate every direct-policy candidate without issuing or publishing one."""

    strategy = candidates.selected_strategy(session, actor)
    if strategy is not None and strategy.semantics is not None:
        raise AdmissionError("AppraisalRequired", "semantic strategy requires a candidate frame")
    enumeration = candidates.enumerate_candidates(session, actor, budget, actions)
    if enumeration.status != "complete":
        return StrategyScoreFrame(enumeration.status)
    strategy, controller = enumeration.strategy, enumeration.controller
    predictions, ranked, minimum = {}, {}, None
    for entry in enumeration.items:
        rule = strategy.candidates[entry.rule]
        prediction = None
        minimum, allowed, priority, parts = rule.evaluate(
            session, controller, entry.values, entry.record, None
        )
        if type(allowed) is not bool or type(priority) is not int:
            raise AdmissionError("InvalidCandidateRank", "candidate guard and priority are invalid")
        if not allowed:
            continue
        use_prediction = rule.predict is not None
        if use_prediction and rule.prediction_when is not None:
            use_prediction = rule.prediction_when(session, controller, entry.values, entry.record)
            if type(use_prediction) is not bool:
                raise AdmissionError("InvalidPrediction", "prediction condition needs Bool")
        if use_prediction:
            prediction_key = entry.rule, entry.opportunity
            if prediction_key not in predictions:
                result = rule.predict(session, controller, entry.values, entry.record)
                validate_prediction(session, controller, result)
                predictions[prediction_key] = result
            prediction = predictions[prediction_key]
            subject = rule.prediction_subject(session, controller, entry.values, entry.record)
            probabilities = dict(prediction.probabilities)
            if subject not in probabilities:
                raise AdmissionError("InvalidPrediction", "candidate absent from model population")
            probability_part = ((prediction.label, round(1_000_000 * probabilities[subject])),)
            if rule.prediction_score_mode == "add":
                parts = probability_part + parts
            elif rule.prediction_score_mode == "replace":
                parts = probability_part
            else:
                raise AdmissionError("InvalidPrediction", "unknown prediction score mode")
        score = sum(value for _, value in parts)
        key = entry.key
        candidate = _ScoredStrategyEntry(
            StrategyScore(key[0], score, parts, tuple(entry.choices), priority),
            entry.rule,
            key,
            tuple(entry.choices),
            entry.request,
            entry.values,
            entry.record,
            prediction,
        )
        if key not in ranked or (priority, score) > (
            ranked[key].score.priority,
            ranked[key].score.score,
        ):
            ranked[key] = candidate
    if not ranked:
        return StrategyScoreFrame("no_candidate", minimum)
    return StrategyScoreFrame("complete", minimum, tuple(ranked.values()))


def propose(session, actor, budget, actions):
    from .processes import request_binding

    frame = score_frame(session, actor, budget, actions)
    if frame.status != "complete":
        return StrategyDecision(frame.status, candidates=frame.candidates)
    priority = max(item.score.priority for item in frame.entries)
    maximum = max(item.score.score for item in frame.entries if item.score.priority == priority)
    if priority == 0 and maximum <= frame.minimum:
        return StrategyDecision("no_positive_score", candidates=frame.candidates)
    best = [
        item
        for item in frame.entries
        if (item.score.priority, item.score.score) == (priority, maximum)
    ]
    strategy = candidates.selected_strategy(session, actor)
    if len(best) > 1 and strategy.tie == "wait":
        return StrategyDecision("tie", candidates=frame.candidates)
    selected = min(best, key=lambda item: (item.rule, item.key))
    controller = session._actor(actor)
    explanations = strategy.candidates[selected.rule].explain(
        session, controller, selected.values, selected.record
    )
    binding = (
        None if selected.request is None else request_binding(session, actor, selected.request)
    )
    choices = dict(selected.choices)
    _, _, _, _, epoch = session._admit(actor, selected.key[0], choices, binding)
    proposal = StrategyProposal(actor, selected.key[0], selected.score.score, selected.score.parts)
    session._strategy_handles[proposal] = (
        controller,
        selected.key[0],
        selected.score.score,
        selected.score.parts,
        tuple(choices.items()),
        binding,
        epoch,
        explanations,
        selected.prediction,
        selected.score.priority,
    )
    return StrategyDecision("proposed", proposal, frame.candidates)


def issued(session, actor, proposal):
    controller = session._actor(actor)
    selected = (
        session._strategy_handles.get(proposal) if type(proposal) is StrategyProposal else None
    )
    if selected is None:
        raise AdmissionError("UnknownProposal", "unknown or consumed strategy proposal")
    reference, ability, score, parts, _, _, _, _, _, _ = selected
    if reference != controller or proposal.actor != actor:
        raise AdmissionError("WrongController", "proposal belongs to another Actor")
    if (
        type(proposal.score) is not int
        or type(proposal.parts) is not tuple
        or any(
            type(p) is not tuple or len(p) != 2 or type(p[0]) is not str or type(p[1]) is not int
            for p in proposal.parts
        )
        or (proposal.ability, proposal.score, proposal.parts) != (ability, score, parts)
    ):
        raise AdmissionError("InvalidProposal", "issued proposal was modified")
    return selected


def validate_prediction(session, actor, prediction):
    from nomos_cognition.prediction import EventPrediction, Prediction

    from .expressions import ValueBindingError, ValueBudget

    if type(prediction) not in (Prediction, EventPrediction) or prediction.basis != len(
        session.history()
    ):
        raise AdmissionError("InvalidPrediction", "current immutable prediction required")
    items = prediction.probabilities
    if (
        type(items) is not tuple
        or not items
        or len(items) > session.limits.value.items
        or any(type(item) is not tuple or len(item) != 2 for item in items)
        or (
            type(prediction) is EventPrediction
            and any(type(subject) is not frozenset for subject, _ in items)
        )
        or len({subject for subject, _ in items}) != len(items)
        or any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for _, p in items
        )
        or (
            type(prediction) is Prediction
            and not math.isclose(math.fsum(p for _, p in items), 1, abs_tol=1e-12)
        )
    ):
        raise AdmissionError(
            "InvalidPrediction",
            "finite normalized subject distribution required"
            if type(prediction) is Prediction
            else "finite typed event probabilities required",
        )
    references = session.context(
        session._states, "actor", actor, receipts=session._receipts
    ).references
    try:
        validator = session.program.validators[prediction.subject_type]
        for subject, _ in items:
            validator(subject, ValueBudget(session.limits.value, references), ())
    except (KeyError, ValueBindingError) as error:
        raise AdmissionError(
            "InvalidPrediction", "prediction subject is not locally well typed"
        ) from error
