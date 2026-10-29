"""Process-local computation provenance for immutable results of memory.recall."""

from dataclasses import dataclass
from weakref import ref

_PARTS = (
    "query",
    "version",
    "episodes",
    "experiences",
    "grounds",
    "status",
    "reason",
    "work",
    "samples",
)


def _expired():
    return None


@dataclass(frozen=True)
class _Origin:
    memory: object
    parts: tuple

    def __deepcopy__(self, memo):
        return None

    def __reduce__(self):
        return _expired, ()


def seal(recalled, memory):
    origin = _Origin(ref(memory), tuple(getattr(recalled, name) for name in _PARTS))
    object.__setattr__(recalled, "_origin", origin)
    return recalled


def memory_for(recalled):
    origin = getattr(recalled, "_origin", None)
    if type(origin) is not _Origin or any(
        getattr(recalled, name) is not item for name, item in zip(_PARTS, origin.parts, strict=True)
    ):
        return None
    return origin.memory()
