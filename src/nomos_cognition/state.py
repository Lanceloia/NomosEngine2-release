"""Pure revision records; world authority and typed binding belong to the caller."""

from dataclasses import dataclass


def _wire(value):
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is not tuple:
        raise ValueError("cognition values require closed primitive wire data")
    for child in value:
        _wire(child)


@dataclass(frozen=True)
class Term:
    name: str
    signature: str
    wire: object

    def __post_init__(self):
        if type(self.name) is not str or not self.name or type(self.signature) is not str:
            raise ValueError("invalid nominal cognition term")
        _wire(self.wire)


@dataclass(frozen=True)
class Evidence:
    scope: str
    producer: str
    slot: str
    recipient: str
    occurrence: int | None

    def __post_init__(self):
        if (
            any(
                type(v) is not str or not v
                for v in (
                    self.scope,
                    self.producer,
                    self.slot,
                    self.recipient,
                )
            )
            or self.occurrence is not None
            and (type(self.occurrence) is not int or self.occurrence < 1)
        ):
            raise ValueError("invalid evidence identity")


@dataclass(frozen=True)
class Frame:
    rule: str
    slot: Term
    ground: Evidence
    proposition: Term | None
    support: int
    opposition: int
    appraisal: Term | None
    score: int

    def __post_init__(self):
        if type(self.rule) is not str or not self.rule or type(self.slot) is not Term:
            raise ValueError("invalid revision slot")
        if type(self.ground) is not Evidence:
            raise ValueError("revision needs evidence provenance")
        if any(type(n) is not int for n in (self.support, self.opposition, self.score)):
            raise ValueError("judgments need integer strengths and scores")
        if self.support < 0 or self.opposition < 0:
            raise ValueError("belief strengths must be nonnegative")
        if self.proposition is None and (self.support or self.opposition):
            raise ValueError("strength needs a proposition")
        if self.appraisal is None and self.score:
            raise ValueError("score needs an appraisal key")
        for term in (self.proposition, self.appraisal):
            if term is not None and type(term) is not Term:
                raise ValueError("judgment has a foreign term")


@dataclass(frozen=True)
class State:
    model: str
    revision: int = 0
    frames: tuple[Frame, ...] = ()
    consumed: tuple[Evidence, ...] = ()
    history: tuple[Frame, ...] = ()
    pending: bool = False
    reasoning: object | None = None
    reasoning_history: tuple = ()
    analysis: object | None = None
    analysis_history: tuple = ()
    local: object | None = None
    local_history: tuple = ()

    def __post_init__(self):
        if type(self.model) is not str or not self.model or type(self.revision) is not int:
            raise ValueError("invalid cognition model/revision")
        if self.revision < 0 or type(self.pending) is not bool:
            raise ValueError("invalid cognition progress")
        for items, carrier in (
            (self.frames, Frame),
            (self.history, Frame),
            (self.consumed, Evidence),
        ):
            if type(items) is not tuple or any(type(v) is not carrier for v in items):
                raise ValueError("cognition history has a foreign carrier")
        # Frozen children validate themselves at construction; check State's own links here.
        consumed = set(self.consumed)
        history = set(self.history)
        if len(consumed) != len(self.consumed):
            raise ValueError("evidence was consumed twice")
        keys = [(frame.rule, frame.slot) for frame in self.frames]
        if len(set(keys)) != len(keys) or any(f.ground not in consumed for f in self.history):
            raise ValueError("invalid active slots or judgment provenance")
        if any(f not in history for f in self.frames):
            raise ValueError("active judgment is absent from revision history")
        latest = {(frame.rule, frame.slot): frame for frame in self.history}
        if self.frames != tuple(latest.values()):
            raise ValueError("active judgments do not match latest declared slots")
        from .reasoning import Graph

        if type(self.reasoning_history) is not tuple or any(
            type(g) is not Graph for g in self.reasoning_history
        ):
            raise ValueError("invalid reasoning history")
        if self.reasoning is not None:
            if not self.reasoning_history or self.reasoning_history[-1] != self.reasoning:
                raise ValueError("reasoning graph is absent from history")
            if not self.pending and self.reasoning.frames != self.frames:
                raise ValueError("current reasoning has a stale basis")
        elif self.reasoning_history:
            raise ValueError("reasoning history has no latest graph")
        for graph in self.reasoning_history:
            if graph.model != self.model or any(f not in history for f in graph.frames):
                raise ValueError("reasoning cites foreign base judgments")
        from .analysis import Analysis

        if type(self.analysis_history) is not tuple or any(
            type(a) is not Analysis for a in self.analysis_history
        ):
            raise ValueError("invalid finite analysis history")
        if self.analysis is None:
            if self.analysis_history:
                raise ValueError("finite history has no current analysis")
        elif not self.analysis_history or self.analysis_history[-1] != self.analysis:
            raise ValueError("current finite analysis is absent from history")
        cutoff = 0
        for analysis in self.analysis_history:
            if analysis.model != self.model or analysis.cutoff < cutoff:
                raise ValueError("finite analysis has a foreign model or backward frontier")
            cutoff = analysis.cutoff
        from .local_analysis import LocalAnalysis

        if type(self.local_history) is not tuple or any(
            type(a) is not LocalAnalysis for a in self.local_history
        ):
            raise ValueError("invalid local analysis history")
        if self.local is None:
            if self.local_history:
                raise ValueError("local history has no current analysis")
        elif not self.local_history or self.local_history[-1] != self.local:
            raise ValueError("current local analysis is absent from history")
        cutoff = 0
        for analysis in self.local_history:
            if analysis.model != self.model or analysis.cutoff < cutoff:
                raise ValueError("local analysis has a foreign model or backward frontier")
            cutoff = analysis.cutoff


