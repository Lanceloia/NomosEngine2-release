"""In-process subjects, explicit visits and post-publication memory barriers."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from time import perf_counter
from types import MappingProxyType
from uuid import uuid4
from weakref import WeakKeyDictionary

from pyrsistent import pvector

from nomos_cognition.appraisal import Limits as AppraisalLimits
from nomos_cognition.appraisal import (
    assess,
    choose,
    consolidate,
    query_for,
    validate_personality,
    validate_weights,
)
from nomos_cognition.exploration import EpsilonGreedy, select
from nomos_cognition.memory import Context, Memory, RecallLimits
from nomos_cognition.planning.values import Limits as PlanningLimits
from nomos_cognition.storage.store import MemoryStore

from .actions import ActionResult
from .candidates import selected_strategy
from .decisions import (
    _basis,
    candidate_details,
    candidate_frame,
    canonical_candidate_order,
    canonical_selection,
    decision_alternatives,
    submit_candidate,
)
from .errors import AdmissionError, SettlementDefect
from .expressions import ExpressionDiagnostic, ExpressionError
from .local_inputs import InputCursor
from .subject_audit import DecisionHistory, capture_audit


@dataclass(frozen=True)
class ParticipationLimits:
    feedback: int | None = None
    candidates: int = 4096
    learning: AppraisalLimits = AppraisalLimits()
    recall: RecallLimits = RecallLimits()
    appraisal: AppraisalLimits = AppraisalLimits()
    planning: PlanningLimits = PlanningLimits(work=100_000, depth=1)
    planning_slice: int = 10_000

    def __post_init__(self):
        if (
            (self.feedback is not None and (type(self.feedback) is not int or self.feedback < 1))
            or type(self.candidates) is not int
            or self.candidates < 1
            or type(self.learning) is not AppraisalLimits
            or type(self.recall) is not RecallLimits
            or type(self.appraisal) is not AppraisalLimits
            or type(self.planning) is not PlanningLimits
            or self.planning.depth != 1
            or type(self.planning_slice) is not int
            or self.planning_slice < 1
        ):
            raise ValueError("participation requires checked positive limits")


@dataclass(frozen=True)
class Visit:
    context: Context
    actor: object
    conclusion: str
    cursor: InputCursor
    pending: tuple
    memory_version: int
    goals: tuple
    limits: ParticipationLimits


@dataclass(frozen=True)
class ParticipationSnapshot:
    context: Context
    memory: Memory
    cursor: InputCursor | None
    pending: tuple
    revision: int
    status: str


@dataclass(frozen=True)
class _Progress:
    participation: object
    context: Context
    cursor: InputCursor | None = None
    pending: tuple = ()
    feedback: object = None


@dataclass(frozen=True)
class _SubjectState:
    memory: Memory
    visits: tuple = ()
    active: _Progress | None = None
    program: object = None
    library: object = None
    profile: str | None = None
    revision: int = 0
    decisions: object = field(default_factory=pvector)


@dataclass
class _DecisionPublication:
    audit: object
    value: object
    prepared: tuple | None = None


class Subject:
    """A new identity owns its memory; callers cannot supply an imported snapshot."""

    __slots__ = (
        "_state",
        "_personality",
        "_exploration",
        "_reservation",
        "_busy",
        "_memory_store",
        "_repository",
        "_closed",
    )

    def __init__(self, *, personality=(), exploration=None, reservation=None):
        if hasattr(self, "_state"):
            raise TypeError("a cognitive subject cannot be reinitialized")
        # Vocabulary is checked at bind, when an exact compiled model is available.
        if type(personality) is not tuple:
            raise ValueError("subject personality requires an immutable tuple")
        if exploration is not None and type(exploration) is not EpsilonGreedy:
            raise ValueError("subject exploration requires EpsilonGreedy or None")
        if reservation is not None and type(reservation) is not int:
            raise ValueError("subject reservation requires an integer or None")
        self._personality = personality
        self._exploration = exploration
        self._reservation = reservation
        self._state = _SubjectState(Memory("subject:" + uuid4().hex))
        self._memory_store = MemoryStore(self.memory.subject)
        self._busy = False
        self._repository, self._closed = None, False

    @property
    def memory(self):
        return self._state.memory

    @property
    def personality(self):
        return self._personality

    def _recall(self, memory, query, *, limits):
        return self._memory_store.recall(memory, query, limits=limits)

    @property
    def exploration(self):
        return self._exploration

    @property
    def reservation(self):
        return self._reservation

    @property
    def visits(self):
        return self._state.visits

    @property
    def decisions(self):
        return DecisionHistory(self._state.decisions)

    @property
    def active(self):
        return self._state.active is not None

    def __copy__(self):
        raise TypeError("a cognitive subject cannot be cloned")

    def __deepcopy__(self, memo):
        raise TypeError("a cognitive subject cannot be cloned")

    def __reduce_ex__(self, protocol):
        raise TypeError("subject persistence requires a separate identity contract")


@dataclass(frozen=True, eq=False)
class SubjectProposal:
    """An opaque, single-participation ticket; decision values are not authority."""


@dataclass(frozen=True)
class DecisionPhases:
    synchronize_ms: float = 0
    candidates_ms: float = 0
    recall_ms: float = 0
    appraisal_ms: float = 0
    candidates: int = 0
    recalled_samples: int = 0
    construction: object = None


@dataclass(frozen=True)
class ParticipationDecision:
    status: str
    decision: object = None
    proposal: SubjectProposal | None = None
    selection: str | None = None
    resolution: str | None = None
    timing: DecisionPhases | None = None
    exploration: object = None
    diagnostic: ExpressionDiagnostic | None = None


@dataclass(frozen=True)
class _IssuedProposal:
    frame: object
    key: str
    checkpoint: _SubjectState
    decision: object
    resolution: str
    exploration: object


@dataclass(frozen=True)
class _PlannedProposal:
    flow: object
    issued: object


@dataclass(frozen=True)
class SubjectDecision:
    trial: object
    context: Context
    memory_version: int
    selection: str
    resolution: str
    decision: object
    explanations: tuple
    alternatives: tuple
    exploration: object
    consideration: object
    planning: object = None


def opening_position(session):
    return session._history, session._advances, session._scheduling, session._time


def validate_binding(session, actor, subject, *, goals, limits):
    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot bind a subject during settlement or after fatal")
    if type(subject) is not Subject or type(limits) is not ParticipationLimits:
        raise ValueError("binding requires a Subject and ParticipationLimits")
    if subject._closed:
        raise AdmissionError("SubjectClosed", "the previous Subject writer is closed")
    if subject._repository is not None and subject._repository._pending is not None:
        raise AdmissionError("SubjectCheckpointPending", "retry pending save before another visit")
    if subject._busy:
        raise AdmissionError("SubjectBusy", "subject is processing a transition")
    if subject.active:
        raise AdmissionError("SubjectAlreadyBound", "subject already has an active visit")
    reference = session._actor(actor)
    if reference in session._subject_actors:
        raise AdmissionError("ActorAlreadyBound", "Actor already has a current or closed visit")
    if opening_position(session) != session._subject_opening:
        raise AdmissionError("OpeningBindingRequired", "subjects bind before world play begins")
    strategy = selected_strategy(session, actor)
    if strategy is None or strategy.semantics is None:
        raise AdmissionError("NoCandidateSemantics", "subject requires checked candidate semantics")
    model, state = strategy.semantics, subject._state
    if any(visit.actor.scope == reference.scope for visit in state.visits):
        raise AdmissionError(
            "SessionAlreadyVisited", "a subject cannot re-enter a previous Session"
        )
    validate_personality(model, subject.personality)
    goals = validate_weights(model, goals)
    if state.program is not None and (
        state.program is not session.program
        or state.library is not session.controllers
        or state.profile != model.domain
    ):
        raise AdmissionError(
            "ForeignSubjectDomain", "reuse the exact loaded Program and AI profile"
        )
    return reference, model, state, goals


def bind_subject(session, actor, subject, *, goals, limits, planning=None):
    reference, model, state, goals = validate_binding(
        session, actor, subject, goals=goals, limits=limits
    )
    if planning is not None:
        from .subject_planning import validate_selection

        validate_selection(session, actor, planning, subject)
    participation = Participation.__new__(Participation)
    participation._subject, participation._session, participation._actor = subject, session, actor
    participation._reference, participation._model = reference, model
    participation._goals, participation._limits = goals, limits
    participation._permit = object()
    participation._proposals = WeakKeyDictionary()
    participation._failure = participation._closed = None
    participation._decisions = ()
    participation._past_visits = state.visits
    participation._planning = planning
    participation._planning_flow = None
    participation._sync_pending = None
    participation._decision_pending = None
    context = Context(model.domain, reference.scope)
    updated = replace(
        state,
        active=_Progress(participation, context),
        program=session.program,
        library=session.controllers,
        profile=model.domain,
        revision=state.revision + 1,
    )
    slots = MappingProxyType({**session._subject_actors, reference: participation})
    session._subject_actors = slots
    subject._state = updated
    return participation


class Participation:
    """One opening Actor binding; world effects and memory publication stay separate."""

    __slots__ = (
        "_subject",
        "_session",
        "_actor",
        "_reference",
        "_model",
        "_goals",
        "_limits",
        "_permit",
        "_proposals",
        "_failure",
        "_closed",
        "_decisions",
        "_past_visits",
        "_planning",
        "_planning_flow",
        "_sync_pending",
        "_decision_pending",
    )

    def __init__(self):
        raise TypeError("use Session.bind_subject")

    def __copy__(self):
        raise TypeError("a participation cannot be cloned")

    def __deepcopy__(self, memo):
        raise TypeError("a participation cannot be cloned")

    def __reduce_ex__(self, protocol):
        raise TypeError("participation persistence requires a separate identity contract")

    @property
    def snapshot(self):
        if self._closed is not None:
            return self._closed
        state = self._check()
        progress = state.active
        return ParticipationSnapshot(
            progress.context,
            state.memory,
            progress.cursor,
            progress.pending,
            state.revision,
            "active",
        )

    @property
    def failure(self):
        return self._failure

    @property
    def decisions(self):
        return DecisionHistory(self._decisions)

    @property
    def past_visits(self):
        return self._past_visits

    @property
    def status(self):
        if self._closed is not None:
            return self._closed.status
        state = self._check()
        return "pending" if self._failure is not None or self._unread(state) else "ready"

    def _check(self):
        if self._closed is not None:
            raise AdmissionError(
                "ParticipationClosed", "participation no longer controls this Actor"
            )
        state = self._subject._state
        if (
            state.active is None
            or state.active.participation is not self
            or self._session._subject_actors.get(self._reference) is not self
        ):
            raise AdmissionError(
                "ParticipationClosed", "participation no longer controls this Actor"
            )
        return state

    @contextmanager
    def _transition(self):
        self._check()
        subject = self._subject
        if subject._busy:
            raise AdmissionError("SubjectBusy", "subject is processing a transition")
        subject._busy = True
        try:
            yield
        finally:
            subject._busy = False

    def _policy(self):
        state, session = self._subject._state, self._session
        strategy = selected_strategy(session, self._actor)
        if (
            session.program is not state.program
            or session.controllers is not state.library
            or strategy is None
            or strategy.semantics != self._model
        ):
            raise AdmissionError("ForeignSubjectDomain", "the bound compiled policy changed")

    def _unread(self, state):
        cursor = state.active.cursor
        return cursor is None or cursor.sequence != len(
            self._session._local_inputs.get(self._reference, ())
        )

    def _synchronize(self):
        state, session = self._check(), self._session
        try:
            self._policy()
            if self._decision_pending is not None:
                self._publish_decision()
                state = self._subject._state
            if self._sync_pending is not None:
                self._publish_memory()
                state = self._subject._state
                self._failure = None
            if self._failure is None and not self._unread(state):
                return self.snapshot
            before = (*_basis(session), session._local_inputs, session._time, session._fatal)
            update = session.feedback_memory(
                self._actor,
                state.memory,
                budget=self._limits.feedback,
                checkpoint=state.active.feedback,
            )
            memory = update.memory
            if memory.samples is not state.memory.samples:
                memory = consolidate(self._model, memory, limits=self._limits.learning)
            after = (*_basis(session), session._local_inputs, session._time, session._fatal)
            if any(a is not b for a, b in zip(before, after, strict=True)):
                raise AdmissionError("StaleSubjectSync", "world changed during feedback processing")
            progress = replace(
                state.active,
                cursor=update.cursor,
                pending=update.pending,
                feedback=update.checkpoint,
            )
            if memory is not state.memory or progress != state.active:
                self._sync_pending = state, memory, progress
                self._publish_memory()
            self._failure = None
            return self.snapshot
        except Exception as error:
            self._proposals.clear()
            self._failure = (type(error).__name__, str(error))
            raise

    def _record_decision(self, audit, value, *, close_planning=False):
        self._decision_pending = _DecisionPublication(audit, value)
        self._proposals.clear()
        if close_planning:
            self._planning_flow = None
        try:
            self._publish_decision()
        except Exception as error:
            self._failure = (type(error).__name__, str(error))
            raise

    def _publish_decision(self):
        draft = self._decision_pending
        if draft.prepared is None:
            before = self._check()
            saved = draft.audit.record(draft.value)
            after = replace(
                before, decisions=before.decisions.append(saved), revision=before.revision + 1
            )
            draft.prepared = before, after, (*self._decisions, saved)
        before, after, decisions = draft.prepared
        if self._subject._state is not before and self._subject._state is not after:
            raise SettlementDefect("cannot register a decision after unrelated Subject updates")
        self._subject._state = after
        self._decisions = decisions
        self._decision_pending = None

    def _publish_memory(self):
        state, memory, progress = self._sync_pending
        session = self._session
        if self._subject._state is not state or session._busy or session._fatal:
            raise SettlementDefect(
                "cannot publish Subject memory during a stale or busy transition"
            )
        # Freeze world submission only for the storage/publication boundary.
        # Failed writes leave the exact feedback draft available for retry.
        session._busy = True
        try:
            memory = self._subject._memory_store.publish(state.memory, memory)
            updated = replace(state, memory=memory, active=progress, revision=state.revision + 1)
            self._subject._state = updated
            self._sync_pending = None
            self._proposals.clear()
        finally:
            session._busy = False

    def sync(self):
        with self._transition():
            return self._synchronize()

    def choose(self, *, actions=None):
        """Construct eligible actions under one budget and the original Subject appraisal."""
        if self._planning is None:
            return self.propose(actions=actions)
        with self._transition():
            self._policy()
            if actions is not None and (
                type(actions) is not tuple
                or any(
                    type(a) is not str or a not in self._session.program.actions for a in actions
                )
                or len(actions) != len(set(actions))
            ):
                raise AdmissionError("InvalidStrategyScope", "distinct selected Actions required")
            strategy = selected_strategy(self._session, self._actor)
            selected = tuple(
                r.ability for r in strategy.candidates if actions is None or r.ability in actions
            )
            current = set(self._session.available_abilities(self._actor)) & set(selected)
            if self._session.requests(self._actor):
                raise AdmissionError(
                    "PlanningProcessUnsupported", "automatic planning requires atomic opportunities"
                )
            if any(
                not self._session.cognition_value(self._reference, name).complete
                for name in strategy.cognition
            ):
                return ParticipationDecision("cognition_pending")
            if self._session.ending(self._actor)["status"] == "closed":
                return ParticipationDecision("closed")
            if not current:
                return ParticipationDecision("no_candidate")
        flow = self.plan(None, limits=self._limits.planning, actions=selected)
        flow.refresh()
        issued = flow.advance(self._limits.planning_slice)
        if issued.status != "ready_intent":
            resumable = issued.status == "thinking"
            return ParticipationDecision("planning_budget" if resumable else issued.status)
        with self._transition():
            flow._check()
            proposal = SubjectProposal()
            self._proposals[proposal] = _PlannedProposal(flow, issued)
            decision, selection = flow.evaluation()
            return ParticipationDecision("proposed", decision, proposal, selection, "planning")

    def propose(self, *, actions=None):
        with self._transition():
            if self._planning is not None and (
                actions is None or set(actions) & {a.name for a in self._planning.actions}
            ):
                raise AdmissionError("PlanningRequired", "selected Actions use Participation.plan")
            began = perf_counter()
            self._synchronize()
            synchronized = perf_counter()
            state = self._subject._state
            try:
                frame = candidate_frame(
                    self._session, self._actor, budget=self._limits.candidates, actions=actions
                )
            except ExpressionError as error:
                self._proposals.clear()
                if error.diagnostic.code != "ExpressionBudget":
                    raise
                return ParticipationDecision(
                    "evaluation_limited",
                    timing=DecisionPhases(
                        (synchronized - began) * 1000,
                        (perf_counter() - synchronized) * 1000,
                    ),
                    diagnostic=error.diagnostic,
                )
            described = perf_counter()
            if frame.status != "complete":
                return ParticipationDecision(
                    frame.status,
                    timing=DecisionPhases(
                        (synchronized - began) * 1000,
                        (described - synchronized) * 1000,
                        candidates=len(frame.candidates),
                        construction=frame.timing,
                    ),
                )
            past = frozenset(visit.context for visit in state.visits)
            query = query_for(
                frame.model, state.memory.subject, state.active.context, past, frame.candidates
            )
            remembered = self._subject._recall(state.memory, query, limits=self._limits.recall)
            recalled = perf_counter()
            decision = choose(
                assess(frame.model, remembered, frame.candidates, limits=self._limits.appraisal),
                personality=self._subject.personality,
                goals=self._goals,
            )
            reservation = self._subject.reservation
            if (
                decision.scores
                and reservation is not None
                and max(score.total for score in decision.scores) <= reservation
            ):
                return ParticipationDecision(
                    "no_interest",
                    decision,
                    timing=DecisionPhases(
                        (synchronized - began) * 1000,
                        (described - synchronized) * 1000,
                        (recalled - described) * 1000,
                        (perf_counter() - recalled) * 1000,
                        len(frame.candidates),
                        len(remembered.samples),
                        frame.timing,
                    ),
                )
            key, resolution = decision.choice, "score"
            if (
                decision.status == "tie"
                and selected_strategy(self._session, self._actor).tie == "canonical"
            ):
                key = canonical_selection(self._session, self._actor, frame, decision)
                resolution = "canonical"
            elif decision.status != "selected":
                return ParticipationDecision(
                    decision.status,
                    decision,
                    timing=DecisionPhases(
                        (synchronized - began) * 1000,
                        (described - synchronized) * 1000,
                        (recalled - described) * 1000,
                        (perf_counter() - recalled) * 1000,
                        len(frame.candidates),
                        len(remembered.samples),
                        frame.timing,
                    ),
                )
            exploration = None
            if self._subject.exploration is not None:
                exploration = select(
                    decision,
                    key,
                    canonical_candidate_order(self._session, self._actor, frame),
                    self._subject.exploration,
                    visit=len(self._past_visits),
                    step=len(self._decisions),
                )
                key = exploration.selected
                if exploration.explored:
                    resolution = "explore"
            ticket = SubjectProposal()
            self._proposals[ticket] = _IssuedProposal(
                frame, key, state, decision, resolution, exploration
            )
            return ParticipationDecision(
                "proposed",
                decision,
                ticket,
                key,
                resolution,
                DecisionPhases(
                    (synchronized - began) * 1000,
                    (described - synchronized) * 1000,
                    (recalled - described) * 1000,
                    (perf_counter() - recalled) * 1000,
                    len(frame.candidates),
                    len(remembered.samples),
                    frame.timing,
                ),
                exploration,
            )

    def plan(self, goal, *, limits=None, capture_budget=4096, actions=None):
        from nomos_cognition.planning.values import Limits

        from .subject_planning import SubjectPlanning

        with self._transition():
            self._policy()
            if self._planning is None:
                raise AdmissionError("NoSubjectPlanning", "bind an explicit planning definition")
            if actions is not None and (
                type(actions) is not tuple
                or not actions
                or len(set(actions)) != len(actions)
                or not set(actions)
                <= {r.ability for r in selected_strategy(self._session, self._actor).candidates}
            ):
                raise AdmissionError("InvalidStrategyScope", "distinct selected Actions required")
            if actions is None and self._planning.atomic:
                actions = tuple(action.name for action in self._planning.actions)
            selected = Limits(depth=1) if limits is None else limits
            if self._planning_flow is not None:
                flow = self._planning_flow
                if (goal, selected, capture_budget, actions) != (
                    flow.goal,
                    flow.limits,
                    flow.capture_budget,
                    flow.actions,
                ):
                    raise AdmissionError(
                        "PlanningAlreadyActive", "resume or refresh the existing calculation"
                    )
                return flow
            self._synchronize()
            flow = SubjectPlanning(self, goal, selected, capture_budget, actions)
            self._planning_flow = flow
            return flow

    def proposal_details(self, proposal):
        saved = self._proposals.get(proposal) if type(proposal) is SubjectProposal else None
        if type(saved) is _PlannedProposal:
            return saved.flow.details(saved.issued)
        state = self._check()
        self._policy()
        if self._failure is not None or self._unread(state):
            raise AdmissionError("SubjectPending", "synchronize inputs before reading a proposal")
        selected = self._proposals.get(proposal) if type(proposal) is SubjectProposal else None
        if selected is None or selected.checkpoint is not state:
            raise AdmissionError("UnknownSubjectProposal", "unknown or stale participation ticket")
        return candidate_details(self._session, self._actor, selected.frame, selected.key)

    def submit(self, proposal):
        saved = self._proposals.get(proposal) if type(proposal) is SubjectProposal else None
        if type(saved) is _PlannedProposal:
            return saved.flow.submit(saved.issued)
        with self._transition():
            state = self._check()
            self._policy()
            if self._failure is not None or self._unread(state):
                raise AdmissionError(
                    "SubjectPending", "synchronize committed inputs before submitting"
                )
            selected = self._proposals.get(proposal) if type(proposal) is SubjectProposal else None
            if selected is None:
                raise AdmissionError(
                    "UnknownSubjectProposal", "unknown or consumed participation ticket"
                )
            if selected.checkpoint is not state:
                return ActionResult("rejected", code="StaleSubjectProposal")
            try:
                details = candidate_details(
                    self._session, self._actor, selected.frame, selected.key
                )
                alternatives = decision_alternatives(
                    self._session, self._actor, selected.frame, selected.decision, selected.key
                )
            except AdmissionError as error:
                if error.code == "StaleCandidateFrame":
                    return ActionResult("rejected", code=error.code)
                raise
            before = len(self._session._local_inputs.get(self._reference, ()))
            audit = capture_audit(self._subject._memory_store, selected.decision)
            del self._proposals[proposal]
            result = submit_candidate(
                self._session, self._actor, selected.frame, selected.key, authority=self._permit
            )
            if result.status == "published":
                trial = self._session._local_inputs[self._reference][before].payload
                self._record_decision(
                    audit,
                    SubjectDecision(
                        trial,
                        state.active.context,
                        state.memory.version,
                        selected.key,
                        selected.resolution,
                        selected.decision,
                        details["explanations"],
                        alternatives,
                        selected.exploration,
                        selected.frame.consideration,
                    ),
                )
            return result

    def finish(self):
        with self._transition():
            if self._session.ending(self._actor)["status"] != "closed":
                raise AdmissionError("WorldNotClosed", "use interrupt to leave an active world")
            return self._release("finished")

    def interrupt(self):
        with self._transition():
            return self._release("interrupted")

    def _release(self, conclusion):
        self._synchronize()
        state = self._subject._state
        progress = state.active
        visit = Visit(
            progress.context,
            self._reference,
            conclusion,
            progress.cursor,
            progress.pending,
            state.memory.version,
            self._goals,
            self._limits,
        )
        closed = replace(self.snapshot, status=conclusion)
        updated = replace(
            state, visits=(*state.visits, visit), active=None, revision=state.revision + 1
        )
        self._subject._state = updated
        self._closed = closed
        self._proposals.clear()
        self._planning_flow = None
        # The closed receipt owns frozen values, not a live world or future visits.
        # A new inert marker revokes the old writer without reopening the Actor.
        self._permit = object()
        self._session = self._subject = self._planning = None
        return visit
