"""Generated local prediction models and single-step control over their actual Program."""

from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from uuid import uuid4

from nomos_cognition.planning.search import Planner, Work
from nomos_cognition.planning.values import (
    Basis,
    Belief,
    Binding,
    Decision,
    Inapplicable,
    Limits,
    Outcome,
    Parameter,
    Scenario,
    Schema,
)

from .actions import ActionResult
from .entities import ReadContext, ReferenceDomain
from .errors import AdmissionError, SettlementDefect
from .expressions import ValueBudget
from .ordering import canonical


@dataclass(frozen=True)
class PlanningAction:
    name: str
    parameters: tuple
    bind: object
    predict: object
    subsets: tuple = ()
    constructions: tuple = ()


@dataclass(frozen=True)
class CompiledPlanning:
    program: object
    name: str
    signature: str
    actor_sort: str
    goal_type: str
    goal_validator: object
    fields: tuple
    actions: tuple
    achieved: object
    reward: int
    step: int


@dataclass(frozen=True)
class LocalSnapshot:
    controller: object
    rows: tuple

    def states(self):
        return MappingProxyType({ref: MappingProxyType(dict(fields)) for ref, fields in self.rows})

    def apply(self, changes):
        states = {ref: dict(fields) for ref, fields in self.rows}
        seen = set()
        for ref, field, value in changes:
            key = ref, field
            if key in seen:
                raise ValueError("prediction effects write the same actual field twice")
            seen.add(key)
            if ref not in states or field not in states[ref]:
                raise ValueError("prediction writes outside its local snapshot")
            states[ref][field] = value
        return LocalSnapshot(
            self.controller,
            tuple((ref, tuple(fields.items())) for ref, fields in states.items()),
        )


class LocalModel:
    """Only generated functions and detached local values, without a Session reference."""

    experience_basis = "no-memory"

    def __init__(self, definition, references, value_limits, initial, goal):
        self.definition, self.references, self.value_limits = definition, references, value_limits
        self.schemas = tuple(
            Schema(a.name, tuple(Parameter(name, carrier) for name, _, carrier in a.parameters))
            for a in definition.actions
        )
        self._domains = {}
        self.initial_achieved = definition.achieved(self.reads(initial), value_limits, goal, None)

    def reads(self, snapshot):
        return ReadContext(
            self.definition.program.schema_id,
            self.references,
            snapshot.states(),
            "actor",
            self.definition.program.reference_readers,
            snapshot.controller,
        )

    @staticmethod
    def state(belief):
        if len(belief.scenarios) != 1 or type(belief.scenarios[0].state) is not LocalSnapshot:
            raise ValueError("the generated deterministic model needs one local snapshot")
        return belief.scenarios[0].state

    def terminal(self, belief, goal, work):
        work.spend()
        if self.definition.achieved(self.reads(self.state(belief)), self.value_limits, goal, work):
            return Fraction(0 if self.initial_achieved else self.definition.reward)
        return None

    def schema_at(self, belief, goal, cursor, work):
        work.spend()
        return self.schemas[cursor] if cursor < len(self.schemas) else None

    def binding_at(self, belief, goal, partial, cursor, work):
        work.spend()
        state = self.state(belief)
        index = self.schemas.index(partial.schema)
        key = state, partial
        if key not in self._domains:
            selected = self.definition.actions[index].bind(
                self.reads(state), self.value_limits, dict(partial.arguments), work
            )
            if selected is None:
                self._domains[key] = None
            else:
                _, field, pool = selected
                work.spend(max(1, len(pool)))
                self._domains[key] = field, tuple(sorted(pool, key=canonical))
        domain = self._domains[key]
        if domain is None or cursor >= len(domain[1]):
            return None
        return Binding(partial.schema, (*partial.arguments, (domain[0], domain[1][cursor])))

    def predict(self, state, goal, action, work):
        work.spend()
        index = self.schemas.index(action.binding.schema)
        changes = self.definition.actions[index].predict(
            self.reads(state), self.value_limits, dict(action.binding.arguments), work
        )
        if changes is None:
            return Inapplicable("local capability conditions do not hold")
        work.spend(max(1, len(changes)))
        updated = state.apply(changes)
        return (Outcome(updated, "step", Fraction(self.definition.step)),)


def _stamp(session):
    return (
        session._states,
        session._history,
        session._processes,
        session._scheduling,
        session._terminal,
        session._local_inputs,
        session._receipts,
        session._opening_receipts,
        session._time,
        session._pending_due,
        session._advances,
        session._cancellations,
        session.limits,
    )


def _capture(session, actor, definition, budget):
    if type(budget) is not int or budget < 1:
        raise ValueError("local capture needs positive work")
    reads = session.context(session._states, "actor", session._actor(actor))
    rows, used = [], 0
    allowed = reads.references.allowed
    for ref in sorted(allowed, key=canonical):
        used += 1
        if used > budget:
            raise AdmissionError("PlanningCaptureBudget", "local reference capture exceeded budget")
        schema = session.program.schemas[ref.sort]
        permitted = (
            schema.view if ref == reads.controller or schema.kind == "object" else schema.public
        )
        fields = []
        needed = {
            field
            for sort, field in definition.fields
            if reads.references.accepts(sort, ref.sort) and field in permitted and field != "id"
        }
        for field in sorted(needed):
            used += 1
            if used > budget:
                raise AdmissionError("PlanningCaptureBudget", "local field capture exceeded budget")
            fields.append((field, reads.read(ref, ref.sort, field, own=ref == reads.controller)))
        rows.append((ref, tuple(fields)))
    symbols = {name: ref for name, ref in reads.references.symbols.items() if ref in allowed}
    references = ReferenceDomain(
        session.program.schemas, symbols, references=allowed, allowed=allowed
    )
    return LocalSnapshot(reads.controller, tuple(rows)), references


