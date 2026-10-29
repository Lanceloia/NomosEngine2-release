"""Detached indexed decision reads and content-bound exact explanation receipts."""

from dataclasses import dataclass
from hashlib import sha256

from nomos_cognition.memory import Recall, RecallLimits, RecallQuery, Source, _recall_from

from .index import RecallInputs
from .records import SCHEMA, TAGS, dumps


class _ReceiptValues:
    """Encode the existing checksum tree once per immutable object, within one receipt."""

    def __init__(self):
        self.memo = {}

    def encode(self, value):
        cls = type(value)
        if value is None or cls in (bool, str):
            return value
        if cls is int:
            return {"integer": format(value, "x")}
        cached = self.memo.get(id(value))
        if cached is not None and cached[0] is value:
            return cached[1]
        if cls is tuple:
            result = [self.encode(item) for item in value]
        elif cls is frozenset:
            result = {"$set": [self.encode(item) for item in sorted(value)]}
        else:
            tag = TAGS.get(cls)
            if tag is None:
                raise ValueError("unsupported pure value")
            result = {
                "$type": tag,
                **{name: self.encode(getattr(value, name)) for name in SCHEMA[tag][1]},
            }
        self.memo[id(value)] = value, result
        return result


def _digest(recalled):
    # The original pure-record codec supplies explicit nominal type/field tags;
    # hex scalars retain arbitrary integers and distinguish bool from int.
    body = (
        recalled.query.subject,
        recalled.query.context,
        tuple(sorted(recalled.query.past, key=lambda c: (c.domain, c.episode))),
        tuple(sorted(recalled.query.cues)),
        recalled.version,
        recalled.status,
        recalled.reason,
        recalled.work,
        recalled.episodes,
        recalled.experiences,
        recalled.grounds,
        recalled.samples,
    )
    return sha256(dumps(_ReceiptValues().encode(body)).encode()).hexdigest()


@dataclass(frozen=True)
class RecallReceipt:
    """Pure exact locators plus a checksum, not authentication or Subject authority."""

    query: RecallQuery
    version: int
    episodes: tuple[Source, ...]
    experiences: tuple[tuple[str, int], ...]
    grounds: tuple[Source, ...]
    status: str
    reason: str | None
    work: int
    samples: tuple[tuple[str, int], ...]
    digest: str

    def __post_init__(self):
        if (
            type(self.query) is not RecallQuery
            or type(self.version) is not int
            or self.version < 0
            or type(self.work) is not int
            or self.work < 0
            or self.status not in ("complete", "limited")
            or (self.status == "complete" and self.reason is not None)
            or (self.status == "limited" and self.reason not in ("work", "items", "grounds"))
            or type(self.digest) is not str
            or len(self.digest) != 64
            or any(c not in "0123456789abcdef" for c in self.digest)
        ):
            raise ValueError("invalid recall receipt")
        for values in (self.episodes, self.grounds):
            if type(values) is not tuple or any(type(v) is not Source for v in values):
                raise ValueError("recall receipt requires full Source locators")
        for values in (self.samples, self.experiences):
            if type(values) is not tuple or any(
                type(v) is not tuple
                or len(v) != 2
                or type(v[0]) is not str
                or not v[0]
                or type(v[1]) is not int
                or v[1] < 1
                for v in values
            ):
                raise ValueError("recall receipt requires exact revision locators")


@dataclass(frozen=True)
class DecisionRead:
    recalled: Recall
    receipt: RecallReceipt


def read_recall(view, query, *, limits=None):
    if limits is None:
        limits = RecallLimits()
    recalled = _recall_from(RecallInputs(view), query, limits=limits)
    return DecisionRead(recalled, receipt_for(recalled))


def receipt_for(recalled):
    if type(recalled) is not Recall:
        raise ValueError("a Recall is required")
    return RecallReceipt(
        recalled.query,
        recalled.version,
        tuple(e.source for e in recalled.episodes),
        tuple((e.key, e.revision) for e in recalled.experiences),
        tuple(e.source for e in recalled.grounds),
        recalled.status,
        recalled.reason,
        recalled.work,
        tuple(s.reference for s in recalled.samples),
        _digest(recalled),
    )


def explain(view, receipt):
    if type(receipt) is not RecallReceipt or receipt.query.subject != view.subject:
        raise ValueError("explanation requires this subject's recall receipt")

    def records(kind, references):
        values = tuple(view.get(kind, key, revision) for key, revision in references)
        if any(value is None for value in values):
            raise ValueError("missing explanation revision")
        return values

    recalled = Recall(
        receipt.query,
        receipt.version,
        tuple(view.episode(s) for s in receipt.episodes),
        records("experience", receipt.experiences),
        tuple(view.episode(s) for s in receipt.grounds),
        receipt.status,
        receipt.reason,
        receipt.work,
        records("sample", receipt.samples),
    )
    if _digest(recalled) != receipt.digest:
        raise ValueError("explanation records or receipt differ from the captured content")
    return recalled
