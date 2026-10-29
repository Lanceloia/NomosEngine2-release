"""Shared decision windows derived from each participant's actual local projection."""

from dataclasses import dataclass

from .errors import AdmissionError


@dataclass(frozen=True)
class JointDecision:
    name: str
    projection: str
    participant: str
    locked: str
    context: str
    epoch: str
    actions: tuple


@dataclass(frozen=True)
class JointWindow:
    plan: JointDecision
    epoch: int
    members: tuple
    locked: frozenset

    @property
    def key(self):
        return self.plan.name, self.epoch, self.members


class JointDecisions:
    def __init__(self, session, player, budget=64):
        self.session, self.player, self.budget = session, player, budget
        self._symbols = {ref: name for name, ref in session.symbols}
        self._waited, self._introduced, self._used, self._cursor = {}, set(), {}, {}
        self.revision = 0

    @property
    def tip(self):
        return len(self.session.history())

    def windows(self):
        windows, occupied = [], set()
        for plan in self.session.program.play.joint_decisions:
            observers = {}
            for viewer in self.session.program.play.seats:
                projected = self.session.project(viewer, plan.projection)
                if not projected["available"]:
                    continue
                members, locked = [], set()
                for row in projected["value"]:
                    member = self._symbols.get(getattr(row, plan.participant))
                    locked_value = getattr(row, plan.locked)
                    if (
                        member not in self.session.program.play.seats
                        or member in members
                        or type(locked_value) is not bool
                    ):
                        raise AdmissionError("InvalidJointDecision", "invalid actual joint roster")
                    members.append(member)
                    if locked_value:
                        locked.add(member)
                if not members or viewer not in members:
                    raise AdmissionError("InvalidJointDecision", "viewer must belong to its roster")
                epoch = self.session.read_context(viewer, plan.context)[plan.epoch]
                observers[viewer] = JointWindow(
                    plan, epoch, tuple(sorted(members)), frozenset(locked)
                )
            unique = {}
            for window in observers.values():
                if any(observers.get(member) != window for member in window.members):
                    raise AdmissionError(
                        "InvalidJointDecision", "participants disagree on roster or locks"
                    )
                unique[window.key] = window
            for window in unique.values():
                if occupied.intersection(window.members):
                    raise AdmissionError("InvalidJointDecision", "actual joint windows overlap")
                occupied.update(window.members)
                windows.append(window)
        keys = {w.key for w in windows}
        self._waited = {k: v for k, v in self._waited.items() if k[0] in keys}
        self._introduced.intersection_update(
            {(w.key, member) for w in windows for member in w.members}
        )
        self._used = {k: v for k, v in self._used.items() if k in keys}
        self._cursor = {k: v for k, v in self._cursor.items() if k in keys}
        return tuple(windows)

    def for_actor(self, actor):
        return next(
            (w for w in self.windows() if actor in w.members and len(w.locked) < len(w.members)),
            None,
        )

    def pending(self, window):
        if self._used.get(window.key, 0) >= self.budget:
            return ()
        cursor = self._cursor.get(window.key, 0)
        order = (*window.members[cursor:], *window.members[:cursor])
        return tuple(
            member
            for member in order
            if member != self.player
            and member not in window.locked
            and self._waited.get((window.key, member)) != self.tip
        )

    def initial(self, window):
        return tuple(
            member
            for member in self.pending(window)
            if (window.key, member) not in self._introduced
        )

    def record(self, window, actor, *, published):
        self.revision += 1
        self._introduced.add((window.key, actor))
        if published:
            self._used[window.key] = self._used.get(window.key, 0) + 1
        else:
            self._waited[window.key, actor] = self.tip
        self._cursor[window.key] = (window.members.index(actor) + 1) % len(window.members)

    def has_paused(self):
        return any(
            self._used.get(w.key, 0) >= self.budget
            for w in self.windows()
            if len(w.locked) < len(w.members)
        )

    def paused(self, window):
        return self._used.get(window.key, 0) >= self.budget

    def resume(self):
        self.revision += 1
        for window in self.windows():
            if self._used.get(window.key, 0) >= self.budget:
                self._used[window.key] = 0
