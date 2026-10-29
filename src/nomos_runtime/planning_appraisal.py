"""Detached Subject interpretation and appraisal, with cumulative stage accounting."""

from dataclasses import dataclass, replace
from hashlib import sha256

from nomos_cognition.appraisal import AppraisalFrame, choose, validate_candidates
from nomos_cognition.planning.search import _Stop

from .errors import AdmissionError


@dataclass(frozen=True)
class StagePreparation:
    name: str
    calls: int
    returned: int
    interrupted: int
    failed: int
    work: int


class PlanningStage:
    def __init__(self, name):
        self.name = name
        self.calls = self.returned = self.interrupted = self.failed = self.work = 0

    def run(self, work, function, *args, **kwargs):
        self.calls += 1
        before = work.used
        try:
            value = function(*args, **kwargs)
        except _Stop:
            self.interrupted += 1
            raise
        except BaseException:
            self.failed += 1
            raise
        else:
            self.returned += 1
            return value
        finally:
            self.work += work.used - before

    def snapshot(self):
        return StagePreparation(
            self.name, self.calls, self.returned, self.interrupted, self.failed, self.work
        )


@dataclass(frozen=True)
class ActionEvaluation:
    binding: object
    candidate: object
    decision: object


class PlanningAppraiser:
    """Pure captured callbacks and recall; no Session, Participation or Subject."""

    def __init__(self, model, remembered, meanings, personality, goals, limits):
        self.model, self.remembered, self.meanings = model, remembered, meanings
        self.personality, self.goals, self.limits = personality, goals, limits
        self.frame = AppraisalFrame(model, remembered)
        self.evaluations = {}
        self._pending_meanings = {}
        self._meaning_serial = 0
        self.meaning = PlanningStage("meaning")
        self.assessment = PlanningStage("appraisal")
        self._pattern_scores = {}

    def preparation(self):
        return self.meaning.snapshot(), self.assessment.snapshot()

    def _interpret(self, binding, key, work):
        candidate = self.meanings[binding.schema.name](binding.arguments, key, logical_work=work)
        validate_candidates(self.model, (candidate,))
        return candidate

    def evaluate(self, binding, work):
        work.spend()
        if binding in self.evaluations:
            return self.evaluations[binding].decision.scores[0].total
        candidate = self._pending_meanings.get(binding)
        if candidate is None:
            work.spend(max(1, len(binding.arguments)))
            candidate = self.meaning.run(
                work, self._interpret, binding, f"planned:{self._meaning_serial + 1}", work
            )
            self._meaning_serial += 1
            self._pending_meanings[binding] = candidate
        remaining = work.until - work.used
        if remaining < 1:
            raise _Stop
        cap = remaining if self.limits.work is None else min(remaining, self.limits.work)

        def assess():
            assessment = self.frame.assess((candidate,), limits=replace(self.limits, work=cap))
            work.spend(max(1, assessment.work))
            return assessment

        assessment = self.assessment.run(work, assess)
        if assessment.status != "complete":
            if assessment.reason and "work budget" in assessment.reason and cap == remaining:
                raise _Stop
            raise AdmissionError(
                "PlanningAppraisalLimited", assessment.reason or "incomplete appraisal"
            )
        decision = choose(assessment, personality=self.personality, goals=self.goals)
        self.evaluations[binding] = ActionEvaluation(binding, candidate, decision)
        del self._pending_meanings[binding]
        return decision.scores[0].total

    def score_complete_pattern(self, features, work):
        """Use ordinary Subject appraisal as a prefix-order hint, with neutral prior."""
        features = tuple(sorted((name, value) for name, value in features if value))
        if features in self._pattern_scores:
            work.spend()
            return self._pattern_scores[features]
        candidate = self._pattern_scores.get(("pending", features))
        if candidate is None:
            from nomos_cognition.appraisal import Candidate

            key = "partial-pattern:" + sha256(repr(features).encode()).hexdigest()
            candidate = Candidate(
                key,
                features,
                tuple((name, 0) for name in self.model.outcomes),
            )
            self._pattern_scores[("pending", features)] = candidate
        remaining = work.until - work.used
        if remaining < 1:
            raise _Stop
        cap = remaining if self.limits.work is None else min(remaining, self.limits.work)

        def assess():
            result = self.frame.assess((candidate,), limits=replace(self.limits, work=cap))
            work.spend(max(1, result.work))
            return result

        result = self.assessment.run(work, assess)
        if result.status != "complete":
            if result.reason and "work budget" in result.reason and cap == remaining:
                raise _Stop
            raise ValueError(result.reason or "partial-pattern appraisal was incomplete")
        from nomos_cognition.appraisal import choose

        value = choose(result, personality=self.personality, goals=self.goals).scores[0].total
        score = value.numerator * 1_000 // value.denominator
        self._pattern_scores[features] = score
        del self._pattern_scores[("pending", features)]
        return score
