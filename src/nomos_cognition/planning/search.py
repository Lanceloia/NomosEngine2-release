"""Incremental finite-horizon AND/OR search over pure subjective models."""

from dataclasses import dataclass, field
from fractions import Fraction
from time import perf_counter_ns

from .agenda import Agenda
from .diagnostics import Diagnostics, family
from .values import (
    Action,
    Basis,
    Belief,
    Binding,
    Branch,
    ConstructDraft,
    Decision,
    Estimate,
    Inapplicable,
    Limits,
    Outcome,
    Plan,
    Scenario,
    Schema,
    SetDraft,
)


class _Stop(Exception):
    def __init__(self, required=None):
        self.required = required


class Work:
    """Cumulative logical work; providers charge additional bounded internal operations."""

    def __init__(self, limit):
        self.limit, self.used, self.until = limit, 0, limit

    def spend(self, amount=1):
        if type(amount) is not int or amount < 1:
            raise ValueError("work charges must be positive integers")
        if self.used + amount > self.until:
            raise _Stop(amount)
        self.used += amount

    def interrupt(self, required=None):
        if required is not None and (type(required) is not int or required < 1):
            raise ValueError("required work must be positive")
        raise _Stop(required)


@dataclass(frozen=True)
class _Solution:
    plan: Plan | None
    value: Fraction
    expectation: bool


@dataclass
class _Node:
    belief: Belief
    depth: int
    parent: object = None
    best: _Solution | None = None
    family: str | None = None


@dataclass
class _Edge:
    parent: _Node
    action: Action
    utility: Fraction
    expectation: bool
    children: list = field(default_factory=list)


@dataclass
class _Job:
    kind: str
    node: _Node
    partial: Binding | None = None
    cursor: int = 0
    outcomes: tuple = ()
    edge: _Edge | None = None
    quantum: int = 0


def _confirming(job):
    return job.kind in {"open", "backup"}


