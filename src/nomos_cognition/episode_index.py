"""Persistent, recipient-owned episode postings for bounded recall selection."""

from dataclasses import dataclass
from heapq import heapify, heappop, heappush

from pyrsistent import pvector


def extend_indexes(contexts, cues, episodes, offset):
    context_rows, cue_rows = {}, {}
    for position, episode in enumerate(episodes, offset):
        context = episode.source.context
        row = position, episode
        context_rows.setdefault(context, []).append(row)
        for cue in episode.cues:
            cue_rows.setdefault((context, cue), []).append(row)
    return (
        contexts.update(
            {key: contexts.get(key, pvector()).extend(rows) for key, rows in context_rows.items()}
        ),
        cues.update({key: cues.get(key, pvector()).extend(rows) for key, rows in cue_rows.items()}),
    )


class EpisodeStream:
    """Explicit cursor: the caller charges before visiting the next posting."""

    def __init__(self, streams):
        self._heap = [
            (-rows[-1][0], index, len(rows) - 1, rows) for index, rows in enumerate(streams)
        ]
        heapify(self._heap)

    def __bool__(self):
        return bool(self._heap)

    def take(self):
        _, index, cursor, rows = heappop(self._heap)
        episode = rows[cursor][1]
        if cursor:
            heappush(self._heap, (-rows[cursor - 1][0], index, cursor - 1, rows))
        # Recall charges every posting visit and deduplicates retained sources.
        # Suppressing duplicates here would hide potentially unbounded merge work.
        return episode


@dataclass(frozen=True)
class EpisodeSelection:
    episodes: object
    work: int
    complete: bool


def select_episodes(by_context, by_cue, contexts, cues, *, work_limit):
    """Route within allowed contexts; unrelated history cannot change cardinalities."""
    if not by_context:
        return EpisodeSelection((), 0, True)
    found, work = [], 0
    for context in contexts:
        if work >= work_limit:
            return EpisodeSelection((), work, False)
        work += 1
        rows = by_context.get(context)
        if rows:
            found.append((context, rows))
    count = sum(len(rows) for _, rows in found)
    if not count:
        return EpisodeSelection((), work, True)
    context_streams = tuple(rows for _, rows in found)
    # Looking up every cue cannot beat directly checking this smaller context set.
    if count <= len(found) * len(cues):
        return EpisodeSelection(EpisodeStream(context_streams), work, True)
    cue_streams = []
    for context, _ in found:
        for cue in cues:
            if work >= work_limit:
                return EpisodeSelection((), work, False)
            work += 1
            rows = by_cue.get((context, cue))
            if rows:
                cue_streams.append(rows)
    streams = context_streams if count <= sum(map(len, cue_streams)) else cue_streams
    return EpisodeSelection(EpisodeStream(streams), work, True)
