"""Stable priority ordering interleaved with a complete baseline exploration order."""

from .search import _Stop


class Ordering:
    """Resume completed member scores and permutation steps without partial output."""

    def __init__(self, values, score, *, exploration):
        if type(exploration) is not int or exploration < 2:
            raise ValueError("exploration interval must be an integer of at least two")
        self.values, self.score, self.exploration = tuple(values), score, exploration
        self.scores, self.ordered = [], []
        self.preferred, self.visited = None, set()
        self.base = self.learned = 0
        self._result = None
        self._failed = False

    def finish(self, work):
        if self._failed:
            raise ValueError("failed generation ordering cannot continue")
        try:
            return self._finish(work)
        except _Stop:
            raise
        except BaseException:
            self._failed = True
            self.values, self.score, self.preferred = (), None, None
            self.scores, self.ordered = (), ()
            self.visited.clear()
            raise

    def _finish(self, work):
        if self._result is not None:
            return self._result
        while len(self.scores) < len(self.values):
            work.spend()
            value = self.values[len(self.scores)]
            priority = self.score(value)
            if type(priority) is not int:
                raise ValueError("generation priority needs an integer, not a probability")
            self.scores.append((value, priority))
        if self.preferred is None:
            work.spend(max(1, len(self.values)))
            self.preferred = sorted(
                range(len(self.values)), key=lambda index: (-self.scores[index][1], index)
            )
        while len(self.ordered) < len(self.values):
            work.spend()
            if (len(self.ordered) + 1) % self.exploration == 0:
                while self.base in self.visited:
                    self.base += 1
                index = self.base
            else:
                while self.preferred[self.learned] in self.visited:
                    self.learned += 1
                index = self.preferred[self.learned]
            self.visited.add(index)
            self.ordered.append(self.values[index])
        self.ordered, self.scores = tuple(self.ordered), tuple(self.scores)
        self._result = self.ordered, self.scores
        self.values, self.score, self.preferred = (), None, None
        self.visited.clear()
        return self._result


def prioritize(values, score, work, *, exploration):
    return Ordering(values, score, exploration=exploration).finish(work)
