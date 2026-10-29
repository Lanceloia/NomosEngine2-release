"""Bounded cardinality propagation over personal, nominal classification evidence."""

from collections import Counter
from dataclasses import dataclass

from .analysis import Ground
from .state import Term


def _key(term):
    if type(term) is not Term:
        raise ValueError("local constraints require nominal terms")
    term.__post_init__()
    return term.name, term.signature, repr(term.wire)


def _terms(values, *, unique=True):
    if type(values) is not tuple:
        raise ValueError("local terms require explicit tuples")
    keys = tuple(_key(v) for v in values)
    if unique and len(set(keys)) != len(keys):
        raise ValueError("local sets cannot contain duplicate members")
    if len({k[:2] for k in keys}) > 1:
        raise ValueError("local terms must share a nominal type")
    return tuple(sorted(values, key=_key))


@dataclass(frozen=True)
class Context:
    holder: tuple[str, str]
    period: str
    assumptions: tuple[tuple[str, str], ...]
    relation: Term

    def __post_init__(self):
        if (
            type(self.holder) is not tuple
            or len(self.holder) != 2
            or any(type(v) is not str or not v for v in self.holder)
            or type(self.period) is not str
            or not self.period
            or type(self.assumptions) is not tuple
            or not self.assumptions
            or any(
                type(v) is not tuple or len(v) != 2 or any(type(s) is not str or not s for s in v)
                for v in self.assumptions
            )
            or len(dict(self.assumptions)) != len(self.assumptions)
        ):
            raise ValueError("local context needs holder, period and explicit assumptions")
        _key(self.relation)


def _input(context, ground, members):
    if type(context) is not Context or type(ground) is not Ground:
        raise ValueError("local input requires context and actual provenance")
    context.__post_init__()
    ground.__post_init__()
    if (ground.evidence.scope, ground.evidence.recipient) != context.holder:
        raise ValueError("local evidence belongs to another holder")
    _terms(members)


@dataclass(frozen=True)
class Count:
    context: Context
    ground: Ground
    members: tuple[Term, ...]
    matching: tuple[Term, ...]
    minimum: int
    maximum: int

    def __post_init__(self):
        _input(self.context, self.ground, self.members)
        _terms(self.matching)
        if (
            type(self.minimum) is not int
            or type(self.maximum) is not int
            or not 0 <= self.minimum <= self.maximum <= len(self.members)
        ):
            raise ValueError("invalid local count interval")


@dataclass(frozen=True)
class Allocation:
    context: Context
    ground: Ground
    members: tuple[Term, ...]
    labels: tuple[Term, ...]

    def __post_init__(self):
        _input(self.context, self.ground, self.members)
        _terms(self.labels, unique=False)
        if len(self.members) != len(self.labels):
            raise ValueError("local allocation requires one label per member")


@dataclass(frozen=True)
class Query:
    members: tuple[Term, ...]
    matching: tuple[Term, ...]

    def __post_init__(self):
        _terms(self.members)
        _terms(self.matching)


@dataclass(frozen=True)
class Limits:
    work: int = 100000
    groups: int = 256
    categories: int = 64
    inputs: int = 1024
    subjects: int = 128
    labels: int = 1024

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("local limits must be positive integers")


@dataclass(frozen=True)
class Bound:
    members: tuple[Term, ...]
    matching: tuple[Term, ...]
    minimum: int
    maximum: int
    lower_grounds: tuple[int, ...]
    upper_grounds: tuple[int, ...]


@dataclass(frozen=True)
class Assignment:
    subject: Term
    label: Term
    grounds: tuple[int, ...]


