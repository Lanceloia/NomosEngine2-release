"""Trusted play control over generated policies and genuine atomic world Actions."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from secrets import token_urlsafe
from time import perf_counter
from weakref import WeakKeyDictionary

from .candidates import selected_strategy
from .errors import AdmissionError, SettlementDefect
from .joint_decisions import JointDecisions
from .strategies import issued


@dataclass(frozen=True)
class PlayDefinition:
    mechanism: str
    player: str | None
    seats: tuple
    joint_decisions: tuple
    formed_kinds: tuple


@dataclass(frozen=True)
class PlayResult:
    status: str
    at: int | None
    opportunity: object = None
    actions: int = 0
    occurrences: int = 0
    deferred: int = 0
    steps: int = 0
    code: str | None = None


@dataclass(frozen=True, eq=False)
class CoordinationOffer:
    player: str


@dataclass(frozen=True)
class PolicyDecision:
    actor: str
    occurrence: int
    ability: str
    score: int
    parts: tuple
    explanations: tuple
    prediction: object | None


@dataclass(frozen=True)
class ControlTiming:
    actor: str
    decision_ms: float
    submit_ms: float
    phases: object = None


def require_controllers(session, player):
    if session.controllers is None:
        raise AdmissionError("NoControllers", "automation requires independent controllers")
    for actor in session.actor_controllers():
        if actor != player and selected_strategy(session, actor) is None:
            raise AdmissionError("NoStrategy", "every computer Actor needs a policy")
    for kind in session.program.play.formed_kinds:
        if not any(
            p.selector == "kind" and session.references.accepts(p.controller, kind)
            for p in session.controllers.strategies
        ):
            raise AdmissionError("NoStrategy", "every possibly formed Actor needs a kind policy")


def drive_play(session, budget):
    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot drive during settlement or after fatal")
    plan = session.program.play
    if plan is None or plan.mechanism != "player_turn":
        raise AdmissionError("NoPlayMechanism", "player-turn control was not selected")
    if type(budget) is not int or budget < 1:
        raise AdmissionError("InvalidBudget", "positive control-step budget required")
    require_controllers(session, plan.player)
    before, actions, deferred, steps = len(session.history()), 0, 0, 0

    def result(status, opportunity=None, code=None):
        return PlayResult(
            status,
            session.read_time(),
            opportunity,
            actions,
            len(session.history()) - before,
            deferred,
            steps,
            code,
        )

    for _ in range(budget):
        if session.ending(plan.player)["status"] == "closed":
            return result("closed")
        scheduled = session.next_opportunity()
        steps += 1
        if scheduled.status == "due":
            continue
        if scheduled.status in ("closed", "idle"):
            return result(scheduled.status)
        offer = scheduled.opportunity
        if offer.actor == plan.player:
            return result("ready", offer)
        decision = session.propose(offer.actor)
        if decision.status == "proposed":
            submitted = session.submit_proposal(offer.actor, decision.proposal)
            if submitted.status != "published":
                return result("rejected", code=submitted.code)
            actions += 1
        elif decision.status in ("no_candidate", "no_positive_score", "tie"):
            if session.defer_opportunity(offer.actor, offer).status != "deferred":
                return result("rejected", code="StaleOpportunity")
            deferred += 1
        else:
            return result("rejected", code=decision.status)
    return result("closed" if session.ending(plan.player)["status"] == "closed" else "budget")


class TableControl:
    def __init__(self, session, player, *, record_decisions=False):
        plan = session.program.play
        if plan is None or plan.mechanism != "tabletop":
            raise AdmissionError("NoPlayMechanism", "fixed-seat tabletop control was not selected")
        if type(player) is not str or player not in plan.seats:
            raise AdmissionError("UnknownSeat", "choose an opening seat")
        if type(record_decisions) is not bool:
            raise AdmissionError("InvalidDecisionRecording", "decision recording is a boolean")
        require_controllers(session, player)
        self.session, self.player = session, player
        self.joint = JointDecisions(session, player)
        self.status, self.code = "ready", None
        self._offers = WeakKeyDictionary()
        self._observer = None
        self._window = None
        self._record_decisions = record_decisions
        self._decisions = []
        self._timings = []

    @property
    def decisions(self):
        return tuple(self._decisions)

    @property
    def timings(self):
        return tuple(self._timings)

    @contextmanager
    def observe(self, observer):
        """Notify a trusted display after each committed computer root."""
        self._check()
        if not callable(observer) or self._observer is not None:
            raise ValueError("table control requires one callable publication observer")
        self._observer = observer
        try:
            yield
        finally:
            self._observer = None

    def _check(self):
        if self.session._busy or self.session._fatal:
            raise SettlementDefect("table control cannot run during settlement or after fatal")

    def _computer(self, actor, window):
        try:
            participation = self.session._subject_actors.get(self.session._actor(actor))
            actions = None if window is None else window.plan.actions
            began = perf_counter()
            decision = (
                self.session.propose(actor, actions=actions)
                if participation is None
                else participation.choose(actions=actions)
            )
            decision_ms = (perf_counter() - began) * 1000
            if decision.proposal is None:
                if decision.status == "planning_budget":
                    self.status, self.code = "budget", "PlanningSlice"
                    return self.status
                if window is not None and decision.status in (
                    "no_candidate",
                    "no_positive_score",
                    "tie",
                ):
                    self.joint.record(window, actor, published=False)
                    return "waited"
                self.status, self.code = (
                    "blocked",
                    (
                        decision.status
                        if participation is not None and participation._planning is not None
                        else "ComputerNoChoice"
                    ),
                )
                return self.status
            snapshot = (
                issued(self.session, actor, decision.proposal)
                if self._record_decisions and participation is None
                else None
            )
            occurrence = len(self.session.history()) + 1 if snapshot is not None else None
            began = perf_counter()
            outcome = (
                self.session.submit_proposal(actor, decision.proposal)
                if participation is None
                else participation.submit(decision.proposal)
            )
            submit_ms = (perf_counter() - began) * 1000
        except AdmissionError as error:
            self.status, self.code = "blocked", error.code
            return self.status
        if outcome.status != "published":
            self.status, self.code = "rejected", outcome.code
            return self.status
        if snapshot is not None:
            _, ability, score, parts, _, _, _, explanations, prediction, _ = snapshot
            self._decisions.append(
                PolicyDecision(actor, occurrence, ability, score, parts, explanations, prediction)
            )
        self._timings.append(
            ControlTiming(
                actor, decision_ms, submit_ms, None if participation is None else decision.timing
            )
        )
        if window is not None:
            self.joint.record(window, actor, published=True)
        if self._observer is not None:
            self._observer(actor, outcome)
        return "published"

    def drive(self, *, budget=64):
        if self.session._busy or self.session._fatal:
            raise SettlementDefect("table control cannot drive during settlement or after fatal")
        if type(budget) is not int or not 1 <= budget <= 256:
            raise AdmissionError("InvalidBudget", "table control needs 1..256 steps")
        before, actions, steps = len(self.session.history()), 0, 0
        self.code = None
        for _ in range(budget):
            steps += 1
            if self.session.ending(self.player)["status"] == "closed":
                self.status = "closed"
                break
            window = self.joint.for_actor(self.player)
            if window is not None:
                initial = self.joint.initial(window)
                if not initial:
                    self.status = "waiting" if self.player in window.locked else "ready"
                    break
                active, scope = initial[0], window
            else:
                active, scope = None, None
                for seat in self.session.program.play.seats:
                    if not (self.session.available_abilities(seat) or self.session.requests(seat)):
                        continue
                    scope = self.joint.for_actor(seat)
                    if seat != self.player and scope is not None:
                        pending = self.joint.pending(scope)
                        if not pending:
                            continue
                        active = pending[0]
                    else:
                        active = seat
                    break
                if active is None:
                    self.status = "budget" if self.joint.has_paused() else "blocked"
                    self.code = None if self.status == "budget" else "NoCurrentChoice"
                    break
                if active == self.player:
                    self.status = "ready"
                    break
            outcome = self._computer(active, scope)
            if outcome not in ("published", "waited"):
                break
            actions += outcome == "published"
        else:
            self.status = (
                "closed" if self.session.ending(self.player)["status"] == "closed" else "budget"
            )
        return PlayResult(
            self.status,
            self.session.read_time(),
            actions=actions,
            occurrences=len(self.session.history()) - before,
            steps=steps,
            code=self.code,
        )

    def coordination_offer(self):
        self._check()
        if self.session.ending(self.player)["status"] == "closed":
            return None
        window = self.joint.for_actor(self.player)
        if window is None or not self.joint.pending(window):
            return None
        offer = CoordinationOffer(self.player)
        self._offers[offer] = (self.joint.tip, self.joint.revision, window.key)
        return offer

    def coordination_state(self):
        self._check()
        if self.session.ending(self.player)["status"] == "closed":
            return None
        window = self.joint.for_actor(self.player)
        if window is None:
            return None
        if self._window is None or self._window[0] != window.key:
            self._window = window.key, token_urlsafe(18)
        return {
            "window": self._window[1],
            "pending": bool(self.joint.pending(window)),
            "paused": self.joint.paused(window),
            "locked": self.player in window.locked,
        }

    def resume_coordination(self):
        self._check()
        if not self.joint.has_paused():
            raise AdmissionError("NoPausedControl", "no shared decision budget is paused")
        self.joint.resume()
        return self.drive()

    def coordinate(self, offer):
        self._check()
        issued = self._offers.get(offer) if type(offer) is CoordinationOffer else None
        if issued is None or offer.player != self.player:
            raise AdmissionError("UnknownCoordination", "unknown or modified control opportunity")
        del self._offers[offer]
        if self.session.ending(self.player)["status"] == "closed":
            raise AdmissionError("StaleCoordination", "world already closed")
        window = self.joint.for_actor(self.player)
        pending = () if window is None else self.joint.pending(window)
        if not pending or issued != (self.joint.tip, self.joint.revision, window.key):
            raise AdmissionError("StaleCoordination", "shared decision opportunity changed")
        before = len(self.session.history())
        outcome = self._computer(pending[0], window)
        if outcome not in ("published", "waited"):
            return PlayResult(self.status, self.session.read_time(), code=self.code)
        count = len(self.session.history()) - before
        result = self.drive()
        return replace(
            result,
            actions=result.actions + (outcome == "published"),
            occurrences=result.occurrences + count,
            steps=result.steps + 1,
        )
