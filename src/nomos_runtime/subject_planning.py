"""One-step Subject planning over detached meanings and actual local memory."""

from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction

from nomos_cognition.appraisal import choose, query_for_features
from nomos_cognition.memory import Memory
from nomos_cognition.planning.search import Work, _Stop
from nomos_cognition.planning.values import Belief, Limits, Scenario

from .actions import ActionResult
from .candidates import selected_strategy
from .decisions import ChoiceDraft, DecisionAlternative
from .errors import AdmissionError
from .expressions import ExpressionError, ValueBindingError, ValueBudget
from .feedback import pack
from .partial_experience import Known, NotApplicable, Unknown
from .planning import _stamp
from .planning_appraisal import PlanningAppraiser, PlanningStage
from .planning_bindings import BindingChoices
from .planning_construction import ConstructionChoices
from .planning_recall import remember_subject
from .scenario_planning import CompiledScenarioPlanning, ScenarioModel, ScenarioPlanningProblem
from .subject_audit import capture_audit


def validate_selection(session, actor, definition, subject):
    if (
        type(definition) is not CompiledScenarioPlanning
        or definition.program is not session.program
    ):
        raise AdmissionError("ForeignPlanningProgram", "planning requires this exact Program")
    if not session.references.accepts(definition.actor_sort, session._actor(actor).sort):
        raise AdmissionError("WrongController", "planning requires its selected Actor sort")
    if subject.exploration is not None:
        raise AdmissionError(
            "PlanningExplorationUnsupported", "whole-menu exploration is not a planning policy"
        )
    strategy = selected_strategy(session, actor)
    if strategy.tie != "canonical":
        raise AdmissionError(
            "PlanningTieUnsupported", "planning requires a deterministic control profile"
        )
    if definition.atomic and len({r.ability for r in strategy.candidates}) != len(
        strategy.candidates
    ):
        raise AdmissionError(
            "AmbiguousPlanningRule", "atomic choice needs one semantic rule per ability"
        )
    for action in definition.actions:
        rules = [r for r in strategy.candidates if r.ability == action.name]
        if len(rules) != 1 or rules[0].prepare is None:
            raise AdmissionError(
                "PlanningMeaningRequired", "each planned Action needs one semantic rule"
            )
        if set(rules[0].value_names) != {name for name, _, _ in action.parameters}:
            raise AdmissionError(
                "PlanningMeaningInputs", "planning needs complete non-derived semantic inputs"
            )


