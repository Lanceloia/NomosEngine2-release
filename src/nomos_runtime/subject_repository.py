"""Exclusive local Subject continuation, independent of world save/restore."""

import hashlib
import os
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4
from weakref import ref

from pyrsistent import pvector

from nomos_cognition.storage import integrity
from nomos_cognition.storage.archive import RevisionArchive, RevisionView, append_entries
from nomos_cognition.storage.audit import _encode, read_receipt
from nomos_cognition.storage.records import Entry
from nomos_cognition.storage.restore import restore_hot
from nomos_cognition.storage.store import MemoryStore

from .artifact_binding import content_binding
from .errors import AdmissionError
from .local_inputs import InputCursor
from .participation import ParticipationLimits, Subject, Visit, _SubjectState
from .subject_audit import DecisionHistory, DecisionRecord, StoredSubjectDecision
from .subject_value_pool import SCHEMA as VALUE_SCHEMA
from .subject_value_pool import SubjectValuePool
from .subject_values import SubjectValueCodec

_SCHEMA = (
    "CREATE TABLE subject_repository(format INTEGER NOT NULL CHECK(format=2))",
    "INSERT INTO subject_repository VALUES(2)",
    "CREATE TABLE subject_checkpoints(sequence INTEGER PRIMARY KEY, "
    "revision INTEGER UNIQUE NOT NULL, request TEXT UNIQUE NOT NULL, body TEXT NOT NULL, "
    "digest TEXT NOT NULL, body_digest TEXT NOT NULL)",
    "CREATE TABLE subject_visits(position INTEGER PRIMARY KEY, body TEXT NOT NULL)",
    "CREATE TABLE subject_decisions(position INTEGER PRIMARY KEY, body TEXT NOT NULL)",
    VALUE_SCHEMA,
    integrity.SCHEMA,
)


@dataclass(frozen=True)
class Checkpoint:
    sequence: int
    revision: int
    memory_version: int
    counts: tuple
    visits: int
    decisions: int
    digest: str


@dataclass(frozen=True)
class SavedSubject:
    checkpoint: Checkpoint
    subject: str
    personality: tuple
    exploration: object
    reservation: int | None
    profile: str
    visits: tuple
    decisions: DecisionHistory


@dataclass(frozen=True)
class _ArchiveReader:
    archive: RevisionArchive


class _WriterLease:
    """An inode-keyed local lease, independent of SQLite's database byte locks."""

    def __init__(self, path, create):
        import fcntl
        import stat

        self._file = open(path, "x+b" if create else "r+b")
        self._lock = None
        try:
            # A fixed local namespace is shared even when callers use different TMPDIRs.
            directory = Path("/tmp") / f"nomos-subject-writers-{os.getuid()}"
            directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError("Subject lease directory must be private to the local user")
            identity = os.fstat(self._file.fileno())
            self._lock = open(directory / f"{identity.st_dev:x}-{identity.st_ino:x}", "a+b")
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            try:
                if create:
                    try:
                        current = path.stat()
                    except FileNotFoundError:
                        pass
                    else:
                        held = os.fstat(self._file.fileno())
                        if (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino):
                            path.unlink()
            finally:
                self.close()
            raise

    @property
    def closed(self):
        return self._file.closed

    def fileno(self):
        return self._file.fileno()

    def close(self):
        self._file.close()
        if self._lock is not None:
            # Do not unlink: an existing waiter may already hold this lock inode.
            self._lock.close()


