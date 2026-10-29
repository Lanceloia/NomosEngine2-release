"""Immutable decoded samples and ordered summary groups, local to a Memory lineage."""

from bisect import bisect_left
from dataclasses import dataclass, field, replace

from pyrsistent import PMap, PVector, pmap, pvector


@dataclass(frozen=True)
class DecodedSample:
    sample: object
    case: tuple | None
    work: int
    position: int
    group: str | None

    @property
    def summary_work(self):
        return len(self.case[1]) + 1 + len(self.sample.evidence) + len(self.sample.boundaries)


@dataclass(frozen=True)
class SummaryGroup:
    features: tuple
    target: object
    origin: object
    members: PMap = field(default_factory=pmap)
    order: PVector = field(default_factory=pvector)
    totals: PMap = field(default_factory=pmap)
    count: int = 0
    work: int = 1
    first: int = 0

    def changed(self, position, slot):
        old = self.members.get(position)
        count = self.count - (old is not None) + (slot is not None)
        if not count:
            return None
        work, totals = self.work, self.totals
        for item, sign in ((old, -1), (slot, 1)):
            if item is None:
                continue
            work += sign * item.summary_work
            for axis, value in item.case[1]:
                total, observations = totals.get(axis, (0, 0))
                total, observations = total + sign * value, observations + sign
                totals = (
                    totals.set(axis, (total, observations)) if observations else totals.remove(axis)
                )
        order = self.order
        if position not in self.members:
            if not order or position > order[-1]:
                order = order.append(position)
            else:
                at = bisect_left(order, position)
                order = order[:at].append(position).extend(order[at:])
        members = self.members.set(position, slot)
        first = next(p for p in order if members[p] is not None)
        return replace(
            self, members=members, order=order, totals=totals, count=count, work=work, first=first
        )

    def samples(self):
        return tuple(self.members[p].sample for p in self.order if self.members[p] is not None)

    def summary(self):
        return tuple((axis, *self.totals[axis]) for axis in sorted(self.totals))


@dataclass(frozen=True)
class ConsolidationIndex:
    sample_cursor: int = 0
    experience_cursor: int = 0
    slots: PMap = field(default_factory=pmap)
    groups: PMap = field(default_factory=pmap)
    outputs: PMap = field(default_factory=pmap)

    def changed(self, sample, case, work, key):
        old = self.slots.get(sample.key)
        position = len(self.slots) if old is None else old.position
        slot = DecodedSample(sample, case, work, position, key)
        groups = self.groups
        if old is not None and old.group is not None and old.group != key:
            group = groups[old.group].changed(position, None)
            groups = groups.remove(old.group) if group is None else groups.set(old.group, group)
        if key is not None:
            group = groups.get(key)
            if group is None:
                group = SummaryGroup(case[0], case[2], sample.trial.context)
            groups = groups.set(key, group.changed(position, slot))
        return replace(self, slots=self.slots.set(sample.key, slot), groups=groups)