class _SubjectModel(ScenarioModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.opportunity = self.definition.atomic
        self.prediction = PlanningStage("prediction")
        self._predictions = {}
        self._partial_patterns = {}
        self._partial_contributions = {}

    def install_partial_experience(self, recalled, projections, appraiser):
        self._partial_appraiser = appraiser
        self._partial_projections = dict(projections)
        for ability, projection in projections.items():
            patterns = set()
            if projection.signature != appraiser.model.domain:
                self._partial_patterns[ability] = Unknown("semantic_signature_mismatch")
                continue
            for sample in recalled.samples:
                if sample.meaning.signature != appraiser.model.signature:
                    continue
                wire = sample.meaning.wire
                if type(wire) is not tuple or len(wire) != 2 or type(wire[0]) is not tuple:
                    continue
                if wire[1] is not None:
                    continue
                vector = tuple(
                    (name, value)
                    for name, value in wire[0]
                    if type(name) is str and type(value) is int and value > 0
                )
                if vector:
                    patterns.add(vector)
            self._partial_patterns[ability] = (
                Known(tuple(sorted(patterns)))
                if patterns
                else Unknown("no_usable_complete_pattern")
            )

    def subset_priority(self, schema, field, pool, members, bounds, complete, goal, work):
        projection = getattr(self, "_partial_projections", {}).get(schema)
        if projection is None or projection.input != field:
            self._partial_patterns[schema] = NotApplicable("no_authored_projection_for_subset")
            return None
        if self.definition.guidance is not None and any(
            action == schema and name == field
            for action, name, _ in self.definition.guidance.members
        ):
            return None
        state = self._partial_patterns.get(schema, Unknown("projection_not_initialized"))
        if type(state) is NotApplicable or type(state) is Unknown:
            return None
        patterns = state.value
        if not patterns or projection.signature != self._partial_appraiser.model.domain:
            return None
        features = projection.features
        offsets = dict(projection.offsets)
        cache_key = schema, field, tuple(sorted(complete.items(), key=lambda item: item[0]))

        def contributions(member):
            key = cache_key, member
            if key not in self._partial_contributions:
                work.spend()
                values = projection.evaluate(complete, member, logical_work=work)
                if type(values) is not tuple:
                    raise AdmissionError(
                        "PartialProjectionValue",
                        "generated partial feature projection is malformed",
                    )
                decoded = dict(values)
                if set(decoded) != set(features) or any(
                    type(decoded[name]) is not int or decoded[name] < 0 for name in features
                ):
                    raise AdmissionError(
                        "PartialProjectionValue",
                        "partial feature projection needs nonnegative integers",
                    )
                self._partial_contributions[key] = decoded
            return self._partial_contributions[key]

        def possible(pattern, selected):
            remaining_pool = pool - selected
            minimum, maximum = bounds
            target = dict(pattern)
            selected_values = [contributions(value) for value in selected]
            for final_size in range(max(minimum, len(selected)), maximum + 1):
                remaining_count = final_size - len(selected)
                if remaining_count > len(remaining_pool):
                    continue
                feasible = True
                for feature in features:
                    current = sum(values[feature] for values in selected_values)
                    work.spend(1 + len(remaining_pool))
                    ordered = sorted(contributions(value)[feature] for value in remaining_pool)
                    low = current + sum(ordered[:remaining_count])
                    high = (
                        current + sum(ordered[len(ordered) - remaining_count :])
                        if remaining_count
                        else current
                    )
                    expected = target.get(feature, 0) - offsets.get(feature, 0)
                    if not low <= expected <= high:
                        feasible = False
                        break
                if feasible:
                    return True
            return False

        current_matches = tuple(pattern for pattern in patterns if possible(pattern, members))
        if len(current_matches) != 1:
            return None
        selected_pattern = current_matches[0]

        def priority(member):
            if not possible(selected_pattern, members | {member}):
                return 0
            return self._partial_appraiser.score_complete_pattern(selected_pattern, work)

        return priority

    def initial(self, goal, work):
        if self.opportunity:
            work.spend()
            return Belief((Scenario(False, Fraction(1)),))
        return super().initial(goal, work)

    def terminal(self, belief, goal, work):
        if self.opportunity:
            work.spend()
            return Fraction(0) if all(s.state is True for s in belief.scenarios) else None
        return super().terminal(belief, goal, work)

    @property
    def experience_basis(self):
        return "subject-memory-appraisal-v1"

    def predict(self, state, goal, action, work):
        work.spend()
        key = id(state), id(goal), id(action.binding)
        previous = self._predictions.get(key)
        if previous is None:
            outcomes = self.prediction.run(work, super().predict, state, goal, action, work)
        else:
            outcomes = previous[3]
        if type(outcomes) is not tuple:
            self._predictions[key] = state, goal, action.binding, outcomes
            return outcomes
        if any(outcome.utility != 0 for outcome in outcomes):
            raise AdmissionError(
                "PlanningUtilityConflict", "Subject appraisal requires zero model utility"
            )
        if self.opportunity and any(
            outcome.state is not True or outcome.observation is not None for outcome in outcomes
        ):
            raise AdmissionError(
                "PlanningOpportunityPrediction",
                "automatic choice predicts only its own atomic publication",
            )
        self._predictions[key] = state, goal, action.binding, outcomes
        value = self.appraiser.evaluate(action.binding, work)
        return tuple(replace(outcome, utility=value) for outcome in outcomes)


@dataclass(frozen=True)
class _Inputs:
    local: object
    reports: tuple
    window: object
    memory: Memory
    context: object
    past: frozenset
    world_revision: tuple


class _Problem(ScenarioPlanningProblem):
    def __init__(self, owner, goal, limits, capture_budget, *, work=None, experience="all"):
        self._owner = owner
        if type(experience) is not str or experience not in {"all", "current", "none"}:
            raise ValueError("planning experience scope must be all, current or none")
        self._experience = experience
        reference = self._bind(
            owner._session, owner._actor, owner._planning, limits, capture_budget
        )
        self.goal = goal
        inputs, references = self._inputs()
        self._initialize(reference, inputs, references, goal, limits, work=work)

    def _inputs(self):
        inputs, references = super()._inputs()
        state = self._owner._check()
        memory = Memory(state.memory.subject) if self._experience == "none" else state.memory
        past = (
            frozenset(visit.context for visit in state.visits)
            if self._experience == "all"
            else frozenset()
        )
        return _Inputs(
            inputs.local,
            inputs.reports,
            inputs.window,
            memory,
            state.active.context,
            past,
            tuple(id(part) for part in _stamp(self._session)),
        ), references

    def _definition(self, work):
        owner, session = self._owner, self._session
        scope = owner._planning_flow.actions
        definition = self.definition
        if scope is not None:
            eligible = set(session.available_abilities(self._actor))
            declared = {action.name: action for action in definition.actions}
            rules = {r.ability: r for r in selected_strategy(session, self._actor).candidates}
            actions = []
            for name in scope:
                if name not in eligible:
                    continue
                work.spend()
                if name in declared:
                    actions.append(declared[name])
                elif rules[name].planning is not None:
                    actions.append(rules[name].planning(session, owner._reference, work))
                else:
                    raise AdmissionError(
                        "MissingPlanningBinding", "no generated finite binding or recipe"
                    )
            definition = replace(definition, actions=tuple(actions))
        return definition

    def _make_model(self, state, references, goal, work):
        owner, session = self._owner, self._session
        try:
            definition = self._definition(work)
            model = _SubjectModel(
                definition, references, session.limits.value, state.local, owner._reference
            )
            belief = model.initial(goal, work)
            if self.definition.guidance is not None:
                model.recall = remember_subject(
                    self.definition,
                    state.memory,
                    state.context,
                    owner._reference,
                    model.reads,
                    session.limits.value,
                    work,
                )
                model.prioritize(goal, work)
            remaining = work.until - work.used
            if remaining < 1:
                raise _Stop
            recall_limits = owner._limits.recall
            cap = remaining if recall_limits.work is None else min(remaining, recall_limits.work)
            strategy = selected_strategy(session, self._actor)
            rules = {rule.ability: rule for rule in strategy.candidates}
            features = frozenset(
                feature
                for action in definition.actions
                for feature in rules[action.name].meaning_features
            )
            remembered = owner._subject._recall(
                state.memory,
                query_for_features(
                    owner._model, state.memory.subject, state.context, state.past, features
                ),
                limits=replace(recall_limits, work=cap),
            )
            work.spend(max(1, remembered.work))
            if remembered.status != "complete":
                raise AdmissionError(
                    "PlanningRecallLimited", remembered.reason or "incomplete recall"
                )
            meanings = {}
            projections = {}
            for action in definition.actions:
                work.spend()
                rule = rules[action.name]
                prepared = rule.prepare(session, owner._reference, None, detached=True)
                meanings[action.name] = prepared.meaning
                if prepared.projection is not None:
                    projections[action.name] = prepared.projection
            model.appraiser = PlanningAppraiser(
                owner._model,
                remembered,
                meanings,
                owner._subject.personality,
                owner._goals,
                owner._limits.appraisal,
            )
            model.install_partial_experience(remembered, projections, model.appraiser)
        except _Stop:
            raise AdmissionError(
                "PlanningPreparationBudget", "Subject recall preparation exceeded budget"
            ) from None
        return model, belief


@dataclass(frozen=True, eq=False)
class SubjectPlanningDecision:
    status: str
    decision: object
    memory_version: int


@dataclass(frozen=True)
class SubjectPlanningReport:
    context: object
    subject: str
    memory_version: int
    past_contexts: frozenset
    sources: tuple
    recalled_samples: tuple
    generation: tuple
    evaluations: tuple
    decision: object
    search: object
    abilities: tuple
    bindings: tuple
    construction: object
    valuation: tuple


class SubjectPlanning:
    """A single bound calculation; issued results are exact, single-use objects."""

    def __init__(self, owner, goal, limits, capture_budget, actions=None):
        if actions is not None and not owner._planning.atomic:
            raise AdmissionError(
                "AtomicPlanningRequired",
                "scoped choice requires a compiled atomic opportunity model",
            )
        if type(limits) is not Limits or limits.depth != 1:
            raise AdmissionError(
                "SubjectPlanningDepth", "current appraisal supports one-step plans"
            )
        self._owner, self._goal, self._limits, self._capture_budget = (
            owner,
            goal,
            limits,
            capture_budget,
        )
        self._goal = owner._planning.goal_validator(
            goal,
            ValueBudget(
                owner._session.limits.value,
                owner._session.context(
                    owner._session._states, "actor", owner._reference
                ).references,
            ),
            (),
        )
        self.actions = actions
        self._checkpoint = owner._check()
        self._problem = None
        self._work = Work(limits.work)
        self._offer = self._last = None

    @property
    def goal(self):
        return self._goal

    @property
    def limits(self):
        return self._limits

    @property
    def capture_budget(self):
        return self._capture_budget

    def _active(self):
        if self._owner._planning_flow is not self:
            raise AdmissionError(
                "SubjectPlanningClosed", "this calculation no longer controls its visit"
            )

    def _check(self):
        self._active()
        state = self._owner._check()
        self._owner._policy()
        if (
            state is not self._checkpoint
            or self._owner._failure is not None
            or self._owner._unread(state)
        ):
            raise AdmissionError(
                "StaleSubjectPlanning", "synchronize and refresh the Subject calculation"
            )
        return state

    def advance(self, quota):
        with self._owner._transition():
            self._offer = None
            state = self._check()
            if type(quota) is not int or quota < 1:
                raise ValueError("a calculation slice needs positive work")
            if self._problem is None:
                self._problem = _Problem(
                    self._owner, self.goal, self.limits, self.capture_budget, work=self._work
                )
            result = self._problem.advance(quota)
            status = result.status
            reservation = self._owner._subject.reservation
            if (
                status == "ready_intent"
                and reservation is not None
                and result.estimate.value <= reservation
            ):
                status = "no_interest"
            issued = SubjectPlanningDecision(status, result, state.memory.version)
            self._last = issued
            if status == "ready_intent":
                self._offer = issued
            return issued

    def refresh(self):
        with self._owner._transition():
            self._active()
            self._offer = None
            self._owner._synchronize()
            if self._problem is not None:
                self._problem.refresh()
            self._checkpoint = self._owner._check()
            self._last = None

    def report(self):
        if self._problem is None:
            state = self._checkpoint
            return SubjectPlanningReport(
                state.active.context,
                state.memory.subject,
                state.memory.version,
                frozenset(visit.context for visit in state.visits),
                (),
                (),
                (),
                (),
                None,
                None,
                (),
                (),
                None,
                (),
            )
        model = self._problem.model
        snapshot = model.recall
        memory = self._problem._state.memory
        return SubjectPlanningReport(
            self._problem._state.context,
            memory.subject,
            memory.version,
            self._problem._state.past,
            () if snapshot is None else snapshot.sources,
            tuple(sample.reference for sample in model.appraiser.remembered.samples),
            tuple(
                (schema.name, domain.field, domain.pool, domain.priorities)
                for (schema, _), domain in model._domains.items()
                if type(domain) is BindingChoices and domain.prepared
            ),
            tuple(model.appraiser.evaluations.values()),
            None if self._last is None else self._last.decision,
            self._problem.search.statistics(),
            tuple(a.name for a in model.actions),
            tuple(
                (schema.name, domain.field, domain.preparation())
                for (schema, _), domain in model._domains.items()
                if type(domain) in {BindingChoices, ConstructionChoices}
            ),
            model._construction_frame.preparation(),
            (model.prediction.snapshot(), *model.appraiser.preparation()),
        )

    def contrast(self, quota, *, experience="none"):
        """Read-only experience ablation with no submission ticket or authority."""
        with self._owner._transition():
            self._check()
            if self._problem is not None and not self._problem._fresh():
                raise AdmissionError("StalePlanningProblem", "refresh before comparing experience")
            problem = _Problem(
                self._owner, self.goal, self.limits, self.capture_budget, experience=experience
            )
            result = problem.advance(quota)
            return result, tuple(problem.model.appraiser.evaluations.values())

    def evaluation(self):
        """Combine only the already visited estimates for the shared decision audit."""
        self._check()
        if self._offer is None:
            raise AdmissionError("UnknownSubjectPlanning", "no current complete planning intent")
        entries = tuple(self._problem.model.appraiser.evaluations.values())
        assessment = replace(
            entries[0].decision.assessment,
            estimates=tuple(entry.decision.assessment.estimates[0] for entry in entries),
            work=sum(entry.decision.assessment.work for entry in entries),
        )
        binding = self._offer.decision.intent.binding
        selected = self._problem.model.appraiser.evaluations[binding].candidate.key
        owner = self._owner
        return choose(
            assessment, personality=owner._subject.personality, goals=owner._goals
        ), selected

    def _description(self, issued):
        self._check()
        if issued is not self._offer or type(issued) is not SubjectPlanningDecision:
            raise AdmissionError(
                "UnknownSubjectPlanning", "need this calculation's latest issued result"
            )
        if not self._problem._fresh():
            raise AdmissionError("StalePlanningProblem", "refresh before describing the choice")
        binding = issued.decision.intent.binding
        owner, session = self._owner, self._owner._session
        _, _, participants, record, epoch = session._admit(
            owner._actor, binding.schema.name, dict(binding.arguments), None
        )
        rule = next(
            r
            for r in selected_strategy(session, owner._actor).candidates
            if r.ability == binding.schema.name
        )
        evaluation = self._problem.model.appraiser.evaluations[binding]
        values = tuple((name, participants[name]) for name in rule.value_names)
        description = rule.prepare(session, owner._reference, record).describe(
            values, evaluation.candidate.key
        )
        if description.candidate != evaluation.candidate:
            raise AdmissionError(
                "StalePlannedMeaning", "actual Action meaning differs from the captured score"
            )
        return rule, evaluation, description, epoch

    def details(self, issued):
        with self._owner._transition():
            _, evaluation, description, epoch = self._description(issued)
            metadata, explanations = description.metadata(), description.explain()
            if not self._problem._fresh():
                raise AdmissionError("StalePlanningProblem", "world changed during description")
            return {
                "ability": evaluation.binding.schema.name,
                "inputs": dict(evaluation.binding.arguments),
                "epoch": epoch,
                "correlation": metadata.correlation,
                "capture": metadata.capture,
                "explanations": explanations,
                "basis": len(self._owner._session.history()),
            }

    def submit(self, issued):
        with self._owner._transition():
            self._check()
            if issued is not self._offer or type(issued) is not SubjectPlanningDecision:
                raise AdmissionError(
                    "UnknownSubjectPlanning", "need this calculation's latest issued result"
                )
            problem, owner = self._problem, self._owner
            if not problem._fresh() or problem._consumed:
                return ActionResult("rejected", code="StalePlanningProblem")
            binding = issued.decision.intent.binding
            session = owner._session
            try:
                rule, evaluation, description, epoch = self._description(issued)
            except (AdmissionError, ExpressionError, ValueBindingError) as error:
                self._offer = None
                code = error.code if isinstance(error, AdmissionError) else error.diagnostic.code
                return ActionResult("rejected", code=code)
            decision, selection_key = self.evaluation()
            metadata, explanations = description.metadata(), description.explain()
            if not problem._fresh() or owner._check() is not self._checkpoint:
                self._offer = None
                return ActionResult("rejected", code="StalePlanningProblem")
            terms = tuple(
                (name, pack(session.controllers.terms, dict(rule.input_types)[name], value))
                for name, value in binding.arguments
            )
            selection = ChoiceDraft(
                evaluation.candidate,
                binding.arguments,
                owner._model.domain,
                metadata.correlation,
                terms,
                metadata.capture,
            )
            report = self.report()
            from .participation import SubjectDecision

            counts = Counter(
                entry.binding.schema.name for entry in problem.model.appraiser.evaluations.values()
            )
            alternatives = tuple(
                DecisionAlternative(
                    entry.candidate.key,
                    entry.binding.schema.name,
                    entry.binding.arguments,
                    explanations if entry.candidate.key == selection_key else (),
                    counts[entry.binding.schema.name],
                    entry.candidate.key == selection_key,
                )
                for entry in problem.model.appraiser.evaluations.values()
            )
            before = len(session._local_inputs.get(owner._reference, ()))
            audit = capture_audit(owner._subject._memory_store, decision, report)
            self._offer = None
            result = session._submit_selected(
                owner._actor,
                binding.schema.name,
                dict(binding.arguments),
                None,
                epoch,
                selection=selection,
                authority=owner._permit,
            )
            if result.status == "published":
                problem._consumed = True
                trial = session._local_inputs[owner._reference][before].payload
                owner._record_decision(
                    audit,
                    SubjectDecision(
                        trial,
                        report.context,
                        report.memory_version,
                        selection_key,
                        "planning",
                        decision,
                        explanations,
                        alternatives,
                        None,
                        None,
                        report,
                    ),
                    close_planning=True,
                )
            return result
