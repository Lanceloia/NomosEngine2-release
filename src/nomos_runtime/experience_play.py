"""An in-process group of long-lived subjects over explicit opening visits."""

from dataclasses import dataclass
from time import perf_counter

from .candidates import selected_strategy
from .errors import AdmissionError
from .participation import ParticipationLimits, Subject, validate_binding


@dataclass(frozen=True)
class SubjectStep:
    actor: str | None
    decision: object = None
    result: object = None
    decision_ms: float = 0
    submit_ms: float = 0


class SubjectGroup:
    def __init__(self, *, limits=ParticipationLimits()):
        if type(limits) is not ParticipationLimits:
            raise ValueError("subject group requires ParticipationLimits")
        self.limits = limits
        self.subjects = ()
        self.visits = {}
        self.rounds = 0
        self.session = None

    def bind(self, session, *, player=None):
        if self.session is not None:
            raise AdmissionError("GroupAlreadyPlaying", "finish or interrupt the previous visit")
        play = session.program.play
        if (
            play is None
            or play.mechanism != "tabletop"
            or player is not None
            and player not in play.seats
        ):
            raise AdmissionError(
                "NoTabletopMechanism", "group needs a table and optional human seat"
            )
        seats = play.seats
        if self.subjects and len(self.subjects) != len(seats):
            raise AdmissionError("ForeignSubjectDomain", "group size changed")
        policies = [selected_strategy(session, seat) for seat in seats]
        if any(p is None or p.semantics is None or p.participation is None for p in policies):
            raise AdmissionError("NoSubjectPolicy", "every seat needs an authored subject policy")
        subjects = self.subjects or tuple(Subject(personality=p.participation[0]) for p in policies)
        assignments = [
            (seat, subjects[(index + self.rounds) % len(subjects)], policy.participation[1])
            for index, (seat, policy) in enumerate(zip(seats, policies, strict=True))
            if seat != player
        ]
        # Validate the whole opening before any subject acquires an Actor.
        planning = session.controllers.planning
        for seat, subject, goals in assignments:
            validate_binding(session, seat, subject, goals=goals, limits=self.limits)
            if planning is not None:
                from .subject_planning import validate_selection

                validate_selection(session, seat, planning, subject)
        visits = {
            seat: session.bind_subject(
                seat, subject, goals=goals, limits=self.limits, planning=planning
            )
            for seat, subject, goals in assignments
        }
        self.subjects, self.visits, self.session = subjects, visits, session
        return visits

    def finish(self):
        if self.session is None:
            raise AdmissionError("NoGroupVisit", "group has no active table")
        if any(self.session.ending(seat)["status"] != "closed" for seat in self.visits):
            raise AdmissionError("WorldNotClosed", "interrupt an active table explicitly")
        self._release("finish")

    def interrupt(self):
        if self.session is not None:
            self._release("interrupt")

    def _release(self, operation):
        for visit in self.visits.values():
            if visit.status not in ("finished", "interrupted"):
                getattr(visit, operation)()
        self.rounds += 1
        self.session = None

    def step(self):
        session = self.session
        if session is None:
            raise AdmissionError("NoGroupVisit", "group has no active table")
        if session.program.play.joint_decisions:
            raise AdmissionError("JointTableControlRequired", "shared windows require TableControl")
        for actor in session.program.play.seats:
            if session.available_abilities(actor) or session.requests(actor):
                if actor not in self.visits:
                    return SubjectStep(actor)
                visit = self.visits[actor]
                began = perf_counter()
                decision = visit.choose()
                decision_ms = (perf_counter() - began) * 1000
                if decision.status != "proposed":
                    return SubjectStep(actor, decision, decision_ms=decision_ms)
                began = perf_counter()
                result = visit.submit(decision.proposal)
                return SubjectStep(
                    actor, decision, result, decision_ms, (perf_counter() - began) * 1000
                )
        return SubjectStep(None)
