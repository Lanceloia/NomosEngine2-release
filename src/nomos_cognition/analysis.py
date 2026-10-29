"""Immutable finite analyses with explicit personal grounds and assumptions."""

from dataclasses import dataclass

from .state import Evidence, Term


@dataclass(frozen=True)
class Ground:
    input: str
    kind: str
    definition: str
    signature: str
    evidence: Evidence
    sample: str
    parameters: tuple

    def __post_init__(self):
        if (
            any(type(v) is not str or not v for v in (self.input, self.definition, self.signature))
            or self.kind not in ("fact", "constraint")
            or self.sample not in ("opening", "before", "after")
            or type(self.evidence) is not Evidence
            or type(self.parameters) is not tuple
            or any(
                type(v) is not tuple
                or len(v) != 2
                or type(v[0]) is not str
                or type(v[1]) is not Term
                for v in self.parameters
            )
            or len(dict(self.parameters)) != len(self.parameters)
        ):
            raise ValueError("finite ground has invalid actual input provenance")
        self.evidence.__post_init__()
        if (self.evidence.occurrence is None) != (self.sample == "opening"):
            raise ValueError("finite ground has a foreign sampling phase")
        for _, value in self.parameters:
            value.__post_init__()


@dataclass(frozen=True)
class Conclusion:
    key: Term
    entailed: bool
    possible: bool
    refuted: bool

    def __post_init__(self):
        if (
            type(self.key) is not Term
            or any(type(v) is not bool for v in (self.entailed, self.possible, self.refuted))
            or self.entailed
            and not self.possible
            or self.refuted == self.possible
        ):
            raise ValueError("invalid conditional finite conclusion")
        self.key.__post_init__()


@dataclass(frozen=True)
class Analysis:
    model: str
    holder: tuple
    cutoff: int
    grounds: tuple
    assumptions: tuple
    status: str
    models: tuple
    answers: tuple
    work: int
    reason: str | None = None

    def __post_init__(self):
        if (
            type(self.model) is not str
            or not self.model
            or type(self.holder) is not tuple
            or len(self.holder) != 2
            or any(type(v) is not str or not v for v in self.holder)
            or type(self.cutoff) is not int
            or self.cutoff < 0
            or type(self.grounds) is not tuple
            or any(type(g) is not Ground for g in self.grounds)
            or type(self.assumptions) is not tuple
            or any(
                type(v) is not tuple or len(v) != 2 or any(type(s) is not str or not s for s in v)
                for v in self.assumptions
            )
            or len(dict(self.assumptions)) != len(self.assumptions)
            or self.status not in ("consistent", "inconsistent", "pending")
            or type(self.models) is not tuple
            or any(type(v) is not Term for v in self.models)
            or type(self.answers) is not tuple
            or any(type(v) is not Conclusion for v in self.answers)
            or type(self.work) is not int
            or self.work < 0
            or self.status == "consistent"
            and not self.models
            or self.status != "consistent"
            and (self.models or self.answers)
            or self.status == "pending"
            and (type(self.reason) is not str or not self.reason)
            or self.status != "pending"
            and self.reason is not None
        ):
            raise ValueError("invalid personal finite analysis")
        for ground in self.grounds:
            ground.__post_init__()
            if (ground.evidence.scope, ground.evidence.recipient) != self.holder:
                raise ValueError("finite analysis crosses personal evidence scopes")
            if (ground.evidence.occurrence or 0) > self.cutoff:
                raise ValueError("finite analysis cites future evidence")
        for value in self.models:
            value.__post_init__()
        for answer in self.answers:
            answer.__post_init__()
        if len(set(self.models)) != len(self.models) or len({q.key for q in self.answers}) != len(
            self.answers
        ):
            raise ValueError("finite analysis has duplicate models or queries")


def analysis_wire(value):
    def term(t):
        return t.name, t.signature, t.wire

    value.__post_init__()
    return (
        value.model,
        value.holder,
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
        value.assumptions,
        value.status,
        tuple(term(m) for m in value.models),
        tuple((term(a.key), a.entailed, a.possible, a.refuted) for a in value.answers),
        value.work,
        value.reason,
    )


def analysis_from_wire(wire):
    if type(wire) is not tuple or len(wire) != 10:
        raise ValueError("stored finite analysis needs its exact layout")
    model, holder, cutoff, grounds, assumptions, status, models, answers, work, reason = wire
    return Analysis(
        model,
        holder,
        cutoff,
        tuple(
            Ground(n, k, d, s, Evidence(*e), sample, tuple((p, Term(*t)) for p, t in args))
            for n, k, d, s, e, sample, args in grounds
        ),
        assumptions,
        status,
        tuple(Term(*t) for t in models),
        tuple(Conclusion(Term(*t), a, p, r) for t, a, p, r in answers),
        work,
        reason,
    )
