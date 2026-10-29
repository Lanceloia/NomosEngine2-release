"""Bounded traversal of recipient-owned sample and summary dependency postings."""

from collections import deque
from dataclasses import dataclass


class _Limit(Exception):
    pass


class _Meter:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def spend(self, amount=1):
        if amount > self.limit - self.used:
            raise _Limit
        self.used += amount


@dataclass(frozen=True)
class RecordSelection:
    samples: tuple
    experiences: tuple
    work: int
    complete: bool


def select_records(index, samples, experiences, positions, query, allowed, *, work_limit):
    if not index.sample_cues and not index.experience_cues:
        return RecordSelection((), (), 0, True)
    meter = _Meter(work_limit)
    selected_samples, selected_experiences = {}, {}
    examined_samples, examined_experiences, result_groups = set(), set(), set()
    pending = deque()

    def sample(key):
        if key in examined_samples:
            return
        meter.spend()
        examined_samples.add(key)
        value = samples[key]
        if value.trial.context in allowed:
            selected_samples[key] = value
            pending.append(("sample", key))

    def experience(key):
        if key in examined_experiences:
            return
        meter.spend()
        examined_experiences.add(key)
        value = experiences[key]
        if value.domain != query.context.domain or value.context not in (None, query.context):
            return
        meter.spend(len(value.grounds))
        if all(source.context in allowed for source in value.grounds):
            selected_experiences[key] = value
            pending.append(("experience", key))

    def members(postings, key, include):
        meter.spend()
        values = postings.get(key, ())
        if values:
            # Pay before sorting/materializing a whole posting; no hidden prefix work.
            meter.spend(len(values))
            for member in sorted(values):
                include(member)

    try:
        if index.sample_cues:
            for context in allowed:
                for cue in query.cues:
                    members(index.sample_cues, (context, cue), sample)
        if index.experience_cues:
            for context in (None, query.context):
                for cue in query.cues:
                    members(index.experience_cues, (query.context.domain, context, cue), experience)
        while pending:
            kind, key = pending.popleft()
            if kind == "experience":
                value = selected_experiences[key]
                meter.spend(len(value.samples))
                for reference, _ in value.samples:
                    sample(reference)
            else:
                value = selected_samples[key]
                meter.spend(len(value.weight_sources))
                for source in value.weight_sources:
                    group = value.content.name, value.content.signature, source.publication
                    if group not in result_groups:
                        members(index.sample_results, group, sample)
                        result_groups.add(group)
                if index.experience_samples:
                    for context in (None, query.context):
                        members(
                            index.experience_samples,
                            (query.context.domain, context, key),
                            experience,
                        )
        meter.spend(len(selected_samples) + len(selected_experiences))
        return RecordSelection(
            tuple(
                selected_samples[key]
                for key in sorted(
                    selected_samples, key=index.sample_positions.__getitem__, reverse=True
                )
            ),
            tuple(
                selected_experiences[key]
                for key in sorted(selected_experiences, key=positions.__getitem__, reverse=True)
            ),
            meter.used,
            True,
        )
    except _Limit:
        return RecordSelection((), (), meter.used, False)
