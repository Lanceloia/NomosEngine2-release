"""Exact relational memory values; file contents never grant Subject restoration."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

from nomos_cognition.memory import (
    Context,
    Episode,
    Experience,
    Memory,
    Sample,
    Source,
    _next_experience,
    _next_sample,
    _same_record,
)
from nomos_cognition.state import Term

from .index import SCHEMA as INDEX_SCHEMA
from .index import index_episode, index_revision
from .records import Entry, dumps

SCHEMA = """
CREATE TABLE metadata(subject TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                      episodes INTEGER NOT NULL DEFAULT 0, samples INTEGER NOT NULL DEFAULT 0,
                      experiences INTEGER NOT NULL DEFAULT 0);
CREATE TABLE contexts(id INTEGER PRIMARY KEY, domain TEXT NOT NULL, episode TEXT NOT NULL,
                      UNIQUE(domain, episode));
CREATE TABLE sources(id INTEGER PRIMARY KEY, context INTEGER NOT NULL REFERENCES contexts,
                     producer TEXT NOT NULL, channel TEXT NOT NULL, recipient TEXT NOT NULL,
                     message TEXT NOT NULL, occurrence TEXT);
CREATE UNIQUE INDEX source_identity ON sources(
    context, producer, channel, recipient, message, ifnull(occurrence, ''));
CREATE TABLE terms(id INTEGER PRIMARY KEY, body TEXT NOT NULL UNIQUE);
CREATE TABLE episodes(source INTEGER PRIMARY KEY REFERENCES sources,
                      position INTEGER NOT NULL UNIQUE, content INTEGER NOT NULL REFERENCES terms,
                      cues TEXT NOT NULL);
CREATE TABLE revisions(id INTEGER PRIMARY KEY,
                       kind TEXT NOT NULL CHECK(kind IN ('sample','experience')),
                       key TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
                       header TEXT NOT NULL, position INTEGER NOT NULL,
                       UNIQUE(kind, key, revision), UNIQUE(kind,position));
