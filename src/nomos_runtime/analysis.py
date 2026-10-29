"""Acquire exact issued guarantee inputs for generated personal analyses."""

from dataclasses import dataclass

from .assurances import CheckedConstraint, CheckedFact
from .cognition import ground


class PreparationBudget(Exception):
    pass


class Preparation:
    def __init__(self, limit):
        self.limit, self.work = limit, 0

    def spend(self, amount=1):
        if amount > self.limit - self.work:
            self.work = self.limit
            raise PreparationBudget
        self.work += amount


@dataclass(frozen=True)
class AnalysisInput:
    name: str
    channel: str
    source: str
    type_name: str
    kind: str
    guarantee: str
    signature: str
    parameters: tuple
    history: str
    sample: str
    required: bool
    expose: tuple
    evaluate: object
    dependencies: tuple


@dataclass(frozen=True)
class AcquiredInput:
    definition: AnalysisInput
    ground: object
    values: object


@dataclass(frozen=True)
class SelectedInputs:
    rows: tuple
    cutoff: int
    missing: bool


def select(inputs, actor, receipts):
    rows, missing, cutoff = [], False, 0
    for definition in inputs:
        matches = sorted(
            (
                r
                for r in receipts
                if (r.source, r.channel) == (definition.source, definition.channel)
            ),
            key=lambda r: (r.occurrence or 0, r.source, r.channel),
        )
        if definition.history == "latest":
            matches = matches[-1:]
        for receipt in matches:
            if (
                receipt.recipient != actor
                or receipt.type_name != definition.type_name
                or receipt.sample != definition.sample
            ):
                raise ValueError("analysis receipt has a foreign recipient, type or sample")
            cutoff = max(cutoff, receipt.occurrence or 0)
        missing |= definition.required and not matches
        rows.append((definition, tuple(matches)))
    return SelectedInputs(tuple(rows), cutoff, missing)


def collect(selection, actor, codec, meter):
    from nomos_cognition.analysis import Ground

    selected = []
    for definition, reports in selection.rows:
        for receipt in reports:
            meter.spend()
            carrier = CheckedFact if definition.kind == "fact" else CheckedConstraint
            values = receipt.guarantees if definition.kind == "fact" else receipt.constraints
            claims = tuple(
                claim
                for claim in values
                if type(claim) is carrier
                and (claim.fact if definition.kind == "fact" else claim.definition)
                == definition.guarantee
            )
            if len(claims) != 1 or claims[0].signature != definition.signature:
                raise ValueError("analysis requires its exact issued guarantee signature")
            claim = claims[0]
            if tuple((n, t, s) for n, t, s, _ in claim.arguments) != definition.parameters:
                raise ValueError("analysis guarantee has foreign nominal parameters")
            parameters = tuple(
                (name, codec.term(kind, value)) for name, kind, _, value in claim.arguments
            )
            evidence = ground(actor, receipt)
            basis = Ground(
                definition.name,
                definition.kind,
                definition.guarantee,
                definition.signature,
                evidence,
                receipt.sample,
                parameters,
            )
            selected.append(
                AcquiredInput(definition, basis, {n: codec.value(t) for n, t in parameters})
            )
    return tuple(selected)


def expose(selection, acquired, codec):
    environment = {}
    for definition, _ in selection.rows:
        matches = tuple(row for row in acquired if row.definition is definition)
        for parameter, alias, kind in definition.expose:
            environment[alias] = codec.validate(kind, tuple(v.values[parameter] for v in matches))
    return environment


def ordered(value):
    from .ordering import canonical

    return tuple(sorted(value, key=canonical)) if type(value) is frozenset else tuple(value)


def budget_error(error):
    return error.diagnostic.code in {"ExpressionBudget", "ValueBudget"}
