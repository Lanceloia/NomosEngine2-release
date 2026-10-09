"""Exact session-local Actor identity; not an Object or occurrence reference."""

from dataclasses import dataclass

from nomos_kernel._identity import K0ProfileError, _checked_label


@dataclass(frozen=True, order=True)
class _K0ActorRef:
    scope: str
    ordinal: int
    family: str

    def __post_init__(self) -> None:
        _checked_label(self.scope, "Actor scope")
        _checked_label(self.family, "Actor family")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise K0ProfileError("Actor ordinal must be positive")
