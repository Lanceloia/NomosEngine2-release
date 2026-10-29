"""Aggregate search work without retaining candidate values or changing model budgets."""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseStatistics:
    family: str | None
    phase: str
    first_work: int
    calls: int
    completed: int
    interrupted: int
    failures: int
    work: int
    elapsed_ns: int | None


@dataclass(frozen=True)
class SearchStatistics:
    starting_work: int
    current_work: int
    families: tuple[str, ...]
    phases: tuple[PhaseStatistics, ...]
    pending: tuple[tuple[str | None, str, int], ...]
    service_quanta: tuple[tuple[str, str, int], ...]


def family(job):
    if job.node.family is not None:
        return job.node.family
    if job.partial is not None:
        return job.partial.schema.name
    edge = job.edge if job.edge is not None else job.node.parent
    if edge is None:
        return None
    return edge.parent.family or edge.action.binding.schema.name


class Diagnostics:
    def __init__(self, profile):
        self.profile = profile
        self.starting_work = None
        self.families = {}
        self.phases = {}

    def register(self, name):
        self.families.setdefault(name, None)

    def record(self, job, before, after, status, elapsed):
        key = family(job), job.kind
        if key not in self.phases:
            self.phases[key] = [before, 0, 0, 0, 0, 0, 0 if self.profile else None]
        row = self.phases[key]
        row[1] += 1
        row[{"completed": 2, "interrupted": 3, "failed": 4}[status]] += 1
        row[5] += after - before
        if self.profile:
            row[6] += elapsed

    def snapshot(self, work, jobs, quanta):
        pending = Counter((family(job), job.kind) for job in jobs)
        return SearchStatistics(
            work if self.starting_work is None else self.starting_work,
            work,
            tuple(self.families),
            tuple(PhaseStatistics(*key, *row) for key, row in self.phases.items()),
            tuple((name, phase, count) for (name, phase), count in pending.items()),
            tuple((name, phase, amount) for (name, phase), amount in quanta.items()),
        )
