"""Detached finite subjective models, conditioned only on captured local reports."""

from dataclasses import dataclass
from fractions import Fraction

from nomos_cognition.planning.guidance import prioritize
from nomos_cognition.planning.search import Work, _Stop
from nomos_cognition.planning.values import (
    Belief,
    ConstructDraft,
    Inapplicable,
    Outcome,
    Parameter,
    Scenario,
    Schema,
    is_draft,
)

from .entities import ReadContext, ReferenceDomain
from .errors import AdmissionError
from .expressions import ValueBudget
from .planning import PlanningProblem
from .planning_bindings import BindingChoices, SubsetDomain
from .planning_construction import ConstructionChoices
from .planning_preparation import ConstructionFrame
from .planning_recall import capture_reports, remember


@dataclass(frozen=True)
class CompiledScenarioPlanning:
    program: object
    name: str
    signature: str
    actor_sort: str
    goal_type: str
    goal_validator: object
    capture: object
    hypotheses: tuple
    consistent: object
    terminal: object
    actions: tuple
    assumptions: tuple
    guidance: object | None
    continuation: object | None
    atomic: bool


@dataclass(frozen=True)
class PlanningWindow:
    scope: object
    ready: bool
    complete: bool
    closed: bool

    def __post_init__(self):
        hash(self.scope)
        if any(type(v) is not bool for v in (self.ready, self.complete, self.closed)):
            raise ValueError("planning window flags must be exact booleans")


@dataclass(frozen=True)
class ScenarioInput:
    local: object
    reports: tuple
    window: PlanningWindow | None


class ScenarioModel:
    """Generated pure callbacks receive values and a known reference domain, never Session."""

    @property
    def experience_basis(self):
        return "no-memory" if self.recall is None else "actor-local-report-recall-v1"

    def __init__(self, definition, references, value_limits, local, controller):
        self.definition, self.references, self.value_limits = definition, references, value_limits
        self.local = local
        self.reads = ReadContext(
            definition.program.schema_id,
            references,
            {},
            "actor",
            definition.program.reference_readers,
            controller,
        )
        self.actions = definition.actions
        self.recall = None
        self.action_priorities = ()
        self._domains = {}
        self._domain_inputs = {}
        self._bindings = {}
        self._construction_frame = ConstructionFrame(self.reads, value_limits)
        self._schemas()

    def _schemas(self):
        self.schemas = tuple(
            Schema(
                a.name,
                tuple(
                    Parameter(n, carrier, dict(a.subsets).get(n), n in dict(a.constructions))
                    for n, _, carrier in a.parameters
                ),
            )
            for a in self.actions
        )
        self._actions_by_schema = dict(zip(self.schemas, self.actions, strict=True))
        if len(self._actions_by_schema) != len(self.schemas):
            raise ValueError("planning requires distinct capability schemas")
        self._constructions = {
            schema: dict(action.constructions) for schema, action in self._actions_by_schema.items()
        }

    def _action(self, schema):
        try:
            return self._actions_by_schema[schema]
        except KeyError:
            raise ValueError("unknown planning capability schema") from None

    def prepare(self, records, goal, work):
        if self.definition.guidance is None:
            return
        self.recall = remember(
            self.definition,
            records,
            self.reads.controller,
            self.reads,
            self.value_limits,
            work,
        )
        self.prioritize(goal, work)

    def prioritize(self, goal, work):
        """Order a supplied checked recall snapshot before constructing full actions."""
        if self.recall is None:
            return
        rules = dict(self.definition.guidance.actions)
        reads = self.recall.reads(self.reads)
        if rules:
            base = self.actions

            def score(action):
                rule = rules.get(action.name)
                return 0 if rule is None else rule(reads, self.value_limits, self.local, goal, work)

            self.actions, self.action_priorities = prioritize(
                base,
                score,
                work,
                exploration=self.definition.guidance.exploration,
            )
            self._schemas()

    def initial(self, goal, work):
        cases = []
        for probability, seed in self.definition.hypotheses:
            work.spend()
            state = seed(self.reads, self.value_limits, self.local, goal, work)
            if self.definition.consistent(
                self.reads, self.value_limits, self.local, state, goal, work
            ):
                cases.append((state, probability))
        if not cases:
            raise AdmissionError(
                "PlanningEvidenceConflict", "local inputs support no model hypothesis"
            )
        total = sum(p for _, p in cases)
        return Belief(tuple(Scenario(s, p / total) for s, p in cases))

    def terminal(self, belief, goal, work):
        for case in belief.scenarios:
            work.spend()
            if not self.definition.terminal(
                self.reads, self.value_limits, self.local, case.state, goal, work
            ):
                return None
        return Fraction(0)

    def schema_at(self, belief, goal, cursor, work):
        work.spend()
        return self.schemas[cursor] if cursor < len(self.schemas) else None

    def subset_priority(self, schema, field, pool, members, bounds, complete, goal, work):
        """Optional Subject-local ordering for one finite subset prefix."""
        return None

    def binding_at(self, belief, goal, partial, cursor, work):
        work.spend()
        complete = tuple((n, v) for n, v in partial.arguments if not is_draft(v))
        construction = any(
            p.structured and p.name in dict(partial.arguments) for p in partial.missing
        )
        arguments = partial.arguments if construction else complete
        work.spend(1 + len(arguments))
        key = partial.schema, (id(goal), tuple((name, id(value)) for name, value in arguments))
        if key not in self._domains:
            work.spend(1 + len(complete))
            bound_key = partial.schema, (id(goal), tuple((n, id(v)) for n, v in complete))
            if bound_key not in self._bindings:
                selected = self._action(partial.schema).bind(
                    self.reads, self.value_limits, self.local, goal, dict(complete), work
                )
                self._bindings[bound_key] = goal, complete, selected
            else:
                selected = self._bindings[bound_key][2]
            # Keep identity keys owned even for ordinary, non-structured domains.
            self._domain_inputs[key] = goal, arguments
            if selected is None:
                self._domains[key] = None
            else:
                field, pool = selected
                if field is None:
                    raise ValueError("partial action binding unexpectedly complete")
                if field in self._constructions[partial.schema]:
                    draft = dict(partial.arguments).get(field, ConstructDraft())
                    recipe = self._constructions[partial.schema][field]

                    self._domains[key] = ConstructionChoices(
                        field,
                        recipe,
                        draft,
                        {"local": self.local, "goal": goal, **dict(complete)},
                        self._construction_frame.evaluate,
                    )
                    return self._domains[key].at(partial, cursor, work)
                priority = None
                if self.recall is not None:
                    rule = next(
                        (
                            f
                            for a, name, f in self.definition.guidance.members
                            if a == partial.schema.name and name == field
                        ),
                        None,
                    )
                    if rule is not None:
                        reads = self.recall.reads(self.reads)

                        def priority(member):
                            return rule(
                                reads,
                                self.value_limits,
                                self.local,
                                goal,
                                dict(complete),
                                member,
                                work,
                            )

                if type(pool) is SubsetDomain:
                    draft = dict(partial.arguments).get(field)
                    members = frozenset() if draft is None else draft.members
                    partial_priority = self.subset_priority(
                        partial.schema.name,
                        field,
                        pool.pool,
                        members,
                        (pool.minimum, pool.maximum),
                        dict(complete),
                        goal,
                        work,
                    )
                    if partial_priority is not None:
                        priority = partial_priority

                self._domains[key] = BindingChoices(
                    field,
                    pool,
                    work,
                    priority=priority,
                    exploration=3 if self.recall is None else self.definition.guidance.exploration,
                )
        selected = self._domains[key]
        return None if selected is None else selected.at(partial, cursor, work)

    def predict(self, state, goal, action, work):
        work.spend()
        selected = self._action(action.binding.schema)
        predicted = selected.predict(
            self.reads,
            self.value_limits,
            self.local,
            state,
            goal,
            dict(action.binding.arguments),
            work,
        )
        if predicted is None:
            return Inapplicable("hypothetical capability conditions do not hold")
        following, observation, utility = predicted
        return (Outcome(following, observation, Fraction(utility)),)


