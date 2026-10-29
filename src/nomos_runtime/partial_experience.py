"""Typed states for Subject-local complete-pattern projection."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Known:
    value: tuple

    def __post_init__(self):
        if type(self.value) is not tuple:
            raise ValueError("known partial experience needs an immutable value")


@dataclass(frozen=True)
class Unknown:
    reason: str

    def __post_init__(self):
        if type(self.reason) is not str or not self.reason:
            raise ValueError("unknown partial experience needs a reason")


@dataclass(frozen=True)
class NotApplicable:
    reason: str

    def __post_init__(self):
        if type(self.reason) is not str or not self.reason:
            raise ValueError("inapplicable partial experience needs a reason")