class SubjectRepository:
    """One managed SQLite file and one writer; snapshots never produce another Subject."""

    def __init__(self):
        raise TypeError("use SubjectRepository.create or SubjectRepository.open")

    @classmethod
    def create(cls, path, module, subject):
        if type(subject) is not Subject or subject._repository is not None or subject._closed:
            raise ValueError("repository requires an unowned live Subject")
        cls._inactive(subject)
        if (
            subject._state.program is not module.PROGRAM
            or subject._state.library is not module.CONTROLLERS
        ):
            raise ValueError("save requires this loaded product's completed participation")
        binding = content_binding(module)
        value = cls._allocate(path, module, subject, create=True)
        value._binding = binding
        subject._repository = value
        return value

    @classmethod
    def open(cls, path, module):
        binding = content_binding(module)
        value = cls._allocate(path, module, None, create=False)
        try:
            with value.archive.read() as view:
                saved, config = value._snapshot(view)
                if config[-1] != binding:
                    raise ValueError("saved Subject uses different product or execution content")
            store = MemoryStore(value.archive.subject)
            # A one-time SQLite working copy keeps unsaved changes out of the sealed head.
            # Subsequent saves import only the actual appended suffix.
            with closing(value.archive._connect()) as source:
                with closing(store.archive._connect(create=True)) as target:
                    source.backup(target)
            models = tuple(s.semantics for s in module.CONTROLLERS.strategies if s.semantics)
            memory = restore_hot(store, models)
            if (
                len(memory.episodes),
                len(memory.samples),
                len(memory.experiences),
            ) != saved.checkpoint.counts:
                raise ValueError("checkpoint memory prefix disagrees with archive")
            subject = Subject.__new__(Subject)
            subject._personality, subject._exploration = saved.personality, saved.exploration
            subject._reservation, subject._busy, subject._closed = saved.reservation, False, False
            subject._memory_store, subject._repository = store, value
            subject._state = _SubjectState(
                memory,
                saved.visits,
                None,
                module.PROGRAM,
                module.CONTROLLERS,
                saved.profile,
                saved.checkpoint.revision,
                pvector(StoredSubjectDecision(store, e.value) for e in saved.decisions.entries),
            )
            store._head = ref(memory)
            value.subject, value._binding = subject, binding
            value._last_state, value._head = subject._state, saved.checkpoint
            return value
        except BaseException:
            value._lease.close()
            raise

    @classmethod
    def _allocate(cls, path, module, subject, *, create):
        value = object.__new__(cls)
        value.path = Path(path).resolve()
        value.codec = SubjectValueCodec(module)
        value._lease = _WriterLease(value.path, create)
        value.module, value.subject = module, subject
        value._pending, value._last_state, value._head = None, None, None
        try:
            if create:
                identity = subject.memory.subject
            else:
                import sqlite3

                with closing(sqlite3.connect(value.path)) as db:
                    if db.execute("SELECT format FROM subject_repository").fetchall() != [(2,)]:
                        raise ValueError("unsupported Subject repository format")
                    identities = db.execute("SELECT subject FROM metadata").fetchall()
                    if len(identities) != 1 or type(identities[0][0]) is not str:
                        raise ValueError("invalid repository Subject identity")
                    identity = identities[0][0]
            value.archive = RevisionArchive(value.path, identity)
            return value
        except BaseException:
            try:
                if create:
                    value._remove_new_file()
            finally:
                value._lease.close()
            raise

    def _check(self):
        if self._lease.closed:
            raise AdmissionError("SubjectRepositoryClosed", "repository writer is closed")
        actual = self.path.stat()
        held = os.fstat(self._lease.fileno())
        if (actual.st_dev, actual.st_ino) != (held.st_dev, held.st_ino):
            raise ValueError("repository file was replaced while checked out")

    @staticmethod
    def _inactive(subject):
        if subject.active or subject._busy or subject._memory_store._pending is not None:
            raise AdmissionError("SubjectNotQuiescent", "save or close between completed visits")

    def _remove_new_file(self):
        self._check()
        self.path.unlink()

    def save(self):
        self._check()
        subject = self.subject
        self._inactive(subject)
        if subject._repository is not self or subject._closed:
            raise ValueError("repository no longer owns this Subject")
        if content_binding(self.module) != self._binding:
            raise ValueError("loaded execution content changed before save")
        if (
            subject._state.program is not self.module.PROGRAM
            or subject._state.library is not self.module.CONTROLLERS
        ):
            raise ValueError("Subject changed its exact loaded product")
        state = subject._state
        if self._last_state is state:
            return self._head
        if self._pending is None:
            counts = (
                len(state.memory.episodes),
                len(state.memory.samples),
                len(state.memory.experiences),
            )
            config = (
                state.memory.subject,
                state.revision,
                subject.personality,
                subject.exploration,
                subject.reservation,
                state.profile,
                counts,
                len(state.visits),
                len(state.decisions),
                self._binding,
            )
            self._pending = state, uuid4().hex, self.codec.dumps(config)
        if self._pending[0] is not state:
            raise ValueError("retry the exact pending Subject checkpoint before continuing")
        result = self._publish()
        self._last_state, self._head, self._pending = state, result, None
        return result

    def _publish(self):
        state, request, body = self._pending
        if not self.subject._memory_store.archive.path.exists():
            self.subject._memory_store.archive.append(())
        with closing(self.archive._connect(create=True)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='subject_repository'"
            ).fetchone()
            if not exists:
                for statement in _SCHEMA:
                    db.execute(statement)
            integrity.watch(db)
            previous = db.execute(
                "SELECT sequence,body,digest FROM subject_checkpoints "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            repeated = db.execute(
                "SELECT sequence,revision,body,digest FROM subject_checkpoints WHERE request=?",
                (request,),
            ).fetchone()
            if repeated:
                if repeated[2] != body or previous[0] != repeated[0]:
                    raise ValueError("checkpoint request was reused with different state")
                return self._info(repeated[0], self.codec.loads(body), repeated[3])
            if (None if previous is None else previous[0]) != (
                None if self._head is None else self._head.sequence
            ):
                raise ValueError("repository head changed outside its writer")
            prior = (0, 0, 0)
            visits = decisions = 0
            if previous:
                old = self.codec.loads(previous[1])
                prior, visits, decisions = old[6:9]
            added = []
            for name, start in zip(("episodes", "samples", "experiences"), prior, strict=True):
                added.extend(
                    Entry(self.archive.subject, record)
                    for record in getattr(state.memory, name)[start:]
                )
            append_entries(db, self.archive.subject, tuple(added))
            if (
                db.execute("SELECT episodes,samples,experiences FROM metadata").fetchone()
                != self.codec.loads(body)[6]
            ):
                raise ValueError("saved memory prefix disagrees with Subject state")
            digest = hashlib.sha256()
            digest.update(("" if previous is None else previous[2]).encode())
            digest.update(body.encode())
            for entry in added:
                digest.update(self.codec.dumps(entry.record).encode())
            for position, visit in enumerate(state.visits[visits:], visits):
                encoded = self.codec.dumps(visit)
                db.execute("INSERT INTO subject_visits VALUES(?,?)", (position, encoded))
                digest.update(encoded.encode())
            with self.subject._memory_store.archive.read() as original:
                destination = RevisionView(db, self.archive.subject)
                translated = {}
                values = SubjectValuePool(db, self.codec)

                def relocate(evidence):
                    identity = translated.get(evidence.receipt)
                    if identity is None:
                        receipt = read_receipt(original, evidence.receipt)
                        encoded = _encode(destination, receipt)
                        identity = db.execute(
                            "INSERT INTO recall_receipts(body) VALUES(?)", (encoded,)
                        ).lastrowid
                        translated[evidence.receipt] = identity
                    return replace(evidence, receipt=identity)

                for position, stored in enumerate(state.decisions[decisions:], decisions):
                    value = stored.value
                    value = replace(
                        value,
                        decision=relocate(value.decision),
                        evaluations=tuple((v, relocate(e)) for v, e in value.evaluations),
                    )
                    encoded = values.dumps(value)
                    db.execute("INSERT INTO subject_decisions VALUES(?,?)", (position, encoded))
                    digest.update(encoded.encode())
            sequence = 1 if previous is None else previous[0] + 1
            result = digest.hexdigest()
            db.execute(
                "INSERT INTO subject_checkpoints VALUES(?,?,?,?,?,?)",
                (
                    sequence,
                    state.revision,
                    request,
                    body,
                    result,
                    hashlib.sha256(body.encode()).hexdigest(),
                ),
            )
            integrity.seal(db, first=previous is None)
            return self._info(sequence, self.codec.loads(body), result)

    @staticmethod
    def _info(sequence, config, digest):
        return Checkpoint(
            sequence, config[1], sum(config[6]), config[6], config[7], config[8], digest
        )

    def _snapshot(self, view, sequence=None):
        integrity.validate(view.db)
        query = "SELECT sequence,body,digest,body_digest,revision FROM subject_checkpoints"
        row = view.db.execute(
            query
            + (" ORDER BY sequence DESC LIMIT 1" if sequence is None else " WHERE sequence=?"),
            () if sequence is None else (sequence,),
        ).fetchone()
        if row is None:
            raise ValueError("no successful Subject checkpoint")
        number, body, digest, body_digest, revision = row
        if hashlib.sha256(body.encode()).hexdigest() != body_digest:
            raise ValueError("damaged Subject checkpoint metadata")
        config = self.codec.loads(body)
        if (
            type(config) is not tuple
            or len(config) != 10
            or config[0] != self.archive.subject
            or type(config[1]) is not int
            or config[1] < 1
            or config[1] != revision
            or type(config[2]) is not tuple
            or config[4] is not None
            and type(config[4]) is not int
            or type(config[5]) is not str
            or type(config[6]) is not tuple
            or len(config[6]) != 3
            or any(type(n) is not int or n < 0 for n in (*config[6], config[7], config[8]))
        ):
            raise ValueError("invalid saved Subject configuration")
        visits = tuple(
            self.codec.loads(r[0])
            for r in view.db.execute(
                "SELECT body FROM subject_visits WHERE position<? ORDER BY position", (config[7],)
            )
        )
        values = SubjectValuePool(view.db, self.codec)
        decisions = tuple(
            StoredSubjectDecision(_ArchiveReader(self.archive), values.loads(r[0]))
            for r in view.db.execute(
                "SELECT body FROM subject_decisions WHERE position<? ORDER BY position",
                (config[8],),
            )
        )
        if len(visits) != config[7] or len(decisions) != config[8]:
            raise ValueError("missing Subject visit or decision prefix")
        self._validate_history(view, config, visits, decisions)
        return SavedSubject(
            self._info(number, config, digest),
            config[0],
            config[2],
            config[3],
            config[4],
            config[5],
            visits,
            DecisionHistory(decisions),
        ), config

    def _validate_history(self, view, config, visits, decisions):
        from nomos_cognition.appraisal import validate_weights
        from nomos_cognition.exploration import EpsilonGreedy

        models = tuple(
            s.semantics
            for s in self.module.CONTROLLERS.strategies
            if s.semantics and s.semantics.domain == config[5]
        )
        if not models or config[3] is not None and type(config[3]) is not EpsilonGreedy:
            raise ValueError("saved Subject has an unknown profile or exploration policy")
        axes = set().union(*(m.outcomes for m in models))
        if any(
            type(p) is not tuple or len(p) != 2 or p[0] not in axes or type(p[1]) is not int
            for p in config[2]
        ):
            raise ValueError("saved personality differs from the selected profile")
        if len({p[0] for p in config[2]}) != len(config[2]):
            raise ValueError("duplicate saved personality dimensions")
        contexts = {}
        for visit in visits:
            if (
                type(visit) is not Visit
                or visit.conclusion not in ("finished", "interrupted")
                or visit.context.domain != config[5]
                or visit.actor.scope != visit.context.episode
                or visit.context in contexts
                or type(visit.cursor) is not InputCursor
                or visit.cursor.recipient != visit.actor
                or type(visit.cursor.sequence) is not int
                or visit.cursor.sequence < 0
                or type(visit.pending) is not tuple
                or type(visit.memory_version) is not int
                or not 0 <= visit.memory_version <= sum(config[6])
                or type(visit.limits) is not ParticipationLimits
                or type(visit.goals) is not tuple
            ):
                raise ValueError("invalid completed Subject visit")
            contexts[visit.context] = visit
        read = {}
        for stored in decisions:
            value = stored.value
            if type(value) is not DecisionRecord or value.metadata.context not in contexts:
                raise ValueError("decision lacks a completed Subject visit")
            metadata = value.metadata
            if not 0 <= metadata.memory_version <= contexts[metadata.context].memory_version:
                raise ValueError("decision points beyond its completed visit")
            action = self.module.PROGRAM.actions.get(metadata.trial.ability)
            if action is None or action.source != metadata.trial.source:
                raise ValueError("decision uses an unknown actual Action source")
            for evidence in (value.decision, *(e for _, e in value.evaluations)):
                receipt = read.get(evidence.receipt)
                if receipt is None:
                    receipt = read_receipt(view, evidence.receipt)
                    read[evidence.receipt] = receipt
                if (
                    receipt.query.subject != self.archive.subject
                    or receipt.query.context != metadata.context
                    or receipt.version != metadata.memory_version
                    or not receipt.query.past <= contexts.keys()
                    or evidence.model not in models
                    or evidence.goals != contexts[metadata.context].goals
                    or evidence.personality != validate_weights(evidence.model, config[2])
                ):
                    raise ValueError("decision receipt differs from its saved Subject context")
                validate_weights(evidence.model, evidence.personality)
                validate_weights(evidence.model, evidence.goals)

    def snapshot(self, sequence=None):
        self._check()
        if sequence is not None and (type(sequence) is not int or sequence < 1):
            raise ValueError("checkpoint sequence requires a positive integer")
        with self.archive.read() as view:
            return self._snapshot(view, sequence)[0]

    def close(self):
        if self._lease.closed:
            return
        self._check()
        self._inactive(self.subject)
        if self._pending is not None:
            raise AdmissionError("SubjectCheckpointPending", "retry pending save before closing")
        if self._head is None:
            self._remove_new_file()
        self.subject._closed = True
        self.subject._repository = None
        self._lease.close()

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *args):
        self.close()