CREATE TABLE recall_receipts(id INTEGER PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE source_links(kind TEXT NOT NULL, key TEXT NOT NULL, field TEXT NOT NULL,
                          position INTEGER NOT NULL, from_revision INTEGER NOT NULL,
                          to_revision INTEGER, target INTEGER NOT NULL REFERENCES episodes(source),
                          CHECK(to_revision IS NULL OR to_revision > from_revision),
                          PRIMARY KEY(kind,key,field,position,from_revision));
CREATE UNIQUE INDEX current_source_link ON source_links(kind,key,field,position)
    WHERE to_revision IS NULL;
CREATE INDEX source_revision_lookup ON source_links(kind,key,field,from_revision,to_revision);
CREATE TABLE sample_links(kind TEXT NOT NULL CHECK(kind='experience'), key TEXT NOT NULL,
                          field TEXT NOT NULL CHECK(field='samples'), position INTEGER NOT NULL,
                          from_revision INTEGER NOT NULL, to_revision INTEGER,
                          target INTEGER NOT NULL REFERENCES revisions,
                          CHECK(to_revision IS NULL OR to_revision > from_revision),
                          PRIMARY KEY(kind,key,field,position,from_revision));
CREATE UNIQUE INDEX current_sample_link ON sample_links(kind,key,field,position)
    WHERE to_revision IS NULL;
CREATE INDEX sample_revision_lookup ON sample_links(kind,key,field,from_revision,to_revision);
PRAGMA user_version=3;
"""


def _wire(value):
    if value is None or type(value) in (bool, str):
        return value
    if type(value) is int:
        return {"int": format(value, "x")}
    if type(value) is tuple:
        return [_wire(item) for item in value]
    raise ValueError("unsupported term wire")


def _unwire(value):
    if value is None or type(value) in (bool, str):
        return value
    if type(value) is list:
        return tuple(_unwire(item) for item in value)
    if type(value) is dict and set(value) == {"int"} and type(value["int"]) is str:
        number = int(value["int"], 16)
        if format(number, "x") == value["int"]:
            return number
    raise ValueError("invalid term wire")


class RevisionView:
    """One read transaction and its local decoding memo; no cross-query mutable cache."""

    def __init__(self, db, subject):
        self.db, self.subject = db, subject
        self._contexts, self._sources, self._terms, self._records = {}, {}, {}, {}
        self._revision_ids = {}
        self._episodes = {}

    def _context(self, identity):
        if identity is None:
            return None
        if identity not in self._contexts:
            row = self.db.execute(
                "SELECT domain,episode FROM contexts WHERE id=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("missing context")
            self._contexts[identity] = Context(*row)
        return self._contexts[identity]

    def _source(self, identity):
        if identity not in self._sources:
            row = self.db.execute(
                "SELECT context,producer,channel,recipient,message,occurrence "
                "FROM sources WHERE id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise ValueError("missing source")
            occurrence = None if row[5] is None else int(row[5], 16)
            self._sources[identity] = Source(self._context(row[0]), *row[1:5], occurrence)
        return self._sources[identity]

    def _term(self, identity):
        if identity not in self._terms:
            row = self.db.execute("SELECT body FROM terms WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise ValueError("missing term")
            name, signature, wire = json.loads(row[0])
            self._terms[identity] = Term(name, signature, _unwire(wire))
        return self._terms[identity]

    def _links(self, table, kind, key, field, revision):
        rows = self.db.execute(
            f"SELECT position,target FROM {table} WHERE kind=? AND key=? AND field=? "
            "AND from_revision<=? AND (to_revision IS NULL OR to_revision>?) ORDER BY position",
            (kind, key, field, revision, revision),
        ).fetchall()
        if any(position != index for index, (position, _) in enumerate(rows)):
            raise ValueError("non-contiguous revision links")
        return tuple(target for _, target in rows)

    def _record(self, identity):
        if identity in self._records:
            return self._records[identity]
        row = self.db.execute(
            "SELECT kind,key,revision,header FROM revisions WHERE id=?", (identity,)
        ).fetchone()
        if row is None:
            raise ValueError("missing revision")
        kind, key, revision, encoded = row
        header = json.loads(encoded)

        def sources(field):
            return tuple(
                self._source(i) for i in self._links("source_links", kind, key, field, revision)
            )

        if kind == "sample":
            trial, meaning, content, cues = header
            value = Sample(
                key,
                revision,
                self._source(trial),
                self._term(meaning),
                self._term(content),
                frozenset(cues),
                sources("evidence"),
                sources("boundaries"),
            )
        elif kind == "experience":
            domain, context, meaning, cues = header
            samples = []
            for sample_identity in self._links("sample_links", kind, key, "samples", revision):
                sample = self.db.execute(
                    "SELECT key,revision FROM revisions WHERE id=? AND kind='sample'",
                    (sample_identity,),
                ).fetchone()
                if sample is None:
                    raise ValueError("experience references a missing or non-sample revision")
                samples.append(sample)
            value = Experience(
                key,
                revision,
                domain,
                self._context(context),
                self._term(meaning),
                frozenset(cues),
                sources("support"),
                sources("opposition"),
                tuple(samples),
            )
        else:
            raise ValueError("unknown revision kind")
        self._records[identity] = value
        return value

    def get(self, kind, key, revision=None):
        if kind not in ("sample", "experience") or type(key) is not str or not key:
            raise ValueError("typed revision key required")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("positive revision required")
        identity = self._revision_id(kind, key, revision)
        return None if identity is None else self._record(identity)

    def _episode(self, identity):
        if identity not in self._episodes:
            row = self.db.execute(
                "SELECT content,cues FROM episodes WHERE source=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("missing retained episode")
            self._episodes[identity] = Episode(
                self.subject,
                self._source(identity),
                self._term(row[0]),
                frozenset(json.loads(row[1])),
            )
        return self._episodes[identity]

    def _source_id(self, source):
        if type(source) is not Source:
            raise ValueError("episode lookup requires a full Source")
        row = self.db.execute(
            "SELECT sources.id FROM sources JOIN contexts ON sources.context=contexts.id "
            "WHERE domain=? AND episode=? AND producer=? AND channel=? AND recipient=? "
            "AND message=? AND ifnull(occurrence,'')=?",
            (
                source.context.domain,
                source.context.episode,
                source.producer,
                source.channel,
                source.recipient,
                source.message,
                "" if source.occurrence is None else format(source.occurrence, "x"),
            ),
        ).fetchone()
        if row is None:
            raise ValueError("missing retained episode")
        return row[0]

    def episode(self, source):
        return self._episode(self._source_id(source))

    def recall(self, query, *, limits=None):
        """Read the current transaction's indexed recall and its exact explanation receipt."""
        from .reads import read_recall

        return read_recall(self, query, limits=limits)

    def explain(self, receipt):
        """Reopen only the receipt's exact records, never today's latest substitutes."""
        from .reads import explain

        return explain(self, receipt)

    def _revision_id(self, kind, key, revision):
        cached = self._revision_ids.get((kind, key, revision))
        if cached is not None:
            return cached
        sql, args = "SELECT id FROM revisions WHERE kind=? AND key=?", (kind, key)
        if revision is not None:
            sql, args = sql + " AND revision=?", (*args, revision)
        row = self.db.execute(sql + " ORDER BY revision DESC LIMIT 1", args).fetchone()
        if row is not None:
            self._revision_ids[kind, key, revision] = row[0]
        return None if row is None else row[0]

    def load_memory(self):
        """Explicit full historical reconstruction, not the local decision read path."""
        episodes = tuple(
            Episode(
                self.subject, self._source(source), self._term(content), frozenset(json.loads(cues))
            )
            for source, content, cues in self.db.execute(
                "SELECT source,content,cues FROM episodes ORDER BY position"
            )
        )
        samples, experiences = [], []
        for identity, kind in self.db.execute("SELECT id,kind FROM revisions ORDER BY id"):
            (samples if kind == "sample" else experiences).append(self._record(identity))
        return Memory(self.subject, episodes, tuple(experiences), tuple(samples))


class _Writer(RevisionView):
    def __init__(self, db, subject):
        super().__init__(db, subject)
        self._context_ids, self._source_ids, self._term_ids = {}, {}, {}
        self._retained_source_ids = set()
        row = db.execute("SELECT episodes,samples,experiences FROM metadata").fetchone()
        self._episode_position = row[0]
        self._revision_positions = dict(zip(("sample", "experience"), row[1:], strict=True))

    def _intern(self, table, columns, values):
        self.db.execute(
            f"INSERT OR IGNORE INTO {table}({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in values)})",
            values,
        )
        row = self.db.execute(
            f"SELECT id FROM {table} WHERE " + " AND ".join(f"{c} IS ?" for c in columns), values
        ).fetchone()
        return row[0]

    def context_id(self, value):
        if value is None:
            return None
        if value not in self._context_ids:
            self._context_ids[value] = self._intern(
                "contexts", ("domain", "episode"), (value.domain, value.episode)
            )
        return self._context_ids[value]

    def source_id(self, value):
        if value not in self._source_ids:
            self._source_ids[value] = self._intern(
                "sources",
                ("context", "producer", "channel", "recipient", "message", "occurrence"),
                (
                    self.context_id(value.context),
                    value.producer,
                    value.channel,
                    value.recipient,
                    value.message,
                    None if value.occurrence is None else format(value.occurrence, "x"),
                ),
            )
        return self._source_ids[value]

    def term_id(self, value):
        cached = self._term_ids.get(id(value))
        if cached is None or cached[0] is not value:
            body = dumps([value.name, value.signature, _wire(value.wire)])
            cached = value, self._intern("terms", ("body",), (body,))
            self._term_ids[id(value)] = cached
        return cached[1]

    def episode(self, value):
        identity = self.source_id(value.source)
        row = self.db.execute(
            "SELECT content,cues FROM episodes WHERE source=?", (identity,)
        ).fetchone()
        if row is not None:
            if (
                not _same_record(self._term(row[0]), value.content)
                or frozenset(json.loads(row[1])) != value.cues
            ):
                raise ValueError("episode source was reused with different content or cues")
            self._retained_source_ids.add(identity)
            return False
        self.db.execute(
            "INSERT INTO episodes VALUES(?,?,?,?)",
            (
                identity,
                self._episode_position,
                self.term_id(value.content),
                dumps(sorted(value.cues)),
            ),
        )
        self._episode_position += 1
        self._retained_source_ids.add(identity)
        index_episode(self.db, value, identity, self._episode_position - 1)
        return True

    def _set_links(self, table, kind, key, field, revision, values):
        old = tuple(
            self.db.execute(
                f"SELECT position,target FROM {table} WHERE kind=? AND key=? AND field=? "
                "AND to_revision IS NULL ORDER BY position",
                (kind, key, field),
            )
        )
        for position in range(max(len(old), len(values))):
            previous = old[position][1] if position < len(old) else None
            current = values[position] if position < len(values) else None
            if previous == current:
                continue
            if previous is not None:
                self.db.execute(
                    f"UPDATE {table} SET to_revision=? WHERE kind=? AND key=? AND field=? "
                    "AND position=? AND to_revision IS NULL",
                    (revision, kind, key, field, position),
                )
            if current is not None:
                self.db.execute(
                    f"INSERT INTO {table} VALUES(?,?,?,?,?,NULL,?)",
                    (kind, key, field, position, revision, current),
                )

    def revision(self, value):
        kind = "sample" if type(value) is Sample else "experience"
        existing = self.get(kind, value.key, value.revision)
        if existing is not None:
            if not _same_record(existing, value):
                raise ValueError("revision was reused with different content")
            return False
        previous = self.get(kind, value.key)
        (_next_sample if kind == "sample" else _next_experience)(previous, value)
        if previous is not None and _same_record(
            replace(value, revision=previous.revision), previous
        ):
            raise ValueError("unchanged revision")
        for source in value.grounds:
            identity = self.source_id(source)
            if identity not in self._retained_source_ids:
                if (
                    self.db.execute("SELECT 1 FROM episodes WHERE source=?", (identity,)).fetchone()
                    is None
                ):
                    raise ValueError("revision cites an unretained episode")
                self._retained_source_ids.add(identity)
        if kind == "sample":
            header = [
                self.source_id(value.trial),
                self.term_id(value.meaning),
                self.term_id(value.content),
                sorted(value.cues),
            ]
            source_fields = ("evidence", "boundaries")
        else:
            retained, references = set(value.grounds), []
            for key, revision in value.samples:
                sample = self.get("sample", key, revision)
                if sample is None or not set(sample.grounds) <= retained:
                    raise ValueError("experience cites an absent sample or its grounds")
                references.append(self._revision_id("sample", key, revision))
            header = [
                value.domain,
                self.context_id(value.context),
                self.term_id(value.meaning),
                sorted(value.cues),
            ]
            source_fields = ("support", "opposition")
        identity = self.db.execute(
            "INSERT INTO revisions(kind,key,revision,header,position) VALUES(?,?,?,?,?)",
            (kind, value.key, value.revision, dumps(header), self._revision_positions[kind]),
        ).lastrowid
        self._revision_positions[kind] += 1
        for field in source_fields:
            self._set_links(
                "source_links",
                kind,
                value.key,
                field,
                value.revision,
                tuple(self.source_id(s) for s in getattr(value, field)),
            )
        if kind == "experience":
            self._set_links(
                "sample_links", kind, value.key, "samples", value.revision, tuple(references)
            )
        self._records[identity] = value
        self._revision_ids[kind, value.key, value.revision] = identity
        self._revision_ids[kind, value.key, None] = identity
        index_revision(self.db, previous, value, identity)
        return True


class RevisionArchive:
    """One detached subject's exact records, with normalized interval membership."""

    def __init__(self, path, subject):
        if type(subject) is not str or not subject:
            raise ValueError("archive subject required")
        self.path, self.subject = Path(path), subject

    def _connect(self, *, create=False):
        if not create and not self.path.is_file():
            raise FileNotFoundError(self.path)
        db = sqlite3.connect(
            self.path if create else self.path.resolve().as_uri() + "?mode=ro", uri=not create
        )
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version == 0 and not tables and create:
                db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + INDEX_SCHEMA)
                db.execute("INSERT INTO metadata(subject) VALUES(?)", (self.subject,))
                db.commit()
            elif version != 3:
                raise ValueError("unsupported revision archive version")
            if db.execute("SELECT subject FROM metadata").fetchall() != [(self.subject,)]:
                raise ValueError("foreign archive subject")
            return db
        except BaseException:
            db.close()
            raise

    def append(self, entries):
        if type(entries) is not tuple or any(
            type(e) is not Entry or e.subject != self.subject for e in entries
        ):
            raise ValueError("archive requires this subject's Entry tuple")
        with closing(self._connect(create=True)) as db, db:
            return append_entries(db, self.subject, entries)

    @contextmanager
    def read(self):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            try:
                yield RevisionView(db, self.subject)
            finally:
                db.rollback()

    def stats(self):
        with self.read() as view:
            return {
                name: view.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                for name in (
                    "contexts",
                    "sources",
                    "terms",
                    "episodes",
                    "revisions",
                    "source_links",
                    "sample_links",
                )
            }


def append_entries(db, subject, entries):
    """Append inside the caller's transaction, including a larger Subject checkpoint."""
    if type(entries) is not tuple or any(
        type(e) is not Entry or e.subject != subject for e in entries
    ):
        raise ValueError("archive requires this subject's Entry values")
    writer = _Writer(db, subject)
    added = {"episodes": 0, "samples": 0, "experiences": 0}
    for cls, label in ((Episode, "episodes"), (Sample, "samples"), (Experience, "experiences")):
        for entry in entries:
            if type(entry.record) is cls:
                added[label] += (
                    writer.episode(entry.record)
                    if cls is Episode
                    else writer.revision(entry.record)
                )
    db.execute(
        "UPDATE metadata SET version=version+?, episodes=episodes+?, samples=samples+?, "
        "experiences=experiences+?",
        (sum(added.values()), added["episodes"], added["samples"], added["experiences"]),
    )
    return added