def capture_scenario(session, actor, definition, goal, budget):
    if type(budget) is not int or budget < 1:
        raise ValueError("scenario capture needs positive work")
    work = Work(budget)
    controller = session._actor(actor)
    reads = session.context(session._states, "actor", controller)
    # Goal checking precedes capture, so even capture cannot use a foreign reference.
    goal = definition.goal_validator(goal, ValueBudget(session.limits.value, reads.references), ())
    try:
        local, domain = definition.capture(session, controller, goal, work)
        work.spend(max(1, len(domain.allowed)))
        allowed = domain.allowed
        references = ReferenceDomain(
            domain.schemas,
            {n: r for n, r in domain.symbols.items() if r in allowed},
            references=allowed,
            allowed=allowed,
        )
        reports = (
            ()
            if definition.guidance is None
            else capture_reports(session, actor, definition.guidance, work)
        )
        window = None
        if definition.continuation is not None:
            detached = ReadContext(
                definition.program.schema_id,
                references,
                {},
                "actor",
                definition.program.reference_readers,
                controller,
            )
            window = definition.continuation(detached, session.limits.value, local, goal, work)
    except _Stop:
        raise AdmissionError(
            "PlanningCaptureBudget", "local model capture exceeded budget"
        ) from None
    return ScenarioInput(local, reports, window), references


class ScenarioPlanningProblem(PlanningProblem):
    definition_type = CompiledScenarioPlanning

    def _inputs(self):
        return capture_scenario(
            self._session,
            self._actor,
            self.definition,
            self.goal,
            self.capture_budget,
        )

    def _make_model(self, state, references, goal, work):
        if self.definition.atomic:
            raise AdmissionError(
                "SubjectPlanningRequired", "atomic opportunities require Subject appraisal"
            )
        model = ScenarioModel(
            self.definition,
            references,
            self._session.limits.value,
            state.local,
            self._session._actor(self._actor),
        )
        try:
            belief = model.initial(goal, work)
            model.prepare(state.reports, goal, work)
        except _Stop:
            raise AdmissionError(
                "PlanningPreparationBudget", "local model and recall preparation exceeded budget"
            ) from None
        return model, belief
