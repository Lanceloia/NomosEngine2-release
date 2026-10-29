"""Work-fair root families with continuation progress and bounded age service."""

from collections import OrderedDict
from dataclasses import dataclass
from heapq import heappop, heappush


@dataclass(frozen=True)
class _Entry:
    serial: int
    job: object
    family: object
    confirming: bool


class _Lane:
    def __init__(self):
        self.pending = {}
        self.focused = OrderedDict()
        self.resuming = OrderedDict()
        self.confirming = OrderedDict()
        self.ages, self.age_keys = [], set()
        self.streak = 0
        self.work = 0
        self.last = -1

    def put(self, entry, focus, resume=False):
        self.pending[entry.serial] = entry
        if entry.serial not in self.age_keys:
            self.age_keys.add(entry.serial)
            heappush(self.ages, entry.serial)
        if focus:
            self.focused[entry.serial] = None
            if entry.confirming:
                self.confirming[entry.serial] = None
        if resume:
            self.resuming[entry.serial] = None

    def new_confirmation(self):
        return min((key for key in self.confirming if key not in self.resuming), default=None)

    def pop(self, confirmation=None):
        if confirmation is not None:
            key = confirmation
        elif (self.resuming or self.focused) and self.streak < 8:
            if self.confirming:
                key, _ = self.confirming.popitem()
            elif self.resuming:
                key = min(self.resuming)
            else:
                key, _ = self.focused.popitem()
            self.streak += 1
        else:
            while True:
                key = heappop(self.ages)
                self.age_keys.remove(key)
                if key in self.pending:
                    break
            self.streak = 0
        self.focused.pop(key, None)
        self.resuming.pop(key, None)
        self.confirming.pop(key, None)
        entry = self.pending.pop(key)
        if not self.pending:
            self.ages.clear()
            self.age_keys.clear()
            self.focused.clear()
            self.resuming.clear()
            self.confirming.clear()
        return entry


class Agenda:
    """Coordinate root families by consumed work, retaining local continuations.

    The pure classifier identifies root families. Unclassified root discovery
    reveals finite capabilities without constructing their parameter products.
    Interrupted entries retain identity and age; suspended entries resume next
    slice without resetting consumed service or the lane's continuation streak.
    """

    def __init__(self, initial, *, key=None, confirming=None):
        self._key, self._confirming = key, confirming
        self._lanes = {}
        self._suspended = {}
        self._queued = set()
        self._inflight = None
        self._serial = self._dispatch = self._count = 0
        self.put(initial)

    def __len__(self):
        return self._count

    @property
    def ready(self):
        return self._count > len(self._suspended)

    def jobs(self):
        return tuple(
            entry.job for lane in self._lanes.values() for entry in lane.pending.values()
        ) + tuple(entry.job for entry in self._suspended.values())

    def _insert(self, entry, focus, *, resume=False):
        if entry.family not in self._lanes:
            self._lanes[entry.family] = _Lane()
        self._lanes[entry.family].put(entry, focus, resume)
        self._queued.add(entry.serial)
        self._count += 1

    def put(self, *jobs, focus=1):
        entries = []
        for job in jobs:
            group = None if self._key is None else self._key(job)
            confirm = self._confirming is not None and self._confirming(job)
            entries.append(_Entry(self._serial, job, group, confirm))
            self._serial += 1
        for entry in entries:
            self._insert(entry, False)
        for entry in reversed(entries[:focus]):
            self._lanes[entry.family].focused[entry.serial] = None
            if entry.confirming:
                self._lanes[entry.family].confirming[entry.serial] = None

    def pop(self):
        ready = [lane for lane in self._lanes.values() if lane.pending]
        if not ready:
            raise IndexError("no ready planning job")
        discovery = self._lanes.get(None)
        confirmation = None
        if discovery is not None and discovery.pending and not discovery.resuming:
            lane = discovery
        else:
            confirmations = [
                (key, lane) for lane in ready if (key := lane.new_confirmation()) is not None
            ]
            if confirmations:
                confirmation, lane = min(confirmations, key=lambda pair: pair[0])
            else:
                lane = min(ready, key=lambda item: (item.work, item.last))
        entry = lane.pop(confirmation)
        lane.last = self._dispatch
        self._dispatch += 1
        self._queued.remove(entry.serial)
        self._count -= 1
        self._inflight = entry
        return entry.job

    def account(self, job, work):
        if self._inflight is None or self._inflight.job is not job:
            raise ValueError("only the dispatched job can consume service")
        if type(work) is not int or work < 0:
            raise ValueError("service needs nonnegative consumed work")
        self._lanes[self._inflight.family].work += work

    def retry(self, job, *, suspend=False):
        entry = self._inflight
        if entry is None or entry.job is not job or entry.serial in self._queued:
            raise ValueError("only the interrupted job can be retried once")
        if suspend:
            self._suspended[entry.serial] = entry
            self._queued.add(entry.serial)
            self._count += 1
        else:
            self._insert(entry, True, resume=True)

    def start_slice(self):
        entries = tuple(self._suspended.values())
        self._suspended.clear()
        for entry in entries:
            self._count -= 1
            self._queued.remove(entry.serial)
            self._insert(entry, True, resume=True)
