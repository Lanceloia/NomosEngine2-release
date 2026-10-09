"""Versioned, deterministic die draws for effect-only C0 value expressions."""

from __future__ import annotations

from hashlib import sha256

MAX_SEED = (1 << 63) - 1
MAX_SIDES = 1000
_SAMPLE_SPACE = 1 << 64


def _seed_bytes(seed: int) -> bytes:
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError("die seed is outside its bounded integer domain")
    return seed.to_bytes(8, "big")


def next_seed(seed: int) -> int:
    digest = sha256(b"nomos.c0.die.next.v1\0" + _seed_bytes(seed)).digest()
    return int.from_bytes(digest[:8], "big") & MAX_SEED


def roll(seed: int, sides: int) -> int:
    seed_bytes = _seed_bytes(seed)
    if type(sides) is not int or not 2 <= sides <= MAX_SIDES:
        raise ValueError("die sides must be between 2 and 1000")
    limit = _SAMPLE_SPACE - _SAMPLE_SPACE % sides
    for counter in range(128):
        digest = sha256(
            b"nomos.c0.die.roll.v1\0"
            + seed_bytes
            + sides.to_bytes(2, "big")
            + counter.to_bytes(2, "big")
        ).digest()
        sample = int.from_bytes(digest[:8], "big")
        if sample < limit:
            return sample % sides + 1
    raise ValueError("die rejection sampling exceeded its finite bound")
