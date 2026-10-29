"""Transactional exact sharing of typed audit records, independent of cognitive recall."""

import hashlib
import json

SCHEMA = "CREATE TABLE subject_values(digest TEXT PRIMARY KEY, body TEXT NOT NULL)"


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


class SubjectValuePool:
    """One operation's cache; rows belong to the caller's checkpoint transaction."""

    def __init__(self, db, codec):
        self.db, self.codec = db, codec

    def dumps(self, value):
        return self._store(self.codec.dumps(value))

    def _store(self, body):
        # Only typed record nodes are shared. Raw value wires contain no JSON objects.
        seen = {}

        def pack(wire):
            if type(wire) is not list:
                return wire
            packed = [pack(item) for item in wire]
            if not wire or wire[0] != "record":
                return packed
            encoded = _json(packed)
            if len(encoded) < 192:
                return packed
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            if digest not in seen:
                self.db.execute(
                    "INSERT INTO subject_values VALUES(?,?) ON CONFLICT(digest) DO NOTHING",
                    (digest, encoded),
                )
                stored = self.db.execute(
                    "SELECT body FROM subject_values WHERE digest=?", (digest,)
                ).fetchone()[0]
                if stored != encoded:
                    raise ValueError("audit value digest collision or damaged shared value")
                seen[digest] = encoded
            return {"shared": digest}

        packed = _json(["nomos.subject.shared-values", 1, pack(json.loads(body))])
        if len(packed.encode()) > self.codec.wire_bytes:
            raise ValueError("shared audit requires bounded encoded text")
        if sum(len(value.encode()) for value in seen.values()) > self.codec.wire_bytes:
            raise ValueError("shared audit exceeds loaded byte limit")
        return packed

    def _expand(self, body):
        limit = self.codec.wire_bytes
        if type(body) is not str or len(body.encode()) > limit:
            raise ValueError("shared audit requires bounded encoded text")
        cache, active = {}, set()
        visited = loaded = 0

        def expand(wire, depth):
            nonlocal visited, loaded
            visited += 1
            if visited > self.codec.nodes * 8 or depth > self.codec.depth * 4 + 8:
                raise ValueError("shared audit exceeds node or depth limit")
            if type(wire) is dict:
                if (
                    set(wire) != {"shared"}
                    or type(wire["shared"]) is not str
                    or len(wire["shared"]) != 64
                ):
                    raise ValueError("invalid shared audit reference")
                key = wire["shared"]
                if key in active:
                    raise ValueError("cyclic shared audit reference")
                if key not in cache:
                    row = self.db.execute(
                        "SELECT body FROM subject_values WHERE digest=?", (key,)
                    ).fetchone()
                    if row is None:
                        raise ValueError("missing shared audit value")
                    encoded = row[0]
                    loaded += len(encoded.encode())
                    if loaded > limit:
                        raise ValueError("shared audit exceeds loaded byte limit")
                    if hashlib.sha256(encoded.encode()).hexdigest() != key:
                        raise ValueError("damaged shared audit value")
                    value = json.loads(encoded)
                    if type(value) is not list or not value or value[0] != "record":
                        raise ValueError("shared audit requires a typed record")
                    active.add(key)
                    cache[key] = expand(value, depth + 1)
                    active.remove(key)
                return cache[key]
            if type(wire) is list:
                parts, size = [], 2
                for item in wire:
                    text = expand(item, depth + 1)
                    size += len(text) + bool(parts)
                    if size > limit:
                        raise ValueError("shared audit exceeds expanded byte limit")
                    parts.append(text)
                return "[" + ",".join(parts) + "]"
            if wire is not None and type(wire) not in (str, bool, int):
                raise ValueError("invalid shared audit scalar")
            text = _json(wire)
            if len(text) > limit:
                raise ValueError("shared audit exceeds expanded byte limit")
            return text

        try:
            wire = json.loads(body)
            if (
                type(wire) is not list
                or len(wire) != 3
                or wire[0] != "nomos.subject.shared-values"
                or type(wire[1]) is not int
                or wire[1] != 1
            ):
                raise ValueError("unsupported shared audit format")
            return expand(wire[2], 0)
        except RecursionError as error:
            raise ValueError("shared audit exceeds nesting limit") from error

    def loads(self, body):
        return self.codec.loads(self._expand(body))