class PlanningProblem:
    """Explicit trusted local control; no automatic world drive, learning or fallback."""

    definition_type = CompiledPlanning

    def _bind(self, session, actor, definition, limits, capture_budget):
        if (
            type(definition) is not self.definition_type
            or definition.program is not session.program
        ):
            raise AdmissionError("ForeignPlanningProgram", "planning belongs to another Program")
        if type(limits) is not Limits:
            raise ValueError("planning needs pure Limits")
        self._session, self._actor, self.definition = session, actor, definition
        self.capture_budget = capture_budget
        self._check()
        reference = session._actor(actor)
        if not session.references.accepts(definition.actor_sort, reference.sort):
            raise AdmissionError("WrongController", "planning requires its selected Actor sort")
        return reference

    def _inputs(self):
        return _capture(self._session, self._actor, self.definition, self.capture_budget)

    def _make_model(self, state, references, goal, work):
        model = LocalModel(self.definition, references, self._session.limits.value, state, goal)
        return model, Belief((Scenario(state, Fraction(1)),))

    def __init__(self, session, actor, definition, goal, *, limits, capture_budget):
        reference = self._bind(session, actor, definition, limits, capture_budget)
        self.goal = goal
        state, references = self._inputs()
        self._initialize(reference, state, references, goal, limits)

    def _initialize(self, reference, state, references, goal, limits, *, work=None):
        goal = self.definition.goal_validator(
            goal, ValueBudget(self._session.limits.value, references), ()
        )
        self.goal = goal
        work = Work(limits.work) if work is None else work
        self.model, belief = self._make_model(state, references, goal, work)
        self.basis = Basis(
            f"{reference.scope}/{reference.ordinal}",
            uuid4().hex,
            self.definition.signature,
            self.model.experience_basis,
        )
        self.search = Planner(self.basis, belief, goal, self.model, limits=limits)
        self.search.work = work
        self._state, self._stamp, self._consumed = state, _stamp(self._session), False

    @classmethod
    def _from_inputs(
        cls, session, actor, definition, goal, *, limits, capture_budget, inputs, work
    ):
        problem = cls.__new__(cls)
        reference = problem._bind(session, actor, definition, limits, capture_budget)
        problem._initialize(reference, *inputs, goal, limits, work=work)
        return problem

    def _check(self):
        if self._session._busy or self._session._fatal:
            raise SettlementDefect("planning needs a completed, nonfatal publication")

    def _fresh(self):
        return all(a is b for a, b in zip(self._stamp, _stamp(self._session), strict=True))

    def advance(self, quota):
        self._check()
        if not self._fresh() or self._consumed:
            raise AdmissionError("StalePlanningProblem", "refresh local input before considering")
        return self.search.advance(quota, basis=self.basis)

    def submit(self, decision):
        self._check()
        if not self._fresh() or self._consumed:
            return ActionResult("rejected", code="StalePlanningProblem")
        if (
            type(decision) is not Decision
            or decision.based_on != self.basis
            or decision.status != "ready_intent"
            or decision.intent is None
            or decision.intent.binding.schema not in self.model.schemas
        ):
            raise AdmissionError("ForeignPlanningDecision", "need this problem's complete intent")
        self._consumed = True
        selected = decision.intent.binding
        return self._session.act(self._actor, selected.schema.name, dict(selected.arguments))

    def refresh(self):
        self._check()
        if self._session.limits.value != self.model.value_limits:
            raise AdmissionError("PlanningLimitsChanged", "new value limits need a new model")
        state, references = self._inputs()
        self._adopt_inputs(state, references)

    def _adopt_inputs(self, state, references):
        if references.allowed != self.model.references.allowed:
            raise AdmissionError("PlanningDomainChanged", "reference growth needs a new model")
        if state != self._state:
            basis = Basis(
                self.basis.actor, uuid4().hex, self.basis.semantics, self.basis.experience
            )
            self.search.work.until = self.search.work.limit
            model, belief = self._make_model(state, references, self.goal, self.search.work)
            self.search.rebase(basis, belief)
            self.search.model = model
            self.model, self.basis, self._state = model, basis, state
        self._stamp, self._consumed = _stamp(self._session), False


def planning_problem(session, actor, definition, goal, *, limits=None, capture_budget=4096):
    from .scenario_planning import CompiledScenarioPlanning, ScenarioPlanningProblem

    problem_type = (
        ScenarioPlanningProblem if type(definition) is CompiledScenarioPlanning else PlanningProblem
    )
    return problem_type(
        session,
        actor,
        definition,
        goal,
        limits=Limits() if limits is None else limits,
        capture_budget=capture_budget,
    )