def revise(state, processed, frames, *, pending):
    """Replace declared slots, retaining old grounds; repeated evidence is not reinforcement."""
    if type(state) is not State or type(pending) is not bool:
        raise ValueError("revision requires a constructed State and boolean progress")
    if type(processed) is not tuple or any(type(v) is not Evidence for v in processed):
        raise ValueError("processed evidence must be explicit")
    if len(set(processed)) != len(processed) or set(processed) & set(state.consumed):
        raise ValueError("evidence revision is duplicated")
    if type(frames) is not tuple or any(
        type(f) is not Frame or f.ground not in processed for f in frames
    ):
        raise ValueError("revision frames need the actual processed grounds")
    active = {(f.rule, f.slot): f for f in state.frames}
    for frame in frames:
        frame.__post_init__()
        active[(frame.rule, frame.slot)] = frame
    pending = pending or (
        state.reasoning is not None and state.reasoning.frames != tuple(active.values())
    )
    if not processed and pending == state.pending:
        return state
    return State(
        state.model,
        state.revision + 1,
        tuple(active.values()),
        (*state.consumed, *processed),
        (*state.history, *frames),
        pending,
        state.reasoning,
        state.reasoning_history,
        state.analysis,
        state.analysis_history,
        state.local,
        state.local_history,
    )


def install_reasoning(state, graph):
    """Publish only a complete graph; unchanged recomputation does not reinforce it."""
    from dataclasses import replace

    if graph == state.reasoning and not state.pending:
        return state
    history = state.reasoning_history
    if graph != state.reasoning:
        history = (*history, graph)
    return replace(
        state,
        revision=state.revision + 1,
        pending=False,
        reasoning=graph,
        reasoning_history=history,
    )


def install_analysis(state, analysis):
    from dataclasses import replace

    if analysis == state.analysis:
        return state
    return replace(
        state,
        revision=state.revision + 1,
        analysis=analysis,
        analysis_history=(*state.analysis_history, analysis),
    )


def judgments(state, *, provisional=False):
    """Incomplete analysis exposes no stale conclusions as current judgments."""
    beliefs, appraisals = {}, {}
    if state.pending and not provisional:
        return (), ()
    for frame in state.frames:
        if frame.proposition is not None:
            support, opposition = beliefs.get(frame.proposition, (0, 0))
            beliefs[frame.proposition] = (support + frame.support, opposition + frame.opposition)
        if frame.appraisal is not None:
            appraisals[frame.appraisal] = appraisals.get(frame.appraisal, 0) + frame.score
    return tuple((key, *scores) for key, scores in beliefs.items()), tuple(appraisals.items())


def install_local(state, analysis):
    from dataclasses import replace

    if state.local == analysis:
        return state
    return replace(
        state,
        revision=state.revision + 1,
        local=analysis,
        local_history=(*state.local_history, analysis),
    )


def _term_wire(value):
    return None if value is None else (value.name, value.signature, value.wire)


def frame_wire(value):
    return (
        value.rule,
        _term_wire(value.slot),
        (
            value.ground.scope,
            value.ground.producer,
            value.ground.slot,
            value.ground.recipient,
            value.ground.occurrence,
        ),
        _term_wire(value.proposition),
        value.support,
        value.opposition,
        _term_wire(value.appraisal),
        value.score,
    )


def frame_from_wire(value):
    def term(value):
        return None if value is None else Term(*value)

    rule, slot, ground, proposition, support, opposition, appraisal, score = value
    return Frame(
        rule,
        term(slot),
        Evidence(*ground),
        term(proposition),
        support,
        opposition,
        term(appraisal),
        score,
    )


def state_wire(state):
    from .analysis import analysis_wire
    from .local_analysis import local_wire
    from .reasoning import graph_wire

    state.__post_init__()
    return (
        state.model,
        state.revision,
        tuple(frame_wire(v) for v in state.frames),
        tuple((v.scope, v.producer, v.slot, v.recipient, v.occurrence) for v in state.consumed),
        tuple(frame_wire(v) for v in state.history),
        state.pending,
        tuple(graph_wire(g) for g in state.reasoning_history),
        tuple(analysis_wire(a) for a in state.analysis_history),
        tuple(local_wire(a) for a in state.local_history),
    )


def state_from_wire(wire):
    from .analysis import analysis_from_wire
    from .local_analysis import local_from_wire
    from .reasoning import graph_from_wire

    if type(wire) is not tuple or len(wire) != 9:
        raise ValueError("stored cognition needs its exact current layout")
    model, revision, frames, consumed, history, pending, graphs, analyses, locals = wire
    reasoning_history = tuple(graph_from_wire(g) for g in graphs)
    analysis_history = tuple(analysis_from_wire(a) for a in analyses)
    local_history = tuple(local_from_wire(a) for a in locals)
    return State(
        model,
        revision,
        tuple(frame_from_wire(v) for v in frames),
        tuple(Evidence(*v) for v in consumed),
        tuple(frame_from_wire(v) for v in history),
        pending,
        reasoning_history[-1] if reasoning_history else None,
        reasoning_history,
        analysis_history[-1] if analysis_history else None,
        analysis_history,
        local_history[-1] if local_history else None,
        local_history,
    )
