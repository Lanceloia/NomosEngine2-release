"""Bounded Session-local reuse of fully prepared pure cardinality calculations."""

from collections import OrderedDict
from dataclasses import fields

from nomos_cognition.analysis import Ground
from nomos_cognition.local import Allocation, Context, Count, Limits, Query
from nomos_cognition.state import Evidence, Term

_FIELDS = {
    kind: tuple(f.name for f in fields(kind))
    for kind in (Allocation, Context, Count, Limits, Query, Ground, Evidence, Term)
}


class _Uncacheable(Exception):
    pass


def _identity(values):
    nodes, characters = 4096, 65536

    def visit(value, depth=0):
        nonlocal nodes, characters
        nodes -= 1
        if nodes < 0 or depth > 64:
            raise _Uncacheable
        kind = type(value)
        if kind is str:
            characters -= len(value)
            if characters < 0:
                raise _Uncacheable
            return kind, value
        if kind in (int, bool, type(None)):
            return kind, value
        if kind is tuple:
            return kind, tuple(visit(child, depth + 1) for child in value)
        if kind in _FIELDS:
            return kind, tuple(visit(getattr(value, f), depth + 1) for f in _FIELDS[kind])
        raise _Uncacheable

    try:
        return visit(values)
    except _Uncacheable:
        return None


class LocalCalculation:
    """Retain at most eight holders' latest small complete result; never cache admission."""

    def __init__(self):
        self.latest = OrderedDict()

    def run(self, compute, context, universe, inputs, queries, *, limits):
        identity = _identity((context, universe, inputs, queries, limits))
        holder = context.holder
        key = compute, identity
        previous = self.latest.get(holder)
        if identity is not None and previous is not None and previous[0] == key:
            self.latest.move_to_end(holder)
            return previous[1]
        # An intervening uncacheable/failed calculation also retires the old snapshot.
        self.latest.pop(holder, None)
        result = compute(context, universe, inputs, queries, limits=limits)
        if identity is not None and result.status == "complete" and len(result.bounds) <= 1024:
            self.latest[holder] = key, result
            if len(self.latest) > 8:
                self.latest.popitem(last=False)
        return result