@dataclass(frozen=True)
class Result:
    context: Context
    status: str
    bounds: tuple[Bound, ...]
    assignments: tuple[Assignment, ...]
    grounds: tuple[Ground, ...]
    conflict: tuple[int, ...]
    work: int
    reason: str | None = None

    def bounds_for(self, queries):
        """Resolve a batch against one temporary nominal-key index."""
        if type(queries) is not tuple or any(type(q) is not Query for q in queries):
            raise ValueError("local bound queries require an explicit tuple of Query values")

        def key(members, matching):
            return tuple(map(_key, _terms(members))), tuple(map(_key, _terms(matching)))

        index = {key(b.members, b.matching): b for b in self.bounds}
        return tuple(index.get(key(q.members, q.matching)) for q in queries)

    def bound(self, members, matching):
        members, matching = _terms(members), _terms(matching)
        key = tuple(map(_key, members)), tuple(map(_key, matching))
        return next(
            (
                b
                for b in self.bounds
                if (tuple(map(_key, b.members)), tuple(map(_key, b.matching))) == key
            ),
            None,
        )


class _Budget(Exception):
    pass


class _Conflict(Exception):
    pass


def propagate(context, universe, inputs, queries=(), *, limits=Limits()):
    """Return a sound local fixed point, not a certificate of global satisfiability."""
    if type(context) is not Context or type(limits) is not Limits:
        raise ValueError("local propagation needs context and limits")
    context.__post_init__()
    limits.__post_init__()
    if type(universe) is not tuple or type(inputs) is not tuple or type(queries) is not tuple:
        raise ValueError("local inputs and queries require tuples")
    if any(type(v) not in (Count, Allocation) for v in inputs) or any(
        type(v) is not Query for v in queries
    ):
        raise ValueError("foreign local constraint")
    if len(universe) > limits.subjects or len(inputs) + len(queries) > limits.inputs:
        return Result(context, "pending", (), (), (), (), 0, "input_budget")
    width = sum(len(v.labels if type(v) is Allocation else v.matching) for v in (*inputs, *queries))
    if width > limits.labels:
        return Result(context, "pending", (), (), (), (), 0, "label_budget")
    universe = _terms(universe)
    people = {_key(v): v for v in universe}
    label_type = None
    for item in (*inputs, *queries):
        if type(item) not in (Count, Allocation, Query):
            raise ValueError("foreign local constraint")
        item.__post_init__()
        if type(item) is not Query and item.context != context:
            raise ValueError("local constraints cross holders, periods, assumptions or relations")
        if any(_key(p) not in people for p in item.members):
            raise ValueError("local constraint has an undeclared subject")
        for label in item.labels if type(item) is Allocation else item.matching:
            nominal = _key(label)[:2]
            if label_type is not None and label_type != nominal:
                raise ValueError("local classification has incompatible label types")
            label_type = nominal
    work, grounds = 0, tuple(dict.fromkeys(v.ground for v in inputs))

    def result(status, bounds=(), assignments=(), conflict=(), reason=None):
        return Result(context, status, bounds, assignments, grounds, conflict, work, reason)

    def spend():
        nonlocal work
        if work >= limits.work:
            raise _Budget("work_budget")
        work += 1

    groups, categories, labels = {}, {}, {}

    def group(members):
        spend()
        key = frozenset(_key(v) for v in members)
        if key not in groups:
            if len(groups) >= limits.groups:
                raise _Budget("group_budget")
            groups[key] = tuple(people[k] for k in sorted(key))
        return key

    def category(values):
        spend()
        key = frozenset(_key(v) for v in values)
        if key not in categories:
            if len(categories) >= limits.categories:
                raise _Budget("category_budget")
            categories[key] = _terms(values)
        labels.update((_key(v), v) for v in values)
        return key

    try:
        whole = group(universe)
        for p in universe:
            group((p,))
        for item in (*inputs, *queries):
            group(item.members)
            if type(item) is Allocation:
                for label in item.labels:
                    category((label,))
            else:
                category(item.matching)
        # Generate differences only from requested/input seeds, never recursively all subsets.
        seeds = tuple(groups)
        for s in seeds:
            group(tuple(people[k] for k in whole - s))
            for t in seeds:
                spend()
                if s <= t:
                    group(tuple(people[k] for k in t - s))
        links = []
        for t in groups:
            for s in groups:
                spend()
                if s < t:
                    links.append((t, s, t - s if t - s in groups else None))
        category_links = []
        for left in categories:
            for right in categories:
                spend()
                if left < right or left.isdisjoint(right):
                    category_links.append((left, right, left < right))
        cells = {}
        for g in groups:
            for c in categories:
                spend()
                cells[g, c] = [0, len(g), (), ()]

        changed = False

        def tighten(g, c, low, high, lower=(), upper=(), *, combine=False):
            nonlocal changed
            spend()
            cell = cells[g, c]
            if low > cell[0]:
                cell[0], cell[2], changed = low, proof(*lower) if combine else lower, True
            if high < cell[1]:
                cell[1], cell[3], changed = high, proof(*upper) if combine else upper, True
            if cell[0] > cell[1]:
                raise _Conflict(tuple(sorted(set(cell[2]) | set(cell[3]))))

        def proof(*values):
            return tuple(sorted(set().union(*values)))

        for item in inputs:
            spend()
            g = frozenset(_key(p) for p in item.members)
            origin = (grounds.index(item.ground),)
            if type(item) is Count:
                c = frozenset(_key(v) for v in item.matching)
                tighten(g, c, item.minimum, item.maximum, origin, origin)
            else:
                counts = Counter(_key(v) for v in item.labels)
                for c in categories:
                    count = sum(counts[k] for k in c)
                    tighten(g, c, count, count, origin, origin)
        for g in groups:
            if frozenset() in categories:
                tighten(g, frozenset(), 0, 0)

        while True:
            changed = False
            # One nominal label per subject gives subset and disjoint-category bounds.
            for g in groups:
                for left, right, subset in category_links:
                    a, b = cells[g, left], cells[g, right]
                    if subset:
                        tighten(g, right, a[0], len(g), a[2])
                        tighten(g, left, 0, b[1], upper=b[3])
                    else:
                        tighten(g, left, 0, len(g) - b[0], upper=b[2])
                        tighten(g, right, 0, len(g) - a[0], upper=a[2])
            # A singleton label is an exact classification, not merely a high soft score.
            for p in universe:
                g = frozenset((_key(p),))
                for c in categories:
                    spend()
                    if len(c) == 1 and cells[g, c][0] == 1:
                        origin = cells[g, c][2]
                        for other in categories:
                            value = int(c <= other)
                            tighten(g, other, value, value, origin, origin)
            for c in categories:
                for t, s, r in links:
                    total, left = cells[t, c], cells[s, c]
                    tighten(t, c, left[0], len(t), left[2])
                    tighten(s, c, 0, total[1], upper=total[3])
                    if r is None:
                        continue
                    right = cells[r, c]
                    tighten(
                        t,
                        c,
                        left[0] + right[0],
                        left[1] + right[1],
                        (left[2], right[2]),
                        (left[3], right[3]),
                        combine=True,
                    )
                    tighten(
                        s,
                        c,
                        total[0] - right[1],
                        total[1] - right[0],
                        (total[2], right[3]),
                        (total[3], right[2]),
                        combine=True,
                    )
                    tighten(
                        r,
                        c,
                        total[0] - left[1],
                        total[1] - left[0],
                        (total[2], left[3]),
                        (total[3], left[2]),
                        combine=True,
                    )
            if not changed:
                break
        bounds = tuple(
            Bound(groups[g], categories[c], *cells[g, c]) for g in groups for c in categories
        )
        assignments = tuple(
            Assignment(p, labels[next(iter(c))], cells[frozenset((_key(p),)), c][2])
            for p in universe
            for c in categories
            if len(c) == 1 and cells[frozenset((_key(p),)), c][0] == 1
        )
        return result("complete", bounds, assignments)
    except _Budget as error:
        return result("pending", reason=str(error))
    except _Conflict as error:
        return result("conflict", conflict=error.args[0])
