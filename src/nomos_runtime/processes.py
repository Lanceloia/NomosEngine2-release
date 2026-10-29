"""Local decision requests and atomic cursors for compiled process functions."""

from dataclasses import dataclass

from pyrsistent import pmap, pvector

from .errors import AdmissionError, ControlRejection


@dataclass(frozen=True)
class ResponseWindow:
    participants: str
    order: str
    successor: str


@dataclass(frozen=True)
class ProcessNode:
    process: str
    point: str
    prompt: str
    chooser: str
    prefix: tuple
    inputs: tuple
    resets: tuple
    window: ResponseWindow | None
    stage: tuple


@dataclass(frozen=True)
class ProcessBinding:
    scope: str
    process: str
    start: int
    point: str
    basis: int


@dataclass(frozen=True, eq=False)
class DecisionOpportunity:
    process: str
    point: str
    prompt: str


@dataclass(frozen=True)
class ProcessStep:
    point: str
    occurrence: int
    actor: object
    inputs: tuple
    next_point: str
    result: object
    advanced: bool


@dataclass(frozen=True)
class ProcessRecord:
    scope: str
    process: str
    initiator: object
    steps: tuple
    captures: tuple
    origins: tuple
    responded: frozenset
    supports: tuple
    stage_actors: frozenset

    @property
    def start(self):
        return self.steps[0].occurrence

    @property
    def point(self):
        return self.steps[-1].next_point

    def binding(self):
        return ProcessBinding(
            self.scope,
            self.process,
            self.start,
            self.point,
            next(step.occurrence for step in reversed(self.steps) if step.advanced),
        )


@dataclass(frozen=True, init=False)
class ProcessStore:
    """Persistent latest records plus active positions, committed as one value."""

    records: object
    _active: object

    def __init__(self, records=()):
        records = pvector(records)
        active = {}
        for position, record in enumerate(records):
            if type(record) is not ProcessRecord:
                raise ValueError("process history requires ProcessRecords")
            if record.point != "finish":
                active[record.scope, record.process, record.start] = position
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "_active", pmap(active))

    def __iter__(self):
        return iter(self.records)

    @property
    def active(self):
        return tuple(self.records[index] for index in sorted(self._active.values()))

    @property
    def active_count(self):
        return len(self._active)

    def find(self, binding):
        if type(binding) is not ProcessBinding:
            return None
        position = self._active.get((binding.scope, binding.process, binding.start))
        if position is None:
            return None
        record = self.records[position]
        return record if record.binding() == binding else None

    def changed(self, previous, record):
        key = record.scope, record.process, record.start
        if previous is None:
            if key in self._active:
                raise AdmissionError("WrongRequest", "process is already active")
            position, records = len(self.records), self.records.append(record)
        else:
            position = self._active.get(key)
            if position is None or self.records[position] is not previous:
                raise AdmissionError("WrongRequest", "process snapshot is no longer active")
            records = self.records.set(position, record)
        active = self._active
        if record.point == "finish":
            if key in active:
                active = active.remove(key)
        else:
            active = active.set(key, position)
        value = object.__new__(ProcessStore)
        object.__setattr__(value, "records", records)
        object.__setattr__(value, "_active", active)
        return value


def roster(window, captures):
    members = tuple(captures[window.participants])
    if not members or len(set(members)) != len(members):
        raise ControlRejection("InvalidWindow", "nonempty distinct captured responders required")
    return members


def choosers(node, record):
    captures = dict(record.captures)
    if node.window is None:
        return (captures[node.chooser],)
    remaining = tuple(
        actor for actor in roster(node.window, captures) if actor not in record.responded
    )
    return remaining[:1] if node.window.order == "declared" else remaining


def stage_participants(names, environment):
    return frozenset(
        actor
        for name in names
        for actor in (
            environment[name]
            if type(environment[name]) in (frozenset, tuple)
            else (environment[name],)
        )
    )


def stage_blocker(session, actor, binding=None):
    return next(
        (
            record
            for record in session._processes.active
            if actor in record.stage_actors and binding != record.binding()
        ),
        None,
    )


def check_stage_entry(session, definition, environment):
    node = definition.process
    if (
        node is not None
        and node.point == "begin"
        and any(
            stage_blocker(session, actor) is not None
            for actor in stage_participants(node.stage, environment)
        )
    ):
        raise AdmissionError("StagePending", "a participant has an unfinished stage")


