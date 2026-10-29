"""Prepared member domains and one-member subset refinements, without combination lists."""

from dataclasses import dataclass

from nomos_cognition.planning.guidance import Ordering
from nomos_cognition.planning.values import Binding, SetDraft

from .ordering import canonical


@dataclass(frozen=True)
class SubsetDomain:
    pool: frozenset
    minimum: int
    maximum: int


@dataclass(frozen=True)
class BindingPreparation:
    members: int
    guided: bool
    scored: int
    ordered: int
    ready: bool
    prefix_requests: int
    prefix_reused: int
    prefixes: int


class BindingChoices:
    def __init__(self, field, domain, work, *, priority=None, exploration=3):
        subset = type(domain) is SubsetDomain
        pool = domain.pool if subset else domain
        work.spend(max(1, len(pool)))
        self.field, self.pool = field, tuple(sorted(pool, key=canonical))
        self.priorities = ()
        self._ordering = (
            None if priority is None else Ordering(self.pool, priority, exploration=exploration)
        )
        self.prepared = priority is None
        self.bounds = (domain.minimum, domain.maximum) if subset else None
        self.ranks = {}
        self._prefixes = {}
        self._prefix_requests = self._prefix_reused = 0
        if self.prepared and subset:
            self.ranks = {value: index for index, value in enumerate(self.pool)}

    def preparation(self):
        ordering = self._ordering
        return BindingPreparation(
            len(self.pool),
            ordering is not None,
            0 if ordering is None else len(ordering.scores),
            len(self.pool) if ordering is None else len(ordering.ordered),
            self.prepared,
            self._prefix_requests,
            self._prefix_reused,
            len(self._prefixes),
        )

    def _start(self, members, work):
        work.spend()
        self._prefix_requests += 1
        if not members:
            return 0
        key = id(members)
        previous = self._prefixes.get(key)
        if previous is not None:
            self._prefix_reused += 1
            return previous[1]
        work.spend(len(members))
        start = max(self.ranks[value] for value in members) + 1
        # Keep the exact set alive so a later draft cannot reuse its identity key.
        self._prefixes[key] = members, start
        return start

    def at(self, partial, cursor, work):
        if not self.prepared:
            self.pool, self.priorities = self._ordering.finish(work)
            if self.bounds is not None:
                self.ranks = {value: index for index, value in enumerate(self.pool)}
            self.prepared = True
        work.spend()
        arguments = dict(partial.arguments)
        if self.bounds is None:
            if cursor >= len(self.pool):
                return None
            arguments[self.field] = self.pool[cursor]
        else:
            minimum, maximum = self.bounds
            draft = arguments.get(self.field)
            members = frozenset() if draft is None else draft.members
            start = self._start(members, work)
            # Finalizing and adding one member are separate, budgeted refinements.
            if minimum <= len(members) <= maximum:
                if cursor == 0:
                    arguments[self.field] = members
                    return Binding(partial.schema, tuple(arguments.items()))
                cursor -= 1
            index = start + cursor
            if (
                len(members) >= maximum
                or index >= len(self.pool)
                or len(members) + len(self.pool) - index < minimum
            ):
                return None
            arguments[self.field] = SetDraft(members | {self.pool[index]})
        return Binding(partial.schema, tuple(arguments.items()))
