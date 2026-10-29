"""Incremental row seals for accidental loss/corruption, not hostile-file authentication."""

import hashlib
import json

TABLES = (
    "metadata",
    "contexts",
    "sources",
    "terms",
    "episodes",
    "revisions",
    "recall_receipts",
    "source_links",
    "sample_links",
    "recall_sizes",
    "recall_members",
    "recall_episodes",
    "record_heads",
    "subject_visits",
    "subject_decisions",
    "subject_values",
    "subject_checkpoints",
)
SCHEMA = (
    "CREATE TABLE subject_integrity(table_name TEXT NOT NULL, identity INTEGER NOT NULL, "
    "digest TEXT NOT NULL, PRIMARY KEY(table_name,identity))"
)


def _digest(row):
    return hashlib.sha256(
        json.dumps(tuple(row), ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def watch(db):
    db.execute(
        "CREATE TEMP TABLE checkpoint_dirty(table_name TEXT, identity INTEGER, "
        "PRIMARY KEY(table_name,identity))"
    )
    for table in TABLES:
        for event, versions in (
            ("INSERT", ("new",)),
            ("DELETE", ("old",)),
            ("UPDATE", ("old", "new")),
        ):
            body = " ".join(
                f"INSERT INTO checkpoint_dirty VALUES('{table}',{v}.rowid) ON CONFLICT DO NOTHING;"
                for v in versions
            )
            db.execute(
                f"CREATE TEMP TRIGGER dirty_{table}_{event} AFTER {event} ON main.{table} "
                f"BEGIN {body} END"
            )


def seal(db, *, first):
    changed = 0
    for table in TABLES:
        if first:
            rows = db.execute(f"SELECT rowid,* FROM {table}")
        else:
            rows = db.execute(
                f"SELECT t.rowid,t.* FROM {table} t JOIN checkpoint_dirty d "
                "ON d.identity=t.rowid WHERE d.table_name=?",
                (table,),
            )
            db.execute(
                f"DELETE FROM subject_integrity WHERE table_name=? AND identity IN "
                "(SELECT identity FROM checkpoint_dirty WHERE table_name=?) "
                f"AND NOT EXISTS(SELECT 1 FROM {table} t WHERE t.rowid=subject_integrity.identity)",
                (table, table),
            )
        for row in rows:
            db.execute(
                "INSERT INTO subject_integrity VALUES(?,?,?) ON CONFLICT(table_name,identity) "
                "DO UPDATE SET digest=excluded.digest",
                (table, row[0], _digest(row)),
            )
            changed += 1
    return changed


def validate(db):
    if set(r[0] for r in db.execute("SELECT DISTINCT table_name FROM subject_integrity")) - set(
        TABLES
    ):
        raise ValueError("unknown Subject integrity table")
    for table in TABLES:
        expected = db.execute(
            "SELECT count(*) FROM subject_integrity WHERE table_name=?", (table,)
        ).fetchone()[0]
        actual = 0
        for row in db.execute(
            f"SELECT t.rowid,t.*,i.digest FROM {table} t LEFT JOIN "
            "subject_integrity i ON i.table_name=? AND i.identity=t.rowid",
            (table,),
        ):
            actual += 1
            if row[-1] != _digest(row[:-1]):
                raise ValueError("damaged Subject row: " + table)
        if actual != expected:
            raise ValueError("missing Subject row: " + table)
