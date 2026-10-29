"""Immutable sample/experience cursors; current values remain available without I/O."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields

from pyrsistent import pmap

from nomos_cognition.memory import Memory


@dataclass(frozen=True, eq=False)
class RevisionHistory(Sequence):
    store: object
    kind: str
    count: int
    tail: tuple = ()

    def __len__(self):
        return self.count + len(self.tail)

    def __getitem__(self, index):
        if type(index) is slice:
            start, stop, step = index.indices(len(self))
            if step != 1:
                return tuple(self[i] for i in range(start, stop, step))
            if start >= self.count:
                return self.tail[start - self.count : stop - self.count]
            with self.store.archive.read() as view:
                rows = view.db.execute(
                    "SELECT id FROM revisions WHERE kind=? AND position>=? "
                    "AND position<? ORDER BY position",
                    (self.kind, start, min(stop, self.count)),
                )
                values = tuple(view._record(row[0]) for row in rows)
            return values + self.tail[: max(0, stop - self.count)]
        if type(index) is not int:
            raise TypeError("revision history requires an index or slice")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        if index >= self.count:
            return self.tail[index - self.count]
        with self.store.archive.read() as view:
            row = view.db.execute(
                "SELECT id FROM revisions WHERE kind=? AND position=?", (self.kind, index)
            ).fetchone()
            if row is None:
                raise ValueError("missing archived revision position")
            return view._record(row[0])

    def extend(self, values):
        return RevisionHistory(self.store, self.kind, self.count, self.tail + tuple(values))

    def __iter__(self):
        # Do not hold a read transaction across a caller-controlled yield.
        for index in range(self.count):
            yield self[index]
        yield from self.tail

    def __hash__(self):
        return hash(tuple(self))

    def __eq__(self, other):
        if self is other:
            return True
        if type(other) is RevisionHistory and self.store is other.store and self.kind == other.kind:
            if self.count == other.count and self.tail == other.tail:
                return True
        return isinstance(other, Sequence) and tuple(self) == tuple(other)


@dataclass(frozen=True, eq=False)
class RevisionVersions(Mapping):
    store: object
    kind: str
    count: int
    current: object
    tail: object = field(default_factory=pmap)

    def __getitem__(self, key):
        if key in self.tail:
            return self.tail[key]
        if type(key) is not tuple or len(key) != 2:
            raise KeyError(key)
        latest = self.current.get(key[0])
        if latest is None or type(key[1]) is not int or not 1 <= key[1] <= latest.revision:
            raise KeyError(key)
        if key[1] == latest.revision:
            return latest
        with self.store.archive.read() as view:
            row = view.db.execute(
                "SELECT id FROM revisions WHERE kind=? AND key=? AND revision=? AND position<?",
                (self.kind, *key, self.count),
            ).fetchone()
            if row is None:
                raise KeyError(key)
            return view._record(row[0])

    def __iter__(self):
        with self.store.archive.read() as view:
            keys = tuple(
                tuple(row)
                for row in view.db.execute(
                    "SELECT key,revision FROM revisions WHERE kind=? AND position<? "
                    "ORDER BY position",
                    (self.kind, self.count),
                )
            )
        yield from keys
        yield from self.tail

    def __len__(self):
        return self.count + len(self.tail)

    def update(self, values):
        # Memory only adds new, checked consecutive versions to this map.
        if not values:
            return self
        return RevisionVersions(
            self.store, self.kind, self.count, self.current, self.tail.update(values)
        )


def cold_revisions(memory, store):
    histories = (
        ("samples", "_sample_versions", "sample", memory._samples),
        ("experiences", "_versions", "experience", memory._latest),
    )
    if all(
        type(history := getattr(memory, name)) is RevisionHistory
        and history.store is store
        and not history.tail
        for name, _, _, _ in histories
    ):
        return memory
    changes = {}
    for name, versions, kind, current in histories:
        history = getattr(memory, name)
        if type(history) is RevisionHistory and history.store is store and not history.tail:
            continue
        count = len(history)
        changes[name] = RevisionHistory(store, kind, count)
        changes[versions] = RevisionVersions(store, kind, count, current)
    value = object.__new__(Memory)
    for item in fields(memory):
        object.__setattr__(value, item.name, changes.get(item.name, getattr(memory, item.name)))
    return value
