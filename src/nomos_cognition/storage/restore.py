"""Rebuild current hot inputs and indexes; historical bodies remain in the exact archive."""

import json
from dataclasses import fields

from pyrsistent import pmap, pvector

from nomos_cognition.appraisal import prepare_consolidation
from nomos_cognition.memory import Memory, _append, _empty, _HistoryPrefix
from nomos_cognition.recall_index import RecordIndex
from nomos_cognition.state import Term

from .archive import _unwire
from .history import RevisionHistory, RevisionVersions


def _check_headers(view):
    """Check all compact headers and interval endpoints without expanding old memberships."""
    db = view.db
    sources = {r[0] for r in db.execute("SELECT source FROM episodes")}
    terms = set()
    for identity, body in db.execute("SELECT id,body FROM terms"):
        name, signature, wire = json.loads(body)
        Term(name, signature, _unwire(wire))
        terms.add(identity)
    contexts = {r[0] for r in db.execute("SELECT id FROM contexts")}
    heads = {}
    for kind, key, revision, body in db.execute(
        "SELECT kind,key,revision,header FROM revisions ORDER BY kind,key,revision"
    ):
        header = json.loads(body)
        if type(header) is not list or len(header) != 4:
            raise ValueError("invalid archived revision header")
        cues = header[3]
        if (
            type(cues) is not list
            or not cues
            or any(type(c) is not str or not c for c in cues)
            or len(set(cues)) != len(cues)
        ):
            raise ValueError("invalid archived revision cues")
        if kind == "sample":
            if (
                any(type(n) is not int for n in header[:3])
                or header[0] not in sources
                or not set(header[1:3]) <= terms
            ):
                raise ValueError("sample header cites a missing source or term")
            fixed = header[0], header[1], tuple(cues)
        elif kind == "experience":
            if (
                type(header[0]) is not str
                or not header[0]
                or header[1] is not None
                and header[1] not in contexts
                or type(header[2]) is not int
                or header[2] not in terms
            ):
                raise ValueError("experience header cites a missing context or term")
            fixed = header[0], header[1]
        else:
            raise ValueError("unknown archived revision kind")
        old = heads.get((kind, key))
        if old is not None and old[1] != fixed:
            raise ValueError("archived revision changed its nominal applicability")
        heads[kind, key] = revision, fixed
    for table in ("source_links", "sample_links"):
        for kind, key, field, position, start, stop in db.execute(
            f"SELECT kind,key,field,position,from_revision,to_revision FROM {table}"
        ):
            head = heads.get((kind, key))
            permitted = (
                ("evidence", "boundaries") if kind == "sample" else ("support", "opposition")
            )
            if table == "sample_links":
                permitted = ("samples",) if kind == "experience" else ()
            if (
                head is None
                or field not in permitted
                or position < 0
                or not 1 <= start <= head[0]
                or stop is not None
                and not start < stop <= head[0]
            ):
                raise ValueError("invalid archived revision interval")
    if db.execute(
        "SELECT 1 FROM sample_links l JOIN revisions r ON l.target=r.id "
        "WHERE r.kind<>'sample' LIMIT 1"
    ).fetchone():
        raise ValueError("experience cites a non-sample revision")


def restore_hot(store, models):
    with store.archive.read() as view:
        db = view.db
        if (
            db.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise ValueError("damaged memory archive")
        version, episodes, samples, experiences = db.execute(
            "SELECT version,episodes,samples,experiences FROM metadata"
        ).fetchone()
        if version != episodes + samples + experiences:
            raise ValueError("memory counters disagree")
        for table, kind, count in (
            ("episodes", None, episodes),
            ("revisions", "sample", samples),
            ("revisions", "experience", experiences),
        ):
            clause, args = ("", ()) if kind is None else (" WHERE kind=?", (kind,))
            actual, first, last = db.execute(
                f"SELECT count(*),min(position),max(position) FROM {table}{clause}", args
            ).fetchone()
            if actual != count or count and (first != 0 or last != count - 1):
                raise ValueError("missing memory history position")
        if db.execute(
            "SELECT 1 FROM revisions GROUP BY kind,key HAVING min(revision)<>1 "
            "OR max(revision)<>count(*) LIMIT 1"
        ).fetchone():
            raise ValueError("nonconsecutive archived revisions")
        _check_headers(view)
        memory = _append(
            _empty(store.subject),
            episodes=tuple(
                view._episode(row[0])
                for row in db.execute("SELECT source FROM episodes ORDER BY position")
            ),
        )
        keys, current, positions = {}, {}, {}
        for kind in ("sample", "experience"):
            rows = db.execute(
                "SELECT r.id,r.key,r.position FROM revisions r JOIN "
                "(SELECT key,max(revision) revision,min(position) first FROM revisions "
                "WHERE kind=? GROUP BY key) h ON r.key=h.key AND r.revision=h.revision "
                "WHERE r.kind=? ORDER BY h.first",
                (kind, kind),
            ).fetchall()
            current[kind] = {key: view._record(identity) for identity, key, _ in rows}
            positions[kind] = {key: position for _, key, position in rows}
            keys[kind] = pvector(
                row[0]
                for row in db.execute(
                    "SELECT key FROM revisions WHERE kind=? ORDER BY position", (kind,)
                )
            )
        index = RecordIndex()
        for position, sample in enumerate(current["sample"].values()):
            if any(source not in memory._sources for source in sample.grounds):
                raise ValueError("sample cites a missing retained source")
            index = index.with_sample(None, sample, position)
        for experience in current["experience"].values():
            if any(source not in memory._sources for source in experience.grounds):
                raise ValueError("experience cites a missing retained source")
            for reference in experience.samples:
                sample = view.get("sample", *reference)
                if sample is None or not set(sample.grounds) <= set(experience.grounds):
                    raise ValueError("experience cites an absent sample or its grounds")
            index = index.with_experience(None, experience)
        changes = {
            "samples": RevisionHistory(store, "sample", samples),
            "experiences": RevisionHistory(store, "experience", experiences),
            "_samples": pmap(current["sample"]),
            "_latest": pmap(current["experience"]),
            "_sample_keys": pvector(current["sample"]),
            "_sample_history_keys": keys["sample"],
            "_experience_history_keys": keys["experience"],
            "_experience_positions": pmap(positions["experience"]),
            "_record_index": index,
            "_sample_versions": RevisionVersions(store, "sample", samples, pmap(current["sample"])),
            "_versions": RevisionVersions(
                store, "experience", experiences, pmap(current["experience"])
            ),
            "_history_prefixes": tuple(
                _HistoryPrefix(None, n) for n in (episodes, samples, experiences)
            ),
        }
        value = object.__new__(Memory)
        for item in fields(memory):
            object.__setattr__(value, item.name, changes.get(item.name, getattr(memory, item.name)))
    for model in dict.fromkeys(models):
        value = prepare_consolidation(model, value)
    return value
