"""Transactional current-record postings and lazy inputs to the shared recall policy."""

from types import SimpleNamespace

from nomos_cognition.memory import Context, Sample, Source
from nomos_cognition.recall_index import (
    _experience_cues,
    _experience_samples,
    _sample_cues,
    _sample_results,
)

from .records import dumps

SCHEMA = """
CREATE TABLE recall_sizes(name TEXT NOT NULL, bucket TEXT NOT NULL,
                          size INTEGER NOT NULL CHECK(size>0), PRIMARY KEY(name,bucket));
CREATE TABLE recall_members(name TEXT NOT NULL, bucket TEXT NOT NULL, member TEXT NOT NULL,
                            PRIMARY KEY(name,bucket,member));
CREATE TABLE recall_episodes(name TEXT NOT NULL, bucket TEXT NOT NULL, ordinal INTEGER NOT NULL,
                             position INTEGER NOT NULL, source INTEGER NOT NULL REFERENCES episodes,
                             PRIMARY KEY(name,bucket,ordinal));
CREATE TABLE record_heads(kind TEXT NOT NULL, key TEXT NOT NULL,
                         identity INTEGER NOT NULL REFERENCES revisions,
                         first_position INTEGER NOT NULL, PRIMARY KEY(kind,key));
"""


def _key(value):
    if type(value) is Context:
        return ["context", value.domain, value.episode]
    if type(value) is Source:
        return [
            "source",
            _key(value.context),
            value.producer,
            value.channel,
            value.recipient,
            value.message,
            _key(value.occurrence),
        ]
    if type(value) is tuple:
        return ["tuple", *map(_key, value)]
    if type(value) is int:
        return ["int", format(value, "x")]
    if value is None or type(value) is str:
        return value
    raise ValueError("unsupported recall posting key")


def _size(db, name, bucket):
    row = db.execute(
        "SELECT size FROM recall_sizes WHERE name=? AND bucket=?", (name, bucket)
    ).fetchone()
    return 0 if row is None else row[0]


def _resize(db, name, bucket, delta):
    size = _size(db, name, bucket) + delta
    if size:
        db.execute(
            "INSERT INTO recall_sizes VALUES(?,?,?) "
            "ON CONFLICT(name,bucket) DO UPDATE SET size=excluded.size",
            (name, bucket, size),
        )
    else:
        db.execute("DELETE FROM recall_sizes WHERE name=? AND bucket=?", (name, bucket))


def index_episode(db, episode, identity, position):
    context = episode.source.context
    for name, key in (
        ("episode_context", context),
        *(("episode_cue", (context, cue)) for cue in episode.cues),
    ):
        bucket = dumps(_key(key))
        ordinal = _size(db, name, bucket)
        db.execute(
            "INSERT INTO recall_episodes VALUES(?,?,?,?,?)",
            (name, bucket, ordinal, position, identity),
        )
        _resize(db, name, bucket, 1)


def index_revision(db, previous, current, identity):
    if type(current) is Sample:
        kind, fields = (
            "sample",
            (("sample_cues", _sample_cues), ("sample_results", _sample_results)),
        )
    else:
        kind, fields = (
            "experience",
            (
                ("experience_cues", _experience_cues),
                ("experience_samples", _experience_samples),
            ),
        )
    for name, keys in fields:
        before, after = keys(previous), keys(current)
        for removed, values in ((True, before - after), (False, after - before)):
            for key in values:
                bucket = dumps(_key(key))
                if removed:
                    db.execute(
                        "DELETE FROM recall_members WHERE name=? AND bucket=? AND member=?",
                        (name, bucket, current.key),
                    )
                else:
                    db.execute(
                        "INSERT INTO recall_members VALUES(?,?,?)", (name, bucket, current.key)
                    )
                _resize(db, name, bucket, -1 if removed else 1)
    db.execute(
        "INSERT INTO record_heads VALUES(?,?,?,?) "
        "ON CONFLICT(kind,key) DO UPDATE SET identity=excluded.identity",
        (kind, current.key, identity, identity),
    )


class _Members:
    def __init__(self, db, name, bucket, size):
        self.db, self.name, self.bucket, self.size = db, name, bucket, size

    def __len__(self):
        return self.size

    def __iter__(self):
        # select_records pays the stored cardinality before requesting members.
        return (
            row[0]
            for row in self.db.execute(
                "SELECT member FROM recall_members WHERE name=? AND bucket=?",
                (self.name, self.bucket),
            )
        )


class _EpisodeRow:
    def __init__(self, view, position, identity):
        self.view, self.position, self.identity = view, position, identity

    def __getitem__(self, index):
        if index == 0:
            return self.position
        if index == 1:
            return self.view._episode(self.identity)
        raise IndexError(index)


class _EpisodeRows(_Members):
    def __getitem__(self, index):
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        row = self.db.execute(
            "SELECT position,source FROM recall_episodes WHERE name=? AND bucket=? AND ordinal=?",
            (self.name, self.bucket, index),
        ).fetchone()
        if row is None:
            raise ValueError("missing episode posting")
        return _EpisodeRow(self.view, *row)


class _Postings:
    def __init__(self, view, name, *, episodes=False):
        self.view, self.name, self.episodes = view, name, episodes

    def __bool__(self):
        return (
            self.view.db.execute(
                "SELECT 1 FROM recall_sizes WHERE name=? LIMIT 1", (self.name,)
            ).fetchone()
            is not None
        )

    def get(self, key, default=None):
        bucket = dumps(_key(key))
        size = _size(self.view.db, self.name, bucket)
        if not size:
            return default
        rows = (_EpisodeRows if self.episodes else _Members)(self.view.db, self.name, bucket, size)
        if self.episodes:
            rows.view = self.view
        return rows


class _Records:
    def __init__(self, view, kind, *, position=False):
        self.view, self.kind, self.position = view, kind, position

    def __getitem__(self, key):
        row = self.view.db.execute(
            "SELECT identity,first_position FROM record_heads WHERE kind=? AND key=?",
            (self.kind, key),
        ).fetchone()
        if row is None:
            raise KeyError(key)
        if self.position:
            return row[1] if self.kind == "sample" else row[0]
        return self.view._record(row[0])


class _Episodes:
    def __init__(self, view):
        self.view = view

    def __getitem__(self, source):
        return self.view.episode(source)


class RecallInputs:
    """Reader-local maps, not a Memory or a grant of trusted appraisal provenance."""

    def __init__(self, view):
        self.subject = view.subject
        self.version = view.db.execute("SELECT version FROM metadata").fetchone()[0]
        self._record_index = SimpleNamespace(
            **{
                name: _Postings(view, name)
                for name in (
                    "sample_cues",
                    "sample_results",
                    "experience_cues",
                    "experience_samples",
                )
            },
            sample_positions=_Records(view, "sample", position=True),
        )
        self._samples = _Records(view, "sample")
        self._latest = _Records(view, "experience")
        self._experience_positions = _Records(view, "experience", position=True)
        self._sources = _Episodes(view)
        self._episode_contexts = _Postings(view, "episode_context", episodes=True)
        self._episode_cues = _Postings(view, "episode_cue", episodes=True)