def destination(session, node, record, environment, following):
    advanced = True
    if node.window is not None:
        members = roster(node.window, dict(record.captures))
        advanced = len(record.responded) + 1 == len(members)
        following = node.window.successor if advanced else node.point
    if advanced and following != "finish":
        target = session.program.processes[node.process][following].process
        if target.window is not None:
            roster(target.window, environment)
    return following, advanced


def pending_record(session, definition, actor, binding):
    if stage_blocker(session, actor, binding) is not None:
        raise AdmissionError("StagePending", "complete the current stage first")
    node = definition.process
    if node is None:
        if binding is not None:
            raise AdmissionError("WrongRequest", "ordinary Action has no decision request")
        return None
    if node.point == "begin":
        if binding is not None or any(
            record.process == node.process and record.initiator == actor
            for record in session._processes.active
        ):
            raise AdmissionError("ProcessPending", "initiator already has a pending process")
        if session._processes.active_count >= session.limits.processes:
            raise AdmissionError("ProcessBudget", "active process capacity is exhausted")
        return None
    record = session._processes.find(binding)
    if (
        record is None
        or record.scope != actor.scope
        or record.process != node.process
        or record.point != node.point
        or actor not in choosers(node, record)
    ):
        raise AdmissionError("WrongRequest", "decision is not pending for this chooser")
    return record


def transition(session, definition, record, actor, environment, draft, occurrence):
    node = definition.process
    if node is None:
        return session._processes
    step = ProcessStep(
        node.point,
        occurrence,
        actor,
        tuple((name, environment[name]) for name in node.inputs),
        draft.next_point,
        draft.result,
        draft.advanced,
    )
    captures = dict(record.captures) if node.window is not None else dict(environment)
    origins = {} if record is None else dict(record.origins)
    origins[node.point] = (*origins.get(node.point, ()), occurrence)
    responded = frozenset() if record is None else record.responded
    supports = () if record is None else record.supports
    if node.window is not None:
        responded = responded | {actor}
    if draft.advanced:
        supports, responded = origins[node.point], frozenset()
    if draft.advanced and draft.next_point != "finish":
        following = session.program.processes[node.process][draft.next_point].process
        captures = {name: captures[name] for name in following.prefix}
        origins = {point: refs for point, refs in origins.items() if point not in following.resets}
    updated = ProcessRecord(
        actor.scope,
        node.process,
        actor if record is None else record.initiator,
        (step,) if record is None else (*record.steps, step),
        tuple(captures.items()),
        tuple(origins.items()),
        responded,
        supports,
        stage_participants(node.stage, environment) if record is None else record.stage_actors,
    )
    return session._processes.changed(record, updated)


def request_binding(session, actor, request):
    controller = session._actor(actor)
    selected = session._requests.get(request) if type(request) is DecisionOpportunity else None
    if selected is None:
        raise AdmissionError("WrongRequest", "unknown or stale decision request")
    owner, binding = selected
    if owner != controller:
        raise AdmissionError("WrongController", "decision belongs to another Actor")
    definition = session.program.processes[binding.process][binding.point]
    pending_record(session, definition, controller, binding)
    return binding


def requests(session, actor):
    from .scheduling import has_opportunity

    controller = session._actor(actor)
    if not has_opportunity(session, controller):
        return ()
    if session._terminal is not None and session._terminal.closed is not None:
        return ()
    opportunities = []
    for record in session._processes.active:
        node = session.program.processes[record.process][record.point].process
        if controller not in choosers(node, record):
            continue
        if stage_blocker(session, controller, record.binding()) is not None:
            continue
        selected = (controller, record.binding())
        request = next((key for key, value in session._requests.items() if value == selected), None)
        if request is None:
            request = DecisionOpportunity(record.process, record.point, node.prompt)
            session._requests[request] = selected
        opportunities.append(request)
    return tuple(opportunities)


def prune_requests(session):
    bindings = {
        (actor, record.binding())
        for record in session._processes.active
        for actor in choosers(
            session.program.processes[record.process][record.point].process, record
        )
    }
    if session._terminal is not None and session._terminal.closed is not None:
        bindings.clear()
    session._requests = {
        key: value for key, value in session._requests.items() if value in bindings
    }
