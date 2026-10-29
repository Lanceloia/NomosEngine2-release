"""Explicit pure-record tags, independent of Subject identity and world authority."""

import json
from dataclasses import dataclass

from nomos_cognition.memory import Context, Episode, Experience, Sample, Source
from nomos_cognition.state import Term

SCHEMA = {
    "Context": (Context, ("domain", "episode")),
    "Source": (Source, ("context", "producer", "channel", "recipient", "message", "occurrence")),
    "Term": (Term, ("name", "signature", "wire")),
    "Episode": (Episode, ("subject", "source", "content", "cues")),
    "Sample": (
        Sample,
        ("key", "revision", "trial", "meaning", "content", "cues", "evidence", "boundaries"),
    ),
    "Experience": (
        Experience,
        (
            "key",
            "revision",
            "domain",
            "context",
            "meaning",
            "cues",
            "support",
            "opposition",
            "samples",
        ),
    ),
}
TAGS = {cls: tag for tag, (cls, _) in SCHEMA.items()}
RECORDS = (Episode, Sample, Experience)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Entry:
    subject: str
    record: Episode | Sample | Experience

    def __post_init__(self):
        if type(self.subject) is not str or not self.subject or type(self.record) not in RECORDS:
            raise ValueError("entry needs a subject and a public memory record")
        if type(self.record) is Episode and self.record.subject != self.subject:
            raise ValueError("episode belongs to another subject")


def plain(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is tuple:
        return [plain(v) for v in value]
    if type(value) is frozenset:
        return {"$set": [plain(v) for v in sorted(value)]}
    tag = TAGS.get(type(value))
    if tag is None:
        raise ValueError("unsupported pure value")
    return {"$type": tag, **{name: plain(getattr(value, name)) for name in SCHEMA[tag][1]}}


def unplain(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is list:
        return tuple(unplain(v) for v in value)
    if type(value) is not dict:
        raise ValueError("unsupported encoded value")
    if set(value) == {"$set"} and type(value["$set"]) is list:
        items = tuple(unplain(v) for v in value["$set"])
        if len(frozenset(items)) != len(items):
            raise ValueError("duplicate set member")
        return frozenset(items)
    tag = value.get("$type")
    if type(tag) is not str or tag not in SCHEMA:
        raise ValueError("unknown record type")
    cls, names = SCHEMA[tag]
    if set(value) != {"$type", *names}:
        raise ValueError("incorrect record fields")
    return cls(*(unplain(value[name]) for name in names))
