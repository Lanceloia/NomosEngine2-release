"""Observed, process-local continuation around the existing pure planning problem."""

from dataclasses import dataclass

from nomos_cognition.planning.search import Work
from nomos_cognition.planning.values import Limits

from .actions import ActionResult
from .errors import AdmissionError, SettlementDefect
from .scenario_planning import CompiledScenarioPlanning, ScenarioPlanningProblem, capture_scenario


@dataclass(frozen=True)
class ContinuationResult:
    status: str
    scope: object
    changed: bool
    work: int
    nodes: int
    decision: object | None = None


class PlanningContinuation:
    """Waiting observes local inputs; it neither yields control nor drives other Actors."""

    def __init__(self, session, actor, definition, goal, *, limits=None, capture_budget=4096):
        if (
            type(definition) is not CompiledScenarioPlanning
            or definition.program is not session.program
        ):
            raise AdmissionError("ForeignPlanningProgram", "continuation needs this exact Program")
        if definition.continuation is None:
            raise AdmissionError("MissingPlanningContinuation", "model needs an observed window")
        limits = Limits() if limits is None else limits
        if type(limits) is not Limits:
            raise ValueError("continuation needs pure Limits")
        controller = session._actor(actor)
        if not session.references.accepts(definition.actor_sort, controller.sort):
            raise AdmissionError("WrongController", "continuation needs its selected Actor sort")
        self._session, self._actor, self.definition, self.goal = session, actor, definition, goal
        self.limits, self.capture_budget = limits, capture_budget
        self._value_limits = session.limits.value
        self._problem, self._offered, self._finished = None, None, None
        self._work = Work(limits.work)
        self._check()
        self._state, self._references = self._capture()
        self._scope = self._state.window.scope
        self._finished = self._terminal_status(self._state.window)

    @property
    def scope(self):
        return self._scope

    @property
    def local(self):
        return self._state.local

    def _check(self):
        if self._session._busy or self._session._fatal:
            raise SettlementDefect("continuation needs a completed, nonfatal publication")
        if self._session.limits.value != self._value_limits:
            raise AdmissionError(
                "PlanningLimitsChanged", "new value limits need a new continuation"
            )

    def _capture(self):
        return capture_scenario(
            self._session,
            self._actor,
            self.definition,
            self.goal,
            self.capture_budget,
        )

    def _result(self, status, changed, decision=None):
        search = None if self._problem is None else self._problem.search
        result = ContinuationResult(
            status,
            self.scope,
            changed,
            self._work.used,
            0 if search is None else search.nodes,
            decision,
        )
        self._offered = result if status == "ready_intent" else None
        return result

    def _terminal_status(self, window):
        if window.scope != self.scope:
            return "window_closed"
        if window.complete:
            return "completed"
        return "window_closed" if window.closed else None

    def poll(self, quota):
        self._check()
        self._offered = None
        if type(quota) is not int or quota < 1:
            raise ValueError("continuation poll needs positive search work")
        if self._finished is not None:
            return self._result(self._finished, False)
        state, references = self._capture()
        if references.allowed != self._references.allowed:
            raise AdmissionError(
                "PlanningDomainChanged", "reference growth needs a new continuation"
            )
        changed = state != self._state
        self._state = state
        window = state.window
        self._finished = self._terminal_status(window)
        if self._finished is not None:
            return self._result(self._finished, changed)
        if not window.ready:
            return self._result("awaiting_input", changed)
        if self._problem is None:
            self._problem = ScenarioPlanningProblem._from_inputs(
                self._session,
                self._actor,
                self.definition,
                self.goal,
                limits=self.limits,
                capture_budget=self.capture_budget,
                inputs=(state, references),
                work=self._work,
            )
        else:
            self._problem._adopt_inputs(state, references)
        decision = self._problem.advance(quota)
        return self._result(decision.status, changed, decision)

    def submit(self, result):
        self._check()
        if self._finished is not None:
            return ActionResult("rejected", code="PlanningContinuationClosed")
        if type(result) is not ContinuationResult or result is not self._offered:
            raise AdmissionError(
                "ForeignPlanningDecision", "submit the latest ready continuation result"
            )
        self._offered = None
        return self._problem.submit(result.decision)
