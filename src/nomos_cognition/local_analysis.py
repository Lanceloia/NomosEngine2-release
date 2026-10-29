"""Compact immutable local conclusions, separate from complete finite models."""

from dataclasses import dataclass

from .analysis import Ground
from .local import Context, Query
from .state import Evidence, Term


@dataclass(frozen=True)
class LocalBound:
    members: tuple[Term, ...]
    category: Term
    minimum: int
    maximum: int
    lower_grounds: tuple[int, ...]
    upper_grounds: tuple[int, ...]

    def __post_init__(self):
        Query(self.members, ())
        if type(self.category) is not Term:
            raise ValueError("local bound needs a nominal category")
        self.category.__post_init__()
        if (
            type(self.minimum) is not int
            or type(self.maximum) is not int
            or not 0 <= self.minimum <= self.maximum <= len(self.members)
        ):
            raise ValueError("invalid published local bounds")


@dataclass(frozen=True)
class LocalAnalysis:
    model: str
    context: Context
    cutoff: int
    grounds: tuple[Ground, ...]
    status: str
    bounds: tuple[LocalBound, ...]
    work: int
    reason: str | None = None
    conflict: tuple[int, ...] = ()

    def __post_init__(self):
        if (
            type(self.model) is not str
            or not self.model
            or type(self.context) is not Context
            or type(self.cutoff) is not int
            or self.cutoff < 0
            or type(self.work) is not int
            or self.work < 0
            or self.status not in ("complete", "conflict", "pending")
            or type(self.grounds) is not tuple
            or type(self.bounds) is not tuple
            or type(self.conflict) is not tuple
            or self.status != "complete"
            and self.bounds
            or self.status == "pending"
            and (type(self.reason) is not str or not self.reason)
            or self.status != "pending"
            and self.reason is not None
            or self.status != "conflict"
            and self.conflict
        ):
            raise ValueError("invalid local analysis")
        self.context.__post_init__()
        for ground in self.grounds:
            if type(ground) is not Ground:
                raise ValueError("local analysis needs actual grounds")
            ground.__post_init__()
            if (ground.evidence.scope, ground.evidence.recipient) != self.context.holder or (
                ground.evidence.occurrence or 0
            ) > self.cutoff:
                raise ValueError("local analysis crosses evidence scopes or frontiers")
        identities = set()
        for bound in self.bounds:
            if type(bound) is not LocalBound:
                raise ValueError("foreign published local bound")
            bound.__post_init__()
            key = (tuple(sorted(repr(t) for t in bound.members)), repr(bound.category))
            if key in identities:
                raise ValueError("duplicate published local bound")
            identities.add(key)
        for indexes in (
            self.conflict,
            *(g for b in self.bounds for g in (b.lower_grounds, b.upper_grounds)),
        ):
            if (
                type(indexes) is not tuple
                or indexes != tuple(sorted(set(indexes)))
                or any(type(i) is not int or not 0 <= i < len(self.grounds) for i in indexes)
            ):
                raise ValueError("local bound cites a foreign ground")


def local_wire(value):
    value.__post_init__()

    def term(t):
        return t.name, t.signature, t.wire

    return (
        value.model,
        (
            value.context.holder,
            value.context.period,
            value.context.assumptions,
            term(value.context.relation),
        ),
        value.cutoff,
        tuple(
            (
                g.input,
                g.kind,
                g.definition,
                g.signature,
                (
                    g.evidence.scope,
                    g.evidence.producer,
                    g.evidence.slot,
                    g.evidence.recipient,
                    g.evidence.occurrence,
                ),
                g.sample,
                tuple((n, term(t)) for n, t in g.parameters),
            )
            for g in value.grounds
        ),
        value.status,
        tuple(
            (
                tuple(term(t) for t in b.members),
                term(b.category),
                b.minimum,
                b.maximum,
                b.lower_grounds,
                b.upper_grounds,
            )
            for b in value.bounds
        ),
        value.work,
        value.reason,
        value.conflict,
    )


def local_from_wire(wire):
    if type(wire) is not tuple or len(wire) != 9:
        raise ValueError("local analysis needs its exact current layout")
    model, context, cutoff, grounds, status, bounds, work, reason, conflict = wire
    if (
        type(context) is not tuple
        or len(context) != 4
        or type(grounds) is not tuple
        or type(bounds) is not tuple
        or any(type(g) is not tuple or len(g) != 7 for g in grounds)
        or any(type(b) is not tuple or len(b) != 6 for b in bounds)
    ):
        raise ValueError("local analysis has an invalid nested layout")
    value = LocalAnalysis(
        model,
        Context(*context[:3], Term(*context[3])),
        cutoff,
        tuple(
            Ground(*g[:4], Evidence(*g[4]), g[5], tuple((n, Term(*t)) for n, t in g[6]))
            for g in grounds
        ),
        status,
        tuple(LocalBound(tuple(Term(*t) for t in b[0]), Term(*b[1]), *b[2:]) for b in bounds),
        work,
        reason,
        conflict,
    )
    value.__post_init__()
    return value