class Planner:
    """A resumable calculation, never an Actor, world controller or persisted Subject.

    The agenda shares consumed work between root families and follows local continuations
    while servicing old alternatives. Experience orders suggestions before any full
    action exists. Only complete observation-conditioned policies receive an
    incumbent value; no optimistic holes.
    """

    def __init__(self, basis, belief, goal, model, *, limits=Limits(), profile=False):
        if type(basis) is not Basis or type(belief) is not Belief or type(limits) is not Limits:
            raise ValueError("planner needs its exact pure values and limits")
        hash(goal)
        if type(profile) is not bool:
            raise ValueError("search profiling selection must be boolean")
        if len(belief.scenarios) > limits.scenarios:
            raise ValueError("initial belief exceeds the scenario limit")
        self.basis, self.goal, self.model, self.limits = basis, goal, model, limits
        self.work = Work(limits.work)
        self.nodes = 1
        self.root = _Node(belief, limits.depth)
        self._agenda = Agenda(_Job("open", self.root), key=family, confirming=_confirming)
        self._cutoffs = set()
        self._halted = None
        self._failed = False
        self._diagnostics = Diagnostics(profile)
        self._phase_quanta = {}

    def statistics(self):
        return self._diagnostics.snapshot(self.work.used, self._agenda.jobs(), self._phase_quanta)

    def advance(self, quota, *, basis):
        if self._failed:
            raise ValueError("planning model failed; this calculation cannot continue")
        if type(quota) is not int or quota < 1:
            raise ValueError("a calculation slice needs positive work")
        if type(basis) is not Basis or basis != self.basis:
            raise ValueError("stale planning basis; rebase before continuing")
        until = min(self.work.limit, self.work.used + quota)
        self._agenda.start_slice()
        if self._diagnostics.starting_work is None:
            self._diagnostics.starting_work = self.work.used
        while self._agenda.ready and self._halted is None and self.work.used < until:
            job = self._agenda.pop()
            service_key = family(job), job.kind
            if not job.quantum:
                job.quantum = min(
                    self.work.limit,
                    max(self.limits.quantum, self._phase_quanta.get(service_key, 0)),
                )
            before = self.work.used
            self.work.until = min(until, before + job.quantum)
            began = perf_counter_ns() if self._diagnostics.profile else None
            status = "failed"
            interrupted = None
            try:
                self.work.spend()
                self._step(job)
                status = "completed"
            except _Stop as error:
                status = "interrupted"
                interrupted = error
            except Exception:
                self._failed = True
                raise
            finally:
                elapsed = None if began is None else perf_counter_ns() - began
                self._diagnostics.record(job, before, self.work.used, status, elapsed)
                self._agenda.account(job, self.work.used - before)
            if interrupted is not None:
                required = interrupted.required or 0
                job.quantum = min(
                    self.work.limit,
                    max(job.quantum * 2, self.work.used - before + required),
                )
                impossible = required > self.work.limit - self.work.used
                self._agenda.retry(job, suspend=self.work.until == until or impossible)
            elif service_key[0] is not None:
                # Learn actual completed service, never an inflated outer-slice cap.
                observed = self.work.used - before
                if observed > self._phase_quanta.get(service_key, self.limits.quantum):
                    self._phase_quanta[service_key] = observed
        self.work.until = until
        if self._halted is None and self._agenda and until == self.work.limit:
            if self.work.used >= until or not self._agenda.ready:
                self._halted = "work_limit"
        stopped = (
            self._halted
            or ("frontier_exhausted" if not self._agenda else None)
            or ("work_limit" if self.work.used >= self.work.limit else "slice")
        )
        return self._decision(stopped)

    def rebase(self, basis, belief):
        """Revise pure inputs, preserving this calculation's accumulated resource usage."""
        if self._failed:
            raise ValueError("planning model failed; this calculation cannot continue")
        if type(basis) is not Basis or type(belief) is not Belief or basis == self.basis:
            raise ValueError("rebasing needs a changed basis and explicit belief")
        if (basis.actor, basis.semantics, basis.experience) != (
            self.basis.actor,
            self.basis.semantics,
            self.basis.experience,
        ):
            raise ValueError("rebasing cannot switch Actor, semantics or experience model")
        if len(belief.scenarios) > self.limits.scenarios:
            raise ValueError("new belief exceeds the scenario limit")
        self.basis = basis
        self.root = _Node(belief, self.limits.depth)
        self.nodes += 1
        self._agenda = Agenda(_Job("open", self.root), key=family, confirming=_confirming)
        self._cutoffs = set()
        self._halted = "node_limit" if self.nodes > self.limits.nodes else None
        self._diagnostics = Diagnostics(self._diagnostics.profile)
        self._phase_quanta = {}

    def _enqueue(self, *jobs, focus=1):
        if len(self._agenda) + len(jobs) > self.limits.pending:
            self._halted = "pending_limit"
            return
        self._agenda.put(*jobs, focus=focus)

    def _step(self, job):
        node = job.node
        if job.kind == "open":
            value = self.model.terminal(node.belief, self.goal, self.work)
            if value is not None:
                if type(value) is not Fraction:
                    raise ValueError("terminal utility must be an explicit fraction")
                self._improve(node, _Solution(None, value, len(node.belief.scenarios) > 1))
            elif node.depth == 0:
                self._cutoffs.add("depth_limit")
            else:
                self._enqueue(_Job("schema", node))
        elif job.kind == "schema":
            schema = self.model.schema_at(node.belief, self.goal, job.cursor, self.work)
            if schema is not None:
                if type(schema) is not Schema:
                    raise ValueError("schema retrieval must return a declared schema")
                if node.family is None:
                    self._diagnostics.register(schema.name)
                if len(schema.parameters) > self.limits.parameters:
                    self._cutoffs.add("parameter_limit")
                    self._enqueue(_Job("schema", node, cursor=job.cursor + 1))
                    return
                partial = Binding(schema)
                kind = "bind" if partial.missing else "predict"
                self._enqueue(
                    _Job(kind, node, partial), _Job("schema", node, cursor=job.cursor + 1)
                )
        elif job.kind == "bind":
            child = self.model.binding_at(
                node.belief, self.goal, job.partial, job.cursor, self.work
            )
            if child is not None:
                self._check_refinement(job.partial, child)
                kind = "bind" if child.missing else "predict"
                self._enqueue(
                    _Job(kind, node, child),
                    _Job("bind", node, job.partial, job.cursor + 1),
                )
        elif job.kind == "backup":
            self._backup(job.edge)
        else:
            self._predict(job)

    @staticmethod
    def _check_refinement(partial, child):
        if type(child) is not Binding or child.schema != partial.schema:
            raise ValueError("refinement must retain its schema")
        before, after = dict(partial.arguments), dict(child.arguments)
        changed = {k for k in after if k not in before or after[k] != before[k]}
        if not set(before) <= set(after) or len(changed) != 1:
            raise ValueError("refinement must bind one hole without changing prior arguments")
        name = next(iter(changed))
        value = after[name]
        parameter = next(p for p in partial.schema.parameters if p.name == name)
        if parameter.structured:
            old = before.get(name, ConstructDraft())
            valid = (
                type(old) is ConstructDraft
                and not old.result
                and (
                    type(value) is ConstructDraft
                    and (
                        not value.result
                        and value.steps[:-1] == old.steps
                        and len(value.steps) == len(old.steps) + 1
                        or value.steps == old.steps
                        and len(value.result) == 1
                    )
                )
            )
            valid = valid or (
                type(old) is ConstructDraft
                and len(old.result) == 1
                and type(value) is not ConstructDraft
                and value == old.result[0]
            )
            if not valid:
                raise ValueError("construction refinement must append one decision, seal or unwrap")
            return
        if name not in before:
            if type(value) is SetDraft:
                valid = len(value.members) == 1
            else:
                valid = not value if parameter.element_type is not None else True
        elif type(before[name]) is SetDraft:
            members = before[name].members
            valid = (
                members < value.members and len(value.members) == len(members) + 1
                if type(value) is SetDraft
                else value == members
            )
        else:
            valid = False
        if not valid:
            raise ValueError("refinement must bind one hole or add one member and finalize it")

    def _predict(self, job):
        node = job.node
        action = Action(job.partial)
        scenario = node.belief.scenarios[job.cursor]
        outcomes = self.model.predict(scenario.state, self.goal, action, self.work)
        if type(outcomes) is Inapplicable:
            return
        if outcomes is None:
            self._cutoffs.add("unmodeled_action")
            return
        if (
            type(outcomes) is not tuple
            or not outcomes
            or any(type(o) is not Outcome for o in outcomes)
        ):
            raise ValueError("prediction must return a bounded outcome tuple or unknown")
        if len(outcomes) > self.limits.outcomes:
            self._cutoffs.add("outcome_limit")
            return
        if sum(o.probability for o in outcomes) != 1:
            raise ValueError("prediction probabilities must sum to one")
        combined = job.outcomes + tuple((scenario.probability * o.probability, o) for o in outcomes)
        if len(combined) > self.limits.scenarios:
            self._cutoffs.add("scenario_limit")
            return
        if job.cursor + 1 < len(node.belief.scenarios):
            self._enqueue(_Job("predict", node, job.partial, job.cursor + 1, combined))
            return
        # Only observed outcomes split the policy. Hidden state and utility do not.
        groups = {}
        for probability, outcome in combined:
            groups.setdefault(outcome.observation, []).append((probability, outcome.state))
        if self.nodes + len(groups) > self.limits.nodes:
            self._halted = "node_limit"
            return
        edge = _Edge(
            node,
            action,
            sum((p * o.utility for p, o in combined), Fraction()),
            len(combined) > 1,
        )
        jobs = []
        for observation, cases in groups.items():
            mass = sum((p for p, _ in cases), Fraction())
            belief = Belief(tuple(Scenario(state, p / mass) for p, state in cases))
            child = _Node(belief, node.depth - 1, edge, family=family(job))
            edge.children.append((observation, mass, child))
            jobs.append(_Job("open", child))
        self.nodes += len(groups)
        self._enqueue(*jobs, focus=len(jobs))

    def _improve(self, node, solution):
        if node.best is not None and solution.value <= node.best.value:
            return
        node.best = solution
        if node.parent is not None:
            self._enqueue(_Job("backup", node.parent.parent, edge=node.parent))

    def _backup(self, edge):
        if any(child.best is None for _, _, child in edge.children):
            return
        plan = Plan(
            edge.action, tuple(Branch(obs, child.best.plan) for obs, _, child in edge.children)
        )
        value = edge.utility + sum(
            (mass * child.best.value for _, mass, child in edge.children), Fraction()
        )
        expectation = edge.expectation or any(c.best.expectation for _, _, c in edge.children)
        self._improve(edge.parent, _Solution(plan, value, expectation))

    def _decision(self, stopped):
        best = self.root.best
        if best is not None:
            status = "ready_intent" if best.plan is not None else "goal_satisfied"
        elif self._halted or stopped == "work_limit":
            status = "search_limited"
        elif self._agenda:
            status = "thinking"
        else:
            status = "no_plan_found"
        plan = None if best is None else best.plan
        estimate = (
            None
            if best is None
            else Estimate(
                best.value, "scenario_expectation" if best.expectation else "exact_under_model"
            )
        )
        return Decision(
            status,
            self.basis,
            None if plan is None else plan.action,
            plan,
            estimate,
            self.work.used,
            self.nodes,
            len(self._agenda),
            not self._agenda and not self._cutoffs and self._halted is None,
            stopped,
            tuple(sorted(self._cutoffs)),
        )
