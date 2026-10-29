"""One process-local owner's hot inputs and exact cold record revisions."""

from pathlib import Path
from tempfile import TemporaryDirectory
from weakref import ref

from nomos_cognition.memory import Memory, RecallLimits, _extends_history, recall

from .archive import RevisionArchive
from .audit import save_decisions
from .history import cold_revisions
from .records import Entry


class MemoryStore:
    """A new temporary archive, never an imported Subject or a restartable identity."""

    def __init__(self, subject):
        self.subject = subject
        self._directory = TemporaryDirectory(prefix="ne2-subject-memory-")
        self.archive = RevisionArchive(Path(self._directory.name) / "memory.sqlite", subject)
        self._head = None
        self._pending = None

    def publish(self, before, after):
        if (
            type(before) is not Memory
            or type(after) is not Memory
            or (before.subject != self.subject or after.subject != self.subject)
        ):
            raise ValueError("memory publication requires this owner's checked snapshots")
        if self._head is None:
            if before.version:
                raise ValueError("a new memory store starts from an empty snapshot")
        elif self._head() is not before:
            raise ValueError("memory publication requires its exact current predecessor")
        if before.version and not _extends_history(before, after):
            raise ValueError("memory update changed a previously checked history prefix")
        if self._pending is not None and (
            self._pending[0] is not before or self._pending[1] is not after
        ):
            raise ValueError("retry the pending exact memory draft before another update")
        if before is after:
            self._head = ref(after)
            return after
        entries = tuple(
            Entry(self.subject, value)
            for old, new in (
                (before.episodes, after.episodes),
                (before.samples, after.samples),
                (before.experiences, after.experiences),
            )
            for value in new[len(old) :]
        )
        # SQLite may already contain this exact batch after a failed post-commit
        # publication. Replaying it is idempotent; the Subject cursor is still old.
        self._pending = before, after
        self.archive.append(entries)
        value = cold_revisions(after, self)
        self._head = ref(value)
        self._pending = None
        return value

    def recall(self, memory, query, *, limits=RecallLimits()):
        if memory.subject != self.subject:
            raise ValueError("memory read belongs to a different owner")
        return recall(memory, query, limits=limits)

    def capture(self, decisions):
        return save_decisions(self.archive, decisions)

    def __reduce_ex__(self, protocol):
        raise TypeError("memory storage does not restore Subject identity")
